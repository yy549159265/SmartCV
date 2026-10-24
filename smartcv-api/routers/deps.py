"""路由共享依赖。

agent 会话 id 由 main.py 的 middleware 写进 request.state，这里只负责读取。
单独放一个模块，避免 routers 反过来 import main 造成循环依赖。
"""

from fastapi import Request


def get_agent_session(request: Request) -> str | None:
    """当前请求的 agent 会话 id（前端没带或格式非法则为 None）。"""
    if not getattr(request.state, "agent_session_valid", False):
        return None
    return getattr(request.state, "agent_session_id", None)
