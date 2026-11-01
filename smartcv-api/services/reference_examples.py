"""优秀示例库：诊断时可选参考的优秀简历范例，存成 JSON 文件。

一份示例 = 一条记录：
    { id, direction, description, resume: Section[], createdAt }

存放位置优先级：环境变量 SMARTCV_REFERENCE_DIR > 容器内 /app/data/reference-examples
> 开发机 smartcv-api/data/reference-examples。
docker compose 通过 SMARTCV_REFERENCE_DIR 指向 /app/reference-examples，
宿主机目录 /opt/smartcv/reference-examples 挂载到该路径。

约束：
  - 没有用户体系，示例库是全局共享的；
  - 上传后不可编辑、不可删除（前端在上传前会二次确认）；
  - 写入用线程锁 + 临时文件原子替换，避免并发把文件写坏。
"""

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("smartcv")

# 单份示例 JSON 的序列化上限（含 dataURL 图片时可能较大，但也要防呆）
MAX_EXAMPLE_BYTES = 5 * 1024 * 1024

# 示例 id 只允许 uuid4 的 32 位十六进制，杜绝用文件名做路径穿越
_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

_lock = threading.Lock()


def _default_dir() -> Path:
    env = os.environ.get("SMARTCV_REFERENCE_DIR")
    if env:
        return Path(env)
    if Path("/.dockerenv").exists():
        return Path("/app/data/reference-examples")
    # 开发机：smartcv-api/data/reference-examples（本文件在 services/ 下，向上两级）
    return Path(__file__).resolve().parent.parent / "data" / "reference-examples"


_DIR = _default_dir()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _meta(record: dict) -> dict:
    """列表只回元数据，不带简历正文（缩略图按需再取详情）。"""
    resume = record.get("resume") or []
    return {
        "id": record.get("id", ""),
        "direction": record.get("direction", ""),
        "description": record.get("description", ""),
        "createdAt": record.get("createdAt", ""),
        "sectionCount": len(resume) if isinstance(resume, list) else 0,
    }


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("优秀示例文件损坏，已跳过：%s", path)
        return None
    if not isinstance(data, dict) or not _ID_PATTERN.match(str(data.get("id", ""))):
        logger.warning("优秀示例文件结构不对，已跳过：%s", path)
        return None
    return data


def list_examples() -> list[dict]:
    """列出全部示例的元数据，按上传时间倒序（新的在前）。"""
    if not _DIR.exists():
        return []
    records = []
    for path in _DIR.glob("*.json"):
        record = _read(path)
        if record is not None:
            records.append(record)
    records.sort(key=lambda r: str(r.get("createdAt", "")), reverse=True)
    return [_meta(r) for r in records]


def get_example(example_id: str) -> dict | None:
    """按 id 读取完整示例；id 不合法或文件不存在返回 None。"""
    if not _ID_PATTERN.match(example_id or ""):
        return None
    path = _DIR / f"{example_id}.json"
    if not path.is_file():
        return None
    return _read(path)


def _validate_resume(resume) -> None:
    """只做缩略图/渲染必需的结构校验，不重写内容（保留前端原始 JSON）。"""
    if not isinstance(resume, list) or not resume:
        raise ValueError("优秀 JSON 必须是非空的章节数组")
    for index, section in enumerate(resume):
        if not isinstance(section, dict):
            raise ValueError(f"第 {index + 1} 个章节不是对象")
        if not isinstance(section.get("rows"), list):
            raise ValueError(f"第 {index + 1} 个章节缺少 rows 数组")
    try:
        size = len(json.dumps(resume, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"优秀 JSON 无法序列化：{exc}") from exc
    if size > MAX_EXAMPLE_BYTES:
        raise ValueError("优秀 JSON 超过 5MB，请压缩后再上传")


def create_example(direction: str, description: str, resume) -> dict:
    """新增一份示例，返回它的元数据。"""
    direction = (direction or "").strip()
    description = (description or "").strip()
    if not direction:
        raise ValueError("适用职业方向不能为空")
    if not description:
        raise ValueError("优秀简历描述不能为空")
    if len(direction) > 60:
        raise ValueError("适用职业方向最多 60 字")
    if len(description) > 2000:
        raise ValueError("优秀简历描述最多 2000 字")
    _validate_resume(resume)

    record = {
        "id": uuid.uuid4().hex,
        "direction": direction,
        "description": description,
        "resume": resume,
        "createdAt": _now_iso(),
    }
    with _lock:
        _DIR.mkdir(parents=True, exist_ok=True)
        target = _DIR / f"{record['id']}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)
    logger.info("新增优秀示例：%s（%s）", record["id"], direction)
    return _meta(record)


def resolve_examples(example_ids: list[str] | None) -> list[dict]:
    """按 id 取完整记录（给诊断用）；不存在的 id 跳过并记日志，不打断整次诊断。"""
    resolved: list[dict] = []
    for example_id in example_ids or []:
        record = get_example(example_id)
        if record is None:
            logger.warning("优秀示例不存在或已损坏，已跳过：%s", example_id)
            continue
        resolved.append(record)
    return resolved
