"""华为招聘适配器：调用官网公开的岗位检索接口。

输入：检索词列表 + 条数上限 + 本次简报 + 来源设置
输出：Hit 列表（url / title / published）

settings 由前端「内置来源」面板透传，键和值都是英文枚举：
- recruitType: "experienced"（社招，jobType=SR）/ "campus"（校招，jobType=CR）；
  缺省、清空或其它值一律返回空。

接口按 keyWord 模糊检索，返回的岗位详情页是前端渲染，所以 Hit 指向
`/cn/job-details?advertisementId=<id>`，由抓取阶段读取。
brief.city 按 `_CITY_ADDRESSES` 换成站点要求的 `China\<省>-<市>` 写法后
作为 jobAddress 传入，查不到就不限城市。
"""

import os
import re

import httpx

from agents.resume.marker.schemas.market import Brief
from agents.resume.marker.tools.adapters import register
from agents.resume.marker.tools.adapters._keywords import clean as _clean, job_keywords as _job_keywords
from agents.resume.marker.tools.adapters.base import Hit, Source
from agents.resume.marker.utils.stage_log import stage_info, stage_warning

_TIMEOUT = float(os.getenv("HUAWEI_TIMEOUT", "12"))
_API = (
    "https://apigw-dgg-b0.huawei.com/api/apig/channelhw/recruitmentPosition/pub/getJobPage"
    "?X-HW-ID=app_000000035886"
)
_DETAIL = "https://career.huawei.com/cn/job-details?advertisementId={advertisement_id}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Origin": "https://career.huawei.com",
    "Referer": "https://career.huawei.com/",
    # 网关注入的租户标识，缺了会返回 missing tenant code。
    "x-jalor-tenantalias": "hcm",
    "x-language": "zh_CN",
    "x-hw-id": "app_000000035886",
    "x-referer": "https://career.huawei.com/cn",
}
_RECRUIT_TYPES = {"experienced": "SR", "campus": "CR"}

# 招聘站的城市筛选项：显示名 → jobAddress（站点支持的固定写法）。
_CITY_ADDRESSES = {
    "东莞": r"China\Guangdong-Dongguan",
    "深圳": r"China\Guangdong-Shenzhen",
    "广州": r"China\Guangdong-Guangzhou",
    "上海": r"China\Shanghai-Shanghai",
    "北京": r"China\Beijing-Beijing",
    "武汉": r"China\Hubei-Wuhan",
    "南京": r"China\Jiangsu-Nanjing",
    "苏州": r"China\Jiangsu-Suzhou",
    "西安": r"China\Shaanxi-Xi'an",
    "成都": r"China\Sichuan-Chengdu",
    "杭州": r"China\Zhejiang-Hangzhou",
    "郑州": r"China\Henan-Zhengzhou",
    "呼和浩特": r"China\Nei Mongol-Huhehaote",
    "乌兰察布": r"China\Nei Mongol-Wulanchabu",
    "济南": r"China\Shandong-Jinan",
    "南宁": r"China\Guangxi-Nanning",
    "银川": r"China\Ningxia-Yinchuan",
    "海口": r"China\Hainan-Haikou",
    "贵阳": r"China\Guizhou-Guiyang",
    "沈阳": r"China\Liaoning-Shenyang",
    "天津": r"China\Tianjin-Tianjin",
    "南昌": r"China\Jiangxi-Nanchang",
    "长春": r"China\Jilin-Changchun",
    "福州": r"China\Fujian-Fuzhou",
}


def _city_address(city: str) -> str:
    """城市名 → jobAddress；先精确匹配，再按包含关系兜住「深圳总部」「东莞市」这类写法。"""
    name = re.sub(r"(市|总部)$", "", _clean(city))
    if not name:
        return ""
    if name in _CITY_ADDRESSES:
        return _CITY_ADDRESSES[name]
    for key, address in _CITY_ADDRESSES.items():
        if key in name or name in key:
            return address
    return ""


class HuaweiSource(Source):
    id = "huawei"
    label = "华为"
    aliases = ("huawei", "华为招聘")
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
        job_type = _RECRUIT_TYPES.get(recruit_type)
        if not job_type:
            stage_info("collect", "华为跳过", reason="未配置招聘类型")
            return []
        keyword = _job_keywords(queries, brief.target_role)
        if not keyword:
            stage_info("collect", "华为跳过", reason="缺少检索词")
            return []

        body = {
            "curPage": 1,
            # 列表项带完整职责/要求，限制条数避免响应过大。
            "pageSize": max(1, min(limit, 50)),
            "jobType": job_type,
            "keyWord": keyword,
        }
        # 用户给了城市且站点支持时按城市过滤，查不到就保持全国检索。
        address = _city_address(brief.city)
        if address:
            body["jobAddress"] = address
        elif _clean(brief.city):
            stage_info("collect", "华为城市未识别，按全国检索", city=_clean(brief.city))
        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT,
                follow_redirects=True,
                trust_env=False,
                headers=_HEADERS,
            ) as client:
                resp = await client.post(_API, json=body)
                resp.raise_for_status()
                payload = resp.json() or {}
        except Exception as exc:
            stage_warning(
                "collect",
                "华为检索失败",
                type="校招" if job_type == "CR" else "社招",
                keyword=keyword,
                error=exc,
            )
            return []

        data = payload.get("data") or {}
        page = data.get("pageVO") or {}
        items = data.get("result") or []
        stage_info(
            "collect",
            "华为检索",
            type="校招" if job_type == "CR" else "社招",
            keyword=keyword,
            city=brief.city or "-",
            count=page.get("totalRows"),
            posts=len(items),
        )

        hits: list[Hit] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            advertisement_id = _clean(item.get("advertisementId"))
            if not advertisement_id or advertisement_id in seen:
                continue
            seen.add(advertisement_id)
            hits.append(
                Hit(
                    url=_DETAIL.format(advertisement_id=advertisement_id),
                    title=_clean(item.get("jobName"), 120) or advertisement_id,
                    published=_clean(item.get("lastUpdateDate"), 40),
                )
            )
            if len(hits) >= limit:
                break
        stage_info(
            "collect",
            "华为命中",
            type="校招" if job_type == "CR" else "社招",
            count=len(hits),
            keyword=keyword,
            city=brief.city or "-",
        )
        return hits


register(HuaweiSource())
