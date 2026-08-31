"""导出统计：PDF / JSON 导出次数，存 JSON 文件，跨容器重建保留。

文件路径默认容器内 /app/data/stats.json（对应 compose 挂载 /opt/smartcv/stats），
开发机落 smartcv-api/data/stats.json；可用环境变量 SMARTCV_STATS_FILE 覆盖。
写入用线程锁 + 临时文件原子替换，避免并发请求把文件写坏。
"""

import json
import os
import threading
from pathlib import Path

_STATS_FILE = Path(
    os.environ.get("SMARTCV_STATS_FILE", Path(__file__).resolve().parent / "data" / "stats.json")
)
_lock = threading.Lock()


def _default() -> dict:
    return {"pdf": 0, "json": 0}


def load_stats() -> dict:
    """读取当前计数；文件缺失或损坏时返回全零。"""
    try:
        data = json.loads(_STATS_FILE.read_text(encoding="utf-8"))
        return {k: int(data.get(k, 0)) for k in ("pdf", "json")}
    except (FileNotFoundError, ValueError):
        return _default()


def increment_stats(kind: str) -> dict:
    """把 kind（pdf / json）计数 +1，返回最新计数。"""
    with _lock:
        data = load_stats()
        data[kind] = data.get(kind, 0) + 1
        _STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _STATS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_STATS_FILE)
        return data
