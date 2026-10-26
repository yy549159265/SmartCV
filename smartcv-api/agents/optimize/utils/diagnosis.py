"""把结构化诊断项格式化成 agent 可读的文本。

优化 agent：需要坐标，且编号必须和 review_diagnosis / patch_content 的 index 对齐（0 起）；
总结 agent：不需要坐标（避免坐标泄漏到给用户的说明里），编号从 1 开始。
"""

from typing import Any


def _result_line(review: dict[str, Any]) -> str:
    """把一条审查状态转成给总结 agent 看的「处理结果」行。"""
    status = review.get("status") or "pending"
    reason = (review.get("reason") or "").strip()
    note = (review.get("note") or "").strip()
    if status == "done":
        return "   处理：已修改"
    if status == "skip":
        return f"   处理：未修改（{reason}）" if reason else "   处理：未修改"
    if status == "failed":
        return f"   处理：未执行（{note or reason}）" if (note or reason) else "   处理：未执行"
    if status == "change":
        return "   处理：待修改"
    return "   处理：未处理"


def format_diagnosis(
    items: list[dict[str, Any]],
    *,
    include_coords: bool = True,
    zero_based: bool = False,
    reviews: list[dict[str, Any]] | None = None,
) -> str:
    """把 DiagnosisItem 列表拼成按条编号的文本。

    Args:
        items: 诊断项列表。
        include_coords: 是否带上 s/r/c/i 坐标（优化 agent 要，总结不要）。
        zero_based: 编号是否从 0 开始（优化 agent 的 index 是 0 起）。
        reviews: 按 index 对齐的审查结果；传入时每条附一行「处理结果」，
            让总结 agent 能区分哪些改了、哪些没改以及原因。
    """
    if not items:
        return "（没有诊断项）"

    blocks: list[str] = []
    for index, item in enumerate(items):
        number = index if zero_based else index + 1
        prefix = f"诊断 {number}" if zero_based else f"{number}."

        # structure 类没有坐标；s 为 None 也按结构问题处理，避免拼出 [s:None ...]
        if item.get("kind") == "structure" or item.get("s") is None:
            head = f"{prefix} [结构调整]"
        else:
            head = prefix
            if include_coords:
                head += (
                    f" [s:{item.get('s')} r:{item.get('r')} "
                    f"c:{item.get('c')} i:{item.get('i')}]"
                )
            quote = item.get("quote") or ""
            if quote:
                head += f" 原文：「{quote}」"

        lines = [
            head,
            f"   问题：{item.get('reason') or ''}",
            f"   依据：{item.get('evidence') or ''}",
            f"   方向：{item.get('suggestion') or ''}",
        ]
        if reviews is not None and index < len(reviews):
            lines.append(_result_line(reviews[index]))
        blocks.append("\n".join(lines))
    return "\n".join(blocks)
