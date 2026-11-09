"""审查 agent 的工具：审查并执行替换、查看标记文本。

工具的「状态」挂在 ReviewStore 上（简历 JSON + 诊断处理状态）：
- patch_content 逐条处理诊断：decision=skip 只记录判定不修改，decision=change
  按该诊断的 [s,r,c,i] 坐标就地替换文字，JSON 结构 / 样式 / 图片不动，
  跑完直接拿 store.resume 返回前端；
- get_resume_markdown 查看当前标记文本。

实际改动数 = 判为 change 且成功执行的诊断数，不会改到诊断之外的位置。

每次调用都经 get_stream_writer() 发 tool_call / tool_result（处理诊断还额外发
diagnosis_status），由外层图转发成 SSE，前端据此展示执行过程。
"""

import logging
from typing import Annotated

from langchain_core.tools import tool
from langgraph.config import get_stream_writer
from pydantic import Field

from agents.resume.optimize.schemas.diagnosis import QUOTE_MAX_LEN
from agents.utils.resume import locate_unit, norm_text, resume_to_marked_text, write_text_unit

logger = logging.getLogger("smartcv")


def _lost_tail(old: str, quote: str, new: str) -> bool:
    """替换文字是否只照着「被截断的原文片段」改写，把片段之后的正文整段丢掉。

    诊断里的 quote 最多 QUOTE_MAX_LEN 字，而 patch_content 替换的是整个文字单元。
    模型拿片段当原文改写时，新文字长度会和片段差不多，原文后半段（几百字的经历、
    链接）就凭空消失。这种情况退回重写，不能写进简历。
    """
    if len((quote or "").strip()) < QUOTE_MAX_LEN:
        return False
    normalized_old = norm_text(old)
    normalized_quote = norm_text(quote)
    if not normalized_old.startswith(normalized_quote):
        return False
    normalized_new = norm_text(new)
    if len(normalized_old) - len(normalized_quote) <= 20:
        return False
    return len(normalized_new) <= len(normalized_quote) + 20


class ReviewStore:
    """审查过程的简历容器 + 诊断处理状态。

    - resume：被 patch_content 就地修改的简历；
    - diagnoses：诊断 agent 产出的只读诊断项（深拷贝，运行时不回写）；
    - reviews：与 diagnoses 一一对应的处理状态，默认 pending；
    - patches：实际执行的改动清单。
    """

    def __init__(self, resume: list[dict], diagnoses: list[dict] | None = None) -> None:
        self.resume = resume
        self.patches: list[dict] = []
        self.diagnoses: list[dict] = []
        self.reviews: list[dict] = []
        self.set_diagnoses(diagnoses or [])

    def set_diagnoses(self, diagnoses: list[dict]) -> None:
        """登记本次要处理的诊断项，重置全部状态为 pending。"""
        self.diagnoses = [dict(d) for d in diagnoses]
        self.reviews = [
            {"index": index, "status": "pending", "reason": "", "note": ""}
            for index in range(len(self.diagnoses))
        ]

    def diagnosis_at(self, index: int) -> dict | None:
        if 0 <= index < len(self.diagnoses):
            return self.diagnoses[index]
        return None

    def can_patch(self, index: int) -> bool:
        """该诊断是否有可定位的坐标和可核对的原文片段。"""
        item = self.diagnosis_at(index)
        if item is None:
            return False
        if any(item.get(key) is None for key in ("s", "r", "c", "i")):
            return False
        return bool((item.get("quote") or "").strip())


def _tool_error(writer, tool: str, message: str) -> str:
    """工具前置校验失败：只回错误，不改任何状态。"""
    writer({"type": "tool_result", "tool": tool, "result": message, "ok": False})
    return message


def _mark_failed(review: dict, writer, index: int, message: str) -> str:
    """执行阶段失败（坐标不存在 / 原文对不上）：标 failed，不重试。"""
    review["status"] = "failed"
    review["note"] = message
    writer({"type": "diagnosis_status", "index": index, "status": "failed", "reason": message})
    writer({"type": "tool_result", "tool": "patch_content", "result": message, "ok": False})
    return message


def make_patch_tools(store: ReviewStore):
    """创建处理 / 查看工具，闭包绑定本次的 store。

    patch_content 同时承担「判定改不改」和「执行替换」两件事：
    - decision=skip 只记录判定与理由，不动简历；
    - decision=change 按该诊断的 [s,r,c,i] 坐标就地替换文字，模型无法把内容写到别的位置；
    - 修改前用诊断的 quote 核对当前位置文字，对不上直接标 failed，不重试。

    因此实际改动数 = 判为 change 且成功执行的诊断数，不会改到诊断之外的位置。
    """

    @tool
    def patch_content(
        index: Annotated[int, Field(description="诊断序号（0 起）")],
        decision: Annotated[
            str,
            Field(description='"change" = 需要修改并立即执行替换；"skip" = 不需要修改'),
        ],
        reason: Annotated[
            str,
            Field(description="判定理由：change 说明为什么必须改，skip 说明为什么不需要改或改不了"),
        ],
        text: Annotated[
            str,
            Field(
                description=(
                    "仅 decision=change 时必填：替换后的完整新文字。只改其中一句时，"
                    "这段文字的其他内容（后半句、链接、数字）要原样保留，只写片段部分会被拒绝"
                )
            ),
        ] = "",
    ) -> str:
        """处理一条诊断：判定是否需要修改；判为 change 时把它指向的那段文字替换成 text。

        只替换文字，不增删内容，结构与排版不变；同一个诊断只能成功处理一次。
        """
        writer = get_stream_writer()
        writer(
            {
                "type": "tool_call",
                "tool": "patch_content",
                "args": {"index": index, "decision": decision, "reason": reason, "text": text},
            }
        )

        item = store.diagnosis_at(index)
        if item is None:
            return _tool_error(
                writer,
                "patch_content",
                f"诊断序号 {index} 不存在，有效范围 0 ~ {len(store.diagnoses) - 1}",
            )

        review = store.reviews[index]
        if review["status"] != "pending":
            return _tool_error(writer, "patch_content", f"诊断 {index} 已处理，不能重复处理")

        decision = (decision or "").strip().lower()
        if decision not in ("change", "skip"):
            return _tool_error(writer, "patch_content", "decision 只能是 change 或 skip")

        reason = (reason or "").strip()
        if not reason:
            return _tool_error(writer, "patch_content", "reason 不能为空")

        disposition = item.get("disposition") or "suggest"

        if decision == "skip":
            review["status"] = "skip"
            review["reason"] = reason
            writer({"type": "diagnosis_status", "index": index, "status": "skip", "reason": reason})
            message = f"诊断 {index} 判定为不修改"
            writer({"type": "tool_result", "tool": "patch_content", "result": message, "ok": True})
            return message

        if disposition in ("keep", "insufficient"):
            label = "可以保留" if disposition == "keep" else "信息不足"
            return _tool_error(
                writer,
                "patch_content",
                f"诊断 {index} 的档位是「{label}」，不应修改；请判为 skip 并说明原因",
            )

        if not store.can_patch(index):
            return _tool_error(
                writer,
                "patch_content",
                "这条诊断没有可用的坐标或原文片段，无法只替换文字；请判为 skip 并说明原因",
            )

        located = locate_unit(store.resume, item["s"], item["r"], item["c"], item["i"])
        if located is None:
            return _mark_failed(review, writer, index, "诊断指向的坐标不存在，未执行")

        content, unit_type, unit_index, old = located
        quote = (item.get("quote") or "").strip()
        if not quote or norm_text(quote) not in norm_text(old):
            return _mark_failed(
                review,
                writer,
                index,
                f"原文核对失败：诊断引用「{quote}」，该位置当前是「{old}」，未执行",
            )

        new = (text or "").strip()
        if not new:
            return _tool_error(
                writer,
                "patch_content",
                f"诊断 {index} 判为 change 时 text 不能为空，请给出替换文字后再调用",
            )

        if new == old.strip():
            return _tool_error(writer, "patch_content", f"诊断 {index} 的新文字和原文相同，请重写后再调用")

        if norm_text(new) == norm_text(old):
            return _tool_error(
                writer,
                "patch_content",
                f"诊断 {index} 的新文字与原文字实质相同（只差格式或空白），没有实际修改，请重写后再调用",
            )

        if _lost_tail(old, quote, new):
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
        review["reason"] = reason
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
        writer({"type": "diagnosis_status", "index": index, "status": "done", "reason": reason})
        message = f"诊断 {index} 已修改：{review['note']}"
        writer({"type": "tool_result", "tool": "patch_content", "result": message, "ok": True})
        return message

    @tool
    def get_resume_markdown() -> str:
        """查看当前简历的标记文本，每行开头带位置编号 [s:章节 r:窗口 c:内容 i:子项]。"""
        writer = get_stream_writer()
        writer({"type": "tool_call", "tool": "get_resume_markdown", "args": {}})
        result = resume_to_marked_text(store.resume)
        writer({"type": "tool_result", "tool": "get_resume_markdown", "result": f"返回 {len(result.splitlines())} 行"})
        return result

    return [patch_content, get_resume_markdown]
