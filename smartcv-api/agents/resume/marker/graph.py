"""市场洞察流水线：LangGraph 编排 + SSE 事件出口。

流程：

  plan             planner 补齐 brief、询问调研方面、生成检索词；完成前不启动其他节点
  collect          按维度组 URL（内置源 / SearXNG + 补充网址），再按抓取方式取页面
  collect → extract 采集结束后按维度动态 fan-out；固定维度 + 用户选择的动态方面各一个节点
  └─ profile       简历画像，和 extract 同批 Send 并行；结果写 state 供 strategy / compose 使用
  synthesis        等全部 extract / profile 结束后跨源合成
  strategy         Agent 3：定位、差距、优先级、写法提示
  compose          固定首尾 + 所选方面各一章的完整报告 → END

固定节点 jobs / trend 永远存在；动态节点的数量和 id 完全由用户在规划阶段选择的
`aspects` 决定。以后前端改成多选，只需返回多个 aspect，图结构不用改。
"""

import time
import uuid
from typing import Annotated, Awaitable, Callable

from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.types import Send
from typing_extensions import TypedDict

from agents.resume.marker.compose_agent import run as run_compose
from agents.resume.marker.market_agent import build_market, collect as run_collect
from agents.resume.marker.market_agent import extract as run_extract
from agents.resume.marker.market_agent import synthesize as run_synthesis
from agents.resume.marker.planner_agent import plan_result_event
from agents.resume.marker.planner_agent import run as run_planner
from agents.resume.marker.resume_agent import run as run_resume
from agents.resume.marker.strategy_agent import run as run_strategy
from agents.resume.marker.utils.dims import graph_payload, report_sections
from agents.resume.marker.utils.runner import safe_writer
from agents.resume.marker.schemas import Brief, MarketRequest
from agents.resume.marker.utils.task import MarketTask
from agents.resume.marker.utils.common import dim_ids, fallback_groups, normalize_request
from agents.resume.marker.utils.stage_log import stage_exception, stage_info
from agents.utils.choose_llm import choose_llm
from schemas.provider import ProviderConfig

Emit = Callable[[dict], Awaitable[None]]


def merge_dict(left: dict | None, right: dict | None) -> dict:
    """并行 extract 分别返回 {dim: result}，按 key 合并；同一维度后写覆盖前写。"""
    return {**(left or {}), **(right or {})}


class MarketState(TypedDict, total=False):
    """整条流水线共享的状态；按产出它的节点分组，只有对应节点的代码写这一段字段。"""

    # ---- 全局：请求带入 / 规划确定后所有阶段只读 ----
    brief: dict  # 归一化后的任务简报（Brief）：岗位、城市、年限、时间窗口、来源、调研方面
    resume: list[dict] | None  # 用户提供的简历快照；None 表示本次不做简历对照
    dims: list[str]  # 本次调研的维度 id：固定 jobs / trend + 用户选择的动态方面
    dim: str  # Send 分发时写入当前并行分支负责的维度（只在 extract 节点内使用）
    pages_per_dim: dict[str, int]  # 三类维度各自的页数：jobs / trend / other
    urls_per_dim: int  # 每个维度最多使用的补充网址条数
    fetch_mode: str  # 抓取方式：get / crawler；由抓取适配器注册表解释

    # ---- plan：规划检索（planner agent） ----
    groups: list[dict]  # 规划出的检索组 [{id, label, queries}]，每个维度一组
    plan_notes: str  # planner 对本次检索策略的一句话说明
    aborted: bool  # 用户没选调研重点：规划阶段主动结束本轮，不进入采集 / 画像

    # ---- collect：采集页面（代码） ----
    collected: Annotated[dict, merge_dict]  # 采集结果 {维度: {pages, coverage, sample_size}}，按维度合并
    pages: list[dict]  # 全部采集页面，已按 kind 标记维度并分配证据 id（J1/T1/E1…）
    valid_ids: list[str]  # 全部有效证据 id；下游 agent 用它过滤引用，防止编造来源
    sources: list[dict]  # 来源站点汇总，用于报告标注
    coverage: str  # 整体覆盖度：full / partial / none
    sample_size: int  # 本次调研的样本页数

    # ---- extract × N：并行抽取 agent（按维度 merge） ----
    facts: Annotated[dict, merge_dict]  # 各并行 agent 的抽取结果 {维度: result}，按维度合并

    # ---- profile：简历画像 agent ----
    profile: dict  # 简历画像结果；没有简历或画像失败时为空 dict

    # ---- synthesis：跨源合成 agent ----
    market: dict  # 跨源合成后的市场结果（build_market 输出），strategy / compose 的输入

    # ---- strategy：策略总结 agent ----
    strategy: dict  # 策略总结：岗位定位、差距、优先级、写法提示

    # ---- compose：报告撰写 agent ----
    sections: list[dict]  # 最终报告章节：固定首尾 + 本次选择的动态方面各一章


def _brief(state: MarketState) -> Brief:
    return Brief.model_validate(state["brief"])


def _route_plan(state: MarketState) -> list[Send]:
    """规划完成后先采集。

    用户没选调研重点时 planner 会标记 aborted；返回空分支即结束整张图，
    不能回退到 collect 用城市 / 年限继续调研。
    """
    if state.get("aborted"):
        return []
    return [Send("collect", dict(state))]


def _route_extract(state: MarketState) -> list[Send]:
    """采集结束后 fan-out：每个维度一个 extract 节点，数量即本次 agent 数。

    简历画像不依赖采集结果，但也不应该拖住抽取：把它放进这一批 Send，和
    各维度 agent 同一个 superstep 并行跑。synthesis 仍然在两者都完成后开始，
    所以 strategy / compose 能拿到 profile。
    """
    base = dict(state)
    sends = [Send("extract", {**base, "dim": dim}) for dim in state.get("dims") or []]
    if state.get("resume") and not state.get("profile"):
        sends.append(Send("profile", base))
    return sends


async def run_market_stream(
    provider: ProviderConfig,
    request: MarketRequest,
    emit: Emit,
    *,
    task: MarketTask | None = None,
    llm=None,
) -> dict:
    """跑完整条市场洞察流水线；每个事件经 emit 发出去，返回最终状态。

    task 用于反问：planner 需要提问时把问题写进任务通道，前端经
    /api/market/answer 回答后恢复同一个 agent。
    """
    # 单次调用最多等 120 秒、只重试一次：供应商卡住时让规划尽快失败并走兜底，
    # 而不是把整轮调研无限期挂在「生成计划」。
    llm = llm or choose_llm(provider, timeout=120, max_retries=1)
    run_id = task.task_id if task else uuid.uuid4().hex
    brief = normalize_request(request)
    started = time.perf_counter()
    stage_info(
        "pipeline",
        "开始",
        run=run_id,
        role=brief.target_role or "-",
        city=brief.location,
        resume=brief.has_resume,
    )

    # 先给固定节点结构；planner 确定动态维度后会再发一次 graph 更新。
    await emit({"type": "graph", **graph_payload(brief.has_resume)})
    await emit({"type": "status", "stage": "start", "text": brief.describe()})

    async def plan_node(state: MarketState) -> dict:
        """入口闸门：规划（含两轮反问）完成前，不启动画像 / 采集 / 抽取。"""
        writer = safe_writer()
        brief_value = _brief(state)
        started_at = time.perf_counter()
        stage_info("plan", "开始", role=brief_value.target_role or "-", resume=brief_value.has_resume)
        writer({"type": "status", "stage": "prepare", "text": "生成检索规划"})
        try:
            plan = await run_planner(llm, brief_value, task, run_id=run_id)
            updated_brief = Brief.model_validate(plan.get("brief") or state["brief"])
            if plan.get("aborted"):
                # 没有调研重点就不生成检索计划；空分支让图直接结束。
                stage_info("plan", "结束", reason="未选择调研重点")
                return {
                    "brief": updated_brief.model_dump(),
                    "groups": [],
                    "dims": [],
                    "plan_notes": plan.get("notes") or "",
                    "aborted": True,
                }
            dims = plan.get("dims") or dim_ids(updated_brief)
            groups = plan["groups"]
            notes = plan.get("notes") or ""
        except Exception as exc:
            stage_exception("plan", "模型调用失败，改用兜底检索词")
            writer({"type": "error", "node": "planner", "message": str(exc), "fatal": False})
            updated_brief = _brief(state)
            dims = dim_ids(updated_brief)
            groups = fallback_groups(updated_brief, dims)
            notes = "规划失败，使用默认检索"
            writer({"type": "status", "stage": "planner", "text": "计划生成失败，已使用默认检索词"})
            # 兜底也要关闭规划闸门，否则前端会一直停在「生成计划」。
            writer(plan_result_event(groups, updated_brief, notes))

        stage_info(
            "plan",
            "完成",
            dims=len(dims),
            queries=sum(len(group.get("queries") or []) for group in groups),
            elapsed=f"{time.perf_counter() - started_at:.1f}s",
        )
        # 动态节点在 plan.result 之后补发给前端；节点 id 仍由后端语义决定。
        await emit(
            {
                "type": "graph",
                **graph_payload(
                    updated_brief.has_resume,
                    dims,
                    updated_brief.aspect_labels,
                ),
            }
        )
        return {
            "brief": updated_brief.model_dump(),
            "groups": groups,
            "dims": dims,
            "plan_notes": notes,
            "facts": {},
            "collected": {},
        }

    async def collect_node(state: MarketState) -> dict:
        """所有维度统一采集；采集结束由条件边动态分发到各 agent。"""
        groups = state["groups"]
        started_at = time.perf_counter()
        stage_info(
            "collect",
            "开始",
            dims=len(groups),
            queries=sum(len(group.get("queries") or []) for group in groups),
        )
        result = await run_collect(
            _brief(state),
            groups,
            run_id=run_id,
            pages_per_dim=state.get("pages_per_dim"),
            urls_per_dim=state.get("urls_per_dim"),
            fetch_mode=state.get("fetch_mode"),
            llm=llm,
        )
        stage_info(
            "collect",
            "完成",
            pages=result.get("sample_size") or 0,
            sources=len(result.get("sources") or []),
            coverage=result.get("coverage") or "none",
            elapsed=f"{time.perf_counter() - started_at:.1f}s",
        )
        return result

    async def profile_node(state: MarketState) -> dict:
        """简历画像；没有简历时直接跳过，不产生事件。"""
        if not state.get("resume"):
            return {}
        writer = safe_writer()
        started_at = time.perf_counter()
        stage_info("profile", "开始", sections=len(state.get("resume") or []))
        try:
            result = await run_resume(llm, state.get("resume"), run_id=run_id)
        except Exception as exc:
            stage_exception("profile", "画像失败，跳过简历对照")
            writer({"type": "error", "node": "profile", "message": str(exc), "fatal": False})
            return {"profile": {}}
        stage_info(
            "profile",
            "完成",
            evidence=result.get("evidence_count") or 0,
            elapsed=f"{time.perf_counter() - started_at:.1f}s",
        )
        return {"profile": result.get("profile") or {}}

    async def extract_node(state: MarketState) -> dict:
        """一个维度的并行 agent；返回值经 merge_dict 合并进 facts。"""
        brief_value = _brief(state)
        dim = str(state["dim"])
        collected = (state.get("collected") or {}).get(dim) or {
            "pages": [],
            "coverage": "none",
            "sample_size": 0,
        }
        started_at = time.perf_counter()
        stage_info("extract", "开始", dim=dim, pages=len(collected.get("pages") or []))
        result = await run_extract(
            llm,
            brief_value,
            dim,
            collected,
            run_id=run_id,
        )
        meta = (result.get("facts") or {}).get(dim) or {}
        stage_info(
            "extract",
            "完成",
            dim=dim,
            coverage=meta.get("coverage") or "none",
            sample=meta.get("sample_size") or 0,
            elapsed=f"{time.perf_counter() - started_at:.1f}s",
        )
        return result

    async def synthesis_node(state: MarketState) -> dict:
        brief_value = _brief(state)
        dims = state.get("dims") or []
        facts = state.get("facts") or {}
        valid_ids = set(state.get("valid_ids") or [])
        started_at = time.perf_counter()
        stage_info("synthesis", "开始", dims=len(dims), facts=len(facts))
        try:
            synthesis = await run_synthesis(
                llm,
                brief_value,
                dims,
                facts,
                valid_ids,
                run_id=run_id,
            )
        except Exception as exc:
            stage_exception("synthesis", "合成失败，跳过合成结论")
            writer = safe_writer()
            writer({"type": "error", "node": "synthesis", "message": str(exc), "fatal": False})
            synthesis = {
                "result": {"items": [], "contradictions": [], "notes": ""},
                "coverage": state.get("coverage") or "none",
                "sample_size": 0,
            }
        result = synthesis.get("result") or {}
        stage_info(
            "synthesis",
            "完成",
            items=len(result.get("items") or []),
            contradictions=len(result.get("contradictions") or []),
            elapsed=f"{time.perf_counter() - started_at:.1f}s",
        )
        market = build_market(
            brief_value,
            dims,
            facts,
            synthesis=synthesis,
            pages=state.get("pages") or [],
            sources=state.get("sources") or [],
            coverage=state.get("coverage") or "none",
            sample_size=int(state.get("sample_size") or 0),
            valid_ids=valid_ids,
        )
        return {"market": market}

    async def strategy_node(state: MarketState) -> dict:
        market = state["market"]
        started_at = time.perf_counter()
        stage_info("strategy", "开始", coverage=market.get("coverage") or "none")
        strategy = await run_strategy(
            llm,
            _brief(state),
            market,
            state.get("profile"),
            set(market.get("valid_ids") or []),
            run_id=run_id,
        )
        result = strategy.get("result") or {}
        stage_info(
            "strategy",
            "完成",
            gaps=len(result.get("gaps") or []),
            priorities=len(result.get("priorities") or []),
            elapsed=f"{time.perf_counter() - started_at:.1f}s",
        )
        return {"strategy": strategy}

    async def compose_node(state: MarketState) -> dict:
        started_at = time.perf_counter()
        stage_info("compose", "开始", sections=len(report_sections(_brief(state))))
        result = await run_compose(
            llm,
            _brief(state),
            state["market"],
            state.get("profile"),
            state.get("strategy"),
            run_id=run_id,
        )
        sections = result["sections"]
        stage_info(
            "compose",
            "完成",
            sections=len(sections),
            failed=sum(1 for section in sections if section.get("status") == "failed"),
            elapsed=f"{time.perf_counter() - started_at:.1f}s",
        )
        return {"sections": sections}

    graph = StateGraph(MarketState)
    graph.add_node("plan", plan_node)
    graph.add_node("collect", collect_node)
    graph.add_node("profile", profile_node)
    graph.add_node("extract", extract_node)
    graph.add_node("synthesis", synthesis_node)
    graph.add_node("strategy", strategy_node)
    graph.add_node("compose", compose_node)

    graph.add_edge(START, "plan")
    # plan 完成同时发出 collect 与 profile；两者都在 superstep 2 跑完，
    # extract 在下一个 superstep 才开始，所以 synthesis 不需要等 profile 的边。
    graph.add_conditional_edges("plan", _route_plan)
    graph.add_conditional_edges("collect", _route_extract)
    graph.add_edge("extract", "synthesis")
    graph.add_edge("profile", END)
    graph.add_edge("synthesis", "strategy")
    graph.add_edge("strategy", "compose")
    graph.add_edge("compose", END)

    compiled = graph.compile()

    state: MarketState = {
        "brief": brief.model_dump(),
        "resume": request.resume,
        "groups": [],
        "dims": [],
        "pages_per_dim": request.pages_per_dim,
        "urls_per_dim": request.urls_per_dim,
        "fetch_mode": request.fetch_mode,
        "plan_notes": "",
        "collected": {},
        "pages": [],
        "valid_ids": [],
        "sources": [],
        "coverage": "none",
        "sample_size": 0,
        "facts": {},
        "profile": {},
        "market": {},
        "strategy": {},
        "sections": [],
    }
    config = {"configurable": {"thread_id": run_id}}

    try:
        async for mode, chunk in compiled.astream(
            state,
            stream_mode=["updates", "custom"],
            config=config,
        ):
            if mode == "custom":
                await emit(chunk)
                continue
            for node_update in chunk.values():
                if not node_update:
                    continue
                for key, value in node_update.items():
                    if key in ("facts", "collected"):
                        state[key] = merge_dict(state.get(key), value)
                    else:
                        state[key] = value
    except Exception as exc:
        stage_exception("pipeline", "失败", run=run_id)
        # 先标记任务失败：路由层据此判断错误事件是否已经发过，避免重复 done。
        if task is not None:
            task.fail(str(exc))
        await emit({"type": "error", "node": "pipeline", "message": str(exc), "fatal": True})
        await emit({"type": "done", "status": "failed"})
        raise

    if state.get("aborted"):
        reason = str(state.get("plan_notes") or "未选择调研重点，已停止本轮调研")
        # 用户没选调研重点：规划阶段结束，采集 / 画像 / 报告都不启动。
        await emit({"type": "done", "status": "cancelled", "reason": reason})
        stage_info("pipeline", "停止", run=run_id, reason=reason)
        return {
            "brief": state.get("brief") or brief.model_dump(),
            "dims": [],
            "groups": [],
            "profile": {},
            "market": {},
            "strategy": {},
            "sections": [],
            "aborted": True,
            "reason": reason,
        }

    await emit({"type": "done", "status": "done"})
    result = {
        "brief": state.get("brief") or brief.model_dump(),
        "dims": state.get("dims") or [],
        "groups": state.get("groups") or [],
        "profile": state.get("profile") or {},
        "market": state.get("market") or {},
        "strategy": state.get("strategy") or {},
        "sections": state.get("sections") or [],
    }
    market = result["market"]
    stage_info(
        "pipeline",
        "完成",
        run=run_id,
        dims=len(result["dims"]),
        sections=len(result["sections"]),
        sample=market.get("sample_size") if market else 0,
        coverage=market.get("coverage") if market else "none",
        elapsed=f"{time.perf_counter() - started:.1f}s",
    )
    return result
