"""诊断用的优秀示例：拼成 prompt 里的 `<优秀示例>` 块。

示例正文是「纯结构 Markdown」（不带用户的 [s:r:c:i] 坐标），
转换本身在 agents/utils/resume.py，这里只负责加外层标签和方向说明。
"""

from agents.utils.resume import resume_to_plain_text


def format_reference_examples(examples: list[dict]) -> str:
    """把选中的优秀示例拼成诊断 prompt 里的 `<优秀示例>` 内容。

    每份示例带方向与说明；正文是纯结构 Markdown，不带用户简历的坐标。
    """
    parts: list[str] = []
    for index, example in enumerate(examples, 1):
        direction = str(example.get("direction") or "").strip()
        description = str(example.get("description") or "").strip()
        attrs = f' 方向="{direction}"' if direction else ""
        body = resume_to_plain_text(example.get("resume") or []).strip()
        note = f"说明：{description}\n" if description else ""
        parts.append(
            f"<示例 {index}{attrs}>\n{note}<内容>\n{body}\n</内容>\n</示例 {index}>"
        )
    return "\n\n".join(parts)
