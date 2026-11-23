"""Chat 流水线的检查点兼容入口。

实际实现已泛化到 `agents/utils/checkpointer.py`（按名字管理 saver）。
这里保留原函数签名，chat / marker 的既有调用无需改动。
"""

from agents.utils.checkpointer import (
    clear_checkpoints,
    close_checkpointer,
    get_checkpointer,
    open_checkpointer,
)

__all__ = ["open_checkpointer", "get_checkpointer", "close_checkpointer", "clear_checkpoints"]
