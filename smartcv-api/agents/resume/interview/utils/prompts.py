"""提示词读取：`prompts/<阶段>/<名字>.md`，模块加载时取一次并缓存。"""

from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=32)
def load_prompt(*parts: str) -> str:
    path = _PROMPTS_DIR.joinpath(*parts)
    return path.read_text(encoding="utf-8").strip()
