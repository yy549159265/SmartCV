"""诊断 agent 的反问工具。

信息不足时模型调用 ask_user_question：
  1. 工具内部 `interrupt(payload)` 暂停诊断，state 存进 checkpointer；
  2. diagnose_agent.run 把问题推成 SSE 事件，等前端 POST /api/chat/answer；
  3. 循环用 `Command(resume=answers)` 恢复，工具从头重跑，interrupt 直接返回答案。

工具只负责「暂停 + 把答案交给模型」；发 SSE、等前端提交都在 diagnose_agent.run 里做
—— 恢复时工具会整段重跑，事件写在工具里会重复下发。
"""

import json
from typing import Annotated

from langchain_core.tools import tool
from langgraph.types import interrupt
from pydantic import BaseModel, Field


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


def _normalize_ask(title: str, questions: list[AskQuestion]) -> dict:
    """补全问题 id / header，返回可直接下发前端的 JSON 结构。"""
    normalized: list[dict] = []
    used: set[str] = set()
    for index, q in enumerate(questions, start=1):
        qid = (q.id or "").strip() or f"q{index}"
        base, suffix = qid, 2
        while qid in used:
            qid = f"{base}-{suffix}"
            suffix += 1
        used.add(qid)
        normalized.append(
            {
                "id": qid,
                "header": (q.header or f"问题 {index}").strip(),
                "question": q.question.strip(),
                "multiSelect": bool(q.multiSelect),
                "options": [
                    {"label": o.label.strip(), "description": (o.description or "").strip()}
                    for o in q.options
                ],
                "allowCustom": True,
            }
        )
    return {"title": title.strip(), "questions": normalized}


def make_ask_tool():
    """创建诊断 agent 的反问工具。

    工具只负责 `interrupt(payload)` 暂停；真正的「发 SSE + 等前端 POST 答案」
    在 diagnose_agent.run 里做 —— 这样恢复时工具会从头重跑（interrupt 直接
    返回答案），不会重复发提问事件。
    """

    @tool
    def ask_user_question(
        title: Annotated[
            str,
            Field(min_length=1, max_length=60, description="本轮反问的总标题，一句话说明为什么问"),
        ],
        questions: Annotated[
            list[AskQuestion],
            Field(min_length=1, max_length=3, description="1~3 个问题"),
        ],
    ) -> str:
        """当简历或 JD 缺少关键信息、无法做出可靠诊断时，向用户提出 1~3 个选择题。

        只在「不问就会猜」的情况下使用：如目标岗位/JD 缺失、经历缺少时间或成果、
        用户要求太笼统、简历里有占位符或事实矛盾。能从简历/JD 推断的不要问。

        每个问题给 2~3 个具体选项；用户还可以选第 4 项「其他」自行输入。
        调用后前端会暂停并等待用户回答，本工具返回答案 JSON（answers / cancelled）。
        得到答案后必须把答案作为诊断依据；用户跳过或超时则按信息不足继续诊断。
        """
        payload = _normalize_ask(title, questions)
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
