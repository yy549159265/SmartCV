"""市场洞察的请求 / 结构化输出 / 事件条目模型。

分层：
  MarketRequest   前端请求（camelCase，经 alias 收进来）
  Brief           归一化后的任务简报（后端内部统一 snake_case）
  *Result         每个 agent 的 response_format，结构化输出由 LangChain 校验
  Finding         右侧面板与报告草稿共用的渲染条目（与前端 Item 协议一致）
  ReportSection   最终报告的章节（固定首尾 + 本次选择的动态方面）

硬约束：所有结论都必须带 evidence_ids；没有证据的字段留空，不靠模型补写。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from schemas.provider import ProviderConfig

QueryGroupId = str
Coverage = Literal["full", "partial", "none"]
FindingKind = Literal["fact", "bar", "step", "pair"]

# 每维页数按三类维度分别设置：固定维度 jobs / trend，其余动态方向统一走 other。
PAGES_PER_DIM_KEYS = ("jobs", "trend", "other")
PAGES_PER_DIM_DEFAULT = 12
PAGES_PER_DIM_MAX = 60


def pages_key(dim: str) -> str:
    """动态维度的 id 不固定，页数配置统一归到 other。"""
    return dim if dim in ("jobs", "trend") else "other"


def default_pages_per_dim() -> dict[str, int]:
    return {key: PAGES_PER_DIM_DEFAULT for key in PAGES_PER_DIM_KEYS}


def normalize_pages_per_dim(value: object) -> dict[str, int]:
    """收窄成三类维度各自的 1~60 页；兼容旧请求里的单个数字。"""
    if isinstance(value, dict):
        source = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        source = {key: value for key in PAGES_PER_DIM_KEYS}
    else:
        source = {}
    result: dict[str, int] = {}
    for key in PAGES_PER_DIM_KEYS:
        try:
            pages = int(source.get(key, PAGES_PER_DIM_DEFAULT))
        except (TypeError, ValueError):
            pages = PAGES_PER_DIM_DEFAULT
        result[key] = max(1, min(PAGES_PER_DIM_MAX, pages))
    return result


class ExtraUrl(BaseModel):
    """用户补充的一条网址及其标签。

    direction 决定采集时把页面归到哪个调研维度：jobs / trend / other；
    note 是自由备注，direction=other 时用来判断它属于哪个动态调研方面。
    """

    url: str = ""
    direction: str = Field("other", description="调研方向：jobs / trend / other")
    note: str = Field(
        "",
        description="用户备注（必填）：岗位 / 方向 / 级别；「其他」按它分流，超配额时按它筛选",
    )


class SourceSelectionItem(BaseModel):
    """一条补充网址的判定结果：留在哪个维度、是否入选。"""

    url: str = Field(..., description="原样返回用户提供的网址")
    dim: str = Field("", description="归到的维度 id；必须从候选维度里选")
    keep: bool = Field(True, description="是否与本轮目标意向相关；无关的填 false")


class SourceSelection(BaseModel):
    """一次调用判定所有补充网址的去向与取舍。"""

    selections: list[SourceSelectionItem] = Field(default_factory=list)


class MarketRequest(BaseModel):
    """一次市场调研的入参。

    前端只要求「目标岗位」或「一份简历」二选一；缺的字段由 planner 多轮反问补全，
    因此 target_role 允许为空，最终必填校验放在路由层（避免误伤只选了简历的请求）。
    """

    model_config = ConfigDict(populate_by_name=True)

    target_role: str = Field("", alias="targetRole", description="目标岗位；可与 resume 二选一")
    city: str = Field("", description="城市；空字符串表示不限")
    experience: str = Field("", description="年限要求；可空，planner 判断是否需要反问")
    direction: str = Field(
        "",
        alias="direction",
        description=(
            "用户希望 AI 回答的内容：自由文本问题/诉求；planner 据此生成第二轮调研方面，"
            "后续检索、抽取、策略与报告都必须围绕它作答；为空时仍通过两轮反问确认岗位信息与调研方面"
        ),
    )
    time_range: str = Field(
        "3m",
        alias="timeRange",
        description="3m / 6m / 12m / 3y，或自定义月数如 18m；由后端换算成绝对年月",
    )
    pages_per_dim: dict[str, int] = Field(
        default_factory=default_pages_per_dim,
        alias="pagesPerDim",
        description=(
            "按维度类别分别设置的每维页数：jobs 招聘矩阵、trend 技术趋势、other 其他动态方向；"
            "各自 1~60，缺省 12"
        ),
    )
    urls_per_dim: int = Field(
        12,
        alias="urlsPerDim",
        ge=1,
        le=60,
        description="每个调研方向最多使用的补充网址条数",
    )
    fetch_mode: str = Field(
        "get",
        alias="fetchMode",
        description="抓取方式：get（普通 GET）/ crawler（Scrapling 抓取并转正文 Markdown）",
    )
    collector: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {"searxng": {}},
        description=(
            "采集方式及其设置：{方式 id: {设置键: 值}}；searxng 无需设置，"
            "deepseek 需要 baseUrl（接口地址）与 apiKey"
        ),
    )
    sources: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description=(
            "用户勾选的来源渠道：key 为来源 id / 名称，value 为该源自己的设置；"
            "设置键和值均为英文枚举（如 recruitType: experienced / campus），"
            "没有设置时为空对象"
        ),
    )
    extra_urls: list[ExtraUrl] = Field(
        default_factory=list,
        alias="extraUrls",
        description="用户补充的带标签网址；direction 决定采集归到哪个维度",
    )
    resume: list[dict] | None = Field(None, description="当前简历快照，直接复用简历 JSON；不提供时为 None")
    provider: ProviderConfig = Field(..., description="本次请求使用的供应商配置")

    @field_validator("pages_per_dim", mode="before")
    @classmethod
    def _accept_pages(cls, value: object) -> dict[str, int]:
        """三类维度都补齐并收窄到 1~60；兼容旧请求里的单个数字。"""
        return normalize_pages_per_dim(value)

    @field_validator("collector", mode="before")
    @classmethod
    def _accept_collector(cls, value: object) -> object:
        """兼容只传方式名 / 方式名数组；空值回落到 SearXNG。"""
        if not value:
            return {"searxng": {}}
        if isinstance(value, str):
            return {value.strip(): {}}
        if isinstance(value, (list, tuple, set)):
            return {str(item).strip(): {} for item in value if str(item or "").strip()}
        return value

    @field_validator("sources", mode="before")
    @classmethod
    def _accept_source_list(cls, value: object) -> object:
        """兼容旧前端的字符串数组：按「没有动态参数」的来源收下。"""
        if value is None:
            return {}
        if isinstance(value, (list, tuple, set)):
            return {str(item).strip(): {} for item in value if str(item or "").strip()}
        return value

    @computed_field
    @property
    def has_resume(self) -> bool:
        return bool(self.resume)


class Brief(BaseModel):
    """归一化后的任务简报，后续 agent 只读这一份。"""

    target_role: str
    city: str = ""
    experience: str = ""
    direction: str = Field(
        "",
        description=(
            "用户希望 AI 回答的内容（自由文本问题/诉求）；planner 据此生成第二轮调研方面，"
            "后续检索/抽取/合成/策略/报告都必须围绕它作答"
        ),
    )
    time_window: str = ""
    date_range: str = Field("", description="由 time_window 换算的绝对年月区间，如 2025.11-2026.11；模型不要自己推算日期")
    collector: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {"searxng": {}},
        description="采集方式及其设置：{方式 id: {设置键: 值}}，由采集适配器注册表解释",
    )
    sources: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="勾选的来源及其设置：{来源名称: {设置键: 值}}，键值均为英文枚举",
    )
    extra_urls: list[ExtraUrl] = Field(default_factory=list, description="带方向标签的补充网址")
    aspects: list[str] = Field(default_factory=list, description="动态调研方面 id；固定维度之外的部分")
    aspect_labels: dict[str, str] = Field(default_factory=dict, description="动态方面 id → 展示名（含自定义）")
    has_resume: bool = False
    mode: Literal["A", "B"] = "A"

    @property
    def location(self) -> str:
        return self.city or "不限"

    def describe(self) -> str:
        parts = [self.target_role or "待确认岗位", self.location, self.time_window or "时间不限"]
        if self.experience:
            parts.append(self.experience)
        return " · ".join(part for part in parts if part)


class BriefPatch(BaseModel):
    """planner 反问后补全的简报字段；只覆盖非空值。"""

    target_role: str = ""
    city: str = ""
    experience: str = ""
    time_window: str = ""


class QueryGroup(BaseModel):
    """一组检索词：固定维度 jobs / trend，或用户选择的动态方面。"""

    id: str = Field(..., description="维度 id：jobs / trend / 用户所选方面的短 id")
    label: str = Field(..., description="中文标签，展示用")
    queries: list[str] = Field(..., min_length=1, max_length=6, description="本组检索词，2~6 条")


class PlanResult(BaseModel):
    """planner agent 的结构化输出。"""

    brief: BriefPatch = Field(default_factory=BriefPatch, description="反问后确认/补全的简报字段")
    aspects: list[str] = Field(
        default_factory=list,
        description="用户在第二轮反问中选择的调研方面 id：自己生成的短 id 或中文名；固定 jobs / trend 不要填",
    )
    aspect_labels: dict[str, str] = Field(
        default_factory=dict,
        description="调研方面 id → 展示名；自定义方面用中文名",
    )
    groups: list[QueryGroup] = Field(..., description="每个维度一组检索词，缺组时由代码补默认值")
    notes: str = Field("", description="本次检索策略的一句话说明")


class ReleaseNote(BaseModel):
    """某个技术的版本发展：哪项技术、发生了哪些版本变化。"""

    tech: str = Field(..., description="技术名，如 React / Vue / LangGraph")
    text: str = Field(..., description="该技术的版本变化摘要，纯文本")
    evidence_ids: list[str] = Field(default_factory=list, description="来源页码 id，如 T1")


class EvidencedText(BaseModel):
    """一条带证据的纯文本结论：行动优先级、写法提示、风险、来源差异。"""

    text: str = Field(..., description="结论正文，纯文本")
    evidence_ids: list[str] = Field(default_factory=list, description="来源页码 id，如 J1 / T2")


class Finding(BaseModel):
    """右侧面板 / 报告草稿共用的条目。"""

    id: str = Field("", description="幂等键；为空时由代码生成")
    kind: FindingKind = Field("fact", description="fact / bar / step / pair")
    label: str = Field(..., description="条目标题或短标签")
    text: str = Field("", description="条目正文，纯文本")
    count: int | None = Field(None, description="bar 的计数")
    total: int | None = Field(None, description="bar 的分母")
    pct: float | None = Field(None, description="bar 的百分比 0~100")
    trend: Literal["up", "down", "flat"] | None = Field(None, description="趋势方向")
    tag: Literal["hit", "gap", "transfer"] | None = Field(None, description="pair 的标签")
    evidence_ids: list[str] = Field(default_factory=list, description="来源页码 id，如 J1")


class AspectOverview(BaseModel):
    """动态方面的汇总卡：调研范围与整体总结。"""

    research_scope: str = Field("", description="本次方面的调研范围：对象、时间、地域、岗位或企业")
    research_summary: str = Field("", description="本方面调研的整体总结，只归纳资料支持的事实")


class AspectBasicInformation(BaseModel):
    """基本情况：调研对象的背景和基础信息。"""

    summary: str = Field("", description="基本情况的归纳总结")
    background: str = Field("", description="调研对象的背景信息，含当前状态")
    scope: str = Field("", description="对象涉及的范围、规模、覆盖领域")
    key_data: list[str] = Field(default_factory=list, description="关键基础数据：规模、数量、时间等")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑基本情况的来源编号")


class AspectCoreContent(BaseModel):
    """核心内容：调研对象的主要组成或核心特征。"""

    summary: str = Field("", description="核心内容的归纳总结")
    main_contents: list[str] = Field(default_factory=list, description="主要内容：业务组成、项目类型、福利组成等")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑核心内容的来源编号")


class AspectKeyDirections(BaseModel):
    """重点方向：当前值得关注的重点或核心事项。"""

    summary: str = Field("", description="重点方向的归纳总结")
    directions: list[str] = Field(default_factory=list, description="具体重点方向，按重要程度从高到低")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑重点方向判断的来源编号")


class AspectSpecificPerformance(BaseModel):
    """具体表现：实际运行情况、数据表现和具体实施情况。"""

    summary: str = Field("", description="实际表现的归纳总结")
    performance_metrics: list[str] = Field(default_factory=list, description="具体指标和统计数据：时长、薪资、占比、频次等")
    typical_cases: list[str] = Field(default_factory=list, description="典型案例，用于说明实际情况")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑实际表现和统计结果的来源编号")


class AspectAdvantages(BaseModel):
    """优势与特点：调研对象的优势、亮点和差异化特征。"""

    summary: str = Field("", description="优势与特点的归纳总结")
    key_advantages: list[str] = Field(default_factory=list, description="主要优势和差异化特点")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑优势判断的来源编号")


class AspectProblems(BaseModel):
    """存在问题：调研过程中发现的痛点和风险。"""

    summary: str = Field("", description="问题与风险的归纳总结")
    key_problems: list[str] = Field(default_factory=list, description="主要问题，例如加班严重、项目延期")
    risk_points: list[str] = Field(default_factory=list, description="潜在风险，例如业务不稳定、管理风险")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑问题和风险判断的来源编号")


class AspectDevelopmentTrends(BaseModel):
    """发展趋势：调研对象的变化情况和未来发展方向。"""

    summary: str = Field("", description="发展趋势的归纳总结")
    current_changes: list[str] = Field(default_factory=list, description="当前已经出现的变化")
    future_directions: list[str] = Field(default_factory=list, description="未来可能的发展方向，含潜在机会")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑趋势判断的来源编号")


class AspectComprehensiveAnalysis(BaseModel):
    """综合分析：对调研发现进行归纳和判断。"""

    summary: str = Field("", description="综合分析的整体总结和整体评价")
    key_conclusions: list[str] = Field(default_factory=list, description="最终得出的关键结论和重要洞察")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑综合分析结论的来源编号")


class AspectResult(BaseModel):
    """动态调研方面的通用抽取结果；固定维度仍走各自的 schema。"""

    overview: AspectOverview = Field(default_factory=AspectOverview)
    basic_information: AspectBasicInformation = Field(default_factory=AspectBasicInformation)
    core_content: AspectCoreContent = Field(default_factory=AspectCoreContent)
    key_directions: AspectKeyDirections = Field(default_factory=AspectKeyDirections)
    specific_performance: AspectSpecificPerformance = Field(default_factory=AspectSpecificPerformance)
    advantages: AspectAdvantages = Field(default_factory=AspectAdvantages)
    problems: AspectProblems = Field(default_factory=AspectProblems)
    development_trends: AspectDevelopmentTrends = Field(default_factory=AspectDevelopmentTrends)
    comprehensive_analysis: AspectComprehensiveAnalysis = Field(default_factory=AspectComprehensiveAnalysis)
    notes: str = ""


class ResearchInfo(BaseModel):
    """本轮调研的样本概况，前端汇总卡直接展示。"""

    research_topic: str = Field("", description="本轮调研的目标岗位或职业方向")
    total_pages: int = Field(0, description="纳入本轮分析的页面总数")
    valid_pages: int = Field(0, description="包含可用招聘信息的有效页面数")
    invalid_pages: int = Field(0, description="无实质内容、重复或无关的页面数")
    companies: list[str] = Field(default_factory=list, description="本轮样本中涉及的企业")
    coverage: Literal["complete", "partial", "insufficient"] = Field(
        "insufficient", description="信息覆盖情况：complete / partial / insufficient"
    )


class CountStat(BaseModel):
    """按页面数量统计的一项事实。"""

    name: str = Field(..., description="统计项名称")
    count: int = Field(0, description="提及该项的有效页面数")
    percentage: float = Field(0.0, description="占有效页面的百分比 0~100")
    evidence_ids: list[str] = Field(
        default_factory=list, description="支撑该项的页面编号，如 J1；无法归属时留空，不编造"
    )


class SalaryRange(BaseModel):
    """一档薪资区间的统计。"""

    min: int | None = Field(None, description="薪资下限；统一换算为月薪人民币时才填写")
    max: int | None = Field(None, description="薪资上限")
    unit: str = Field("CNY/month", description="薪资单位；不能直接折算时保留原单位")
    salary_months: int | None = Field(None, description="一年几薪，未明确则为 None")
    count: int = Field(0, description="符合该薪资区间的页面数")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑该区间的页面编号")


class SalaryMatrix(BaseModel):
    """薪资信息汇总。"""

    available_count: int = Field(0, description="有明确薪资信息的页面数")
    unavailable_count: int = Field(0, description="没有明确薪资信息的页面数")
    salary_ranges: list[SalaryRange] = Field(default_factory=list)
    evidence: str = Field("", description="薪资原始信息或归纳依据")
    summary: str = Field("", description="薪资情况总结")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑薪资结论的页面编号")


class JobDistribution(BaseModel):
    """岗位方向、企业分布与薪资情况。"""

    job_types: list[CountStat] = Field(default_factory=list, description="岗位方向及其出现页面数")
    company_distribution: list[CountStat] = Field(default_factory=list, description="企业分布")
    salary_matrix: SalaryMatrix | None = Field(None, description="薪资信息；没有明确薪资时为 None")
    summary: str = Field("", description="岗位分布整体归纳")


class TechnicalRequirement(CountStat):
    """一项技术需求。"""

    requirement_level: Literal["must_have", "preferred", "common", "unknown"] = Field(
        "unknown", description="must_have 明确必备 / preferred 明确加分 / common 经常出现 / unknown 无法判断"
    )
    evidence: str = Field("", description="支撑该判断的招聘内容归纳，不编造证据")


class TechnicalMatrix(BaseModel):
    """技术需求：只统计技术名称、框架、工具、平台。"""

    technologies: list[TechnicalRequirement] = Field(default_factory=list)
    summary: str = Field("", description="技术需求整体总结")


class AbilityRequirement(CountStat):
    """一项实际工作能力或职责。"""

    description: str = Field("", description="具体能力要求")
    importance: Literal["high", "medium", "low"] = Field("medium", description="综合重要程度")


class AbilityMatrix(BaseModel):
    """能力需求：只统计实际工作能力和职责，不重复列技术名称。"""

    abilities: list[AbilityRequirement] = Field(default_factory=list)
    ability_summary: str = Field("", description="能力需求整体总结")


class QualificationMatrix(BaseModel):
    """任职要求：只统计学历、专业、工作年限、项目背景等准入条件。"""

    education_requirements: list[CountStat] = Field(default_factory=list)
    experience_requirements: list[CountStat] = Field(default_factory=list)
    project_requirements: list[CountStat] = Field(default_factory=list)
    other_requirements: list[CountStat] = Field(default_factory=list)
    summary: str = Field("", description="任职要求整体总结")


class DataQuality(BaseModel):
    """本轮调研的数据质量说明。"""

    limitations: list[str] = Field(default_factory=list, description="本轮调研的数据局限")
    statistics_note: str = Field("", description="统计口径说明")
    unverified_items: list[str] = Field(default_factory=list, description="当前无法确认的信息")


class JobsResult(BaseModel):
    """招聘矩阵抽取结果。"""

    research_info: ResearchInfo = Field(default_factory=ResearchInfo)
    job_distribution: JobDistribution = Field(default_factory=JobDistribution)
    technical_matrix: TechnicalMatrix = Field(default_factory=TechnicalMatrix)
    ability_matrix: AbilityMatrix = Field(default_factory=AbilityMatrix)
    qualification_matrix: QualificationMatrix = Field(default_factory=QualificationMatrix)
    data_quality: DataQuality = Field(default_factory=DataQuality)
    coverage: Coverage = Field("none", description="内部覆盖度 full / partial / none")
    sample_size: int = Field(0, description="本次实际参考的页面数")
    notes: str = ""


class TrendOverview(BaseModel):
    """技术调研矩阵的汇总卡数据。"""

    total_technologies: int = Field(0, description="本轮调研识别出的不同技术总数")
    high_frequency_count: int = Field(0, description="高频技术数量")
    emerging_count: int = Field(0, description="新兴技术方向数量")
    application_scenario_count: int = Field(0, description="识别出的技术应用场景总数")
    top_technologies: list[str] = Field(default_factory=list, description="当前出现频率较高的技术名称")
    top_category: str = Field("", description="技术集中度最高的领域")
    time_range: str = Field("", description="本轮调研时间范围")
    research_summary: str = Field("", description="整体技术调研总结")


class CategoryStat(BaseModel):
    """一个技术领域的分布统计。"""

    name: str = Field(..., description="技术领域名称")
    technology_count: int = Field(0, description="该领域包含的不同技术数量")
    mention_count: int = Field(0, description="该领域技术在有效信息源中的累计提及次数")
    percentage: float = Field(0.0, description="占全部技术提及次数的比例 0~100")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑该领域统计的页面编号")


class CategoryDistribution(BaseModel):
    """技术领域分布。"""

    items: list[CategoryStat] = Field(default_factory=list)
    summary: str = ""


class FishboneTechnology(BaseModel):
    """鱼骨图中的一个技术节点。"""

    name: str = Field(..., description="标准化后的技术名称")
    total_count: int = Field(0, description="统计周期内提及该技术的信息源总数")
    monthly_counts: list[int] = Field(default_factory=list, description="按 months 顺序对应每个月的提及数量")
    percentage: float = Field(0.0, description="提及该技术的信息源占有效信息源总数的比例")
    evidence: str = Field("", description="支撑该技术频次的来源归纳")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑该技术统计的页面编号")


class FishboneBranch(BaseModel):
    """鱼骨图的一条主分支，按技术领域归类。"""

    category: str = Field(..., description="技术领域名称")
    technologies: list[FishboneTechnology] = Field(default_factory=list)


class TechnologyFishbone(BaseModel):
    """高频技术鱼骨图。"""

    center: str = Field("", description="鱼骨图中心主题")
    branches: list[FishboneBranch] = Field(default_factory=list)


class TechnologyFrequency(BaseModel):
    """高频技术及其月度分布。"""

    time_range: str = Field("", description="高频技术统计时间范围")
    months: list[str] = Field(default_factory=list, description="YYYY-MM 月份列表，作为月度统计时间轴")
    fishbone: TechnologyFishbone = Field(default_factory=TechnologyFishbone)
    summary: str = ""


class FrameworkItem(BaseModel):
    """一个代表性框架、工具或开源项目。"""

    name: str = Field(..., description="框架、工具或开源项目名称")
    type: str = Field("", description="项目类型")
    category: str = Field("", description="所属技术领域")
    description: str = Field("", description="核心定位和功能")
    related_technologies: list[str] = Field(default_factory=list, description="相关技术或配套生态")
    evidence: str = Field("", description="相关信息")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑该条目的页面编号")


class FrameworkEcosystem(BaseModel):
    """技术生态。"""

    items: list[FrameworkItem] = Field(default_factory=list)
    summary: str = ""


class TrendSignal(BaseModel):
    """一条技术趋势。"""

    name: str = Field(..., description="技术或趋势名称")
    category: str = Field("", description="所属技术领域")
    trend_type: Literal["rising", "stable", "declining", "emerging"] = Field(
        "stable", description="rising 上升 / stable 稳定 / declining 下降 / emerging 新兴"
    )
    description: str = Field("", description="趋势具体表现")
    time_range: str = Field("", description="趋势观察时间范围")
    change_points: list[str] = Field(default_factory=list, description="具体技术变化或发展方向")
    evidence: str = Field("", description="支撑趋势判断的来源归纳")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑该趋势的页面编号")


class TechnologyProblem(BaseModel):
    """一个技术问题与挑战。"""

    name: str = Field(..., description="问题名称")
    category: str = Field("", description="所属技术领域")
    description: str = Field("", description="问题具体表现")
    impact: str = Field("", description="问题产生的影响")
    related_technologies: list[str] = Field(default_factory=list, description="相关技术")
    evidence: str = Field("", description="问题依据")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑该问题的页面编号")


class TechnologyTrends(BaseModel):
    """新技术趋势与问题。"""

    trends: list[TrendSignal] = Field(default_factory=list)
    problems: list[TechnologyProblem] = Field(default_factory=list)
    summary: str = ""


class ScenarioStat(BaseModel):
    """一个应用场景的统计。"""

    name: str = Field(..., description="应用场景名称")
    count: int = Field(0, description="提及该应用场景的信息源数量")
    percentage: float = Field(0.0, description="提及该场景的信息源占有效信息源总数的比例")
    related_technologies: list[str] = Field(default_factory=list, description="支撑该场景的相关技术")
    evidence: str = Field("", description="应用案例依据")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑该场景的页面编号")


class ScenarioRanking(BaseModel):
    """应用场景排行。"""

    items: list[ScenarioStat] = Field(default_factory=list)
    summary: str = ""


class ScenarioTrendItem(BaseModel):
    """一个应用场景的月度变化。"""

    name: str = Field(..., description="应用场景名称")
    monthly_counts: list[int] = Field(default_factory=list, description="按 months 顺序对应每个月的提及数量")
    trend: Literal["rising", "stable", "declining"] = Field("stable", description="场景变化方向")
    evidence: str = Field("", description="场景变化依据")
    evidence_ids: list[str] = Field(default_factory=list, description="支撑该变化的页面编号")


class ScenarioTrends(BaseModel):
    """应用场景的月度变化。"""

    months: list[str] = Field(default_factory=list, description="YYYY-MM 月份列表，作为月度统计时间轴")
    items: list[ScenarioTrendItem] = Field(default_factory=list)
    summary: str = ""


class TechnologyApplications(BaseModel):
    """技术应用与场景统计。"""

    total_scenarios: int = Field(0, description="识别出的不同应用场景数量")
    total_mentions: int = Field(0, description="所有应用场景的累计信息源提及次数")
    scenario_ranking: ScenarioRanking = Field(default_factory=ScenarioRanking)
    scenario_trends: ScenarioTrends = Field(default_factory=ScenarioTrends)


class TrendResult(BaseModel):
    """技术趋势 / 新技术调研矩阵的抽取结果。"""

    overview: TrendOverview = Field(default_factory=TrendOverview)
    category_distribution: CategoryDistribution = Field(default_factory=CategoryDistribution)
    technology_frequency: TechnologyFrequency = Field(default_factory=TechnologyFrequency)
    framework_ecosystem: FrameworkEcosystem = Field(default_factory=FrameworkEcosystem)
    technology_trends: TechnologyTrends = Field(default_factory=TechnologyTrends)
    technology_applications: TechnologyApplications = Field(default_factory=TechnologyApplications)
    coverage: Coverage = "none"
    sample_size: int = 0
    notes: str = ""


class SynthesisResult(BaseModel):
    """跨源合成：招聘、趋势、实战三组结果之间的交叉结论。"""

    items: list[Finding] = Field(default_factory=list)
    contradictions: list[EvidencedText] = Field(default_factory=list, description="来源之间互相矛盾的点；每条都要引用冲突双方")
    coverage: Coverage = "none"
    sample_size: int = 0
    notes: str = ""


class ResumeEvidence(BaseModel):
    """简历里的一条事实证据：坐标 + 原文。

    coordinate 必须与带坐标简历行首的 [s:章节 r:窗口 c:内容 i:子项] 逐位一致；
    section / line / location / verified 由代码校验后回填，模型不需要输出。
    """

    coordinate: str = Field(
        "",
        description="简历坐标，格式 [s:0 r:1 c:0 i:0]；必须与标记简历行首逐位一致",
    )
    quote: str = Field("", description="该坐标对应的原文，必须逐字复制")
    section: str = Field("", description="章节标题；代码校验后填充")
    line: int = Field(0, description="坐标在标记简历中的行号（1 起）；代码校验后填充")
    location: str = Field("", description="章节与条目位置，如「工作经历·第 2 条」；代码校验后填充")
    verified: bool = Field(False, description="坐标是否能在简历里定位；代码校验后填充")


class CareerStage(BaseModel):
    """职业路径中的一个阶段。"""

    stage: str = Field(
        "",
        description="该阶段的时间范围，如 2020.09-2023.06；只写时间，不得追加教育期/实习期等阶段说明",
    )
    role: str = Field("", description="该阶段的岗位角色")
    focus: str = Field("", description="该阶段的工作重点")


class CareerCompetitiveness(BaseModel):
    """职业竞争力画像，展示在画像汇总卡上。"""

    candidate_type: str = Field("", description="职业定位")
    seniority: str = Field("", description="职业级别")
    career_tags: list[str] = Field(default_factory=list, description="核心职业标签")
    career_summary: str = Field("", description="职业背景概括")
    career_path: list[CareerStage] = Field(default_factory=list, description="职业发展路径")


class ResumeSkill(BaseModel):
    """能力图谱中的一项具体技能。"""

    name: str
    level: str = Field("", description="掌握程度：精通 / 熟练 / 了解")
    evidence: list[ResumeEvidence] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class TechnicalCapabilities(BaseModel):
    """技能与能力图谱。"""

    skills: list[ResumeSkill] = Field(default_factory=list)
    technical_summary: str = Field("", description="能力总结")


class QuantifiedResult(BaseModel):
    """项目中的一条量化成果。"""

    metric: str = Field(..., description="指标名称")
    value: str = Field("", description="指标结果")
    source: ResumeEvidence | None = Field(None, description="指标来源；有原文时必须给坐标")


class ProjectItem(BaseModel):
    """一个项目及其证明的能力。"""

    project_name: str
    project_role: str = Field("", description="用户在项目中的角色")
    technical_complexity: Literal["high", "medium", "low"] = "medium"
    business_value: str = Field("", description="项目带来的业务影响，不能只是功能复述")
    personal_contribution: list[str] = Field(
        default_factory=list, description="候选人自己完成的动作与产出"
    )
    quantified_results: list[QuantifiedResult] = Field(default_factory=list)
    proven_capabilities: list[str] = Field(
        default_factory=list, description="项目证明的能力（项目优势），不写技术名词清单"
    )


class ProjectValue(BaseModel):
    """项目价值。"""

    projects: list[ProjectItem] = Field(default_factory=list)
    project_summary: str = Field("", description="项目经验整体总结")


class Advantage(BaseModel):
    """一项竞争优势。"""

    title: str
    description: str = Field("", description="优势具体表现")
    evidence: list[ResumeEvidence] = Field(default_factory=list)
    strength: Literal["high", "medium", "low"] = "medium"


class DifferentiatedAdvantages(BaseModel):
    """竞争优势。"""

    advantages: list[Advantage] = Field(default_factory=list)
    overall_summary: str = Field("", description="竞争优势总结")


class ResumeGap(BaseModel):
    """简历中未体现或体现不足的能力。"""

    name: str
    description: str = Field("", description="缺口说明")
    gap_type: Literal["skill", "experience", "depth", "evidence"] = "skill"
    severity: Literal["high", "medium", "low"] = "medium"


class ResumeWeakness(BaseModel):
    """简历表达本身的问题。"""

    type: str = Field(
        "",
        description=(
            "result_expression / project_description / responsibility / "
            "technical_depth / structure"
        ),
    )
    description: str = Field("", description="问题说明")


class PotentialAndGaps(BaseModel):
    """能力缺口与简历缺口；前端在「缺口画像」页签内分成两个子视图。"""

    gaps: list[ResumeGap] = Field(default_factory=list)
    resume_weaknesses: list[ResumeWeakness] = Field(default_factory=list)


class AnalysisMetadata(BaseModel):
    """画像分析元数据。"""

    resume_version: str = Field("", description="本次分析对应的简历版本")
    analysis_status: Literal["pending", "processing", "completed", "failed"] = "completed"
    evidence_policy: str = Field("", description="证据约束规则")
    unverified_items: list[str] = Field(default_factory=list, description="尚未得到简历证实的信息")


class ResumeProfile(BaseModel):
    """Agent 2 简历画像的结构化输出。

    career_competitiveness 进入画像汇总卡；其余四块作为明细标题展示。
    """

    career_competitiveness: CareerCompetitiveness = Field(default_factory=CareerCompetitiveness)
    technical_capabilities: TechnicalCapabilities = Field(default_factory=TechnicalCapabilities)
    project_value: ProjectValue = Field(default_factory=ProjectValue)
    differentiated_advantages: DifferentiatedAdvantages = Field(
        default_factory=DifferentiatedAdvantages
    )
    potential_and_gaps: PotentialAndGaps = Field(default_factory=PotentialAndGaps)
    analysis_metadata: AnalysisMetadata = Field(default_factory=AnalysisMetadata)


class RoleOption(BaseModel):
    """简历反推出来的一个目标岗位选项。"""

    title: str = Field(..., description="岗位名称，包含方向与级别，如「高级前端工程师」")
    reason: str = Field("", description="一句话说明简历里哪些经历 / 技能匹配")


class RoleInference(BaseModel):
    """简历反推结果：4 个目标岗位 + 直接填入 MarketRequest 的城市 / 年限。"""

    roles: list[RoleOption] = Field(..., min_length=4, max_length=4, description="4 个互不重复的目标岗位")
    city: str = Field("", description="求职城市，如「上海」；简历里没有明确城市时留空")
    experience: str = Field("", description="累计工作年限，如「3 年」「5-7 年」「应届」；无法判断时留空")


class StrategyPositioning(BaseModel):
    """一、职业竞争力定位。"""

    career_positioning: str = Field("", description="候选人的职业定位")
    market_level: str = Field("", description="在目标市场中的竞争力水平")
    job_match: str = Field("", description="与目标岗位的整体匹配程度")
    competitive_advantages: list[str] = Field(default_factory=list, description="核心竞争优势")
    competitive_disadvantages: list[str] = Field(default_factory=list, description="相比目标岗位的主要劣势")


class StrategyGap(BaseModel):
    """二、一条「目标岗位要求 - 简历现状」的能力差距。"""

    requirement: str = Field("", description="目标岗位要求的能力")
    current_level: str = Field("", description="候选人当前具备的能力")
    gap_analysis: str = Field("", description="具体能力差距")
    priority: Literal["high", "medium", "low"] = "medium"
    improvement_direction: str = Field("", description="能力提升方向")
    evidence_ids: list[str] = Field(default_factory=list, description="相关调研证据编号")
    resume_locations: list[str] = Field(default_factory=list, description="简历中相关经历的位置")


class StrategyPriority(BaseModel):
    """三、一条改进优先级。"""

    rank: int = Field(0, description="优先级排序，从 1 开始")
    task: str = Field("", description="需要优先完成的事项")
    reason: str = Field("", description="优先处理的原因")
    expected_outcome: str = Field("", description="预期达到的效果")
    related_gaps: list[str] = Field(default_factory=list, description="关联的能力差距")


class StrategyWritingTip(BaseModel):
    """四、一条简历优化建议。"""

    resume_location: str = Field("", description="简历需要优化的位置")
    problem: str = Field("", description="当前简历存在的问题")
    optimization: str = Field("", description="具体优化方案")
    reference_requirement: str = Field("", description="对应的市场岗位要求")
    suggested_keywords: list[str] = Field(default_factory=list, description="建议补充的关键词")
    evidence_ids: list[str] = Field(default_factory=list, description="相关调研证据编号")


class StrategyRisk(BaseModel):
    """五、一条求职风险。"""

    risk_type: str = Field("", description="风险类型")
    risk: str = Field("", description="具体风险")
    impact: str = Field("", description="对求职的潜在影响")
    response: str = Field("", description="应对策略")
    evidence_ids: list[str] = Field(default_factory=list, description="相关证据编号")


class StrategyResult(BaseModel):
    """Agent 3 策略总结的结构化输出。"""

    positioning: StrategyPositioning = Field(default_factory=StrategyPositioning)
    gaps: list[StrategyGap] = Field(default_factory=list)
    priorities: list[StrategyPriority] = Field(default_factory=list)
    writing_tips: list[StrategyWritingTip] = Field(default_factory=list)
    risks: list[StrategyRisk] = Field(default_factory=list)
    coverage: Coverage = "full"
    notes: str = ""


class ReportSection(BaseModel):
    """报告章节：固定首尾 + 本次选择的动态方面章节。"""

    id: str = Field(..., description="overview / skills / 用户所选动态方面的 id / profile / conclusion")
    title: str
    status: Literal["ready", "uncovered", "failed"] = "ready"
    prose: str = ""
    sources: list[dict] = Field(default_factory=list)
