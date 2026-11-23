"""市场洞察的维度、章节与图结构常量。

维度分两类：
  - 固定维度 jobs / trend：岗位信息、技术趋势，永远参与调研；
  - 动态维度：用户在规划阶段选填的调研方面，id 由 planner 按用户所选方向生成。

没有任何预置的动态维度 id：除固定维度外，出现什么维度完全取决于用户这一轮选了什么。
每个维度对应一个并行 agent；页面在采集阶段被标记 kind=维度 id，
agent 只读取与自己 kind 匹配的页面。坐标由前端计算，后端只给语义节点/边。
"""

import os
from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from agents.resume.marker.schemas import Brief

FIXED_DIMS = ("jobs", "trend")

DIM_LABELS = {"jobs": "招聘矩阵", "trend": "技术趋势"}

# 规划阶段给用户的示例方向：只是提示文案，不绑定维度 id。
# 用户选了什么、写了什么，就按那一条动态生成维度，不做 id 归一。
ASPECT_HINTS = (
    ("面试流程", "面经、几面、手撕、系统设计"),
    ("薪资福利", "薪资区间、13/14 薪、补贴与福利"),
    ("公司背景", "融资、团队规模、口碑、加班情况"),
)

DIM_MAX_QUERIES = 6
DIM_EVIDENCE_PREFIX = {"jobs": "J", "trend": "T"}

# 页数由用户按维度配置（每维各抓 N 页），不再预置各维度的权重上限。
# 抓取页数与送入模型的阅读量是两件事：这里只限制「一个维度最多给模型多少字符」。
MAX_PAGE_CHARS = 3500
MAX_GROUP_CHARS = int(os.getenv("MARKET_GROUP_CHARS", "48000"))
# 单页保留下限：预算摊薄到每页时不低于此值，否则正文太短撑不起结论。
MIN_PAGE_CHARS = 1000

REPORT_FIXED_SECTIONS = (
    ("overview", "岗位概览"),
    ("skills", "技能要求"),
)


def report_sections(brief: "Brief") -> list[tuple[str, str]]:
    """报告目录：岗位概览 + 技能要求 + 每个已选动态方面一章 + 总结与建议。

    动态章节 id 直接用维度 id，标题用该维度的展示名，与左侧维度卡片、证据前缀一一对应；
    没选的方面不会出现空章节。总结章节覆盖各章核心结论。
    """
    sections: list[tuple[str, str]] = list(REPORT_FIXED_SECTIONS)
    for dim in brief.aspects:
        if dim in FIXED_DIMS:
            continue
        sections.append((dim, dim_label(dim, brief.aspect_labels)))
    if brief.has_resume:
        sections.append(("profile", "简历对照"))
    sections.append(("conclusion", "总结与建议"))
    return sections

# 固定维度：走专用 agent 与专用 schema；其余维度统一走 aspect_agent。
GROUP_IDS = FIXED_DIMS
GROUP_LABELS = DIM_LABELS
GROUP_MAX_QUERIES = DIM_MAX_QUERIES
GROUP_KINDS = {}


def dim_label(dim: str, labels: dict[str, str] | None = None) -> str:
    """维度中文名；动态维度从 labels 取，取不到时回退到 id 本身。"""
    if labels and labels.get(dim):
        return labels[dim]
    return DIM_LABELS.get(dim, dim)


def dim_prefix(dim: str) -> str:
    return DIM_EVIDENCE_PREFIX.get(dim, "E")


def evidence_prefixes(groups: list[dict]) -> dict[str, str]:
    """按分组顺序分配证据前缀：固定维度用 J/T，其余维度依次 E1、E2…

    前端据此把 E1 这类编号还原成维度，所以采集和规划必须用同一套分配结果。
    """
    result: dict[str, str] = {}
    custom_index = 0
    for group in groups:
        dim = str(group.get("id") or "")
        if not dim or dim in result:
            continue
        prefix = DIM_EVIDENCE_PREFIX.get(dim)
        if not prefix:
            custom_index += 1
            prefix = f"E{custom_index}"
        result[dim] = prefix
    return result


class GraphNode(TypedDict, total=False):
    id: str
    label: str
    kind: str
    parent: str


class GraphEdge(TypedDict, total=False):
    source: str
    target: str
    dashed: bool


def graph_payload(has_resume: bool, dims: list[str] | None = None, labels: dict[str, str] | None = None) -> dict:
    """流程图：brief → planner → collect → 固定/动态 agent → synthesis → strategy → compose。"""
    dims = list(dims or FIXED_DIMS)
    nodes: list[GraphNode] = [
        {"id": "brief", "label": "任务简报", "kind": "code"},
        {"id": "planner", "label": "规划检索", "kind": "agent"},
        {"id": "collect", "label": "采集页面", "kind": "group"},
    ]
    if has_resume:
        # 画像不依赖采集结果，采集结束后和抽取 agent 同批并行，不再拖住抽取。
        nodes.append({"id": "profile", "label": "简历画像", "kind": "agent", "parent": "collect"})
    for dim in dims:
        nodes.append({"id": dim, "label": dim_label(dim, labels), "kind": "agent", "parent": "collect"})
    nodes.append({"id": "synthesis", "label": "跨源合成", "kind": "agent", "parent": "collect"})
    nodes.extend(
        [
            {"id": "strategy", "label": "策略总结", "kind": "agent"},
            {"id": "compose", "label": "整合报告", "kind": "agent"},
        ]
    )
    edges: list[GraphEdge] = [
        {"source": "brief", "target": "planner"},
        {"source": "planner", "target": "collect"},
    ]
    for dim in dims:
        edges.append({"source": "collect", "target": dim})
        edges.append({"source": dim, "target": "synthesis"})
    if has_resume:
        # 画像与各维度抽取并行，结果写 state 供 strategy / compose 使用。
        edges.append({"source": "collect", "target": "profile", "dashed": True})
    edges.extend(
        [
            {"source": "synthesis", "target": "strategy"},
            {"source": "strategy", "target": "compose"},
        ]
    )

    return {"nodes": nodes, "edges": edges, "hasResume": has_resume, "dims": dims}
