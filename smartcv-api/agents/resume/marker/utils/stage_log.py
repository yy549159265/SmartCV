"""Agent 阶段日志：业务域 + 阶段标识 + 核心字段。

格式固定为 `[业务域][阶段] 动作 字段=值 ...`。默认业务域是「市场调研」，
模拟面试等其它流程复用时必须显式传 `scope`，否则日志会把人带到错误的流程里。
阶段与图节点同名，便于按阶段过滤、也便于和前端事件 / 代码位置对照。
只记录核对流程所需的核心字段，不打印简历、回答或参考答案正文。
"""

import logging

logger = logging.getLogger("smartcv")

DEFAULT_SCOPE = "市场调研"


def _line(scope: str, stage: str, message: str, fields: dict[str, object]) -> str:
    context = " ".join(f"{key}={value}" for key, value in fields.items())
    return f"[{scope}][{stage}] {message}" + (f" {context}" if context else "")


def stage_info(
    stage: str, message: str, *, scope: str = DEFAULT_SCOPE, **fields: object
) -> None:
    logger.info(_line(scope, stage, message, fields))


def stage_warning(
    stage: str, message: str, *, scope: str = DEFAULT_SCOPE, **fields: object
) -> None:
    logger.warning(_line(scope, stage, message, fields))


def stage_exception(
    stage: str, message: str, *, scope: str = DEFAULT_SCOPE, **fields: object
) -> None:
    logger.exception(_line(scope, stage, message, fields))
