"""优化 agent 用的简历修补工具：get_resume_markdown / patch_content。

工具的「状态」挂在 OptimizeStore 上：整份简历 JSON。patch_content 按 [s,r,c,i]
坐标就地替换文字，JSON 结构/样式/图片不动；跑完直接拿 store.resume 返回前端，
前端据此重绘，格式不会乱。

工具每次调用都经 get_stream_writer() 发一条 custom 事件（tool_call / tool_result），
由外层图转发成 SSE，前端据此展示「执行过程」。
"""

from langchain_core.tools import tool
from langgraph.config import get_stream_writer

from agents.optimize.markdown import locate_unit, resume_to_markdown, write_text_unit


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
