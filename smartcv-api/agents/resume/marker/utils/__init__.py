"""市场洞察的通用辅助函数：纯函数、常量、agent 运行器与任务通道。

注意：这里不 import 任何 agent / tools，保持「工具层不反向依赖业务层」。
"""

from agents.resume.marker.utils.common import (
    clean_text,
    fallback_groups,
    filter_evidence,
    format_pages,
    merge_coverage,
    normalize_request,
    normalize_skill,
    now_iso,
    parse_salary,
    time_window_label,
    valid_evidence_ids,
)
from agents.resume.marker.utils.dims import (
    GROUP_IDS,
    GROUP_KINDS,
    GROUP_LABELS,
    GROUP_MAX_QUERIES,
    MAX_GROUP_CHARS,
    MAX_PAGE_CHARS,
    MIN_PAGE_CHARS,
    REPORT_FIXED_SECTIONS,
    graph_payload,
    report_sections,
)
from agents.resume.marker.utils.profile import (
    coverage as profile_coverage,
    iter_evidence as iter_profile_evidence,
    skill_count as profile_skill_count,
    verified_locations as profile_verified_locations,
)

__all__ = [
    "GROUP_IDS",
    "GROUP_KINDS",
    "GROUP_LABELS",
    "GROUP_MAX_QUERIES",
    "MAX_GROUP_CHARS",
    "MAX_PAGE_CHARS",
    "MIN_PAGE_CHARS",
    "REPORT_FIXED_SECTIONS",
    "clean_text",
    "fallback_groups",
    "filter_evidence",
    "format_pages",
    "graph_payload",
    "merge_coverage",
    "normalize_request",
    "normalize_skill",
    "now_iso",
    "parse_salary",
    "profile_coverage",
    "profile_skill_count",
    "profile_verified_locations",
    "iter_profile_evidence",
    "report_sections",
    "time_window_label",
    "valid_evidence_ids",
]
