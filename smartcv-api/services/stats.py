"""导出统计：PDF / JSON 导出次数，存 JSON 文件，跨容器重建保留。

写路径优先级：环境变量 SMARTCV_STATS_FILE > 容器内固定 /app/data/stats.json
（对应 compose 挂载 /opt/smartcv/stats，与 stats.py 放在主目录还是 services/ 无关）
> 开发机 smartcv-api/data/stats.json。
写入用线程锁 + 临时文件原子替换，避免并发请求把文件写坏。
"""

import json
import os
import threading
from pathlib import Path


def _default_stats_file() -> Path:
    env = os.environ.get("SMARTCV_STATS_FILE")
    if env:
        return Path(env)
    if Path("/.dockerenv").exists():
        # 容器内固定写挂载点，不随 __file__ 位置漂移
        return Path("/app/data/stats.json")
    # 开发机：仓库根 smartcv-api/data/stats.json（stats.py 在 services/ 下，向上两级）
    return Path(__file__).resolve().parent.parent / "data" / "stats.json"


_STATS_FILE = _default_stats_file()
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
