"""阿里巴巴招聘适配器：调用社招 / 校招站点的岗位检索接口。

输入：检索词列表 + 条数上限 + 本次简报 + 来源设置
输出：Hit 列表（url / title / published）

settings 由前端「内置来源」面板透传，键和值都是英文枚举：
- recruitType: "experienced"（社招，talent-holding.alibaba.com）/
  "campus"（校招，campus-talent.alibaba.com）；缺省、清空或其它值一律返回空。

检索接口是 POST `/position/search?_csrf=<token>`，防跨站用的 token 就是站点
任意页面下发的 `XSRF-TOKEN` Cookie，这里先 GET 首页拿 Cookie，再把同一个值
放进 `_csrf` query 和 `X-XSRF-TOKEN` 请求头，不依赖任何固定值。

校招的 `batchId` 也不写死：先调 `/searchCondition/listBatch` 取当前应届生批次
（没有就用实习 / 顶尖人才批次）。社招 `batchId` 留空即可。

brief.city 按 `_CITIES` 换成站点要求的写法（校招用中文城市名，社招用行政区
编码），为空或不在表里直接返回空，不做全国兜底。

检索结果的 id 拼成站点详情页 URL 交给抓取阶段；校招没有 `positionUrl`，用
`/campus/position/<id>?positionId=<id>`，社招优先用接口返回的相对路径。
"""

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

import httpx

from agents.resume.marker.schemas.market import Brief
from agents.resume.marker.tools.adapters import register
from agents.resume.marker.tools.adapters._keywords import clean as _clean, job_keywords as _job_keywords
from agents.resume.marker.tools.adapters.base import Hit, Source
from agents.resume.marker.utils.stage_log import stage_info, stage_warning

_TIMEOUT = float(os.getenv("ALIBABA_TIMEOUT", "12"))
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
}
# 两个站点接口路径相同，但渠道和详情页路由不同。
_SITES = {
    "experienced": {
        "base": "https://talent-holding.alibaba.com",
        "channel": "group_official_site",
        "referer": "https://talent-holding.alibaba.com/position",
        "detail": "https://talent-holding.alibaba.com/off-campus/position-detail?positionId={job_id}",
    },
    "campus": {
        "base": "https://campus-talent.alibaba.com",
        "channel": "campus_group_official_site",
        "referer": "https://campus-talent.alibaba.com/campus/position",
        "detail": "https://campus-talent.alibaba.com/campus/position/{job_id}?positionId={job_id}",
    },
}

# 站点支持的城市：显示名 → 社招行政区编码（校招直接用显示名）。
_CITIES = {
    "杭州": "330100",
    "北京": "110100",
    "上海": "310100",
    "广州": "440100",
    "深圳": "440300",
    "成都": "510100",
    "重庆": "500100",
    "南京": "320100",
    "武汉": "420100",
    "中国香港": "HKG",
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


async def _csrf(client: httpx.AsyncClient, base: str) -> str:
    """GET 任意页面，从下发的 XSRF-TOKEN Cookie 取本次请求要用的 csrf。"""
    await client.get(f"{base}/")
    return _clean(client.cookies.get("XSRF-TOKEN"))


async def _post(client: httpx.AsyncClient, base: str, path: str, token: str, body: dict) -> dict:
    resp = await client.post(
        f"{base}{path}?_csrf={quote(token, safe='')}",
        json=body,
        headers={"X-XSRF-TOKEN": token},
    )
    resp.raise_for_status()
    return resp.json() or {}


def _detail_url(raw: str, base: str, fallback: str) -> str:
    """详情页统一成干净 URL：补全相对路径，去掉仅用于本次检索追踪的 track_id。"""
    if not raw:
        return fallback
    if raw.startswith("/"):
        raw = base + raw
    parts = urlsplit(raw)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in ("track_id", "trackId")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


async def _campus_batch(client: httpx.AsyncClient, base: str, token: str) -> int:
    """取当前校招批次 id：优先应届生，其次实习、顶尖人才。"""
    payload = await _post(client, base, "/searchCondition/listBatch", token, {})
    content = payload.get("content") or {}
    for key in ("graduate", "internship", "topTalentPlan"):
        for item in content.get(key) or []:
            if isinstance(item, dict) and item.get("id"):
                return int(item["id"])
    return 0


def _search_body(
    site: dict,
    *,
    recruit_type: str,
    city: str,
    region: str,
    keyword: str,
    page_size: int,
    batch_id: int = 0,
) -> dict:
    if recruit_type == "campus":
        return {
            "batchId": batch_id,
            "searchKey": keyword,
            "pageIndex": 1,
            "pageSize": page_size,
            # 校招接口要中文城市名。
            "regions": city,
            "channel": site["channel"],
            "language": "zh",
        }
    return {
        "channel": site["channel"],
        "language": "zh",
        "batchId": "",
        "categories": "",
        "deptCodes": [],
        "key": keyword,
        "pageIndex": 1,
        "pageSize": page_size,
        # 社招接口要行政区编码。
        "regions": region,
        "subCategories": "",
        "shareType": "",
        "shareId": "",
        "myReferralShareCode": "",
    }


async def _search(
    client: httpx.AsyncClient,
    site: dict,
    token: str,
    body: dict,
) -> tuple[int, list[dict]]:
    """执行一次检索，返回（命中总数，岗位列表）。"""
    payload = await _post(client, site["base"], "/position/search", token, body)
    content = payload.get("content") or {}
    items = [item for item in (content.get("datas") or []) if isinstance(item, dict)]
    return int(content.get("totalCount") or 0), items


class AlibabaSource(Source):
    id = "alibaba"
    label = "阿里巴巴"
    aliases = ("alibaba", "阿里")
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
        site = _SITES.get(recruit_type)
        if not site:
            stage_info("collect", "阿里巴巴跳过", reason="未配置招聘类型")
            return []
        city = _clean(brief.city)
        region = _CITIES.get(city)
        if not region:
            stage_info("collect", "阿里巴巴跳过", reason="城市未命中", city=city or "-")
            return []
        keyword = _job_keywords(queries, brief.target_role)
        if not keyword:
            stage_info("collect", "阿里巴巴跳过", reason="缺少检索词")
            return []

        base = site["base"]
        page_size = max(1, min(limit, 50))
        headers = {**_HEADERS, "Origin": base, "Referer": site["referer"]}

        label = "校招" if recruit_type == "campus" else "社招"
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                follow_redirects=True,
                trust_env=False,
                headers=headers,
            ) as client:
                token = await _csrf(client, base)
                if not token:
                    stage_warning("collect", "阿里巴巴未取到 csrf token")
                    return []
                batch_id = 0
                if recruit_type == "campus":
                    batch_id = await _campus_batch(client, base, token)
                    if not batch_id:
                        stage_warning("collect", "阿里巴巴未取到校招批次")
                        return []

                def body_for(text: str) -> dict:
                    return _search_body(
                        site,
                        recruit_type=recruit_type,
                        city=city,
                        region=region,
                        keyword=text,
                        page_size=page_size,
                        batch_id=batch_id,
                    )

                total, items = await _search(client, site, token, body_for(keyword))
                stage_info(
                    "collect",
                    "阿里巴巴检索",
                    type=label,
                    keyword=keyword,
                    city=city or "-",
                    count=total,
                    posts=len(items),
                )
                # 站点按标题字面匹配，多词关键词容易一条都不中；无结果时按分词再检索一轮。
                words = keyword.split()
                if not items and len(words) > 1:
                    merged: list[dict] = []
                    seen_ids: set[str] = set()
                    for word in words:
                        if len(merged) >= limit:
                            break
                        _, extra = await _search(client, site, token, body_for(word))
                        for item in extra:
                            job_id = _clean(item.get("id"))
                            if job_id and job_id not in seen_ids:
                                seen_ids.add(job_id)
                                merged.append(item)
                    if merged:
                        stage_info(
                            "collect",
                            "阿里巴巴按分词重试",
                            type=label,
                            keyword=keyword,
                            words="、".join(words),
                        )
                        items = merged
        except Exception as exc:
            stage_warning("collect", "阿里巴巴检索失败", type=label, keyword=keyword, error=exc)
            return []

        hits: list[Hit] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            job_id = _clean(item.get("id"))
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)
            hits.append(
                Hit(
                    url=_detail_url(
                        _clean(item.get("positionUrl")),
                        base,
                        site["detail"].format(job_id=job_id),
                    ),
                    title=_clean(item.get("name"), 120) or job_id,
                    published=_published(item.get("publishTime") or item.get("modifyTime")),
                )
            )
            if len(hits) >= limit:
                break
        stage_info(
            "collect",
            "阿里巴巴命中",
            type="校招" if recruit_type == "campus" else "社招",
            count=len(hits),
            keyword=keyword,
            city=city or "-",
        )
        return hits


register(AlibabaSource())
