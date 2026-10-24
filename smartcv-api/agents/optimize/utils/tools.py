"""优化流水线用的工具。

- 优化 agent：get_resume_markdown / patch_content。
  工具的「状态」挂在 OptimizeStore 上（整份简历 JSON）。patch_content 按 [s,r,c,i]
  坐标就地替换文字，JSON 结构/样式/图片不动；跑完直接拿 store.resume 返回前端，
  前端据此重绘，格式不会乱。

- 诊断 agent：ask_user_question。
  信息不足时进入工具 → interrupt() 暂停诊断 → 前端展示选择题并 POST 答案 →
  工具拿到 Command(resume=...) 的答案后返回给模型，诊断继续。

工具每次调用都经 get_stream_writer() 发一条 custom 事件（tool_call / tool_result），
由外层图转发成 SSE，前端据此展示「执行过程」。
"""

import json
from typing import Any

from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from agents.optimize.utils.markdown import locate_unit, resume_to_markdown, write_text_unit


class OptimizeStore:
    """优化过程的简历容器：resume 被 patch_content 就地修改，patches 记录每次改动。"""

    def __init__(self, resume: list[dict]) -> None:
        self.resume = resume
        self.patches: list[dict] = []


def make_patch_tools(store: OptimizeStore):
    """创建修补工具，闭包绑定本次的 store（与 md2json 的 make_section_tools 同套路）。

    工具内部用 get_stream_writer() 发 custom 事件（tool_call / tool_result），
    由外层 optimize_graph 的节点转发成 SSE，不再需要 on_patch 回调。
    """

    @tool
    def get_resume_markdown() -> str:
        """查看当前简历的标记文本，每行开头带位置编号 [s:章节 r:窗口 c:内容 i:子项]。"""
        writer = get_stream_writer()
        writer({"type": "tool_call", "tool": "get_resume_markdown", "args": {}})
        result = resume_to_markdown(store.resume)
        writer({"type": "tool_result", "tool": "get_resume_markdown", "result": f"返回 {len(result.splitlines())} 行"})
        return result

    @tool
    def patch_content(s: int, r: int, c: int, i: int, text: str) -> str:
        """把 [s:章节 r:窗口 c:内容 i:子项] 指向的那段文字替换成 text。

        只替换文字、不增删内容，因此简历的章节/窗口/内容结构与排版都不会变。

        Args:
            s: 章节序号（0 起）
            r: 窗口序号（0 起，章节内叶子窗口按自上而下顺序编号）
            c: 内容序号（0 起，该窗口内可改文字的内容，image/spacer 不计）
            i: 子项序号（0 起；iconText/timeRange 恒为 0，listText=第几条，
               tag=第几个标签，twoColumn=第几列）
            text: 新文字
        """
        writer = get_stream_writer()
        writer({"type": "tool_call", "tool": "patch_content", "args": {"s": s, "r": r, "c": c, "i": i, "text": text}})
        located = locate_unit(store.resume, s, r, c, i)
        if located is None:
            msg = (
                f"坐标 [s:{s} r:{r} c:{c} i:{i}] 不存在，"
                "请先调用 get_resume_markdown 查看当前简历的有效坐标。"
            )
            writer({"type": "tool_result", "tool": "patch_content", "result": msg, "ok": False})
            return msg
        content, unit_type, unit_index, old = located
        new = (text or "").strip()
        write_text_unit(content, unit_type, unit_index, new)
        store.patches.append({"s": s, "r": r, "c": c, "i": i, "old": old, "new": new})
        msg = f"已把 [s:{s} r:{r} c:{c} i:{i}] 更新为「{new}」"
        writer({"type": "tool_result", "tool": "patch_content", "result": msg, "ok": True})
        return msg

    return [get_resume_markdown, patch_content]


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
