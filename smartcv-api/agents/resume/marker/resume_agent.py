"""Agent 2 · 简历画像：从带坐标简历里提取能力、事实证据与位置。

输出只用于后续策略对照，不改简历、不评价写法。
"""

import re
import time
import uuid
from pathlib import Path

from langchain.agents import create_agent
from pydantic import ValidationError

from agents.resume.marker.utils.profile import coverage as profile_coverage
from agents.resume.marker.utils.runner import (
    DropInvalidToolCallsMiddleware,
    run_structured,
    safe_writer,
)
from agents.resume.marker.schemas import ResumeGap, ResumeProfile
from agents.resume.marker.utils.stage_log import stage_info, stage_warning
from agents.resume.optimize.utils.checkpointer import get_checkpointer
from agents.utils.resume import describe_location_detail, locate_unit, norm_text, resume_to_marked_text
from agents.utils.skillmiddleware import SkillMiddleware

_SYSTEM_PROMPT = (Path(__file__).resolve().parent / "prompts" / "profile" / "resume.md").read_text(encoding="utf-8")
_COORD_RE = re.compile(r"\[s:(\d+)\s+r:(\d+)\s+c:(\d+)\s+i:(\d+)\]")
# 职业路径阶段只保留时间；兼容模型把「2020.09-2023.06 教育期」整段写进 stage。
_STAGE_TIME_RE = re.compile(
    r"^\s*((?:19|20)\d{2}(?:[./-]\d{1,2})?"
    r"(?:\s*(?:-|–|—|~|至)\s*(?:(?:19|20)\d{2}(?:[./-]\d{1,2})?|至今|现在|今))?)"
    r"(?=$|[^\d])"
)


def build_agent(llm):
    return create_agent(
        model=llm,
        tools=[],
        middleware=[SkillMiddleware(["coordinate"]), DropInvalidToolCallsMiddleware()],
        response_format=ResumeProfile,
        checkpointer=get_checkpointer(),
    )


def _parse_coordinate(value: str) -> dict | None:
    match = _COORD_RE.search(value or "")
    if not match:
        return None
    return {key: int(number) for key, number in zip(("s", "r", "c", "i"), match.groups())}


def _coordinate_lines(markdown: str) -> dict[tuple[int, int, int, int], int]:
    """标记简历里每个坐标对应的行号（1 起）；只认行首坐标。"""
    lines: dict[tuple[int, int, int, int], int] = {}
    for number, line in enumerate(markdown.splitlines(), start=1):
        match = _COORD_RE.match(line.strip())
        if match:
            lines[tuple(int(part) for part in match.groups())] = number
    return lines


def _iter_evidence(profile: ResumeProfile):
    """按输出结构遍历所有证据：技术能力 / 竞争优势 / 能力缺口 / 量化成果。"""
    for skill in profile.technical_capabilities.skills:
        yield from skill.evidence
    for advantage in profile.differentiated_advantages.advantages:
        yield from advantage.evidence
    for project in profile.project_value.projects:
        for result in project.quantified_results:
            if result.source is not None:
                yield result.source


def _verify_coordinates(profile: ResumeProfile, resume: list[dict], markdown: str) -> int:
    """把模型复制的坐标落到真实简历上，并回填章节 / 行号 / 位置。

    定位不到的证据保留但标记 verified=False，供前端提示。
    """
    line_numbers = _coordinate_lines(markdown)
    verified = 0
    for evidence in _iter_evidence(profile):
        evidence.section = ""
        evidence.line = 0
        evidence.location = ""
        evidence.verified = False

        coords = _parse_coordinate(evidence.coordinate)
        if coords is None:
            continue
        located = locate_unit(resume, coords["s"], coords["r"], coords["c"], coords["i"])
        if located is None:
            continue

        evidence.coordinate = (
            f"[s:{coords['s']} r:{coords['r']} c:{coords['c']} i:{coords['i']}]"
        )
        detail = describe_location_detail(resume, coords)
        evidence.section = detail["section"]
        evidence.line = line_numbers.get(
            (coords["s"], coords["r"], coords["c"], coords["i"]), 0
        )
        evidence.location = detail["path"]
        # 坐标能定位、且 quote 是原文片段（忽略空白 / Markdown 标记）才算通过。
        quote = (evidence.quote or "").strip()
        evidence.verified = not quote or norm_text(quote) in norm_text(located[3])
        if evidence.verified:
            verified += 1
    return verified


def _unwrap_profile(value: dict | None) -> dict | None:
    """把模型常见的两种结构偏差掰回 ResumeProfile 的形状。

    - 多包一层 resume_profile（按示例输出时常见）；
    - differentiated_advantages 本该是 {advantages, overall_summary} 对象，
      模型偶尔直接把 advantages 数组给它，校验会报 model_type，这里补回外层。
    """
    if not isinstance(value, dict):
        return value
    if isinstance(value.get("resume_profile"), dict):
        value = value["resume_profile"]
    advantages = value.get("differentiated_advantages")
    if isinstance(advantages, list):
        items = [{"title": item} if isinstance(item, str) else item for item in advantages]
        return {**value, "differentiated_advantages": {"advantages": items}}
    return value


def _log_validation_errors(exc: ValidationError) -> None:
    """逐条打出字段路径，模型少字段 / 枚举写错 / 容器形状错时能直接看出是哪个字段。"""
    for error in exc.errors()[:6]:
        stage_warning(
            "profile",
            "结构校验失败",
            field=".".join(str(part) for part in error.get("loc") or ()) or "-",
            error=error.get("msg"),
        )


def _schema_retry_hint(exc: ValidationError) -> str:
    """把校验错误回给模型，要求它按 schema 重新调用一次结构化输出工具。"""
    lines = [
        f"- {'.'.join(str(part) for part in error.get('loc') or ()) or '-'}: {error.get('msg')}"
        for error in exc.errors()[:6]
    ]
    return (
        "你上一次输出的结构化结果与 schema 不符，校验错误：\n"
        + "\n".join(lines)
        + "\n请重新调用结构化输出工具，严格按 schema 的字段类型输出："
        "对象字段不能写成数组，数组字段不能写成对象，不要省略外层结构，也不要新增字段。"
    )


def _fallback() -> dict:
    return ResumeProfile(
        career_competitiveness={
            "career_summary": "简历信息不足，无法形成画像",
        },
        analysis_metadata={"analysis_status": "failed"},
    ).model_dump()


_COMPLEXITY_LABEL = {"high": "高", "medium": "中", "low": "低"}
_SEVERITY_LABEL = {"high": "严重", "medium": "中等", "low": "轻微"}
_GAP_TYPE_LABEL = {
    "skill": "技能缺口",
    "experience": "经验缺口",
    "depth": "深度不足",
    "evidence": "证据不足",
}
_WEAKNESS_LABEL = {
    "result_expression": "成果表达",
    "project_description": "项目描述",
    "responsibility": "职责边界",
    "technical_depth": "技术描述",
    "structure": "结构重点",
}
# 缺口先按类型分组，再按严重程度排序；顺序与提示词里的枚举一致。
_GAP_TYPE_ORDER = {"skill": 0, "experience": 1, "depth": 2, "evidence": 3}
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
_WEAKNESS_TYPE_ORDER = {
    "result_expression": 0,
    "project_description": 1,
    "responsibility": 2,
    "technical_depth": 3,
    "structure": 4,
}


def _entry(item_id: str, kind: str, **fields) -> dict:
    return {"id": item_id, "key": item_id, "kind": kind, "evidence_ids": [], **fields}


def _divider(key: str, label: str) -> dict:
    return {"id": key, "key": key, "kind": "divider", "label": label, "text": ""}


def _stage_time(stage: str) -> str:
    """阶段名只留时间范围，后面的「教育期」等说明不进入展示数据。"""
    text = (stage or "").strip()
    matched = _STAGE_TIME_RE.match(text)
    return matched.group(1).strip() if matched else text


def _evidence_chips(evidence_list, limit: int = 2) -> list[str]:
    """把已校验坐标转成「章节·条目」短标签，供现有面板行展示。"""
    chips: list[str] = []
    for evidence in evidence_list:
        if not evidence.verified:
            continue
        label = evidence.location or evidence.section
        if label and label not in chips:
            chips.append(label)
    return chips[:limit]


def _evidence_payload(evidence_list) -> list[dict]:
    """完整坐标载荷：前端后续据此展示章节、行号与原文。"""
    return [
        {
            "coordinate": evidence.coordinate,
            "quote": evidence.quote,
            "section": evidence.section,
            "line": evidence.line,
            "location": evidence.location,
            "verified": evidence.verified,
        }
        for evidence in evidence_list
    ]


def _skill_count(profile: ResumeProfile) -> int:
    return len(profile.technical_capabilities.skills)


def _ensure_gap(profile: ResumeProfile) -> None:
    """能力缺口至少保留一条低严重度提示。

    投递型简历往往已经比较完整，模型可能不输出任何缺口；前端仍需要一侧
    「能力缺口」页签，因此缺失时补一条保守的证据缺口，不制造严重问题。
    """
    if profile.potential_and_gaps.gaps:
        return
    profile.potential_and_gaps.gaps.append(
        ResumeGap(
            name="能力证据可补充",
            description="简历暂未体现明显的能力缺口；可补充更具体的项目背景、技术深度或量化结果，让能力证明更完整。",
            gap_type="evidence",
            severity="low",
        )
    )


def _emit_items(profile: ResumeProfile, writer) -> int:
    """画像事件。

    career_competitiveness 用 tone=summary/meta 的行进入汇总卡；
    technical_capabilities / project_value / differentiated_advantages /
    potential_and_gaps 各用一条 divider 作为明细标题；能力缺口与简历缺口
    分开展示，各自使用一条 divider。
    """
    items: list[dict] = []

    # ---- 汇总卡：职业竞争力 ----
    career = profile.career_competitiveness
    if career.career_summary or career.candidate_type or career.career_tags:
        items.append(
            _entry(
                "profile:career",
                "fact",
                tone="summary",
                label="职业竞争力",
                text=career.career_summary,
                value="",
                chips=[],
                resume_evidence=[],
            )
        )
    if career.candidate_type:
        items.append(
            _entry(
                "profile:career:type",
                "fact",
                tone="meta",
                label="职业定位",
                value=career.candidate_type,
                text="",
                chips=[],
            )
        )
    if career.seniority:
        items.append(
            _entry(
                "profile:career:seniority",
                "fact",
                tone="meta",
                label="职业级别",
                value=career.seniority,
                text="",
                chips=[],
            )
        )
    if career.career_tags:
        items.append(
            _entry(
                "profile:career:tags",
                "fact",
                tone="meta",
                label="职业标签",
                value="",
                text="",
                chips=list(career.career_tags),
            )
        )
    if career.career_path:
        items.append(
            _entry(
                "profile:career:path",
                "fact",
                tone="meta",
                label="职业路径",
                value="",
                text="",
                chips=[
                    " · ".join(
                        part
                        for part in (_stage_time(stage.stage), stage.role, stage.focus)
                        if part
                    )
                    for stage in career.career_path
                ],
                stages=[
                    {
                        "stage": _stage_time(stage.stage),
                        "role": stage.role,
                        "focus": stage.focus,
                    }
                    for stage in career.career_path
                ],
            )
        )

    # ---- 技能图谱 / 技能总结 ----
    tech = profile.technical_capabilities
    if tech.skills or tech.technical_summary:
        items.append(_divider("profile:section:technical", "技能图谱"))
        for skill_index, skill in enumerate(tech.skills):
            items.append(
                _entry(
                    f"profile:skill:{skill_index}",
                    "fact",
                    tone="skill",
                    label=skill.name,
                    value=skill.level,
                    text="",
                    chips=_evidence_chips(skill.evidence),
                    resume_evidence=_evidence_payload(skill.evidence),
                )
            )
        if tech.technical_summary:
            items.append(
                _entry(
                    "profile:tech:summary",
                    "fact",
                    tone="meta",
                    label="技能总结",
                    value="",
                    text=tech.technical_summary,
                    chips=[],
                )
            )

    # ---- 项目价值 / 竞争优势 ----
    project_value = profile.project_value
    if project_value.projects or project_value.project_summary:
        items.append(_divider("profile:section:project", "项目价值"))
        for index, project in enumerate(project_value.projects):
            quantified = [
                f"{result.metric}：{result.value}"
                for result in project.quantified_results
                if result.metric
            ]
            # 个人贡献 / 项目优势 / 量化成果分开成组，前端按组加标题展示，
            # 不再挤进不区分的 chips 里被截断。
            groups = [
                {"label": label, "items": values}
                for label, values in (
                    ("个人贡献", project.personal_contribution),
                    ("项目优势", project.proven_capabilities),
                    ("量化成果", quantified),
                )
                if values
            ]
            sources = [
                result.source
                for result in project.quantified_results
                if result.source is not None
            ]
            items.append(
                _entry(
                    f"profile:project:{index}",
                    "fact",
                    tone="project",
                    label=project.project_name,
                    value=project.project_role,
                    text=project.business_value,
                    chips=[
                        f"复杂度：{_COMPLEXITY_LABEL.get(project.technical_complexity, project.technical_complexity)}",
                    ],
                    groups=groups,
                    resume_evidence=_evidence_payload(sources),
                )
            )
        if project_value.project_summary:
            items.append(
                _entry(
                    "profile:project:summary",
                    "fact",
                    tone="meta",
                    label="项目总结",
                    value="",
                    text=project_value.project_summary,
                    chips=[],
                )
            )

    # ---- 竞争优势 ----
    advantages = profile.differentiated_advantages
    if advantages.advantages or advantages.overall_summary:
        items.append(_divider("profile:section:advantage", "竞争优势"))
        for index, advantage in enumerate(advantages.advantages):
            items.append(
                _entry(
                    f"profile:advantage:{index}",
                    "pair",
                    tag="hit",
                    label=advantage.title,
                    text=advantage.description,
                    chips=_evidence_chips(advantage.evidence),
                    resume_evidence=_evidence_payload(advantage.evidence),
                )
            )
        if advantages.overall_summary:
            items.append(
                _entry(
                    "profile:advantage:summary",
                    "fact",
                    tone="meta",
                    label="优势总结",
                    value="",
                    text=advantages.overall_summary,
                    chips=[],
                )
            )

    # ---- 能力缺口 / 简历缺口 ----
    potential = profile.potential_and_gaps
    if potential.gaps:
        items.append(_divider("profile:section:gap", "能力缺口"))
        ordered_gaps = sorted(
            potential.gaps,
            key=lambda gap: (
                _GAP_TYPE_ORDER.get(gap.gap_type, 9),
                _SEVERITY_ORDER.get(gap.severity, 9),
            ),
        )
        for index, gap in enumerate(ordered_gaps):
            items.append(
                _entry(
                    f"profile:gap:{index}",
                    "pair",
                    tag="gap",
                    label=gap.name,
                    text=gap.description,
                    type_label=_GAP_TYPE_LABEL.get(gap.gap_type, gap.gap_type),
                    severity_label=_SEVERITY_LABEL.get(gap.severity, gap.severity),
                    chips=[],
                    resume_evidence=[],
                )
            )
    if potential.resume_weaknesses:
        items.append(_divider("profile:section:weakness", "简历缺口"))
        ordered_weaknesses = sorted(
            potential.resume_weaknesses,
            key=lambda weakness: _WEAKNESS_TYPE_ORDER.get(weakness.type, 9),
        )
        for index, weakness in enumerate(ordered_weaknesses):
            items.append(
                _entry(
                    f"profile:weakness:{index}",
                    "pair",
                    tag="gap",
                    label="简历表达",
                    text=weakness.description,
                    type_label=_WEAKNESS_LABEL.get(weakness.type, weakness.type),
                    chips=[],
                    resume_evidence=[],
                )
            )

    writer({"type": "profile.chunk", "items": items})
    return len(items)


async def run(llm, resume: list[dict] | None, run_id: str | None = None) -> dict:
    """跑简历画像 agent，返回 {profile, evidence_count}。

    每个阶段打一条 INFO 日志（输入规模 / 模型耗时 / 结构校验 / 坐标定位），
    画像出问题时可以从日志直接看出卡在哪一步。
    """
    writer = safe_writer()
    started = time.perf_counter()
    writer({"type": "node.enter", "node": "profile", "label": "简历画像"})

    if not resume:
        stage_info("profile", "跳过", reason="无简历")
        writer({"type": "profile.chunk", "items": []})
        writer({"type": "profile.done", "count": 0, "coverage": "none", "evidence": 0})
        writer({"type": "node.exit", "node": "profile", "state": "done", "text": "无简历"})
        return {"profile": _fallback(), "evidence_count": 0}

    writer({"type": "agent_start", "agent": "resume", "label": "简历画像 agent"})
    markdown = resume_to_marked_text(resume)
    agent = build_agent(llm)
    config = {
        "configurable": {
            "thread_id": f"{run_id or uuid.uuid4().hex}:resume",
        }
    }
    structured = await run_structured(
        agent,
        _SYSTEM_PROMPT,
        f"<resume>\n{markdown}\n</resume>",
        config,
        stage="resume",
    )

    profile: ResumeProfile | None = None
    # 结构校验失败多半是模型把某个对象写成了数组（如 differentiated_advantages）。
    # 把校验错误回给它重试一次；仍不合法才按原来的方式失败，由上层跳过简历对照。
    for attempt in (1, 2):
        if structured is None:
            break
        try:
            profile = ResumeProfile.model_validate(_unwrap_profile(structured))
            break
        except ValidationError as exc:
            _log_validation_errors(exc)
            if attempt == 2:
                raise
            stage_warning("profile", "结构校验失败，重试一次模型", fields=len(exc.errors()))
            structured = await run_structured(
                agent,
                _SYSTEM_PROMPT,
                _schema_retry_hint(exc),
                config,
                stage="resume",
            )

    if profile is None:
        stage_warning(
            "profile",
            "模型未返回可用画像，使用兜底画像",
            elapsed=f"{time.perf_counter() - started:.1f}s",
        )
        writer({"type": "profile.chunk", "items": []})
        writer({"type": "profile.done", "count": 0, "coverage": "none", "evidence": 0})
        writer({"type": "agent_end", "agent": "resume", "label": "简历画像 agent"})
        writer({"type": "node.exit", "node": "profile", "state": "error", "text": "画像失败"})
        return {"profile": _fallback(), "evidence_count": 0}

    _ensure_gap(profile)
    evidence_list = list(_iter_evidence(profile))
    verified = _verify_coordinates(profile, resume, markdown)
    unverified = [item.coordinate for item in evidence_list if not item.verified]
    stage_info(
        "profile",
        "坐标校验",
        verified=len(evidence_list) - len(unverified),
        total=len(evidence_list),
        unverified="；".join(unverified[:3]) or "-",
    )

    item_count = _emit_items(profile, writer)
    profile_data = profile.model_dump()
    skill_count = _skill_count(profile)
    coverage = profile_coverage(profile_data)
    writer(
        {
            "type": "profile.done",
            "count": skill_count,
            "coverage": coverage,
            "evidence": verified,
        }
    )
    writer({"type": "agent_end", "agent": "resume", "label": "简历画像 agent"})
    writer(
        {
            "type": "node.exit",
            "node": "profile",
            "state": "done",
            "text": f"{item_count} 条 · {verified} 条证据",
        }
    )
    return {"profile": profile_data, "evidence_count": verified}
