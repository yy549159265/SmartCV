"""字节跳动招聘适配器：调用站内检索与岗位详情接口。

输入：检索词列表 + 条数上限 + 本次简报 + 来源设置
输出：Hit 列表（url / title / published）

settings 由前端「内置来源」面板透传，键和值都是英文枚举：
- recruitType: "experienced"（社招，portal_type=2）/ "campus"（校招，portal_type=3）；
  缺省、清空或其它值一律返回空。

检索接口只认 keyword / limit / location_code_list，其余筛选项留空即可；
结果里的 id 用来拼岗位详情接口（portal_type + with_recommend=true）。
brief.city 按 `_CITY_CODES` 换成站点编码，为空或不在表里直接返回空，不做
全国兜底。

检索接口要求 x-csrf-token 与同名 Cookie 一致，token 从 /api/v1/csrf/token
现取；实测 `_signature` 不校验（带不带、真伪都返回 200），所以不生成签名。
详情接口任何情况下都能直接 GET。
"""

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import httpx

from agents.resume.marker.schemas.market import Brief
from agents.resume.marker.tools.adapters import register
from agents.resume.marker.tools.adapters._keywords import clean as _clean, job_keywords as _job_keywords
from agents.resume.marker.tools.adapters.base import Hit, Source
from agents.resume.marker.utils.stage_log import stage_info, stage_warning

_TIMEOUT = float(os.getenv("BYTEDANCE_TIMEOUT", "12"))
_SEARCH = "https://jobs.bytedance.com/api/v1/search/job/posts"
_DETAIL = "https://jobs.bytedance.com/api/v1/job/posts/{job_id}"
_CSRF = "https://jobs.bytedance.com/api/v1/csrf/token"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "portal-channel": "office",
    "portal-platform": "pc",
}
# 站点路径和详情页 Referer 按招聘类型区分。
_PORTALS = {
    "experienced": {"portal_type": 2, "website_path": "society", "referer": "https://jobs.bytedance.com/experienced/position"},
    "campus": {"portal_type": 3, "website_path": "campus", "referer": "https://jobs.bytedance.com/campus/position"},
}

# 招聘站的城市筛选项：显示名 → location_code。
_CITY_CODES = {
    "北京": "CT_11",
    "上海": "CT_125",
    "深圳": "CT_128",
    "杭州": "CT_52",
    "广州": "CT_45",
    "成都": "CT_22",
    "西安": "CT_155",
    "武汉": "CT_154",
    "珠海": "CT_192",
    "南京": "CT_107",
    "重庆": "CT_190",
    "青岛": "CT_119",
    "郑州": "CT_188",
    "济南": "CT_66",
    "沈阳": "CT_129",
    "长沙": "CT_20",
    "合肥": "CT_55",
    "厦门": "CT_158",
    "昆明": "CT_80",
    "福州": "CT_40",
    "苏州": "CT_199",
    "中国香港": "CT_159",
    "南昌": "CT_105",
    "三亚": "CT_100065",
    "太原": "CT_141",
    "贵阳": "CT_47",
    "石家庄": "CT_133",
    "呼和浩特": "CT_59",
    "兰州": "CT_83",
    "天津": "CT_143",
    "哈尔滨": "CT_48",
    "南宁": "CT_108",
    "临沂": "CT_89",
    "丽水": "CT_100202",
    "泉州": "CT_121",
    "鄂尔多斯": "CT_38",
    "海口": "CT_49",
    "乌鲁木齐": "CT_150",
    "乌兰察布": "CT_100132",
    "长春": "CT_19",
    "大同": "CT_27",
}


def _published(value: object) -> str:
    """发布时间统一成 YYYY-MM-DD；站点给的是毫秒时间戳（东八区），其它原样保留。"""
    raw = _clean(value)
    if raw.isdigit():
        stamp = int(raw)
        if stamp > 10**12:
            stamp //= 1000
        try:
            moment = datetime.fromtimestamp(stamp, timezone(timedelta(hours=8)))
        except (OverflowError, OSError, ValueError):
            return raw[:40]
        return moment.strftime("%Y-%m-%d")
    return raw[:40]


class BytedanceSource(Source):
    id = "bytedance"
    label = "字节跳动"
    aliases = ("bytedance", "字节")
    dims = ("jobs",)  # 招聘站只服务 jobs 维度

    async def urls(
        self,
        queries: list[str],
        *,
        limit: int,
        brief: Brief,
        settings: dict[str, str] | None = None,
    ) -> list[Hit]:
        if limit <= 0:
            return []
        recruit_type = _clean((settings or {}).get("recruitType")).casefold()
        portal = _PORTALS.get(recruit_type)
        if not portal:
            stage_info("collect", "字节跳动跳过", reason="未配置招聘类型")
            return []
        code = _CITY_CODES.get(_clean(brief.city))
        if not code:
            stage_info("collect", "字节跳动跳过", reason="城市未命中", city=brief.city or "-")
            return []
        keyword = _job_keywords(queries, brief.target_role)
        if not keyword:
            stage_info("collect", "字节跳动跳过", reason="缺少检索词")
            return []

        portal_type = portal["portal_type"]
        params = {
            "keyword": keyword,
            "limit": max(1, min(limit, 50)),
            "offset": 0,
            "job_category_id_list": "",
            "tag_id_list": "",
            "location_code_list": code,
            "subject_id_list": "",
            "recruitment_id_list": "",
            "portal_type": portal_type,
            "job_function_id_list": "",
            "storefront_id_list": "",
            "portal_entrance": 1,
        }
        body = {
            "keyword": keyword,
            "limit": params["limit"],
            "offset": 0,
            "job_category_id_list": [],
            "tag_id_list": [],
            "location_code_list": [code],
            "subject_id_list": [],
            "recruitment_id_list": [],
            "portal_type": portal_type,
            "job_function_id_list": [],
            "storefront_id_list": [],
            "portal_entrance": 1,
        }
        url = f"{_SEARCH}?{urlencode(params, quote_via=quote)}"
        headers = {
            **_HEADERS,
            "website-path": portal["website_path"],
            "Referer": portal["referer"],
        }

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                follow_redirects=True,
                trust_env=False,
                headers=headers,
            ) as client:
                # 检索接口按 CSRF 防跨站，token 必须与同名 Cookie 一致。
                token_resp = await client.post(_CSRF, content=b"{}")
                token_resp.raise_for_status()
                token = _clean(((token_resp.json() or {}).get("data") or {}).get("token"))
                if not token:
                    stage_warning("collect", "字节跳动未取到 csrf token")
                    return []
                resp = await client.post(
                    url,
                    content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    headers={
                        "x-csrf-token": token,
                        "Cookie": f"atsx-csrf-token={quote(token, safe='')}",
                    },
                )
                resp.raise_for_status()
                payload = resp.json() or {}
        except Exception as exc:
            stage_warning(
                "collect",
                "字节跳动检索失败",
                type="校招" if recruit_type == "campus" else "社招",
                keyword=keyword,
                error=exc,
            )
            return []

        data = payload.get("data") or {}
        items = data.get("job_post_list") or []
        stage_info(
            "collect",
            "字节跳动检索",
            type="校招" if recruit_type == "campus" else "社招",
            keyword=keyword,
            city=brief.city or "-",
            count=data.get("count"),
            posts=len(items),
        )

        picked: list[dict] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            job_id = _clean(item.get("id"))
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            picked.append(item)
            if len(picked) >= limit:
                break
        if not picked:
            return []

        hits: list[Hit] = []
        for item in picked:
            job_id = _clean(item.get("id"))
            hits.append(
                Hit(
                    url=(
                        f"{_DETAIL.format(job_id=job_id)}"
                        f"?portal_type={portal_type}&with_recommend=true"
                    ),
                    title=_clean(item.get("title") or item.get("job_title"), 120) or job_id,
                    published=_published(item.get("publish_time") or item.get("create_time")),
                )
            )
        stage_info(
            "collect",
            "字节跳动命中",
            type="校招" if recruit_type == "campus" else "社招",
            count=len(hits),
            keyword=keyword,
            city=brief.city or "-",
        )
        return hits


register(BytedanceSource())
