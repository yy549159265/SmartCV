"""compose：逐章写报告。

目录 = 岗位概览 + 技能要求 + 本次选择的动态方面各一章 +（简历对照）+ 总结与建议；
动态章节的 id / 标题来自 brief.aspects，没选的方面不会出现空章节。
每章单独流式生成，前端按 `report.section.started` / delta(section) / `report.section`
逐步填充；模型失败或返回空时用同一批事实拼兜底正文，不阻塞报告落盘。
"""

import json
import uuid
from pathlib import Path

from langchain.agents import create_agent

from agents.resume.marker.utils.dims import dim_label, dim_prefix, report_sections
from agents.resume.marker.utils.profile import coverage as profile_coverage
from agents.resume.marker.utils.profile import skill_count
from agents.resume.marker.utils.runner import run_stream, safe_writer
from agents.resume.marker.schemas import Brief
from agents.resume.marker.utils.common import clean_text
from agents.resume.marker.utils.stage_log import stage_warning

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "compose" / "compose.md").read_text(encoding="utf-8")
_MAX_SOURCES_PER_SECTION = 6
# 画像里的枚举只用于结构化筛选，写报告前转成中文，避免 depth / structure 这类值漏进正文。
_GAP_TYPE_LABEL = {
    "skill": "技能缺口",
    "experience": "经验缺口",
    "depth": "深度不足",
    "evidence": "证据不足",
}
_SEVERITY_LABEL = {"high": "严重", "medium": "中等", "low": "轻微"}
# 复杂度 / 优势强度 / 行动优先级共用 high-medium-low 三档。
_LEVEL_LABEL = {"high": "高", "medium": "中", "low": "低"}
_WEAKNESS_LABEL = {
    "result_expression": "成果表达",
    "project_description": "项目描述",
    "responsibility": "职责边界",
    "technical_depth": "技术描述",
    "structure": "结构重点",
}
_REQUIREMENT_LABEL = {
    "must_have": "明确必备",
    "preferred": "明确加分",
    "common": "经常出现",
    "unknown": "未明确",
}
_SALARY_UNIT_LABEL = {"CNY/month": "元/月", "CNY/year": "元/年", "CNY/day": "元/天"}
_TREND_TYPE_LABEL = {
    "rising": "上升",
    "stable": "稳定",
    "declining": "下降",
    "emerging": "新兴",
}


def build_agent(llm):
    return create_agent(model=llm, tools=[])


def section_meta(market: dict, profile: dict | None, has_resume: bool) -> dict[str, dict]:
    """算每个报告章节的覆盖度与样本量。

    动态方面章节的 key 就是维度 id，和本模块的章节 id 保持一致。
    """
    groups = market.get("groups") or {}
    jobs = groups.get("jobs") or {}
    overall = str(market.get("coverage") or "none")

    meta = {
        "overview": {
            "coverage": str(jobs.get("coverage") or "none"),
            "sample_size": int(jobs.get("sample_size") or 0),
        },
        "skills": {
            "coverage": str(jobs.get("coverage") or "none"),
            "sample_size": int(jobs.get("sample_size") or 0),
        },
        "conclusion": {
            "coverage": overall,
            "sample_size": int(market.get("sample_size") or 0),
        },
    }
    for aspect in market.get("aspects") or []:
        dim = str(aspect.get("id") or "")
        if not dim:
            continue
        # 采集阶段的覆盖度/样本量比抽取结果里的更可信（抽取失败也如实反映）。
        meta[dim] = {
            "coverage": str(aspect.get("coverage") or "none"),
            "sample_size": int(aspect.get("sample_size") or 0),
        }
    if has_resume:
        meta["profile"] = {
            "coverage": profile_coverage(profile),
            "sample_size": skill_count(profile),
        }
    return meta


def _money(value: object) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return ""


def _salary_range_text(item: dict) -> str:
    low, high = item.get("min"), item.get("max")
    unit = _SALARY_UNIT_LABEL.get(str(item.get("unit") or ""), str(item.get("unit") or "元/月"))
    if low and high:
        text = f"{_money(low)}-{_money(high)} {unit}"
    elif low:
        text = f"{_money(low)} {unit} 起"
    elif high:
        text = f"{_money(high)} {unit} 以内"
    else:
        return ""
    if item.get("salary_months"):
        text += f" · {int(item['salary_months'])} 薪"
    if item.get("count"):
        text += f"，{int(item['count'])} 个页面提及"
    return text


def _salary_text(jobs: dict) -> str:
    """薪资汇总：只复述结构化区间，不写「N/M」分式。"""
    distribution = jobs.get("job_distribution") or {}
    salary = distribution.get("salary_matrix") or {}
    if not salary:
        return ""
    ranges = [
        text
        for text in (_salary_range_text(item) for item in salary.get("salary_ranges") or [])
        if text
    ]
    if ranges:
        return "；".join(ranges[:4])
    available = salary.get("available_count")
    summary = clean_text(salary.get("summary") or "")
    if available and summary:
        return f"共 {int(available)} 个页面给出明确薪资。{summary}"
    if available:
        return f"共 {int(available)} 个页面给出明确薪资。"
    return summary


def _aspect(market: dict, dim: str) -> dict:
    return next(
        (item for item in market.get("aspects") or [] if item.get("id") == dim),
        {},
    )


_ASPECT_SECTIONS = (
    ("basic_information", "基本情况"),
    ("core_content", "核心内容"),
    ("key_directions", "重点方向"),
    ("specific_performance", "具体表现"),
    ("advantages", "优势与特点"),
    ("problems", "存在问题"),
    ("development_trends", "发展趋势"),
    ("comprehensive_analysis", "综合分析"),
)
_ASPECT_FIELD_LABEL = {
    "background": "背景",
    "scope": "范围",
    "key_data": "关键数据",
    "main_contents": "主要内容",
    "directions": "重点方向",
    "performance_metrics": "具体指标",
    "typical_cases": "典型案例",
    "key_advantages": "主要优势",
    "key_problems": "主要问题",
    "risk_points": "潜在风险",
    "current_changes": "当前变化",
    "future_directions": "未来方向",
    "key_conclusions": "关键结论",
}


def _aspect_conclusions(result: dict) -> list[str]:
    """把动态方面的八个内容块摊平成「字段：结论」，供报告章节引用。"""
    conclusions: list[str] = []
    for section_key, section_label in _ASPECT_SECTIONS:
        section = result.get(section_key)
        if not isinstance(section, dict):
            continue
        summary = clean_text(section.get("summary") or "")
        if summary:
            conclusions.append(f"{section_label}：{summary}")
        for name, value in section.items():
            if name in ("summary", "evidence_ids"):
                continue
            field_label = _ASPECT_FIELD_LABEL.get(name)
            if not field_label:
                continue
            if isinstance(value, list):
                for item in value:
                    text = clean_text(str(item))
                    if text:
                        conclusions.append(f"{field_label}：{text}")
            else:
                text = clean_text(str(value or ""))
                if text:
                    conclusions.append(f"{field_label}：{text}")
    return conclusions


def _aspect_facts(market: dict, dim: str, label: str, direction: str = "") -> dict:
    """动态方面章节的素材：只取该维度自己的结论，其他维度的事实不混进来。"""
    result = _aspect(market, dim).get("result") or {}
    facts = {
        "用户问题": clean_text(direction),
        "方面": label,
        "结论": _aspect_conclusions(result)[:16],
        "备注": clean_text(result.get("notes") or ""),
    }
    return {key: value for key, value in facts.items() if value not in ("", [], None)}


def _plain_text(item: object) -> str:
    """把 EvidencedText / 纯字符串统一成正文；兼容旧快照。"""
    if isinstance(item, dict):
        return clean_text(str(item.get("text") or ""))
    return clean_text(str(item or ""))


def _plain_texts(items: object) -> list[str]:
    return [text for text in (_plain_text(item) for item in (items or [])) if text]


def _overview_facts(brief: Brief, market: dict) -> dict:
    jobs = market.get("jobs") or {}
    distribution = jobs.get("job_distribution") or {}
    qualification = jobs.get("qualification_matrix") or {}
    synthesis = market.get("synthesis") or {}
    job_types = [
        item.get("name") for item in distribution.get("job_types") or [] if item.get("name")
    ]
    companies = [
        item.get("name")
        for item in distribution.get("company_distribution") or []
        if item.get("name")
    ]
    years = [
        item.get("name")
        for item in qualification.get("experience_requirements") or []
        if item.get("name")
    ]
    facts = {
        "用户问题": clean_text(brief.direction),
        "目标岗位": brief.target_role,
        "城市": brief.location,
        "时间窗口": brief.time_window or "时间不限",
        "岗位名称": job_types,
        "岗位分布": clean_text(distribution.get("summary") or ""),
        "薪资": _salary_text(jobs),
        "经验要求": "、".join(years[:3]),
        "代表公司": companies[:6],
        "跨源结论": _plain_texts([item.get("text") for item in synthesis.get("items") or []]),
        "来源差异": _plain_texts(synthesis.get("contradictions")),
        "样本量": market.get("sample_size") or 0,
    }
    return {key: value for key, value in facts.items() if value not in ("", [], None, 0)}


def _trend_facts(trend: dict) -> dict:
    """把新的技术趋势矩阵收拢成报告素材；只保留带统计量的条目。"""
    overview = trend.get("overview") or {}
    frequency = trend.get("technology_frequency") or {}
    fishbone = frequency.get("fishbone") or {}
    trends_group = trend.get("technology_trends") or {}
    applications = trend.get("technology_applications") or {}
    ranking = applications.get("scenario_ranking") or {}
    ecosystem = trend.get("framework_ecosystem") or {}

    technologies = []
    for branch in fishbone.get("branches") or []:
        for item in branch.get("technologies") or []:
            technologies.append(
                {
                    "技术": item.get("name"),
                    "领域": branch.get("category"),
                    "提及次数": item.get("total_count"),
                    "占比": item.get("percentage"),
                }
            )
    technologies.sort(key=lambda item: item.get("提及次数") or 0, reverse=True)

    return {
        "高频技术": technologies[:10],
        "技术趋势": [
            {
                "技术": item.get("name"),
                "方向": _TREND_TYPE_LABEL.get(
                    str(item.get("trend_type") or ""), item.get("trend_type")
                ),
                "说明": clean_text(item.get("description") or ""),
                "变化点": [
                    clean_text(point) for point in item.get("change_points") or [] if clean_text(point)
                ][:4],
            }
            for item in (trends_group.get("trends") or [])[:8]
        ],
        "技术问题": [
            {
                "问题": item.get("name"),
                "说明": clean_text(item.get("description") or ""),
                "影响": clean_text(item.get("impact") or ""),
            }
            for item in (trends_group.get("problems") or [])[:6]
        ],
        "应用场景": [
            {
                "场景": item.get("name"),
                "页面数": item.get("count"),
                "占比": item.get("percentage"),
            }
            for item in (ranking.get("items") or [])[:8]
        ],
        "技术生态": [
            {
                "项目": item.get("name"),
                "类型": item.get("type"),
                "定位": clean_text(item.get("description") or ""),
            }
            for item in (ecosystem.get("items") or [])[:8]
        ],
        "技术调研总结": clean_text(overview.get("research_summary") or ""),
        "高频技术总结": clean_text(frequency.get("summary") or ""),
        "趋势总结": clean_text(trends_group.get("summary") or ""),
        "应用场景总结": clean_text(ranking.get("summary") or ""),
    }


def _skills_facts(market: dict) -> dict:
    jobs = market.get("jobs") or {}
    trend = _trend_facts(market.get("trend") or {})
    technical = jobs.get("technical_matrix") or {}
    ability = jobs.get("ability_matrix") or {}
    technologies = [
        {
            "技术": item.get("name"),
            "出现次数": item.get("count"),
            "要求程度": _REQUIREMENT_LABEL.get(
                str(item.get("requirement_level") or ""), item.get("requirement_level")
            ),
            "说明": clean_text(item.get("evidence") or ""),
        }
        for item in (technical.get("technologies") or [])[:12]
    ]
    abilities = [
        {
            "能力": item.get("name"),
            "出现次数": item.get("count"),
            "重要程度": _LEVEL_LABEL.get(
                str(item.get("importance") or ""), item.get("importance")
            ),
            "说明": clean_text(item.get("description") or ""),
        }
        for item in (ability.get("abilities") or [])[:8]
    ]
    facts = {
        "技术需求": technologies,
        "能力需求": abilities,
        "技术需求总结": clean_text(technical.get("summary") or ""),
        "能力需求总结": clean_text(ability.get("ability_summary") or ""),
        **trend,
    }
    return {key: value for key, value in facts.items() if value}


def _compact(value):
    """去掉嵌套结构里的空字符串 / 空数组 / 空对象，避免报告素材里出现空字段。"""
    if isinstance(value, dict):
        cleaned = {key: _compact(item) for key, item in value.items()}
        return {key: item for key, item in cleaned.items() if item not in ("", [], {}, None)}
    if isinstance(value, list):
        cleaned = [_compact(item) for item in value]
        return [item for item in cleaned if item not in ("", [], {}, None)]
    return value


def _profile_facts(profile: dict | None) -> dict:
    """把新画像结构收拢成报告可引用的素材；只保留有内容的块。"""
    if not profile:
        return {}
    career = profile.get("career_competitiveness") or {}
    tech = profile.get("technical_capabilities") or {}
    project = profile.get("project_value") or {}
    advantages = profile.get("differentiated_advantages") or {}
    potential = profile.get("potential_and_gaps") or {}

    skills = []
    for skill in tech.get("skills") or []:
        locations = [
            evidence.get("location")
            for evidence in (skill.get("evidence") or [])
            if evidence.get("verified") and evidence.get("location")
        ]
        skills.append(
            {
                "能力": skill.get("name"),
                "水平": skill.get("level"),
                "位置": locations[:2],
            }
        )

    projects = []
    for item in project.get("projects") or []:
        projects.append(
            {
                "项目": item.get("project_name"),
                "角色": item.get("project_role"),
                "复杂度": _LEVEL_LABEL.get(
                    item.get("technical_complexity"), item.get("technical_complexity")
                ),
                "业务价值": item.get("business_value"),
                "个人贡献": item.get("personal_contribution") or [],
                "量化成果": [
                    f"{result.get('metric')}：{result.get('value')}"
                    for result in item.get("quantified_results") or []
                    if result.get("metric")
                ],
                "项目优势": item.get("proven_capabilities") or [],
            }
        )

    facts = {
        "职业竞争力": {
            "定位": career.get("candidate_type"),
            "级别": career.get("seniority"),
            "标签": career.get("career_tags") or [],
            "概括": career.get("career_summary"),
            "路径": [
                " · ".join(part for part in (stage.get("stage"), stage.get("role"), stage.get("focus")) if part)
                for stage in career.get("career_path") or []
            ],
        },
        "技术能力": {
            "能力": skills[:12],
            "总结": tech.get("technical_summary"),
        },
        "项目价值": {
            "项目": projects[:6],
            "总结": project.get("project_summary"),
        },
        "竞争优势": {
            "优势": [
                {
                    "标题": item.get("title"),
                    "说明": item.get("description"),
                    "突出程度": _LEVEL_LABEL.get(item.get("strength"), item.get("strength")),
                }
                for item in advantages.get("advantages") or []
            ][:6],
            "总结": advantages.get("overall_summary"),
        },
        "能力缺口": [
            {
                "能力": item.get("name"),
                "说明": item.get("description"),
                "类型": _GAP_TYPE_LABEL.get(item.get("gap_type"), item.get("gap_type")),
                "严重程度": _SEVERITY_LABEL.get(item.get("severity"), item.get("severity")),
            }
            for item in potential.get("gaps") or []
        ][:6],
        "简历缺口": [
            {
                "类型": _WEAKNESS_LABEL.get(item.get("type"), item.get("type")),
                "说明": item.get("description"),
            }
            for item in potential.get("resume_weaknesses") or []
        ][:6],
    }
    return _compact(facts)


def _strategy_item_text(item: object, *keys: str) -> str:
    """从结构化策略条目里取正文；兼容旧快照的 `text` 字段。"""
    if isinstance(item, dict):
        for key in keys:
            text = clean_text(str(item.get(key) or ""))
            if text:
                return text
        return ""
    return _plain_text(item)


def _conclusion_facts(strategy: dict | None) -> dict:
    result = (strategy or {}).get("result") or {}
    positioning = result.get("positioning")
    if isinstance(positioning, dict):
        positioning_facts = {
            "职业定位": clean_text(str(positioning.get("career_positioning") or "")),
            "市场竞争力": clean_text(str(positioning.get("market_level") or "")),
            "岗位匹配度": clean_text(str(positioning.get("job_match") or "")),
            "核心优势": positioning.get("competitive_advantages") or [],
            "主要劣势": positioning.get("competitive_disadvantages") or [],
        }
    else:
        # 旧快照里 positioning 是一句话字符串。
        positioning_facts = {"职业定位": clean_text(str(positioning or ""))}

    facts = {
        **positioning_facts,
        "差距": [
            {
                "市场要求": gap.get("requirement"),
                "简历现状": gap.get("current_level") or "",
                "能力差距": gap.get("gap_analysis") or "",
                "优先级": _LEVEL_LABEL.get(gap.get("priority"), gap.get("priority")),
                "提升方向": gap.get("improvement_direction") or "",
            }
            for gap in (result.get("gaps") or [])[:8]
        ],
        "改进优先级": [
            {
                "事项": _strategy_item_text(item, "task"),
                "原因": item.get("reason") or "",
                "预期结果": item.get("expected_outcome") or "",
            }
            for item in (result.get("priorities") or [])[:6]
        ],
        "写法提示": [
            {
                "简历位置": item.get("resume_location") or "",
                "问题": item.get("problem") or "",
                "优化": item.get("optimization") or "",
                "建议关键词": item.get("suggested_keywords") or [],
            }
            for item in (result.get("writing_tips") or [])[:6]
        ],
        "风险": [
            {
                "类型": item.get("risk_type") or "",
                "风险": item.get("risk") or "",
                "影响": item.get("impact") or "",
                "应对": item.get("response") or "",
            }
            for item in (result.get("risks") or [])[:6]
        ],
    }
    return {key: value for key, value in facts.items() if value not in ("", [], None)}


def _summary_facts(brief: Brief, market: dict, profile: dict | None, strategy: dict | None) -> dict:
    """总结章节素材：把各章核心结论收拢，供模型系统性总结整轮调研。

    覆盖：岗位概览 + 技能要求 + 每个动态方面 + 简历对照 + 策略建议。
    """
    facts: dict[str, object] = {}
    question = clean_text(brief.direction)
    if question:
        # 总结章节也必须回到用户的问题，不能只做通用岗位总结。
        facts["用户问题"] = question
    overview = _overview_facts(brief, market)
    if overview:
        facts["岗位概览"] = overview

    skills = _skills_facts(market)
    if skills:
        facts["技能要求"] = skills

    aspects: list[dict] = []
    for item in market.get("aspects") or []:
        dim = str(item.get("id") or "")
        label = str(item.get("label") or dim_label(dim, brief.aspect_labels))
        result = item.get("result") or {}
        conclusions = _aspect_conclusions(result)
        note = clean_text(result.get("notes") or "")
        if conclusions or note:
            aspects.append({"方面": label, "结论": conclusions[:6], "备注": note})
    if aspects:
        facts["调研方面"] = aspects

    profile_facts = _profile_facts(profile)
    if profile_facts:
        facts["简历对照"] = profile_facts

    strategy_facts = _conclusion_facts(strategy)
    if strategy_facts:
        facts["策略建议"] = strategy_facts

    return facts


def _evidence_ids(value: object) -> list[str]:
    """从任意嵌套结构里收集 evidence_ids，用于挑本章来源。"""
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            # 兼容 evidence_ids 与 role_evidence_ids 这类带前缀的证据字段。
            if (key == "evidence_ids" or key.endswith("_evidence_ids")) and isinstance(item, list):
                found.extend(str(eid) for eid in item)
            else:
                found.extend(_evidence_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_evidence_ids(item))
    return list(dict.fromkeys(found))


def _section_evidence(section: str, market: dict, strategy: dict | None) -> list[str]:
    """按章节挑证据编号：先取该章事实引用的来源，取不到再按前缀兜底。"""
    if section == "overview":
        jobs = market.get("jobs") or {}
        synthesis = market.get("synthesis") or {}
        ids = _evidence_ids(jobs)
        ids += _evidence_ids(market.get("aspects") or [])
        ids += _evidence_ids(synthesis.get("items")) + _evidence_ids(synthesis.get("contradictions"))
        return list(dict.fromkeys(ids))
    if section == "skills":
        jobs = market.get("jobs") or {}
        trend = market.get("trend") or {}
        return list(dict.fromkeys(_evidence_ids(jobs) + _evidence_ids(trend)))
    if section == "profile":
        return []
    if section == "conclusion":
        ids = _evidence_ids((strategy or {}).get("result") or {})
        ids += _evidence_ids(market.get("jobs") or {})
        ids += _evidence_ids(market.get("trend") or {})
        ids += _evidence_ids(market.get("aspects") or [])
        ids += _evidence_ids(market.get("synthesis") or {})
        return list(dict.fromkeys(ids))
    # 动态方面章节：只取该维度自己的结论来源。
    return _evidence_ids(_aspect(market, section).get("result"))


def _has_material(section: str, facts: dict) -> bool:
    """判断本章是否真的拿到了可写素材，避免用空事实喂模型。"""
    if section == "overview":
        return any(facts.get(key) for key in ("岗位名称", "薪资", "经验要求", "跨源结论"))
    if section == "skills":
        return bool(
            facts.get("技术需求")
            or facts.get("能力需求")
            or facts.get("高频技术")
            or facts.get("技术趋势")
            or facts.get("应用场景")
            or facts.get("技术生态")
        )
    if section == "profile":
        return bool(
            facts.get("职业竞争力")
            or facts.get("技术能力")
            or facts.get("项目价值")
            or facts.get("竞争优势")
            or facts.get("能力缺口")
            or facts.get("简历缺口")
        )
    if section == "conclusion":
        return bool(
            facts.get("岗位概览")
            or facts.get("技能要求")
            or facts.get("调研方面")
            or facts.get("简历对照")
            or facts.get("策略建议")
        )
    # 动态方面章节
    return bool(facts.get("结论") or facts.get("备注"))


def _source_entries(pages: list[dict], evidence_ids: list[str], fallback_prefix: str) -> list[dict]:
    by_id = {str(page.get("evidence_id")): page for page in pages}
    picked: list[dict] = []
    seen: set[str] = set()
    for eid in evidence_ids:
        page = by_id.get(eid)
        if page is None or page.get("url") in seen:
            continue
        seen.add(page.get("url"))
        picked.append(
            {
                "id": page.get("evidence_id"),
                "title": page.get("title") or page.get("url"),
                "url": page.get("url"),
                "site": page.get("site") or "",
                "published": page.get("published") or "",
            }
        )
        if len(picked) >= _MAX_SOURCES_PER_SECTION:
            break
    if picked:
        return picked
    for page in pages:
        if not str(page.get("evidence_id") or "").startswith(fallback_prefix):
            continue
        if page.get("url") in seen:
            continue
        seen.add(page.get("url"))
        picked.append(
            {
                "id": page.get("evidence_id"),
                "title": page.get("title") or page.get("url"),
                "url": page.get("url"),
                "site": page.get("site") or "",
                "published": page.get("published") or "",
            }
        )
        if len(picked) >= _MAX_SOURCES_PER_SECTION:
            break
    return picked


def _fallback_prose(section: str, facts: dict, meta: dict) -> str:
    """模型不可用时的确定性正文：只复述事实，不补常识。"""
    sample = int(meta.get("sample_size") or 0)
    if section == "overview":
        if not _has_material(section, facts):
            return "本次未获得足够证据，岗位概览无法形成结论。建议补充招聘来源或放宽城市/时间范围后重试。"
        parts = [f"{facts.get('目标岗位', '该岗位')} 的招聘样本共 {sample} 页。"]
        if facts.get("用户问题"):
            parts.append(f"本次调研要回答的问题：{facts['用户问题']}。")
        if facts.get("岗位名称"):
            parts.append(f"岗位名称包括 {'、'.join(facts['岗位名称'][:4])}。")
        if facts.get("薪资"):
            parts.append(f"薪资方面，{facts['薪资']}。")
        if facts.get("经验要求"):
            parts.append(f"经验要求为 {facts['经验要求']}。")
        if facts.get("跨源结论"):
            parts.append(f"跨源结论：{facts['跨源结论'][0]}。")
        if meta.get("coverage") == "partial":
            parts.append(f"样本 {sample} 条，结论仅供参考。")
        return "".join(parts)
    if section == "skills":
        technologies = facts.get("技术需求") or []
        abilities = facts.get("能力需求") or []
        if not _has_material(section, facts):
            return "本次未获得足够证据，技能要求无法排序。建议补充招聘页面后重试。"
        text = ""
        if technologies:
            top = "、".join(
                f"{item['技术']}（{item['出现次数']} 个页面提及）"
                for item in technologies[:5]
            )
            text = f"样本中出现频次最高的技术需求是 {top}。"
        if abilities:
            top_ability = "、".join(item["能力"] for item in abilities[:4])
            text += f"能力要求方面，{top_ability} 被多个岗位提及。"
        if facts.get("高频技术"):
            hot = "、".join(item["技术"] for item in facts["高频技术"][:5])
            text += f"技术关注方面，{hot}的出现频次较高。"
        if facts.get("技术趋势"):
            trend = "、".join(item["技术"] for item in facts["技术趋势"][:4])
            text += f"技术趋势方面，{trend} 被来源提及。"
        if facts.get("应用场景"):
            scenes = "、".join(item["场景"] for item in facts["应用场景"][:4])
            text += f"应用场景方面，{scenes}较为常见。"
        if meta.get("coverage") == "partial":
            text += f"样本 {sample} 条，结论仅供参考。"
        return text
    if section not in ("overview", "skills", "profile", "conclusion"):
        label = facts.get("方面") or section
        if not _has_material(section, facts):
            return f"本次未获得足够证据，{label}方面无法形成结论。建议补充来源后重试。"
        parts = []
        if facts.get("用户问题"):
            parts.append(f"围绕用户的问题「{facts['用户问题']}」，{label}方面的情况如下：")
        for item in (facts.get("结论") or [])[:4]:
            parts.append(f"{item}。")
        if facts.get("备注"):
            parts.append(f"补充：{facts['备注']}。")
        if meta.get("coverage") == "partial":
            parts.append(f"样本 {sample} 条，结论仅供参考。")
        return "".join(parts)
    if section == "profile":
        if not _has_material(section, facts):
            return "本次未能从简历中提取足够信息，简历对照暂不可用。建议先补全简历中的项目与技能描述。"
        career = facts.get("职业竞争力") or {}
        summary = career.get("概括") or career.get("定位") or "简历画像已完成"
        text = f"职业竞争力：{summary}。"
        advantage = facts.get("竞争优势") or {}
        titles = [
            item.get("标题")
            for item in (advantage.get("优势") or [])[:3]
            if item.get("标题")
        ]
        if titles:
            text += f"竞争优势包括：{'、'.join(titles)}。"
        gaps = [
            item.get("能力")
            for item in (facts.get("能力缺口") or [])[:3]
            if item.get("能力")
        ]
        if gaps:
            text += f"简历暂未体现：{'、'.join(gaps)}。"
        return text
    # conclusion
    if not _has_material(section, facts):
        return "本次未获得足够证据，暂不给出总结。建议补充来源或缩小岗位范围后重试。"
    strategy_facts = facts.get("策略建议") or {}
    text = ""
    if facts.get("用户问题"):
        text += f"针对用户的问题「{facts['用户问题']}」："
    positioning_text = strategy_facts.get("职业定位") or strategy_facts.get("定位") or ""
    if positioning_text:
        text += f"{positioning_text}。"
    priorities = [
        _strategy_item_text(item, "事项", "task", "text")
        for item in (strategy_facts.get("改进优先级") or strategy_facts.get("行动优先级") or [])[:3]
    ]
    priorities = [item for item in priorities if item]
    if priorities:
        text += f"优先做：{'；'.join(priorities)}。"
    risks = strategy_facts.get("风险") or []
    if risks:
        first_risk = risks[0]
        if isinstance(first_risk, dict):
            first_risk = (
                clean_text(str(first_risk.get("风险") or ""))
                or clean_text(str(first_risk.get("应对") or ""))
            )
        if first_risk:
            text += f"注意：{first_risk}。"
    if meta.get("coverage") == "partial":
        text += f"样本 {sample} 条，结论仅供参考。"
    return text


def _market_prefixes(market: dict) -> dict[str, str]:
    """从采集页面反推每个维度的证据前缀：同一维度下编号首字母相同，取第一次出现的即可。"""
    prefixes: dict[str, str] = {}
    for page in market.get("pages") or []:
        dim = str(page.get("kind") or "")
        dims = str(page.get("evidence_id") or "")
        if not dim or not dims or dim in prefixes:
            continue
        prefix = dims.rstrip("0123456789")
        if prefix:
            prefixes[dim] = prefix
    return prefixes


def _section_material(
    section: str,
    brief: Brief,
    market: dict,
    profile: dict | None,
    strategy: dict | None,
    prefixes: dict[str, str] | None = None,
) -> tuple[dict, str]:
    """返回（本章事实, 兜底来源前缀）。"""
    if section == "overview":
        return _overview_facts(brief, market), "J"
    if section == "skills":
        return _skills_facts(market), "J"
    if section == "profile":
        return _profile_facts(profile), "J"
    if section == "conclusion":
        return _summary_facts(brief, market, profile, strategy), "J"
    # 动态方面章节：全部走通用结论结构，前缀用采集阶段真实分配的那一个。
    return (
        _aspect_facts(
            market,
            section,
            dim_label(section, brief.aspect_labels),
            brief.direction,
        ),
        (prefixes or {}).get(section) or dim_prefix(section),
    )


async def _write_section(
    llm,
    *,
    brief: Brief,
    section: str,
    title: str,
    facts: dict,
    sources: list[dict],
    meta: dict,
    run_id: str,
) -> tuple[str, str]:
    """返回（正文, 状态）。"""
    writer = safe_writer()
    has_material = _has_material(section, facts)
    status = "ready" if has_material else "uncovered"
    writer(
        {
            "type": "report.section.started",
            "section": section,
            "title": title,
            "status": status,
        }
    )

    if not has_material:
        prose = _fallback_prose(section, facts, meta)
        return prose, status

    message = (
        f"<brief>\n{brief.model_dump_json(indent=2)}\n</brief>\n\n"
        f"<section>\nid: {section}\ntitle: {title}\n</section>\n\n"
        f"<facts>\n{json.dumps(facts, ensure_ascii=False, indent=2)}\n</facts>\n\n"
        f"<sources>\n"
        + "\n".join(f"[{item['id']}] {item['title']} / {item['url']}" for item in sources)
        + "\n</sources>\n\n"
        f"<coverage>\n{meta.get('coverage') or 'none'} · 样本 {meta.get('sample_size') or 0}\n</coverage>"
    )

    agent = build_agent(llm)
    config = {"configurable": {"thread_id": f"{run_id}:compose:{section}"}}
    try:
        prose = await run_stream(
            agent,
            _SYSTEM_PROMPT,
            message,
            config,
            stage="compose",
            section=section,
        )
    except Exception as exc:
        stage_warning("compose", "章节生成失败", section=section, error=exc)
        prose = ""
        status = "failed"

    prose = clean_text(prose)
    if not prose:
        prose = _fallback_prose(section, facts, meta)
        status = "ready" if has_material else status
    return prose, status


async def run(
    llm,
    brief: Brief,
    market: dict,
    profile: dict | None,
    strategy: dict | None,
    run_id: str | None = None,
) -> dict:
    """逐章写报告：固定首尾 + 本次选择的动态方面。"""
    writer = safe_writer()
    run_id = run_id or uuid.uuid4().hex
    writer({"type": "node.enter", "node": "compose", "label": "整合报告"})
    writer({"type": "agent_start", "agent": "compose", "label": "报告撰写 agent"})

    # 简历画像失败时仍保留「简历对照」章节，用 uncovered 状态告诉用户哪里没拿到证据。
    has_resume = brief.has_resume
    meta_all = section_meta(market, profile, has_resume)
    pages = market.get("pages") or []
    plan = report_sections(brief)
    prefixes = _market_prefixes(market)

    sections: list[dict] = []
    for section, title in plan:
        facts, prefix = _section_material(section, brief, market, profile, strategy, prefixes)
        meta = meta_all.get(section) or {"coverage": "none", "sample_size": 0}
        evidence_ids = _section_evidence(section, market, strategy)
        sources = (
            _source_entries(pages, evidence_ids, prefix)
            if section != "profile"
            else []
        )
        prose, status = await _write_section(
            llm,
            brief=brief,
            section=section,
            title=title,
            facts=facts,
            sources=sources,
            meta=meta,
            run_id=run_id,
        )
        entry = {
            "id": section,
            "title": title,
            "status": status,
            "prose": prose,
            "sources": sources,
        }
        sections.append(entry)
        writer({"type": "report.section", **entry})

    writer({"type": "agent_end", "agent": "compose", "label": "报告撰写 agent"})
    writer({"type": "report.done", "sections": sections, "count": len(sections)})
    writer(
        {
            "type": "node.exit",
            "node": "compose",
            "state": "done",
            "text": f"{len(sections)} 章",
        }
    )
    return {"sections": sections, "titles": dict(plan)}
