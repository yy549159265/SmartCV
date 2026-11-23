"""腾讯招聘适配器：按 recruitType 走社招 / 校招的公开岗位接口。

输入：检索词列表 + 条数上限 + 本次简报 + 来源设置
输出：Hit 列表（url / title / published）

settings 由前端「内置来源」面板透传，键和值都是英文枚举：
- recruitType: "experienced"（社招）/ "campus"（校招）；缺省、清空或其它值一律返回空。

两站的检索页都是前端渲染，直接 GET 只能拿到空壳，所以先请求站内的岗位检索
接口拿岗位列表，再用「岗位详情接口」作为待抓取链接（返回 JSON，含职责与要求）。
检索页 URL 只作为 Referer 使用，保证站点侧看到的是正常的搜索来源。
"""

import os
import re
import time
from urllib.parse import quote

import httpx

from agents.resume.marker.schemas.market import Brief
from agents.resume.marker.tools.adapters import register
from agents.resume.marker.tools.adapters._keywords import (
    clean as _clean,
    job_keywords as _job_keywords,
    keyword_variants as _keyword_variants,
)
from agents.resume.marker.tools.adapters.base import Hit, Source
from agents.resume.marker.utils.stage_log import stage_info, stage_warning

_TIMEOUT = float(os.getenv("TENCENT_TIMEOUT", "12"))
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}

_EXPERIENCED_SEARCH = "https://careers.tencent.com/search.html"
_EXPERIENCED_QUERY = "https://careers.tencent.com/tencentcareer/api/post/Query"
_EXPERIENCED_DETAIL = "https://careers.tencent.com/tencentcareer/api/post/ByPostId"

_CAMPUS_SEARCH = "https://join.qq.com/post.html"
_CAMPUS_QUERY = "https://join.qq.com/api/v1/position/searchPosition"
_CAMPUS_DETAIL = "https://join.qq.com/api/v1/jobDetails/getJobDetailsByPostId"

# 社招城市编码（搜索页 query=co_1,ci_<code>，co_1 固定为中国）
_EXPERIENCED_CITIES = {
    "北京": "2",
    "上海": "3",
    "广州": "5",
    "深圳": "1",
    "成都": "8",
    "杭州": "7",
    "中国香港": "37",
    "中国台北": "46",
    "中国澳门": "87",
    "武汉": "6",
    "长沙": "18",
    "重庆": "14",
    "长春": "25",
    "天津": "31",
    "大连": "39",
    "福州": "4",
    "贵阳": "17",
    "哈尔滨": "20",
    "合肥": "30",
    "呼和浩特": "23",
    "济南": "24",
    "昆明": "16",
    "兰州": "21",
    "南宁": "27",
    "南昌": "19",
    "南京": "11",
    "沈阳": "10",
    "石家庄": "28",
    "太原": "26",
    "乌鲁木齐": "22",
    "西安": "9",
    "西宁": "15",
    "厦门": "29",
    "郑州": "12",
    "青岛": "47",
    "无锡": "48",
    "烟台": "49",
    "苏州": "50",
    "海口": "53",
    "淄博": "54",
    "宁波": "55",
    "银川": "56",
    "扬州": "57",
    "汕尾": "58",
    "顺德": "84",
    "桂林": "86",
    "珠海": "89",
    "贵安": "91",
    "佛山": "93",
    "保定": "94",
    "南通": "96",
    "拉萨": "97",
    "清远": "2601",
    "三亚": "102",
    "东莞": "107",
    "张家口": "2602",
    "雄安新区": "95",
    "澄迈县": "78",
    "霍尔果斯": "92",
}

# 校招城市编码（搜索页 query=w_<code>，c_t=1 固定为中国）
_CAMPUS_CITIES = {
    "深圳": "1",
    "北京": "2",
    "广州": "5",
    "上海": "3",
    "成都": "8",
    "武汉": "6",
    "中国香港": "37",
    "重庆": "14",
    "杭州": "7",
    "合肥": "30",
    "南京": "11",
    "西安": "9",
    "厦门": "29",
    "芜湖": "190",
    "韶关": "276",
}

_RECRUIT_TYPE_VALUES = ("experienced", "campus")


def _city_code(city: str, table: dict[str, str]) -> str:
    """城市名 → 站点编码；先精确匹配，再按包含关系兜住「深圳总部」「香港」这类写法。"""
    name = re.sub(r"(总部|市)$", "", _clean(city))
    if not name:
        return ""
    if name in table:
        return table[name]
    for key, code in table.items():
        if key in name or name in key:
            return code
    return ""


def _experienced_search_url(code: str, keyword: str) -> str:
    query = f"co_1,ci_{code}" if code else "co_1"
    return f"{_EXPERIENCED_SEARCH}?query={query}&keyword={quote(keyword)}"


def _campus_search_url(code: str, keyword: str) -> str:
    query = f"&query=w_{code}" if code else ""
    return f"{_CAMPUS_SEARCH}?keyword={quote(keyword)}{query}&c_t=1"


async def _experienced(client: httpx.AsyncClient, keyword: str, city: str, limit: int) -> list[Hit]:
    """社招：careers.tencent.com 的 Query 接口，一条岗位一个详情链接。"""
    code = _city_code(city, _EXPERIENCED_CITIES)
    hits: list[Hit] = []
    seen: set[str] = set()
    for term in _keyword_variants(keyword):
        try:
            resp = await client.get(
                _EXPERIENCED_QUERY,
                params={
                    "timestamp": str(int(time.time() * 1000)),
                    "countryId": "",
                    "cityId": code,
                    "bgIds": "",
                    "productId": "",
                    "categoryId": "",
                    "parentCategoryId": "",
                    "attrId": "",
                    "keyword": term,
                    "pageIndex": 1,
                    "pageSize": max(1, min(limit, 100)),
                    "language": "zh-cn",
                    "area": "cn",
                },
                headers={"Referer": _experienced_search_url(code, term)},
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("Data") or {}
            posts = data.get("Posts") or []
        except Exception as exc:
            stage_warning("collect", "腾讯社招检索失败", keyword=term, error=exc)
            continue
        # 接口对查不到的词返回 Code 200 + Count 0 + Posts null，换下一个候选。
        stage_info(
            "collect",
            "腾讯社招检索",
            keyword=term,
            city=code or "-",
            count=data.get("Count"),
            posts=len(posts),
        )
        for item in posts:
            if not isinstance(item, dict):
                continue
            post_id = _clean(item.get("PostId"))
            if not post_id or post_id in seen:
                continue
            seen.add(post_id)
            hits.append(
                Hit(
                    url=f"{_EXPERIENCED_DETAIL}?postId={post_id}&language=zh-cn",
                    title=_clean(item.get("RecruitPostName"), 120) or post_id,
                    published=_clean(item.get("LastUpdateTime"), 40),
                )
            )
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    return hits


async def _campus(client: httpx.AsyncClient, keyword: str, city: str, limit: int) -> list[Hit]:
    """校招：join.qq.com 的 searchPosition 接口，一条岗位一个详情链接。"""
    code = _city_code(city, _CAMPUS_CITIES)
    hits: list[Hit] = []
    seen: set[str] = set()
    for term in _keyword_variants(keyword):
        try:
            resp = await client.post(
                _CAMPUS_QUERY,
                json={
                    "projectIdList": [],
                    "projectMappingIdList": [],
                    "keyword": term[:30],
                    "bgList": [],
                    "workCountryType": 1,
                    "workCityList": [code] if code else [],
                    "recruitCityList": [],
                    "positionFidList": [],
                    "pageIndex": 1,
                    "pageSize": max(1, min(limit, 100)),
                },
                headers={"Referer": _campus_search_url(code, term)},
            )
            resp.raise_for_status()
            data = (resp.json() or {}).get("data") or {}
            posts = data.get("positionList") or []
        except Exception as exc:
            stage_warning("collect", "腾讯校招检索失败", keyword=term, error=exc)
            continue
        stage_info(
            "collect",
            "腾讯校招检索",
            keyword=term,
            city=code or "-",
            count=data.get("count"),
            posts=len(posts),
        )
        for item in posts:
            if not isinstance(item, dict):
                continue
            post_id = _clean(item.get("postId"))
            if not post_id or post_id in seen:
                continue
            seen.add(post_id)
            hits.append(
                Hit(
                    url=f"{_CAMPUS_DETAIL}?postId={post_id}",
                    title=_clean(item.get("positionTitle"), 120) or post_id,
                    published="",
                )
            )
            if len(hits) >= limit:
                break
        if len(hits) >= limit:
            break
    return hits


class TencentSource(Source):
    id = "tencent"
    label = "腾讯"
    # 旧前端存过「腾讯招聘」，按别名继续解析，避免历史设置失效。
    aliases = ("tencent", "腾讯招聘")
    dims = ("jobs",)  # 招聘站只服务 jobs 维度

    async def urls(
        self,
        queries: list[str],
        *,
        limit: int,
        brief: Brief,
        settings: dict[str, str] | None = None,
    ) -> list[Hit]:
        # 检索词优先用规划输出的 queries（再确定性清洗一遍），city 作为站点筛选项；
        # recruitType 决定走哪个招聘站。
        if limit <= 0:
            return []
        recruit_type = _clean((settings or {}).get("recruitType")).casefold()
        if recruit_type not in _RECRUIT_TYPE_VALUES:
            stage_info("collect", "腾讯跳过", reason="未配置招聘类型")
            return []
        keyword = _job_keywords(queries, brief.target_role)
        if not keyword:
            stage_info("collect", "腾讯跳过", reason="缺少检索词")
            return []

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                follow_redirects=True,
                trust_env=False,
                headers=_HEADERS,
            ) as client:
                if recruit_type == "campus":
                    hits = await _campus(client, keyword, brief.city, limit)
                else:
                    hits = await _experienced(client, keyword, brief.city, limit)
        except Exception as exc:
            stage_warning("collect", "腾讯检索失败", type="校招" if recruit_type == "campus" else "社招", error=exc)
            return []
        stage_info(
            "collect",
            "腾讯命中",
            type="校招" if recruit_type == "campus" else "社招",
            count=len(hits),
            keyword=keyword,
            city=brief.city or "-",
        )
        return hits


register(TencentSource())
