"""统一响应格式：{ code, message, data }。

约定：
  code    0 = 成功，非 0 = 失败（一般直接取 HTTP 状态码，如 422/501）
  message 成功时 "ok"，失败时给人看的中文说明
  data    成功时为业务数据，失败时为 None

HTTP 状态码仍然保留意义：2xx 成功、4xx/5xx 失败。
前端用 !res.ok 拦非 2xx，再用 body.code 判断业务是否成功（见前端 src/api/error.ts）。
"""


def ok(data=None, message: str = "ok") -> dict:
    """成功响应：code=0。"""
    return {"code": 0, "message": message, "data": data}


def error(code: int, message: str) -> dict:
    """失败响应：code 非 0，data 恒为 None。"""
    return {"code": code, "message": message, "data": None}
