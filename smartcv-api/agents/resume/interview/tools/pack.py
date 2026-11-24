"""画像 id 补全、问题卡分组、卡片校准与结构校验。

这里只做确定性的数据加工，不调用模型：

  assign_profile   核对锚点原文、补全项目 / 锚点 id、为技术栈补追溯锚点
  group_specs      按 scene 拆分组（项目一个组 / 综合五个主题组 / 排查三类题型）
  primary_techs    按等级、项目使用与求职方向给出排查面试的主技术栈提示
  prepare_cards    单组卡片归一化（补证据引用、清理空追问 / 空信号、清空答案）
  focus_gap        考察方向的维度占比检查；不达标只提示，不阻断整组
  assign_ids       合并后统一编号
"""

from __future__ import annotations

from agents.resume.interview.schemas import (
    Anchor,
    PackRequest,
    ProfileExtraction,
    ProjectItem,
    QuestionCard,
    ReferenceAnswer,
    ResumeProfile,
    TechStackItem,
)
from agents.resume.interview.tools.text import quote_in_text
from agents.utils.resume import norm_text, resolve_refs

_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}

# 项目至少要这么多条可追溯锚点，才值得单独出题。
MIN_PROJECT_ANCHORS = 2

COMPREHENSIVE_THEMES = [
    ("motivation", "求职动机", "为什么离开上一段经历、为什么选择这个方向与这类团队；动机要与简历经历自洽"),
    ("career_plan", "职业规划", "未来 1-3 年想成为什么样的工程师、成长路径与目标岗位的匹配度"),
    ("salary", "薪资期望", "期望区间与依据、可接受的弹性；只问期望，不追问隐私"),
    ("stability", "稳定性", "离职原因、空窗期、频繁变动的解释、到岗时间"),
    ("authenticity", "项目真实性", "挑简历里最亮的结果或最含糊的表述，核对数据口径、个人贡献与细节"),
]

# 排查面试的三类题型；分组对用户不可见，只用于让每类题单独结构化生成。
SCENARIO_THEMES = [
    ("troubleshoot", "故障排查"),
    ("performance", "性能优化"),
    ("design", "方案设计"),
]

_LEVEL_RANK = {"精通": 3, "熟练": 2, "掌握": 1}

# 考察方向只作用于项目面试；未选择方向或综合面试用 balanced，不追加提示词，也不做比例校验。
FOCUS_LABELS = {
    "business": "业务场景",
    "tech": "实现细节",
    "architecture": "架构设计",
    "review": "复盘决策",
}
FOCUS_DIMENSIONS = {
    "business": {"project_background", "business_need", "result", "contribution"},
    "tech": {"implementation", "tech_stack", "difficulty"},
    "architecture": {"architecture", "difficulty", "problem_solving"},
    "review": {"architecture", "difficulty", "problem_solving", "result", "contribution"},
}
FOCUS_DIMENSION_LABELS = {
    "project_background": "项目背景",
    "business_need": "业务需求",
    "result": "项目成果",
    "contribution": "个人贡献",
    "implementation": "核心实现",
    "tech_stack": "技术栈掌握",
    "difficulty": "技术难点",
    "architecture": "架构选型",
    "problem_solving": "问题解决",
}
FOCUS_MIN_RATIO = 0.6


def focus_gap(cards: list[QuestionCard], focus: str) -> str:
    """检查方向是否落在约定维度内；不达标只提示，不阻断整包。"""
    dimensions = FOCUS_DIMENSIONS.get(focus)
    if not dimensions or not cards:
        return ""
    matched = sum(1 for card in cards if card.dimension in dimensions)
    if matched / len(cards) >= FOCUS_MIN_RATIO:
        return ""
    names = "、".join(
        FOCUS_DIMENSION_LABELS[dimension]
        for dimension in sorted(dimensions)
        if dimension in FOCUS_DIMENSION_LABELS
    )
    label = FOCUS_LABELS.get(focus, focus)
    return (
        f"考察方向为「{label}」，但只有 {matched}/{len(cards)} 张卡的考察维度落在"
        f"{names}内；请调整主问题与追问，使至少 60% 的卡片覆盖该方向。"
    )


def _project_text(project: ProjectItem) -> str:
    parts = [project.name, project.intro, project.role, *project.highlights, *project.tech_stack]
    return "\n".join(str(p) for p in parts if p)


def profile_payload(profile: ResumeProfile) -> dict:
    """画像 JSON：去掉引用坐标，只留下模型出题需要的事实。

    坐标是给前端定位用的，混进提示词或数字校验只会增加噪声。
    """
    data = profile.model_dump()
    data.pop("intro_refs", None)
    for item in data.get("tech_stacks") or []:
        item.pop("refs", None)
    return data


def anchor_payload(anchor: Anchor, *, by_alias: bool = False) -> dict:
    """锚点的出题用 JSON：只留原文 quote，不把引用坐标喂给模型。"""
    data = anchor.model_dump(by_alias=by_alias)
    data.pop("refs", None)
    return data


def _tech_used(name: str, project: ProjectItem) -> bool:
    key = name.casefold()
    for tech in project.tech_stack:
        other = (tech or "").strip().casefold()
        if other and (key in other or other in key):
            return True
    return False


def primary_techs(profile: ResumeProfile, limit: int = 3) -> list[str]:
    """按等级、项目使用与求职方向给出主技术栈提示。

    只作为排查面试的出题重心，不替代模型对项目描述的判断；简历里并列列出的
    多门技术不会因此被平均分配。
    """
    direction = profile.direction.casefold()
    scores: dict[str, int] = {}
    names: dict[str, str] = {}

    def add(name: str, score: int) -> None:
        key = name.casefold()
        if key not in names:
            names[key] = name
            scores[key] = score
        else:
            scores[key] = max(scores[key], score)

    for item in profile.tech_stacks:
        name = (item.name or "").strip()
        if not name:
            continue
        used = sum(1 for project in profile.projects if _tech_used(name, project))
        add(
            name,
            _LEVEL_RANK.get(item.level, 1) * 2
            + used
            + (2 if name.casefold() in direction else 0),
        )

    for project in profile.projects:
        for tech in project.tech_stack:
            tech = (tech or "").strip()
            if tech:
                add(tech, 1)

    ranked = sorted(scores, key=lambda key: (-scores[key], names[key]))
    return [names[key] for key in ranked[:limit]]


def _resolved_quote(
    resume: list[dict],
    resume_text: str,
    refs,
    fallback: str = "",
) -> tuple[str, list[list[int]]]:
    """按坐标解析引用；每个文字单元都要通过原文核对。

    坐标为空时保留旧的 quote 兜底，兼容升级前保存的画像；
    给了坐标但全部无效时不回退到 quote，避免把错误的坐标悄悄当成有效引用。
    """
    resolved = [
        (ref, text)
        for ref, text in resolve_refs(resume, refs)
        if quote_in_text(text, resume_text)
    ]
    if resolved:
        return "\n".join(text for _, text in resolved), [ref for ref, _ in resolved]
    if not refs:
        quote = (fallback or "").strip()
        if quote and quote_in_text(quote, resume_text):
            return quote, []
    return "", []


def assign_profile(
    extraction: ProfileExtraction,
    resume: list[dict],
    resume_text: str,
) -> tuple[ResumeProfile, list[Anchor], list[str]]:
    """把模型输出收敛成可追溯的画像；坐标解析不到原文的锚点直接丢弃。"""
    warnings: list[str] = []

    projects: list[ProjectItem] = []
    key_to_id: dict[str, str] = {}
    for raw in extraction.projects:
        name = (raw.name or "").strip()
        if not name:
            warnings.append("已丢弃一个没有名称的项目")
            continue
        project = raw.model_copy(deep=True)
        project.name = name
        project.id = f"p{len(projects) + 1}"
        projects.append(project)
        for key in (raw.id, name):
            if key:
                key_to_id[str(key)] = project.id

    tech_stacks: list[TechStackItem] = []
    seen_tech: set[str] = set()
    for item in extraction.tech_stacks:
        name = (item.name or "").strip()
        key = name.casefold()
        if not name or key in seen_tech:
            continue
        seen_tech.add(key)
        quote, refs = _resolved_quote(resume, resume_text, item.refs, item.quote)
        tech_stacks.append(item.model_copy(update={"name": name, "quote": quote, "refs": refs}))

    intro_source, intro_refs = _resolved_quote(
        resume, resume_text, extraction.intro_refs, extraction.intro
    )
    profile = ResumeProfile(
        direction=(extraction.direction or "").strip(),
        intro=(extraction.intro or "").strip() or intro_source,
        intro_refs=intro_refs,
        tech_stacks=tech_stacks,
        projects=projects,
    )

    anchors: list[Anchor] = []
    seen_anchor: set[tuple[str, str]] = set()
    dropped = 0
    for raw in extraction.anchors:
        quote, refs = _resolved_quote(resume, resume_text, raw.refs, raw.quote)
        if not quote:
            dropped += 1
            continue
        key = (raw.kind, norm_text(quote))
        if key in seen_anchor:
            continue
        seen_anchor.add(key)

        project_id = str(raw.project_id or "").strip()
        if project_id not in {p.id for p in projects}:
            project_id = key_to_id.get(project_id, "")
        if not project_id:
            # 模型没给项目 id 时，用原文反查：引用出现在哪个项目里就归到哪个项目。
            for project in projects:
                if quote_in_text(quote, _project_text(project)):
                    project_id = project.id
                    break
        anchors.append(
            raw.model_copy(update={"quote": quote, "refs": refs, "project_id": project_id})
        )

    if dropped:
        warnings.append(f"已丢弃 {dropped} 个引用坐标无法在简历中定位的锚点")

    # 技术栈有原文依据但模型没给锚点时，补一条 tech 锚点，
    # 保证清单里的技术栈问题也能关联到可追溯的证据。
    for item in tech_stacks:
        if not item.quote or not quote_in_text(item.quote, resume_text):
            continue
        covered = any(
            anchor.kind == "tech" and quote_in_text(item.quote, anchor.quote)
            for anchor in anchors
        )
        if covered:
            continue
        anchors.append(
            Anchor(
                kind="tech",
                refs=item.refs,
                quote=item.quote,
                follow_directions=["原理与边界", "项目中的真实用法", "遇到的问题与取舍"],
            )
        )

    # 锚点太少的项目多半是简历里轻轻带过的一段，撑不起追问，不留在画像里。
    kept = [
        project
        for project in projects
        if sum(1 for anchor in anchors if anchor.project_id == project.id) >= MIN_PROJECT_ANCHORS
    ]
    if len(kept) != len(projects):
        warnings.append(
            f"已丢弃 {len(projects) - len(kept)} 个证据锚点不足 {MIN_PROJECT_ANCHORS} 条的项目"
        )
        kept_ids = {project.id for project in kept}
        dropped_ids = {project.id for project in projects} - kept_ids
        anchors = [anchor for anchor in anchors if anchor.project_id not in dropped_ids]
        remap = {project.id: f"p{index}" for index, project in enumerate(kept, 1)}
        for project in kept:
            project.id = remap[project.id]
        for anchor in anchors:
            if anchor.project_id in remap:
                anchor.project_id = remap[anchor.project_id]
        profile = profile.model_copy(update={"projects": kept})

    for index, anchor in enumerate(anchors, 1):
        anchor.id = f"a{index}"
    return profile, anchors, warnings


def group_specs(
    req: PackRequest, profile: ResumeProfile, anchors: list[Anchor]
) -> list[dict]:
    """按场景拆分组；组间并发，每组一次结构化调用。"""
    project_by_id = {p.id: p for p in profile.projects}

    def anchors_for_project(project_id: str) -> list[dict]:
        picked = [a for a in anchors if a.project_id == project_id]
        if not picked:
            picked = list(anchors)
        return [anchor_payload(anchor) for anchor in picked]

    if req.scene == "project":
        # 项目面试只围绕所选的一个项目出题，题量由模型按证据量决定。
        project = project_by_id[req.project_ids[0]]
        return [
            {
                "key": f"project:{project.id}",
                "kind": "project",
                "label": project.name,
                "theme": "",
                "project": project.model_dump(),
                "tech": "",
                "anchors": anchors_for_project(project.id),
            }
        ]

    if req.scene == "scenario":
        # 排查面试固定拆成三类题型；用户只选场景，不感知分组。
        return [
            {
                "key": f"scenario:{theme_id}",
                "kind": "scenario",
                "label": label,
                "theme": theme_id,
                "project": {},
                "tech": "",
                "anchors": [anchor_payload(anchor) for anchor in anchors],
            }
            for theme_id, label in SCENARIO_THEMES
        ]

    # comprehensive：五个主题各一组，每组由模型按主题出 1~2 张卡。
    return [
        {
            "key": f"theme:{theme_id}",
            "kind": "theme",
            "label": label,
            "theme": focus,
            "project": {},
            "tech": "",
            "anchors": [anchor_payload(anchor) for anchor in anchors],
        }
        for theme_id, label, focus in COMPREHENSIVE_THEMES
    ]


def prepare_cards(
    cards: list[QuestionCard],
    *,
    scene: str,
    profile: ResumeProfile,
    anchors: list[Anchor],
    resume_text: str,
) -> list[QuestionCard]:
    """单组卡片归一化：补证据引用、清理空追问与空信号，不做结构校验。

    出题阶段不保留任何参考答案；即使模型擅自输出，也在这里清空，
    确保答案只会在进入清单后由答案 Agent 生成。
    """
    anchor_by_id = {a.id: a for a in anchors}
    project_ids = {p.id for p in profile.projects}
    prepared: list[QuestionCard] = []

    for card in cards:
        if not (card.main_question or "").strip():
            continue
        card = card.model_copy(deep=True)
        card.main_question = card.main_question.strip()
        card.intent = (card.intent or "").strip()
        card.dimension = card.dimension or "implementation"
        card.priority = card.priority or "medium"
        card.project_id = card.project_id if card.project_id in project_ids else ""

        anchor = anchor_by_id.get(card.anchor_id)
        if anchor is not None:
            if not card.project_id:
                card.project_id = anchor.project_id
            if not card.evidence_quote or not quote_in_text(card.evidence_quote, resume_text):
                card.evidence_quote = anchor.quote
        elif card.evidence_quote and not quote_in_text(card.evidence_quote, resume_text):
            card.evidence_quote = ""
        if anchor is None and scene == "scenario":
            # 排查面试的锚点是可选的；模型自造的 id 会让建场校验失败，直接清空。
            card.anchor_id = ""

        follow_ups = []
        seen: set[str] = set()
        for follow in card.follow_ups:
            question = (follow.question or "").strip()
            key = norm_text(question)
            if not question or key in seen:
                continue
            seen.add(key)
            follow_ups.append(
                follow.model_copy(
                    update={"question": question, "reference_answer": ReferenceAnswer()}
                )
            )
        card.follow_ups = follow_ups

        card.leak_signals = [
            text.strip() for text in card.leak_signals if text and text.strip()
        ]
        card.coverage = [text.strip() for text in card.coverage if text and text.strip()]
        if not card.coverage:
            card.coverage = [card.dimension]
        card.dynamic_questions = []

        card.reference_answer = ReferenceAnswer()

        prepared.append(card)
    return prepared


def assign_ids(cards: list[QuestionCard]) -> list[QuestionCard]:
    """合并后统一编号；卡片、追问、动态追问的 id 都以卡片序号为前缀。"""
    for index, card in enumerate(cards, 1):
        card.id = f"c{index}"
        for order, follow in enumerate(card.follow_ups, 1):
            follow.id = f"f{index}_{order}"
        for order, dynamic in enumerate(card.dynamic_questions, 1):
            dynamic.id = dynamic.id or f"d{index}_{order}"
    return cards


def dedupe_cards(cards: list[QuestionCard]) -> list[QuestionCard]:
    seen: set[str] = set()
    result: list[QuestionCard] = []
    for card in cards:
        key = norm_text(card.main_question)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(card)
    return result


def sort_cards(cards: list[QuestionCard], *, keep_order: bool = False) -> list[QuestionCard]:
    """默认保持生成顺序；面试出题时再按优先级取。"""
    if keep_order:
        return cards
    return sorted(cards, key=lambda c: _PRIORITY_RANK.get(c.priority, 1))


def first_pending(cards: list[QuestionCard], done_ids: set[str]) -> QuestionCard | None:
    """未答卡片里优先级最高的一张；同优先级按生成顺序。"""
    pending = [
        (index, card)
        for index, card in enumerate(cards)
        if card.id not in done_ids
    ]
    if not pending:
        return None
    return min(
        pending,
        key=lambda item: (_PRIORITY_RANK.get(item[1].priority, 1), item[0]),
    )[1]


_DIMENSION_LABEL = {
    "project_background": "项目背景",
    "business_need": "业务需求",
    "architecture": "架构选型",
    "implementation": "核心实现",
    "difficulty": "技术难点",
    "problem_solving": "问题解决",
    "result": "项目成果",
    "contribution": "个人贡献",
    "tech_stack": "技术栈掌握",
    "motivation": "求职动机",
    "career_plan": "职业规划",
    "salary": "薪资",
    "stability": "稳定性",
    "authenticity": "项目真实性",
}


def dimension_label(dimension: str) -> str:
    return _DIMENSION_LABEL.get(dimension, dimension)
