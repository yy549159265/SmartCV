"""按名字管理的 LangGraph SQLite 检查点。

使用方在 FastAPI lifespan 里为每个名字打开一个 saver：

    await open_checkpointer("chat_checkpoints.sqlite", name="chat")
    await open_checkpointer("interview_checkpoints.sqlite", name="interview")

业务图编译时挂 `get_checkpointer(name)`。chat 仍按 1h 整库清空；
面试按线程空闲时间裁剪（checkpoint_id 是 UUID7，前 48 位是毫秒时间戳），
避免整库删除误伤进行中的面试。
"""

import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

logger = logging.getLogger("smartcv")

_DEFAULT_NAME = "chat"

_savers: dict[str, AsyncSqliteSaver] = {}
_holders: dict[str, Any] = {}
_paths: dict[str, str] = {}


async def open_checkpointer(db_path: str, name: str = _DEFAULT_NAME) -> None:
    """打开某个命名空间的 sqlite 检查点连接（应用级单例）。"""
    if name in _savers:
        return
    holder = AsyncSqliteSaver.from_conn_string(db_path)
    _savers[name] = await holder.__aenter__()
    _holders[name] = holder
    _paths[name] = db_path
    logger.info("%s checkpointer 已打开：%s", name, db_path)


def get_checkpointer(name: str = _DEFAULT_NAME) -> AsyncSqliteSaver:
    saver = _savers.get(name)
    if saver is None:
        raise RuntimeError(
            f"{name} checkpointer 未初始化（main.py lifespan 未调 open_checkpointer）"
        )
    return saver


async def close_checkpointer(name: str = _DEFAULT_NAME) -> None:
    holder = _holders.pop(name, None)
    _savers.pop(name, None)
    if holder is not None:
        await holder.__aexit__(None, None, None)


def _checkpoint_file(name: str) -> Path:
    path = _paths.get(name)
    if not path:
        raise RuntimeError(f"{name} checkpointer 未打开，无法定位 sqlite 文件")
    return Path(path)


async def clear_checkpoints(
    db_path: str | None = None, name: str = _DEFAULT_NAME
) -> None:
    """关闭连接 → 删除 sqlite 及其 -shm/-wal → 重新打开。

    chat 每 1h 调用一次，防止 langgraph checkpoint 无限膨胀占磁盘。
    关闭连接后 sqlite 会把 WAL 合并回主文件，此时删除三个文件即可真正回收空间。
    """
    path = Path(db_path) if db_path else _checkpoint_file(name)
    await close_checkpointer(name)
    for suffix in ("", "-wal", "-shm", "-sh"):
        f = Path(str(path) + suffix)
        try:
            f.unlink(missing_ok=True)
        except PermissionError:
            logger.warning("无法删除 %s（可能被占用，已跳过）", f)
    await open_checkpointer(str(path), name=name)


def _uuid7_ms(value: str) -> int | None:
    """UUID7 的前 12 位十六进制是毫秒时间戳；其它版本返回 None。"""
    raw = (value or "").replace("-", "")
    if len(raw) < 12:
        return None
    try:
        ms = int(raw[:12], 16)
    except ValueError:
        return None
    now_ms = int(time.time() * 1000)
    # UUID1 的 time_low/time_mid 也会解出一个数，但通常远超当前时间。
    if ms <= 0 or ms > now_ms + 24 * 3600 * 1000:
        return None
    return ms


def _latest_checkpoint_ids(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT thread_id, MAX(checkpoint_id) FROM checkpoints GROUP BY thread_id"
    ).fetchall()
    return {str(thread_id): str(checkpoint_id) for thread_id, checkpoint_id in rows}


def prune_idle_threads(name: str, max_idle_seconds: int) -> int:
    """删除最后更新时间超过阈值的线程，返回删除的线程数。

    checkpoint_id 由 langgraph 生成为 UUID7，按毫秒时间戳排序；解析不出来的
    线程保守跳过，不误删。
    """
    path = _checkpoint_file(name)
    if not path.exists():
        return 0
    cutoff_ms = int((time.time() - max_idle_seconds) * 1000)
    stale: list[str] = []
    try:
        conn = sqlite3.connect(str(path), timeout=10)
        try:
            for thread_id, checkpoint_id in _latest_checkpoint_ids(conn).items():
                ms = _uuid7_ms(checkpoint_id)
                if ms is not None and ms < cutoff_ms:
                    stale.append(thread_id)
            if stale:
                placeholders = ",".join("?" for _ in stale)
                conn.execute(f"DELETE FROM writes WHERE thread_id IN ({placeholders})", stale)
                conn.execute(
                    f"DELETE FROM checkpoints WHERE thread_id IN ({placeholders})", stale
                )
                conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        logger.exception("%s 检查点裁剪失败", name)
        return 0
    if stale:
        logger.info("%s 检查点已清理 %d 个空闲线程", name, len(stale))
    return len(stale)


def new_thread_id() -> str:
    """面试线程 id：UUID4，避免与 chat 的会话 id 混淆。"""
    return uuid.uuid4().hex
