"""Chat 流水线的 LangGraph SQLite 检查点。

图状态（markdown / diagnosis / summary / result_json）按 thread_id（= agent 会话 id）
持久化到一个 sqlite 文件。服务启动时在 FastAPI lifespan 里 open_checkpointer，
之后每次 /api/chat 编译图时 compile(checkpointer=get_checkpointer()) 挂上。
"""

import logging
from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger("smartcv")

_saver: AsyncSqliteSaver | None = None
# from_conn_string 返回异步上下文管理器，手动 __aenter__ 后持有，退出时 __aexit__
_holder = None


async def open_checkpointer(db_path: str) -> None:
    """FastAPI lifespan 里调用：打开 sqlite 检查点连接（应用级单例）。"""
    global _saver, _holder
    holder = AsyncSqliteSaver.from_conn_string(db_path)
    _saver = await holder.__aenter__()
    _holder = holder
    logger.info("chat checkpointer 已打开：%s", db_path)


def get_checkpointer() -> AsyncSqliteSaver:
    if _saver is None:
        raise RuntimeError("chat checkpointer 未初始化（main.py lifespan 未调 open_checkpointer）")
    return _saver


async def close_checkpointer() -> None:
    global _saver, _holder
    if _holder is not None:
        await _holder.__aexit__(None, None, None)
    _saver = None
    _holder = None


async def clear_checkpoints(db_path: str) -> None:
    """清空 chat 的 sqlite 检查点：关闭连接 → 删除 sqlite 及其 -shm/-wal → 重新打开。

    每 1h 由 main.py 的定时任务调用，防止 langgraph checkpoint 无限膨胀占磁盘。
    关闭连接后 sqlite 会把 WAL 合并回主文件，此时删除三个文件即可真正回收空间。
    """
    await close_checkpointer()
    base = Path(db_path)
    for suffix in ("", "-wal", "-shm", "-sh"):
        f = Path(str(base) + suffix)
        try:
            f.unlink(missing_ok=True)
        except PermissionError:
            logger.warning("无法删除 %s（可能被占用，已跳过）", f)
    await open_checkpointer(str(base))
