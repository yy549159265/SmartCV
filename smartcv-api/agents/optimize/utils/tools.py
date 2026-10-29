"""优化流水线用的工具。

- 优化 agent：review_diagnosis / patch_content / get_resume_markdown。
  工具的「状态」挂在 OptimizeStore 上（简历 JSON + 诊断审查状态）。
  review_diagnosis 逐条判定改不改；patch_content 只收诊断序号，按该诊断的 [s,r,c,i]
  坐标就地替换文字，JSON 结构/样式/图片不动；跑完直接拿 store.resume 返回前端，
  前端据此重绘，格式不会乱。

- 诊断 agent：ask_user_question。
  信息不足时进入工具 → interrupt() 暂停诊断 → 前端展示选择题并 POST 答案 →
  工具拿到 Command(resume=...) 的答案后返回给模型，诊断继续。

工具每次调用都经 get_stream_writer() 发一条 custom 事件（tool_call / tool_result），
由外层图转发成 SSE，前端据此展示「执行过程」。
"""

import json
import logging
import re
from typing import Any

from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from agents.optimize.schemas.diagnosis import QUOTE_MAX_LEN
from agents.optimize.utils.markdown import locate_unit, resume_to_markdown, write_text_unit

logger = logging.getLogger("smartcv")


def _norm_text(text: str) -> str:
    """去掉空白和 Markdown 装饰，用于原文核对。

    诊断 agent 有时会把 quote 写成 `**加粗**`、`` `代码` `` 或带列表符号，
    而简历原文是纯文本；不抹掉这些标记，核对必然对不上，优化阶段就会误判成
    「原文核对失败」而不执行。两侧都走同一个函数，所以是安全的。
    """
    value = re.sub(r"\s+", "", text or "")
    # 强调 / 代码 / 删除线符号：原文里没有，纯装饰
    value = re.sub(r"[*`~]", "", value)
    # 成对的下划线强调（__加粗__ / _斜体_）：只去掉包裹符号，单词里的下划线（user_id）不动
    value = re.sub(r"_{1,2}([^_\s]+?)_{1,2}", r"\1", value)
    # 行首列表符号（"- xxx" / "• xxx"）
    return re.sub(r"^[-+•·]+", "", value)


def _lost_tail(old: str, quote: str, new: str) -> bool:
    """替换文字是否只照着「被截断的原文片段」改写，把片段之后的正文整段丢掉。

    诊断里的 quote 最多 QUOTE_MAX_LEN 字，而 patch_content 替换的是整个文字单元。
    模型拿片段当原文改写时，新文字长度会和片段差不多，原文后半段（几百字的经历、
    链接）就凭空消失。这种情况退回重写，不能写进简历。
    """
    # 片段没被截断 → 模型手里就是整段原文，不存在这个问题。
    # 用原始长度判断：_norm_text 会去掉空白，归一化后的长度比截断上限只会更短。
    if len((quote or "").strip()) < QUOTE_MAX_LEN:
        return False
    normalized_old = _norm_text(old)
    normalized_quote = _norm_text(quote)
    if not normalized_old.startswith(normalized_quote):
        return False
    normalized_new = _norm_text(new)
    if len(normalized_old) - len(normalized_quote) <= 20:
        return False
    # 新文字与片段长度相当 = 按片段改写，片段之后的内容整段丢失
    return len(normalized_new) <= len(normalized_quote) + 20


class OptimizeStore:
    """优化过程的简历容器 + 诊断审查状态。

    - resume：被 patch_content 就地修改的简历；
    - diagnoses：诊断 agent 产出的只读诊断项（深拷贝，运行时不回写）；
    - reviews：与 diagnoses 一一对应的审查状态，默认 pending；
    - patches：实际执行的改动清单。
    """

    def __init__(self, resume: list[dict], diagnoses: list[dict] | None = None) -> None:
        self.resume = resume
        self.patches: list[dict] = []
        self.diagnoses: list[dict] = []
        self.reviews: list[dict] = []
        self.set_diagnoses(diagnoses or [])

    def set_diagnoses(self, diagnoses: list[dict]) -> None:
        """登记本次要审查的诊断项，重置全部审查状态为 pending。"""
        self.diagnoses = [dict(d) for d in diagnoses]
        self.reviews = [
            {"index": index, "status": "pending", "reason": "", "note": ""}
            for index in range(len(self.diagnoses))
        ]

    def diagnosis_at(self, index: int) -> dict | None:
        if 0 <= index < len(self.diagnoses):
            return self.diagnoses[index]
        return None

    def pending_indexes(self) -> list[int]:
        """还没审查的诊断序号。"""
        return [r["index"] for r in self.reviews if r["status"] == "pending"]

    def can_patch(self, index: int) -> bool:
        """该诊断是否有可定位的坐标和可核对的原文片段。"""
        item = self.diagnosis_at(index)
        if item is None or item.get("kind") == "structure":
            return False
        if any(item.get(key) is None for key in ("s", "r", "c", "i")):
            return False
        return bool((item.get("quote") or "").strip())


def _tool_error(writer, tool: str, message: str) -> str:
    """工具前置校验失败：只回错误，不改任何状态。"""
    writer({"type": "tool_result", "tool": tool, "result": message, "ok": False})
    return message


def _mark_failed(review: dict, writer, index: int, message: str) -> str:
    """执行阶段失败（坐标不存在 / 原文对不上 / 新旧相同）：标 failed，不重试。"""
    review["status"] = "failed"
    review["note"] = message
    writer({"type": "diagnosis_status", "index": index, "status": "failed", "reason": message})
    writer({"type": "tool_result", "tool": "patch_content", "result": message, "ok": False})
    return message


def make_patch_tools(store: OptimizeStore):
    """创建审查 / 修改 / 查看工具，闭包绑定本次的 store。

    审查（review_diagnosis）和修改（patch_content）分开：
    - patch_content 只收诊断序号，改哪段文字由诊断决定，模型无法把内容写到别的位置；
    - 必须全部诊断都审查完，才允许第一次修改；
    - 修改前用诊断的 quote 核对当前位置文字，对不上直接标 failed，不重试。

    因此实际改动数 = 判为 change 且成功执行的诊断数（y），不会改到诊断之外的位置。
    """

    @tool
    def review_diagnosis(index: int, decision: str, reason: str) -> str:
        """审查一条诊断：判定是否需要修改，并写出理由。

        Args:
            index: 诊断序号（0 起，对应诊断结果里的「诊断 0 / 诊断 1 …」）
            decision: "change" = 需要修改；"skip" = 不需要修改
            reason: 判定理由。change 说明为什么必须改，skip 说明为什么不需要改或改不了
        """
        writer = get_stream_writer()
        writer(
            {
                "type": "tool_call",
                "tool": "review_diagnosis",
                "args": {"index": index, "decision": decision, "reason": reason},
            }
        )

        item = store.diagnosis_at(index)
        if item is None:
            return _tool_error(
                writer,
                "review_diagnosis",
                f"诊断序号 {index} 不存在，有效范围 0 ~ {len(store.diagnoses) - 1}",
            )

        review = store.reviews[index]
        if review["status"] in ("done", "failed"):
            return _tool_error(writer, "review_diagnosis", f"诊断 {index} 已执行或已失败，不能再改判定")

        decision = (decision or "").strip().lower()
        if decision not in ("change", "skip"):
            return _tool_error(writer, "review_diagnosis", "decision 只能是 change 或 skip")

        reason = (reason or "").strip()
        if not reason:
            return _tool_error(writer, "review_diagnosis", "reason 不能为空")

        if decision == "change" and not store.can_patch(index):
            return _tool_error(
                writer,
                "review_diagnosis",
                "这条诊断没有可用的坐标或原文片段，无法只替换文字；请判为 skip 并说明原因",
            )

        review["status"] = decision
        review["reason"] = reason
        writer({"type": "diagnosis_status", "index": index, "status": decision, "reason": reason})
        label = "需要修改" if decision == "change" else "不修改"
        message = f"诊断 {index} 判定为{label}"
        writer({"type": "tool_result", "tool": "review_diagnosis", "result": message, "ok": True})
        return message

    @tool
    def patch_content(index: int, text: str) -> str:
        """执行一条已判定为 change 的诊断：把它指向的那段文字替换成 text。

        只替换文字，不增删内容，结构与排版不变；同一个诊断只能成功修改一次。

        text 必须是该坐标的**完整**新文字：只改其中一句时，这段文字的其他内容
        （后半句、链接、数字）要原样保留；只写片段部分会被拒绝。

        Args:
            index: 诊断序号（0 起）
            text: 替换后的完整文字
        """
        writer = get_stream_writer()
        writer({"type": "tool_call", "tool": "patch_content", "args": {"index": index, "text": text}})

        item = store.diagnosis_at(index)
        if item is None:
            return _tool_error(
                writer,
                "patch_content",
                f"诊断序号 {index} 不存在，有效范围 0 ~ {len(store.diagnoses) - 1}",
            )

        pending = store.pending_indexes()
        if pending:
            return _tool_error(
                writer,
                "patch_content",
                f"还有 {len(pending)} 条诊断没有审查（序号 {pending}），请先用 review_diagnosis 全部审查完再修改",
            )

        review = store.reviews[index]
        if review["status"] == "done":
            return _tool_error(writer, "patch_content", f"诊断 {index} 已经修改过，不能重复修改")
        if review["status"] == "failed":
            return _tool_error(writer, "patch_content", f"诊断 {index} 之前核对失败，不再重试；请继续处理其他诊断")
        if review["status"] != "change":
            return _tool_error(
                writer,
                "patch_content",
                f"诊断 {index} 没有判定为需要修改（当前状态 {review['status']}），不能执行",
            )

        located = locate_unit(store.resume, item["s"], item["r"], item["c"], item["i"])
        if located is None:
            return _mark_failed(review, writer, index, "诊断指向的坐标不存在，未执行")

        content, unit_type, unit_index, old = located
        quote = (item.get("quote") or "").strip()
        if not quote or _norm_text(quote) not in _norm_text(old):
            return _mark_failed(
                review,
                writer,
                index,
                f"原文核对失败：诊断引用「{quote}」，该位置当前是「{old}」，未执行",
            )

        new = (text or "").strip()
        if new == old.strip():
            # 模型给了个和原文一样的版本：这是笔误，不算执行失败，允许它改了再试
            return _tool_error(writer, "patch_content", f"诊断 {index} 的新文字和原文相同，请重写后再调用")

        if _lost_tail(old, quote, new):
            # 只照着 60 字的原文片段改写，会把片段之后的正文整段删掉：保持 change 状态让它重写
            logger.warning("patch_content 拦截疑似截断的替换：诊断 %d，「%s」→「%s」", index, old, new)
            return _tool_error(
                writer,
                "patch_content",
                f"诊断 {index} 的新文字明显短于原文，疑似只照着「原文」片段改写，"
                f"会把片段之后的正文丢掉。该坐标的完整原文是「{old}」，请保留片段之后的内容，"
                "重新给出整段替换文字后再调用",
            )

        write_text_unit(content, unit_type, unit_index, new)
        review["status"] = "done"
        review["note"] = f"「{old}」→「{new}」"
        store.patches.append(
            {
                "index": index,
                "s": item["s"],
                "r": item["r"],
                "c": item["c"],
                "i": item["i"],
                "old": old,
                "new": new,
            }
        )
        writer({"type": "diagnosis_status", "index": index, "status": "done", "reason": review["reason"]})
        message = f"诊断 {index} 已修改：{review['note']}"
        writer({"type": "tool_result", "tool": "patch_content", "result": message, "ok": True})
        return message

    @tool
    def get_resume_markdown() -> str:
        """查看当前简历的标记文本，每行开头带位置编号 [s:章节 r:窗口 c:内容 i:子项]。"""
        writer = get_stream_writer()
        writer({"type": "tool_call", "tool": "get_resume_markdown", "args": {}})
        result = resume_to_markdown(store.resume)
        writer({"type": "tool_result", "tool": "get_resume_markdown", "result": f"返回 {len(result.splitlines())} 行"})
        return result

    return [review_diagnosis, patch_content, get_resume_markdown]


# ==================== 诊断 agent：向用户反问 ====================


class AskOption(BaseModel):
    """一个预设选项。"""

    label: str = Field(..., min_length=1, max_length=40, description="选项文字（用户点选的就是它）")
    description: str = Field("", max_length=120, description="可选补充说明，前端显示在选项下方")


class AskQuestion(BaseModel):
    """一个问题。预设选项 2~3 个；第 4 个「其他（自定义输入）」由前端固定追加，不要自己写。"""

    id: str = Field("", max_length=32, description="问题 id，不填由后端补 q1 / q2…")
    header: str = Field("", max_length=16, description="短标签（如「目标岗位」），前端作为小标题")
    question: str = Field(..., min_length=1, max_length=200, description="完整问题，一行，直接问用户")
    multiSelect: bool = Field(False, description="true = 多选，false = 单选")
    options: list[AskOption] = Field(
        ...,
        min_length=2,
        max_length=3,
        description="2~3 个预设选项（从简历内容里生成具体选项）",
    )


class AskInput(BaseModel):
    """ask_user_question 的完整入参：一个总标题 + 一组问题。"""

    title: str = Field(..., min_length=1, max_length=60, description="本轮反问的总标题，一句话说明为什么问")
    questions: list[AskQuestion] = Field(..., min_length=1, max_length=4, description="1~4 个问题")


def _normalize_ask(payload: AskInput) -> dict:
    """校验并补全问题 id / header，返回可直接下发前端的 JSON 结构。"""
    questions: list[dict] = []
    used: set[str] = set()
    for index, q in enumerate(payload.questions, start=1):
        qid = (q.id or "").strip() or f"q{index}"
        base, suffix = qid, 2
        while qid in used:
            qid = f"{base}-{suffix}"
            suffix += 1
        used.add(qid)
        questions.append(
            {
                "id": qid,
                "header": (q.header or f"问题 {index}").strip(),
                "question": q.question.strip(),
                "multiSelect": bool(q.multiSelect),
                "options": [
                    {"label": o.label.strip(), "description": (o.description or "").strip()}
                    for o in q.options
                ],
                # 第 4 项由前端固定渲染成「其他（自定义输入）」
                "allowCustom": True,
            }
        )
    return {"title": payload.title.strip(), "questions": questions}


def make_ask_tool():
    """创建诊断 agent 的反问工具。

    工具只负责 `interrupt(payload)` 暂停；真正的「发 SSE + 等前端 POST 答案」
    在 diagnose_agent.run 里做 —— 这样恢复时工具会从头重跑（interrupt 直接
    返回答案），不会重复发提问事件。
    """

    @tool(args_schema=AskInput)
    def ask_user_question(title: str, questions: list[dict[str, Any]]) -> str:
        """当简历或 JD 缺少关键信息、无法做出可靠诊断时，向用户提出 1~4 个选择题。

        只在「不问就会猜」的情况下使用：如目标岗位/JD 缺失、经历缺少时间或成果、
        用户要求太笼统、简历里有占位符或事实矛盾。能从简历/JD 推断的不要问。

        每个问题给 2~3 个具体选项；用户还可以选第 4 项「其他」自行输入。
        调用后前端会暂停并等待用户回答，本工具返回答案 JSON（answers / cancelled）。
        得到答案后必须把答案作为诊断依据；用户跳过或超时则按信息不足继续诊断。

        Args:
            title: 本轮反问的总标题（一句话说明为什么问）
            questions: 1~4 个问题；每题包含 header、question、multiSelect、options
        """
        payload = _normalize_ask(AskInput.model_validate({"title": title, "questions": questions}))
        # 暂停：value 会随 SSE 下发前端；恢复时这里直接拿到 Command(resume=...) 的值
        answer = interrupt(payload)
        if not isinstance(answer, dict):
            answer = {}
        answers = answer.get("answers") or []
        cancelled = bool(answer.get("cancelled")) or not answers
        return json.dumps(
            {"title": payload["title"], "answers": answers, "cancelled": cancelled},
            ensure_ascii=False,
        )

    return ask_user_question
