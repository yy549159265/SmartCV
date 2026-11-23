"""简历画像结构的公共读取。

画像先由 resume_agent 产出并校验坐标，再以 dict 形式写进 state；下游
（compose）统一用这里的函数读它，避免各自猜字段。
"""

from collections.abc import Iterator


def iter_evidence(profile: dict | None) -> Iterator[dict]:
    """按输出结构遍历画像里的所有证据对象。"""
    if not profile:
        return
    tech = profile.get("technical_capabilities") or {}
    for skill in tech.get("skills") or []:
        yield from skill.get("evidence") or []
    for advantage in (profile.get("differentiated_advantages") or {}).get("advantages") or []:
        yield from advantage.get("evidence") or []
    for project in (profile.get("project_value") or {}).get("projects") or []:
        for result in project.get("quantified_results") or []:
            source = result.get("source")
            if isinstance(source, dict):
                yield source


def verified_locations(profile: dict | None) -> set[str]:
    """坐标校验通过的位置集合，同时接受「章节·条目」和 [s:r:c:i] 两种写法。"""
    locations: set[str] = set()
    for evidence in iter_evidence(profile):
        if not evidence.get("verified"):
            continue
        for key in ("location", "coordinate"):
            value = str(evidence.get(key) or "").strip()
            if value:
                locations.add(value)
    return locations


def skill_count(profile: dict | None) -> int:
    """画像里的能力项数，用于前端「N 项能力」与质量样本量。"""
    if not profile:
        return 0
    tech = profile.get("technical_capabilities") or {}
    return len(tech.get("skills") or [])


def coverage(profile: dict | None) -> str:
    """画像覆盖度：full / partial / none。

    新结构不再由模型输出 coverage，这里按「是否有内容 + 分析状态」判断：
    分析失败或全空为 none；完整完成为 full；其余为 partial。
    """
    if not profile:
        return "none"
    status = str((profile.get("analysis_metadata") or {}).get("analysis_status") or "")
    if status == "failed":
        return "none"

    career = profile.get("career_competitiveness") or {}
    has_content = bool(
        career.get("career_summary")
        or career.get("candidate_type")
        or skill_count(profile)
        or (profile.get("project_value") or {}).get("projects")
        or (profile.get("differentiated_advantages") or {}).get("advantages")
        or (profile.get("potential_and_gaps") or {}).get("gaps")
        or (profile.get("potential_and_gaps") or {}).get("resume_weaknesses")
    )
    if not has_content:
        return "none"
    return "full" if status == "completed" else "partial"
