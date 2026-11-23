"""市场洞察的纯函数工具：简报归一化、兜底检索词、薪资/技能归一、证据格式化。"""

import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from agents.resume.marker.schemas import Brief, ExtraUrl, MarketRequest
from agents.resume.marker.utils.dims import FIXED_DIMS, MAX_PAGE_CHARS, MIN_PAGE_CHARS, dim_label

TIME_WINDOW_LABELS = {
    "3m": "近 3 个月",
    "6m": "近 6 个月",
    "12m": "近 12 个月",
    "3y": "近 3 年",
}

_TIME_WINDOW_ALIASES = {
    "3 个月": "3m",
    "近3个月": "3m",
    "近 3 个月": "3m",
    "6 个月": "6m",
    "近6个月": "6m",
    "近 6 个月": "6m",
    "12 个月": "12m",
    "近12个月": "12m",
    "近 12 个月": "12m",
    "1 年": "12m",
    "近1年": "12m",
    "3 年": "3y",
    "近3年": "3y",
    "近 3 年": "3y",
}

_TIME_WINDOW_MONTHS = {"3m": 3, "6m": 6, "12m": 12, "3y": 36}

# 自定义窗口：18m / 18个月 / 近 18 个月 / 2y / 2年。数字最多 3 位，避免把年份当月份。
_TIME_WINDOW_RE = re.compile(
    r"^(?:近|最近)?\s*(\d{1,3})\s*(个月|月|m|months?|年|y|years?)?$",
    re.IGNORECASE,
)


def _parse_time_window_months(value: str) -> int | None:
    """把自定义窗口解析成月数；无法识别或非正数时返回 None。"""
    match = _TIME_WINDOW_RE.match(value)
    if not match:
        return None
    number = int(match.group(1))
    unit = (match.group(2) or "个月").lower()
    months = number * 12 if unit in {"年", "y", "year", "years"} else number
    return months if months > 0 else None


def time_window_label(value: str) -> str:
    raw = (value or "").strip()
    key = _TIME_WINDOW_ALIASES.get(raw, raw)
    label = TIME_WINDOW_LABELS.get(key)
    if label:
        return label
    months = _parse_time_window_months(raw)
    return f"近 {months} 个月" if months else (raw or "时间不限")


def time_window_range(value: str, today=None) -> str:
    """把 3m / 6m / 12m / 3y 或自定义月数换算成绝对年月区间（如 2025.11-2026.11）。

    日期由后端算好写进 brief，避免模型自己推算「现在是哪年哪月」时算错。
    """
    start = time_window_start(value, today)
    if start is None:
        return ""
    end = today or datetime.now().date()
    return f"{start.year}.{start.month:02d}-{end.year}.{end.month:02d}"


def time_window_start(value: str, today=None) -> date | None:
    """时间窗口的起始日：用于丢弃检索结果里明显过期的页面。

    入参既可以是 3m / 6m / 12m / 3y、自定义 18m / 2y，也可以是 brief 里的
    展示名「近 3 个月」「近 18 个月」。时间不限或无法识别时返回 None，表示不做日期过滤。
    """
    raw = (value or "").strip()
    months = _TIME_WINDOW_MONTHS.get(_TIME_WINDOW_ALIASES.get(raw, raw))
    if months is None:
        months = _parse_time_window_months(raw)
    if not months:
        return None
    # 用服务器本地日期：UTC 在月初凌晨会算到上一个月。
    end = today or datetime.now().date()
    total = end.year * 12 + end.month - 1 - months
    year, month = divmod(total, 12)
    return date(year, month + 1, 1)


# 招聘站链接的跟踪参数：同一岗位会因这些参数不同而看起来像不同页面。
_TRACKING_PARAMS = {"lid", "securityid", "ka", "source", "seorefer"}


def normalize_url(url: str) -> str:
    """URL 合并键：判断两个链接是不是同一页。

    忽略大小写、www、锚点、末尾斜杠与跟踪参数，剩下的 query 排序；
    只用于去重，输出给前端的仍是原始 URL。
    """
    raw = str(url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw if "://" in raw else f"https://{raw}")
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAMS
    )
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), ""))


def strip_city(query: str, city: str) -> str:
    """从检索词里去掉城市名；只用于非招聘维度。"""
    name = (city or "").strip()
    text = str(query or "")
    if not name or not text:
        return text.strip()
    cleaned = re.sub(rf"\s*{re.escape(name)}\s*", " ", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" \t,，、·/")


_DIRECTION_ALIASES = {
    "jobs": "jobs",
    "招聘": "jobs",
    "招聘矩阵": "jobs",
    "trend": "trend",
    "技术": "trend",
    "技术矩阵": "trend",
    "技术栈": "trend",
    "技术趋势": "trend",
    "other": "other",
    "其他": "other",
}


def source_direction(value: str) -> str:
    """把前端标签收成采集维度：jobs / trend / other。"""
    raw = (value or "").strip()
    return _DIRECTION_ALIASES.get(raw.lower(), _DIRECTION_ALIASES.get(raw, "other"))


def normalize_request(request: MarketRequest) -> Brief:
    """把前端请求收成后端统一使用的简报。

    - 简历为空 => mode A（不做简历对照）；有简历 => mode B。
    - 城市为空表示不限；岗位/年限为空交给 planner 反问补全。
    - `direction` 是用户希望 AI 回答的内容，原样保留给 planner 和后续所有阶段。
    - 采集方式收成 {方式 id: {设置键: 值}}，没有可用项时回落到 SearXNG。
    - extra_urls 按 URL 去重，方向收成 jobs / trend / other。
    """
    has_resume = bool(request.resume)
    # 局部导入：adapters 的 searxng 适配器依赖本模块的 normalize_url。
    from agents.resume.marker.tools.adapters import get_source

    collector: dict[str, dict[str, str]] = {}
    for name, settings in request.collector.items():
        key = (name or "").strip()
        if not key:
            continue
        collector.setdefault(key, {}).update(
            {
                str(setting).strip(): str(value).strip()
                for setting, value in (settings or {}).items()
                if str(setting).strip()
            }
        )

    sources: dict[str, dict[str, str]] = {}
    for name, settings in request.sources.items():
        key = (name or "").strip()
        if not key:
            continue
        # key 统一成适配器展示名，planner 拼检索词时可以直接用。
        source = get_source(key)
        label = source.label if source is not None else key
        clean = {
            str(setting).strip(): str(value).strip()
            for setting, value in (settings or {}).items()
            if str(setting).strip()
        }
        sources.setdefault(label, {}).update(clean)

    extra_urls: list[ExtraUrl] = []
    seen_urls: set[str] = set()
    for item in request.extra_urls:
        url = (item.url or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        extra_urls.append(
            ExtraUrl(
                url=url,
                direction=source_direction(item.direction),
                note=(item.note or "").strip(),
            )
        )
    return Brief(
        target_role=request.target_role.strip(),
        city=(request.city or "").strip(),
        experience=(request.experience or "").strip(),
        direction=(request.direction or "").strip(),
        time_window=time_window_label(request.time_range),
        date_range=time_window_range(request.time_range),
        collector=collector or {"searxng": {}},
        sources=sources,
        extra_urls=extra_urls,
        has_resume=has_resume,
        mode="B" if has_resume else "A",
    )


def _city_part(brief: Brief) -> str:
    return f" {brief.city}" if brief.city else ""


def dim_ids(brief: Brief) -> list[str]:
    """参与本次调研的维度：固定 jobs / trend + 用户选择的动态方面。"""
    fixed = list(FIXED_DIMS)
    return fixed + [item for item in brief.aspects if item not in fixed]


def fallback_groups(brief: Brief, dims: list[str] | None = None) -> list[dict]:
    """planner 失败或输出缺组时的兜底检索词；维度数量由用户选择决定。

    用户填写的 `direction` 是希望 AI 回答的问题，兜底检索词必须把它带上；
    否则模型不可用时整轮答案会退回通用岗位信息，完全答非所问。
    """
    dims = list(dims or dim_ids(brief))
    role = brief.target_role or "目标岗位"
    city = _city_part(brief)
    window = brief.date_range or brief.time_window or "近期"
    sources = " ".join(list(brief.sources)[:3])
    source_hint = f" {sources}" if sources else ""
    question = (brief.direction or "").strip()
    question_part = f" {question}" if question else ""

    base = {
        "jobs": [
            f"{role}{city}{question_part} 招聘 岗位职责 任职要求{source_hint}",
            f"{role}{city}{question_part} 薪资 {window}",
            f"{role}{city}{question_part} 技术栈 要求",
        ],
        "trend": [
            f"{role}{question_part} 技术栈 要求 {window}",
            f"{role}{question_part} 常用框架 工具链 最佳实践",
            f"{role}{question_part} 官方文档 release notes",
        ],
    }

    groups: list[dict] = []
    for dim in dims:
        label = dim_label(dim, brief.aspect_labels)
        # 只有招聘维度带城市；趋势 / 动态方面是全国口径的信息，混入城市会漏掉大部分来源。
        queries = base.get(dim) or [
            f"{role} {label}{question_part} 真实情况",
            f"{role} {label}{question_part} 经验 分享",
            f"{role} {label}{question_part} {window}",
        ]
        groups.append({"id": dim, "label": label, "queries": queries})
    return groups


_ALIASES = {
    "react.js": "react",
    "reactjs": "react",
    "vue.js": "vue",
    "vuejs": "vue",
    "nextjs": "next.js",
    "next": "next.js",
    "node": "node.js",
    "nodejs": "node.js",
    "ts": "typescript",
    "js": "javascript",
    "golang": "go",
    "k8s": "kubernetes",
    "postgres": "postgresql",
    "springboot": "spring boot",
    "spring-boot": "spring boot",
    "tailwindcss": "tailwind css",
    "tailwind": "tailwind css",
}


def normalize_skill(name: object) -> str:
    """技能词归一：小写、去空白、合并常见别名。返回用于去重的 key。"""
    text = str(name or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"[\s/]+", "", text)
    return _ALIASES.get(text, text)


_RANGE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[kK千]?\s*[-~—–至]\s*(\d+(?:\.\d+)?)\s*([kK千万wW])?"
)
_SINGLE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([kK千万wW])")
_MONTHS_RE = re.compile(r"(\d+)\s*薪")
_ANNUAL_RE = re.compile(r"年薪|年包|/年|每年")
_DAILY_RE = re.compile(r"元?\s*/\s*天|日薪|每天")


def _unit_value(number: float, unit: str) -> float:
    unit = (unit or "").lower()
    if unit in ("k", "千"):
        return number * 1000
    if unit in ("万", "w"):
        return number * 10000
    return number


def parse_salary(raw: str) -> dict:
    """把常见薪资写法换算成月薪人民币。

    支持 `20-35K·14薪`、`1.5-2.5万`、`年薪 30-50 万`、`400-600 元/天`。
    解析不出就返回空值，保留 raw；不要猜。
    """
    text = str(raw or "").strip()
    result = {
        "min": None,
        "max": None,
        "median": None,
        "months": None,
        "raw": text,
    }
    if not text:
        return result

    months_match = _MONTHS_RE.search(text)
    if months_match:
        result["months"] = int(months_match.group(1))

    annual = bool(_ANNUAL_RE.search(text))
    daily = bool(_DAILY_RE.search(text))

    numbers: list[float] = []
    range_match = _RANGE_RE.search(text)
    if range_match:
        low, high, unit = range_match.groups()
        # 没有单位时，从整段文本里找一次单位（如「20-35K」里的 K 被第二段吃掉）
        if not unit:
            unit = "k" if re.search(r"[kK]", text) else "万" if re.search(r"[万wW]", text) else ""
        numbers = [_unit_value(float(low), unit), _unit_value(float(high), unit)]
    else:
        single_match = _SINGLE_RE.search(text)
        if single_match:
            number, unit = single_match.groups()
            numbers = [_unit_value(float(number), unit)]

    if not numbers:
        return result

    if daily:
        numbers = [value * 21.75 for value in numbers]
    elif annual:
        numbers = [value / 12 for value in numbers]

    low, high = min(numbers), max(numbers)
    result["min"] = int(round(low))
    result["max"] = int(round(high))
    result["median"] = int(round((low + high) / 2))
    return result


def clean_text(value: object, limit: int = 0) -> str:
    """压缩空白、去掉零宽字符；可选截断。"""
    text = str(value or "")
    text = text.replace("​", "").replace("﻿", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    return text[:limit] if limit else text


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _clip_middle(text: str, limit: int) -> str:
    """超长正文保留头尾：页尾常放薪资表、发布时间、招聘要求，只截头会丢掉。"""
    if len(text) <= limit:
        return text
    head = int(limit * 0.7)
    tail = limit - head
    return f"{text[:head]}\n……\n{text[-tail:]}" if tail > 0 else text[:head]


def _pick_even(pages: list[dict], keep: int) -> list[dict]:
    """页数超过预算能承载的数量时，按站点轮流挑，避免单一站点占满名额。

    同站点最多占 keep 的 1/6（站点不足 6 个时按站点数均分），其余页面仍进
    来源索引，只是不给模型读。
    """
    by_site: dict[str, list[dict]] = {}
    for page in pages:
        by_site.setdefault(str(page.get("site") or "未知"), []).append(page)
    sites = max(1, len(by_site))
    per_site = max(1, -(-keep // min(sites, 6)))
    picked: list[dict] = []
    depth = 0
    while len(picked) < keep:
        added = False
        for bucket in by_site.values():
            if len(picked) >= keep:
                break
            if depth >= len(bucket) or depth >= per_site:
                continue
            picked.append(bucket[depth])
            added = True
        if not added:
            break
        depth += 1
    return picked


def format_pages(pages: list[dict], max_total_chars: int) -> str:
    """把采集页按证据编号拼成模型输入。

    抓取页数可以大于模型读得下的页数，因此这里按预算等量压缩：所有页都保留，
    每页分到的字符数 = 预算 / 页数（限制在 MIN_PAGE_CHARS ~ MAX_PAGE_CHARS）。
    页数多到连下限都摊不下时，按站点轮流挑选预算放得下的数量，保证样本不被
    单一站点垄断；未入选的页仍会出现在来源索引里。
    """
    if not pages:
        return ""

    # 头部（编号 / 标题 / url / 站点 / 时间）也要占预算，先扣掉再摊正文。
    head_allowance = 200
    total = max_total_chars

    def per_page_for(count: int) -> int:
        return (total - head_allowance * count) // max(1, count)

    chosen = pages
    if per_page_for(len(pages)) < MIN_PAGE_CHARS:
        keep = max(1, total // (MIN_PAGE_CHARS + head_allowance))
        chosen = _pick_even(pages, keep)
    per_page = min(max(per_page_for(len(chosen)), MIN_PAGE_CHARS), MAX_PAGE_CHARS)

    blocks: list[str] = []
    used = 0
    for page in chosen:
        text = _clip_middle(clean_text(page.get("text"), MAX_PAGE_CHARS), per_page)
        if not text:
            continue
        published = str(page.get("published") or "").strip()
        head = (
            f"[{page.get('evidence_id')}] {page.get('title') or page.get('url')}\n"
            f"url: {page.get('url')}\n"
            f"site: {page.get('site') or '未知'}"
            f"{'  (仅摘要)' if page.get('excerpt') else ''}"
            f"{f'  发布时间: {published}' if published else ''}\n"
        )
        block = f"{head}{text}"
        if used + len(block) > max_total_chars and blocks:
            break
        blocks.append(block)
        used += len(block)
    return "\n\n---\n\n".join(blocks)


def valid_evidence_ids(pages: list[dict]) -> set[str]:
    return {str(page.get("evidence_id")) for page in pages if page.get("evidence_id")}


def filter_evidence(evidence_ids: list[str], valid: set[str]) -> list[str]:
    return [eid for eid in evidence_ids if eid in valid]


_COVERAGE_RANK = {"none": 0, "partial": 1, "full": 2}


def merge_coverage(*values: str) -> str:
    """取最保守的覆盖度：页面只有摘要时，模型说 full 也要降成 partial。"""
    candidates = [value for value in values if value in _COVERAGE_RANK]
    if not candidates:
        return "none"
    return min(candidates, key=lambda value: _COVERAGE_RANK[value])
