# SmartCV SDD（Spec-Driven Design）

> 本文件是 SmartCV 的设计总纲：从需求到实现的可追溯说明。改动涉及接口、数据结构、
> Agent 流水线或隐私边界时，先改本文件再改代码。文中代码路径均相对仓库根目录。
> 配套文件：[AGENT.md](AGENT.md)（AI 协作与注释规范）、
> [PIPELINE.md](smartcv-api/agents/md2json/PIPELINE.md)（解析流水线细节）、

## 1. 目标与非目标

### 目标

1. 把一份 PDF / Word 简历变成可结构化编辑的 JSON，并保证排版不崩。
2. 让用户用「对话」而不是「改文档」来优化简历，且 AI **不得编造事实**。
3. 编辑、预览、导出三处的排版必须一致（页数一致、分页位置一致）。
4. 隐私优先：简历不落服务端库，API Key 只在浏览器。
5. 基于公开检索数据产出「市场洞察」报告：先采集可追溯的网页，再按维度并行抽取，
   所有结论必须带证据编号，且能回到原网页。
6. 基于用户简历提供「AI 模拟面试」：问题包提前生成且可追溯，出题阶段只产问题、
   不产答案；对话面试按预设追问链推进，进入清单后才生成参考答案。答案能落到
   画像事实上就按事实写，依据不足时保留缺口并给出带显式假设的示范答案。

### 非目标

- 不做账号体系、云存档、多端同步（会破坏 `localStorage` 单机模型）。
- 不做自由画布（简历是线性文档，用「章节 → 布局窗口 → 内容」三层替代）。
- 不让模型负责排版：排版由确定性代码完成，保证同一输入同一输出。
- 不做富文本（内容走 Markdown 子集，`html: false` 防 XSS）。
- 市场洞察不做自动投递、不登录招聘站、不抓取候选人个人信息、不绕过反爬；
  只采集公开页面 + 用户主动补充的网址。
- 模拟面试不做通用题库 / 独立刷题模块：问题必须来自用户简历与所选项目；不做完整
  面试报告（只保留最近 5 场对话 / 清单记录与结束摘要，报告入口仅占位），不做真人
  语音面试与视频录制。

## 2. 系统总览

```
┌─────────────────── 浏览器（唯一数据持有方）───────────────────┐
│ Vue 3 + Pinia + naive-ui                                      │
│   stores/resume.ts        ← Section[] 唯一真相（localStorage）│
│   stores/documents.ts     ← IndexedDB 文件句柄 + 本地索引      │
│   stores/marketSources.ts ← 补充网址标签（备份库 JSON + 缓存）  │
│   stores/interview.ts     ← 面试画像 / 问题包 / 最近 5 场记录   │
│   pages/ Home Editor Review ReferenceExamples Provider        │
│          Market MarketInsights Interview                      │
└──────────────┬────────────────────────────────────────────────┘
               │ /api/*（dev 走 vite proxy，生产走 nginx）
┌──────────────▼────────────────────────────────────────────────┐
│ FastAPI                                                        │
│   main.py       lifespan / 会话中间件 / 统一错误包装 / 路由注册 │
│   routers/      business | agent | market | interview          │
│   services/     pdf2json | html2pdf | stats | reference_examples│
│   agents/       md2json | resume/{optimize,grammar,marker,     │
│                 interview} | single                             │
└──────────────┬────────────────────────────────────────────────┘
               │
   MinerU 云解析 │ 用户自配 LLM（OpenAI 兼容）│ SearXNG（自建搜索）
                  │ 用户补充网址（公开页面）
```

关键约束：**服务端无状态**。除「优秀示例库」「导出计数」「LangGraph 检查点（按 1h
空闲清理）」外，后端不保存任何用户数据；市场洞察任务的事件与结果只存在进程内存
（15 分钟 TTL），浏览器端另存一份结果快照用于刷新恢复。模拟面试的画像、问题包、
答题记录与最近 5 场对话 / 清单记录都只落浏览器 IndexedDB；服务端检查点仅保存进行中
的面试状态。

## 3. 领域模型

### 3.1 简历三层树

```
Resume = Section[]                      整份简历（全应用唯一数据源）
  Section                               章节（页面级）
    id, kind:"section", title, icon?, style: SectionStyle, rows: LayoutWindow[],
    pageBreakBefore?
    LayoutWindow                        布局窗口（叶子 = 放内容；容器 = 放子窗口）
      id, layout: "horizontal"|"vertical", contents: Content[], rows?: LayoutWindow[], tight?
      Content                           内容单元
        id, kind:"content", type: ContentType, content: ContentData,
        style: ContentStyle, tight?
```

- `ContentType`：`iconText | twoColumn | timeRange | tag | listText | image | spacer`。
- **类型描述「长什么样」，预设描述「叫什么」**：预设 = 类型 + 默认内容，渲染只看 `type`，
  代码里不出现「联系电话」这类写死判断。
- 样式继承：内容的显式值 > 章节的值 > `utils/constants.ts` 默认值
  （实现：`smartcv-web/src/utils/style.ts`）。`titleSize` 只属于章节，不继承。
- 窗口可嵌套，横向容器的子窗口按 `layout.ts::spanForIndex` 均分列，**不支持自由列宽**。

### 3.2 坐标模型（AI 改文字的唯一锚点）

`smartcv-api/agents/utils/resume.py::resume_to_marked_text` 把简历拍平成：

```
# 基本信息
[s:0 r:0 c:0 i:0] 王先生
```

- `s` 章节 / `r` 叶子窗口 / `c` 可改内容 / `i` 文字单元。
- 文字单元：`iconText` → 1；`twoColumn` → 每列 1；`timeRange` → 起止合并为 1；
  `listText` → 每项 1；`tag` → 每标签 1；`image`/`spacer` → 0（不占编号）。
- 写回用 `write_text_unit` + `norm_text` 核对原文片段，防止模型改错位置。
- 章节标题用 `resume_to_marked_text(title_with_coord=True)` 输出为 `[标题 s:N]`，
  只给全文纠错的 `title_fixes` 使用。

### 3.3 分页模型

`smartcv-web/src/utils/pagination.ts` 把简历拍平成「可裁切单元」：

```
章节 A → [A:title, A:row0, A:row1, ...]   章节 B → [B:title, B:row0, ...]
```

- 逐行分页而非逐章节：长章节可跨页且能填满上一页剩余空隙，页数不虚高。
- `Section.pageBreakBefore` 记在章节标题单元上；`computePages` 遇到 `forced` 立即换页。
- `computePages(units, contentHeight)` 产出 `PagePlan { pages, pageStartOffsets, totalHeight }`。
- **不变量**：预览与导出使用同一份 `plan + units`；导出 HTML 的 `@page size` 取自
  `pageWidth/pageHeight`，`prefer_css_page_size` 让物理页 = 预览页。
- 纸面尺寸：宽度可调（620~1000），高度 = 宽 × `PAGE_RATIO`（1123/794 ≈ 1.414，
  A4 纵向比例）。

### 3.4 市场洞察领域模型

```
MarketRequest（前端请求，camelCase）
  targetRole / city / experience / timeRange（3m/6m/12m/3y，或自定义 <n>m）
  pagesPerDim   { jobs, trend, other } 三类维度各自的页数（预设 12/24/36 + 自定义 1~60）
  urlsPerDim    每个调研方向最多使用的补充网址条数（同一套预设）
  fetchMode     抓取方式：get（默认）/ crawler；由 tools/fetch 注册表解释
  sources       勾选的结构化招聘来源（当前只注册 BOSS 直聘）
  sourceUrls    [{ url, direction: jobs|trend|other, note }]
  resume / provider
        ↓ normalize_request
Brief（后端统一简报，snake_case）
  target_role / city / experience / time_window / date_range
  source_urls / aspects[] / aspect_labels{} / has_resume / mode(A|B)
        ↓
维度 = jobs + trend + aspects[]       每个维度一个并行抽取 agent
```

- **维度不预置**：固定维度只有 `jobs`（招聘信息）与 `trend`（技术栈）；
  其余维度由用户在规划反问里选 / 自定义，id 由用户文字生成，不做关键词归类。
- **页面与证据**：每个维度对应一个 `SourcePage`
  （`url,title,site,text,kind=维度 id,evidence_id,published,excerpt,user_tag`）。
  证据前缀按分组顺序分配：`jobs→J`、`trend→T`、动态维度依次 `E1/E2…`
  （`utils/dims.py::evidence_prefixes`）。前端靠前缀把结论还原成可点击来源。
- **每维独立额度（不做比例分配）**：
  - `pagesPerDim` 按维度类别配置，键固定三组：`jobs` / `trend` / `other`。动态维度的 id
    不固定，由 `schemas/market.py::pages_key` 统一折算到 `other`；后端在
    `tools/collect.py::_dim_pages` 收窄到 1~60 并取当前维度的页数；
  - `urlsPerDim` 是每个方向各自可用的补充网址上限，不与其他方向共享；
  - 维度 i 的页面 = 搜索结果（≤ 该维度页数）+ 内置源岗位（jobs 且启用内置源，
    ≤ `jobs` 页数）+ 补充网址（≤ `urlsPerDim`）；
  - 兼容旧请求：`pagesPerDim` 收到单个数字时按三类维度同值展开，不再拒收。
- **内置来源不降级**：`resolve_sources(Brief.sources, dim)` 命中可用来源时，
  jobs 只采内置源 + 补充网址；来源返回 0 条就是 0 页，`collect.done` 带 `reason` 说明原因，
  **不回退 SearXNG**。降级会掩盖来源故障，因此彻底移除。未启用来源时 jobs 与其他维度一样走搜索。
- **多内置来源共享额度**：勾选多个来源时，`pagesPerDim.jobs` 是 jobs 维度的总额度而不是
  每个来源各一份。各来源按全额并发采集（以便某个来源返回少时把额度让出来），再按来源
  轮流取（A1、B1、A2、B2…）凑满额度；某来源只返回 3 条时其余 9 条由别的来源补足。
- **页数设置**：设置页把三类维度分别渲染成一行（招聘矩阵 / 技术趋势 / 其他方向），
  各自 12/24/36 预设或 1~60 自定义，读写 `pagesPerDim` 的对应键；不再有单独的
  「招聘页数」覆盖项。
- **补充网址一次判定**：`market_agent._assign_user_urls` 用一次结构化调用同时决定归属与取舍
  （`{url, dim, keep}`）。显式标 `jobs`/`trend` 的网址只能判 `keep`，不许模型改派维度；
  `other` 才允许分配；每个维度最多取 `urlsPerDim` 条，`keep=false` 直接丢弃、不补齐。
  模型不可用 / 超时 / 结果不合法时回退「按标签归组、原顺序取前 N 条」。
- **抓取适配器**：`tools/fetch/` 用 `PageFetcher` 抽象「候选 URL → SourcePage」，
  固定输入 `FetchRequest(url,title,snippet,published,query,max_chars)`、
  固定输出 `FetchResult(page|None, reason)`，`fetch_many` 与入参等长同序且不抛异常。
  `get`（GET 直取，默认）与 `crawler`（Scrapling 指纹抓取，按 article/main 抽正文
  转 Markdown，不执行 JavaScript）在注册表里注册；爬虫依赖缺失时不注册，自动回退 GET。
- **模型阅读预算**：抓取页数 ≠ 送模型页数。`format_pages` 按 `MAX_GROUP_CHARS`（默认 48k，
  可用环境变量覆盖）等量压缩：每页 `预算/页数` 字符（1000~3500），超长正文保留头 70% / 尾 30%；
  页数多到连下限都摊不下时按站点轮流挑选，保证不被单一站点垄断。
  未送入模型的页面仍在 `sources.index` 与采集面板中可见。
- **覆盖度**：`full`（全部页面拿到正文）/ `partial`（存在仅摘要页面）/ `none`（无页面）；
  页面少于 3 条时标记 `thin`，只影响报告降级，不触发补采。

### 3.5 AI 模拟面试领域模型

```
出题场景 scene：project（项目面试）/ comprehensive（综合面试）/ scenario（排查面试）
追问强度 followDepth：normal / deep（仅项目面试）
        ↓
面试方式 useMode：dialog（对话面试）/ checklist（清单自测），题包生成后选择
        ├─ dialog：第 3 步题包直接用于建场
        └─ checklist：复用同一套题卡，直接展开自测
        ↓
ResumeProfile + Anchor[]   用户确认后的简历画像（浏览器 IndexedDB）
        ↓
QuestionCard[]   每种方式各生成一份，卡片结构相同
        ↓
InterviewState             仅对话面试：LangGraph 状态 + sqlite 检查点
```

实体定义在 `smartcv-api/agents/resume/interview/schemas/`（跨层唯一出处）。API 边界
用 camelCase，图状态与提示词输入用 snake_case；Pydantic 统一 `alias_generator=to_camel`
+ `populate_by_name=True`，出参 `model_dump(by_alias=True)`。

- `TechStackItem {name, level: 精通|熟练|掌握, refs[], quote}`：模型只输出 `refs`
  坐标；`quote` 由后端按坐标解析原文，供出题与校验，不进入结构化输出 schema。
- `ProjectItem {id, name, intro, role, techStack[], highlights[]}`：`highlights` 对应
  项目经历里的每个小点，一条一个字符串。
- `Anchor {id, kind, refs[], quote, projectId, followDirections[]}`：
  `kind ∈ tech|result|architecture|metric|contribution`；`refs` 是 `[s, r, c, i]`
  坐标列表，服务端用 `locate_unit` 解析原文、再按 `norm_text` 逐字核对，
  坐标无效或对不上的锚点直接丢弃。
- `ResumeProfile {direction, intro, introRefs[], techStacks[], projects[]}`：
  **不含工作年限字段**。「删除工作年限相关字段与逻辑」只约束面试模块，市场洞察的
  `experience` 与其反问逻辑保持不变，两者不共用这个模型。
- `FollowUp {id, level: L1|L2|L3, question, intent, referenceAnswer}`：L1 澄清实现细节，
  L2 决策权衡，L3 归因 / 反事实（个人贡献、结果归因、替代方案、条件变化）；
  `referenceAnswer` 进入清单后单独生成。
- `ReferenceAnswer {thinking, answer, keyPoints[], missingInfo[], assumptions[]}`：
  不再区分状态与来源，统一作为引导用户回答的示范内容。`answer` 为空表示尚未生成；
  能落到画像事实的部分按事实写，依据不足时用 `missingInfo` 说明简历缺什么、
  用 `assumptions` 逐条标注补了哪些假设，正文仍然必须完整。
- `QuestionCard {id, projectId, anchorId, dimension, priority, mainQuestion, followUps[],
  evidenceQuote, intent, referenceAnswer, leakSignals[], coverage[],
  dynamicQuestions[]}`：`dimension` 取项目背景 / 业务需求 / 架构选型 /
  核心实现 / 技术难点 / 问题解决 / 项目成果 / 个人贡献 / 技术栈掌握 / 求职动机 /
  职业规划 / 薪资 / 稳定性 / 项目真实性；`leakSignals` 至少 2 条；`dynamicQuestions[]`
  只由面试过程追加，记录问题、L 级别、关联锚点和触发原因，用于追溯；
  主问题与追问的 `referenceAnswer` 都不参与出题结构化输出，出题完成后由后端清空。
- 题包没有独立实体：`/pack` 直接返回 `{cards[], warnings[]}`，前端把题卡与
  `scene / followDepth / focus / projectIds` 一起存进同一条 `PackRecord`。
  `warnings` 只放非阻断问题（如某个分组没有返回可用题目），结构不合规不允许返回题卡。
  场景有项目 / 综合 / 排查三种；对话与清单共用同一份题卡列表。
  题量由模型按证据量决定，前端不再按 10 / 15 / 20 重新出题。
  `focus` 只用于项目面试：`balanced` 均衡（默认）/ `business` 业务场景 /
  `tech` 实现细节 / `architecture` 架构设计；综合面试与排查面试固定 `balanced`。
  方向只改变提问粒度与追问口径，不改变检查点结构。
- `AnswerRecord {cardId, question, answer, source, level, leaks[], offTopic, feedback,
  sampleAnswer, skipped, createdAt}`：`source ∈ main|followup|reanswer|skip`；
  `sampleAnswer` 由用户点击按本轮改进建议生成，未生成或跳过时为空。
- `TeachingEvent {cardId, question, turns[{role, content}], outcome,
  startedAt, endedAt}`：`outcome ∈ active|returned|skipped`。
- `InterviewState`（LangGraph TypedDict）：`threadId, ownerSession, scene, followDepth,
  profile, anchors, pack, phase, currentCardId, currentQuestion, currentLevel,
  currentIsDynamic, followupUsed{}, dynamicCount, consecutiveOffTopic, records[],
  teachingEvents[], skippedCards[], progressDigest[], finishedReason`；
  `phase ∈ interviewing|teaching|finished`。

面试模块的关键规则：

1. **问题包是唯一题源**：对话面试只从当前卡的追问链里选下一问，或按规则生成动态
   追问，不脱离题包自由出题；清单自测也直接渲染这份题包。
2. **追问级别配比**：代码校验 `L3 追问数 / 追问总数 ≥ 30%`；不满足先补生成一次，
   仍不满足不返回问题包。
3. **证据可追溯**：项目面试的问题必须带存在的 `anchorId`；`evidenceQuote` 要能在
   确认后的简历文本中找到（综合面试的动机类问题与排查面试的假设场景允许为空，
   清单题沿用同一规则）。
4. **不虚构事实**：问题生成 Agent 只接收用户确认后的 `ResumeProfile + Anchor[]`，
   不接收原始简历（用户删掉的经历不能被模型捡回来），并且只出题、不生成参考答案。
   进入清单后，答案 Agent 会先判断画像依据：数字、年月与职责能对上就按事实写；
   对不上时保留 `missingInfo`，同时给出带 `assumptions` 的示范答案，不能把假设
   伪装成简历事实。L1/L2/L3 追问同样按此规则生成：只回答已存在的追问 id，
   不生成新问题，也不改写主问题参考答案。
5. **露馅信号**：每张卡至少 2 条，且要可操作（明确指出回答里可能出现的知识漏洞、
   指标依据不足、个人贡献模糊）；不足时补生成，仍不足返回 502。
6. **动态追问约束**：单锚点最多追问 3 轮；单场动态问题不超过 5 条；只有出现新锚点、
   矛盾点、量化指标异常、回答过浅时才允许动态生成；达到轮次上限、当前卡考察点已
   覆盖或连续两次答非所问时，退出当前锚点进入下一题。
7. **先场景后方式**：`/pack` 的场景只允许 `scene=project|comprehensive|scenario`；项目面试
   必须选择一个项目并带 `followDepth`，综合面试与排查面试的 `followDepth` 必须为空、
   `focus` 必须为 `balanced`、`projectIds` 必须为空。项目面试可选 `focus`：业务场景只问
   真实需求、链路与结果；实现细节只问单模块 / 接口 / 数据的落地、并发与异常边界；
   架构设计只问拆分、容量、扩展、容灾与成本。方向会同时传给题包生成和面试中的动态追问。
   第 3 步出一次题包，第 4 步选对话或清单都复用它，不再重新出题。三种场景都能用清单，
   非法组合返回 400。

## 4. 接口契约

统一响应：`{ code, message, data }`，`code = 0` 成功；非 2xx 保留 HTTP 语义。
前端解包：`src/api/error.ts::unwrap`。所有请求带 `X-Agent-Session-Id`（UUID7，
浏览器级，非标签页级；见 `src/api/session.ts` 与 `main.py` 中间件）；路由用
`routers/deps.py::get_agent_session` 从 `request.state` 取会话 id。

### 4.1 business（`routers/business.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/resume/parse` | multipart：`file` + `parser`(mineru) + `mineruToken` + provider 四字段。同步返回 `Section[]`；解析中的进度另经 `/status` 轮询 |
| GET | `/api/resume/parse/status` | 只回 `{ state, error, steps }`，**不含简历内容**；store 不存在返回 `unknown` |
| POST | `/api/resume/pdf` | 入参 `{ html }`，Playwright 打 PDF 直接返回文件流 |
| GET/POST | `/api/stats`, `/api/stats/inc` | 导出计数（PDF/JSON），存文件、原子替换 |
| GET | `/api/examples`, `/api/examples/{name}` | 本地 `example/` 示例，读 `index.json`；文件名做路径穿越校验 |
| GET/POST | `/api/reference-examples`；GET `/{id}` | 优秀示例库：列表只回元数据；上传后不可改不可删 |

### 4.2 agent（`routers/agent.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/polish` | `{ items, provider, description?, context?, mode }`，`mode ∈ strict\|free\|enhance`；条数与顺序与入参一致 |
| POST | `/api/analyze` | `{ resume, provider }` → `{ items: [职业名称, 可借鉴写法] }`；只读、不写会话 |
| POST | `/api/grammar` | `{ resume, provider }` → `{ resume, changes, skipped, stats }`（含章节标题修正）；一次结构化调用 + 代码校验 |
| GET | `/api/agent/md` | 提示词（`system_prompt*.md`、`*_prompt.md`）与技能（`skill/**/*.md`）只读预览 |
| POST | `/api/chat` | SSE 流式优化对话，见 4.4 |
| POST | `/api/chat/answer` | 回答诊断 agent 的反问；404 任务过期 / 409 已答或 id 不符 |

### 4.3 market（`routers/market.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/market/stream` | 启动一轮调研并返回 SSE；响应头 `X-Market-Task-Id` 与首条 `task` 事件都带 taskId；岗位与简历都缺时返回 400 |
| POST | `/api/market/answer` | `{ taskId, questionId, answers[] }` 回答 planner 反问；已失效 / 已答返回 409 |
| POST | `/api/market/cancel` | `{ taskId }` 取消本轮调研；任务已结束也按成功返回（幂等） |
| POST | `/api/market/roles` | `{ resume, provider }` → 4 个目标岗位 + 城市 / 年限；独立能力，不参与调研流水线 |

请求体为 `MarketRequest`（见 3.4）：`targetRole` 与 `resume` 至少一个；
`pagesPerDim` 为 `{jobs,trend,other}` 对象、各项与 `urlsPerDim` 均 1~60（旧版单个数字仍兼容），
`fetchMode ∈ get|crawler`；
`timeRange` 为 `3m|6m|12m|3y` 或自定义 `<n>m`（1~120 个月），由后端换算成绝对年月。
`/roles` 的 `resume` 不写回、不落库，只用于本次反推。

任务通道（`utils/task.py`）：按 taskId 注册，TTL 900s、最多 100 个任务；
事件缓存 512 条、队列 64；支持 `Last-Event-ID` 断线重放；15s 心跳 `: keepalive`。
「重新调研」时前端先 `/cancel` 掐断旧 producer，避免旧任务继续占用模型与采集资源。

#### SSE 事件

| type | 载荷 | 前端用途 |
|---|---|---|
| `task` | `taskId, status` | 记录任务号，供反问 / 取消 |
| `graph` | `nodes[], edges[], dims, hasResume` | 流程图；plan 前后各发一次，规划后补上动态维度 |
| `status` | `stage, text` | 阶段提示 |
| `plan.step` | `index, key, text` | 规划步骤逐条落下 |
| `plan.result` | `queries[], dims[], budget, brief, notes` | 解锁后续节点，按 dims 重建节点 / 页签 / 报告章节 |
| `ask_question` / `ask_question_closed` | `questionId, title, questions[], timeoutSeconds` | 反问卡片（240s 超时后按现有信息继续） |
| `tool_call` / `tool_result` | `tool, args/result` | 反问工具过程 |
| `agent_start` / `agent_end` | `agent, label` | 时间线节点开合 |
| `node.enter` / `node.exit` | `node, label / state, text` | 流程节点状态；动态维度 id 直接作为 node |
| `collect.chunk` | `group, site, got, total, overallGot, overallTotal` | 按站点逐页上报采集进度；`overallTotal` 为各维 `planned` 之和 |
| `collect.skip` | `group, site, total, reason` | 某页既抓不到正文也没有可用摘要；只更新行内「未采」说明，不产生箭头 |
| `collect.done` | `total, planned, published, thin, coverage, timeWindow, dateRange, reason?` | 每维度采集结算；内置源启用却 0 页时带 `reason` |
| `sources.index` | `items[{id,title,url,site,published,kind,excerpt,userTag}]` | 证据编号 → 可点击来源；`userTag` 标记补充网址 |
| `extract.chunk` / `extract.done` | `dim, items[] / count, coverage` | 维度面板逐条填充；`dim=synthesis` 为跨源结论 |
| `profile.chunk` / `profile.done` | `items[] / count, coverage, evidence` | 简历画像 |
| `strategy.chunk` / `strategy.done` | `items[] / count` | 策略总结 |
| `report.section.started` | `section, title, status` | 开始写某一章 |
| `delta` | `stage, section?, text, kind` | 报告逐 token 打字机（thinking / answer） |
| `report.section` | `id, title, status, prose, sources[]` | 一章完成 |
| `report.done` | `sections[], count` | 报告收尾 |
| `error` | `node, message, fatal` | `fatal=false` 只提示，不中断流水线 |
| `done` | `status` | 结束（done / failed） |

### 4.4 `/api/chat` SSE 事件

请求：`{ resume, message, jd?, provider, referenceIds?(≤3), rewriteMode?("standard"|"bold") }`

| type | 载荷 | 前端用途 |
|---|---|---|
| `status` | `stage, text` | 阶段提示（convert） |
| `agent_start` / `agent_end` | `agent, label` | 时间线节点开合 |
| `resume_markdown` | `text` | 「位置诊断」折叠区 |
| `reference_examples` | `items[]` | 本次实际生效的示例 |
| `web_search` | `query, results[], error?` | 「Web 搜索」折叠区 |
| `tool_call` / `tool_result` | `tool, args/result` | 工具执行过程 |
| `delta` | `stage, text, kind?` | 逐 token 打字机（thinking / answer） |
| `ask_question` / `ask_question_closed` | `questionId, title, questions[]` | 反问卡片（默认 300s 超时） |
| `diagnosis` | `count, items[], styleNotes[]` | 诊断结论树 |
| `diagnosis_status` | `index, status, reason` | 单条诊断的审查/执行状态 |
| `resume` | `resume, summary, diagnosis` | **不直接覆盖**，进 `pendingDiff` |
| `done` / `error` | — / `message` | 收尾 / 抛错 |

传输约定：`fetch` + `ReadableStream` 手解析 `\n\n` 分块（EventSource 只支持 GET）；
服务端 15s 心跳 `: keepalive`；`Last-Event-ID` 支持断线重放（deque 缓存 256 条）。
任务与事件缓存在内存，按会话隔离，任务 600s 过期。

### 4.5 interview（`routers/interview.py`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/interview/profile` | `{ resume, provider }` → `{ profile, anchors }`；锚点已用代码核对，不可追溯的已丢弃 |
| POST | `/api/interview/pack` | `{ provider, profile, anchors, scene, followDepth, focus?, projectIds[] }` → `{ cards[], warnings[] }`；第 3 步按场景出题，对话与清单共用，不创建检查点 |
| POST | `/api/interview/reference-answer` | `{ provider, profile, anchors, card }` → `{ answer }`；进入清单后按卡生成主问题参考答案，不写检查点 |
| POST | `/api/interview/follow-up-answers` | `{ provider, profile, anchors, card, followUpIds[] }` → `{ answers[] }`；一次补齐卡片缺失的追问答案，key 为 `followUpId`，不生成新问题 |
| POST | `/api/interview/sample-answer` | `{ provider, threadId, cardId?, question? }` → `{ answer }`；按评价卡上这一轮已记录的作答生成示例回答，只读检查点，不推进面试 |
| POST | `/api/interview/thread` | `{ profile, anchors, cards[], scene, followDepth, focus, useMode }` → `{ threadId }`；题卡生成后选对话面试才建场，不调用模型、不重新出题 |
| POST | `/api/interview/stream` | SSE：`{ threadId, action, answer?, message?, provider }`；按 action 推进一轮面试 / 教学 |
| GET | `/api/interview/state?threadId=` | 只读恢复：当前题、追问轮次、phase、作答记录、教学轮次；不返回整份问题包与参考答案 |

请求约定：

- `provider` 每次请求都要带：API Key 只在浏览器，服务端不持久化、不写进检查点。
  因此对话面试每轮的入参是 `threadId + action + 本轮输入 + provider`，比需求里
  「只传 thread_id 和 action」多一个 provider，这是隐私约束下的必要字段。
- `ownerSession` 在创建面试时写入检查点；之后 `stream` / `state` / `sample-answer`
  必须带同一个 `X-Agent-Session-Id`。不匹配与线程不存在都按 404 返回，避免探测他人线程。
- 线程不存在 / 已被 1h 空闲清理 → 404；当前处于教学阶段却提交回答 → 409；
  动作缺必填字段 → 422。非流式校验失败走统一 `error()`；流内失败以 `error` 事件收尾。
- 请求体只允许本轮内容：`answer` 1~4000 字；`teach_message` 1~2000 字。
  不接收问题包、历史记录或参考答案，避免前端状态覆盖服务端检查点。
- 组合校验（`/pack`）：`scene=project` 必须带 `projectIds=[一个]` 与 `followDepth`；
  `scene=comprehensive` 与 `scene=scenario` 的 `followDepth` 必须为空、`focus` 必须为
  `balanced`，且不接收 `projectIds`。项目面试的 `focus` 可省略，默认 `balanced`。
  题量由模型按证据量决定，不接收目标题量。
- `/thread` 只校验题包可答：`useMode` 必须是 `dialog`，题包非空、引用的项目与证据
  锚点都在当前画像里。清单自测不建线程，在浏览器端直接消费同一份题包。
- `/reference-answer` 由用户在清单里主动点击触发：答案围绕该卡的主问题与追问链，
  优先使用画像事实；依据不足时保留 `missingInfo`，同时仍返回完整示范答案，
  假设写进 `assumptions`。不写回检查点，只随清单包保存在浏览器 IndexedDB。
- `/follow-up-answers` 同样由用户主动触发，`followUpIds` 为空时处理该卡全部追问；
  返回项必须命中卡片里已存在的 id，答案与缺口处理规则同 `/reference-answer`，
  合并进对应 `FollowUp.referenceAnswer` 后随题包存浏览器。

`action` 取值：

| action | 适用阶段 | 含义 |
|---|---|---|
| `answer` | interviewing | 提交当前问题的回答，评估并决定追问 / 下一题 |
| `skip` | interviewing / teaching | 跳过整道题：当前卡记为跳过（含剩余追问）；教学阶段则结束教学并跳过 |
| `skip_followup` | interviewing / teaching | 只跳过当前追问，接着问本卡下一条未问追问；没有剩余追问才进入下一张主问题 |
| `teach` | interviewing | 「我不会，AI 教我」，暂停面试并创建教学事件 |
| `teach_message` | teaching | 教学中的多轮追问 |
| `return` | teaching | 返回原问题继续回答 |
| `end` | interviewing / teaching | 结束本场面试并返回摘要 |

SSE 事件：

| type | 载荷 | 前端用途 |
|---|---|---|
| `interview.started` | `threadId, scene, followDepth, totalCards` | 首轮恢复 / 开始面试 |
| `turn.start` | `cardId, index, total` | 显示「第 N / 共 M 题」 |
| `status` | `stage, text` | 评估 / 出题 / 教学准备提示 |
| `delta` | `stage, text` | 教学导师逐 token 输出（`stage=teaching`） |
| `question` | `cardId, text, level, dynamic, mainQuestion, followupsUsed, progress` | 展示当前问题；`level` 为空表示主问题 |
| `evaluation` | `cardId, leaks[], offTopic, feedback` | 单轮反馈卡；每轮回答后展示 |
| `teaching.started` | `cardId, question` | 切到教学模式 |
| `teaching.turn` | `role, text` | 教学对话追加一条（用户或导师） |
| `teaching.closed` | `outcome` | 教学结束（returned / skipped） |
| `state` | `phase, currentCardId, index, total, dynamicCount, followupsUsed, finishedReason` | 同步 store 与服务端一致 |
| `summary` | `records[], dynamicCount, teachingCount, finishedReason` | 结束时写入本地面试记录并展示摘要 |
| `error` | `message, fatal` | 失败提示 |
| `done` | `status` | 本轮流结束 |

推给前端的 SSE 载荷（包括 `state`、`summary` 里的 `records`）一律按 camelCase 别名
序列化，只有检查点内部存 snake_case。前端结束收尾时会按「卡 + 问题 + 回答」把本地
`sampleAnswer` 合回服务端记录，两边字段名不一致就会整段丢失。

示例回答不随 `answer` 自动生成：评价里有改进建议或遗漏点时，评价卡显示
「生成 AI 示例回答」按钮，点击后走 `POST /api/interview/sample-answer`，后端从
检查点还原本轮作答并调用通用 Agent，结果写回浏览器里的本场记录（`sampleAnswer`），
刷新与复盘仍能看到。示例回答只按需生成，不占用每轮 SSE 的等待时间。

没有反问工具，因此不引入市场洞察那样的任务通道与断线重放：每条 SSE 只服务一次
action 请求，断开即取消本轮；刷新 / 重连后由前端用 `GET /api/interview/state`
重新对齐。已提交但未收到 `evaluation` 的回答需要重新提交。

## 5. Agent 流水线

### 5.1 解析（`agents/md2json/`）

```
PDF/DOCX → MinerU → content_list.json（full.md 兜底）→ 清洗(Block[]) → 一次 LLM → CanonicalResume → 代码排版 → Section[]
```

- 只有「语义结构化」调模型；清洗、分章、排版、校验全是纯代码（结果可复现）。
- 模型超时(120s)/报错/输出非法 → 回退「确定性分章 + 规则转换」，仍返回 `Section[]`。
- 隐私：`PDF2ResumeStore` 只存步骤状态，`finally` 里 `delete_store` 立即清除。

### 5.2 优化对话（`agents/resume/optimize/`，LangGraph）

```
convert（代码：JSON → 带坐标文本）
  → diagnose（诊断 agent：可反问、可联网；输出结构化诊断 + 从示例提炼的写作规范）
  → review（审查 agent：逐条 patch_content 判 change/skip，就地替换文字）
  → summarize（主 agent：给用户的简短修改说明）
```

- 图状态（`ChatState`）经 SQLite checkpointer 按 `thread_id = 会话 id` 持久化；每小时清理。
- 事件全部走 `get_stream_writer()` 的 custom 流，`astream(stream_mode=["updates","custom"])`
  单生产者转发 SSE，保证事件顺序与执行一致。
- 反问：工具内 `interrupt()` 暂停 → 前端 `POST /api/chat/answer` → `Command(resume=...)`。
- **约束**：只改文字单元，不改结构/样式/图片；不得新增事实与数字。
- 改写强度：`standard`（保留语气、信息量与事实边界，但句子要重新组织，不照搬原句）/
  `bold`（可整段重写表达，仍不新增事实）。
- 双重判定：诊断先给档位 `must | suggest | keep | insufficient`；审查 agent 只对前两档
  判 `change`，`keep/insufficient` 必须 `skip`；`change` 还要通过 `quote` 原文核对，
  不通过记失败、不写入。

### 5.3 全文纠错（`agents/resume/grammar/`）

单次结构化调用，模型回「坐标 + 原文片段 + 完整改后文字」，章节标题另走 `title_fixes`；
代码核对坐标、原文、是否新增数字/链接/邮箱、改动幅度与日期范围，不通过的进 `skipped`
绝不写入；返回 `stats`（`checkedUnits/fixed/skipped/titleFixed`）。前端复用修改对比弹窗确认。

### 5.4 单次任务（`agents/single/`）

润色 / 提示词增强 / 简历分析。提示词结构 = 「模板 `system_prompt_base.md` + 模式片段
`*_prompt.md`」：模板固定六段（`# 角色 / # 输入格式 / # 可以做 / # 不能做 / # 输出格式 /
# 示例`），末尾 `{other}` 接片段里的额外段落；`strict|free` 共用 `polish_prompt.md`，
`enhance|analyze` 各用一份。加模式 = 加一个 md 片段，不改代码。

### 5.5 技能（`agents/skill/`）

`coordinate`（坐标约定）、`diagnose`（诊断标准）、`review`（改写标准）。诊断与审查
两个 agent 经 `SkillMiddleware` 把技能摘要拼进系统消息，正文用 `load_skill_through_path`
按需加载（路径白名单 + 防穿越）；grammar / md2json / single 不加载技能。

### 5.6 市场洞察（`agents/resume/marker/`，LangGraph）

```
plan（planner：两轮反问 + 每维度检索词）
  └─ collect（代码 + 来源适配器：SearXNG / BOSS 占位 / 用户补充网址）
collect → extract × N（每个维度一个 Send 分支）
  └─ profile（简历画像；仅在有简历时，与 extract 同批并行）
extract → synthesis → strategy → compose
```

- **direction**：请求里的 `direction` 是「用户希望 AI 回答的内容」，不是调研维度。
  planner 据此生成第二轮的调研方面选项与各维度检索词；`Brief.direction` 随 `<brief>`
  进入 collect / extract / synthesis / strategy / compose，兜底检索词、补充网址筛选和所有
  下游提示词都要求围绕它作答。
- **plan**：`planner_agent` 通过 `ask_user_question` 工具发起两轮反问（缺岗位 / 城市 /
  年限先补基础信息；再单独问调研方面），答案经 `/api/market/answer` 回到任务通道；
  模型漏问或把调研方面混进第一轮时由代码补问。调研方面是调研的触发条件：补问后仍
  没有选择就结束本轮，不会用城市 / 年限生成检索计划。确认方面后一次结构化调用为
  每个维度生成 2~6 条检索词，模型失败或缺组走 `fallback_groups`。反问超时 240s，
  超时按跳过处理。
- **collect**：`tools/collect.py` 协调，页面统一编号；每维独立额度（见 3.4）：
  - `DimensionPlan` 为每个维度显式列出：检索词、搜索页数、是否内置源、补充网址；
  - SearXNG 每条 query 的候选数按该维度页数摊算（8~20），全局 URL 去重后批量抓取；
  - 补充网址由 `market_agent._assign_user_urls` 一次判定归属与取舍，采集器只按名额截断；
  - 抓取交给 `tools/fetch` 的 `PageFetcher`（GET 直取 / 爬虫渲染），适配器只决定抓哪些 URL；
  - 抓取前做 SSRF 校验（逐跳重定向都校验、拒绝私网）、2MB 上限、12s 超时，
    GET 并发 6、爬虫并发 3（浏览器实例较重）；
  - 正文过短或抓取失败时退回搜索摘要（`excerpt=True`）；既无正文也无摘要的页面丢弃，
    并发 `collect.skip` 带上原因，前端在站点行显示「未采 N 页」与原因；
  - 带发布时间且早于时间窗口的页面直接丢弃；
  - BOSS 直聘适配器目前是占位实现（返回空）：启用后 jobs 就是 0 页，`collect.done`
    带 `reason`，**不回退 SearXNG**；不启用时 jobs 与其他维度一样走搜索。
- **阅读预算**：`utils/common.py::format_pages` 按 `MAX_GROUP_CHARS` 等量压缩，
  每个维度实际抓到的页面全部进入来源索引，但送入模型的正文按预算摊分（1000~3500 字/页）。
- **extract**：每个维度一个 agent（`jobs_agent` / `trend_agent` / `aspect_agent`），
  只读 `kind=自己` 的页面与可选结构化岗位；输出 `findings` 并引用证据编号，
  代码过滤不存在的 id。
- **synthesis**：只接收各维度的结构化结果，不重读页面；输出跨源一致点与矛盾点，
  前端按证据编号把它们分发到相关维度面板，不单独成章。
- **strategy**：结合简报、市场结果与简历画像，输出定位、差距、优先级、写法提示、风险。
- **compose**：按 `report_sections` 逐章流式生成（岗位概览 / 技能要求 / 动态方面各一章 /
  简历对照 / 结论与建议）；模型失败或正文为空时用同一批事实拼兜底正文。
- 图状态经 SQLite checkpointer 持久化（`thread_id` 按节点区分），与对话流水线共用 1h 清理。
- **分层约束**：`tools/` 不导入 agent / LLM；需要模型判断（`other` 分流、超配额筛选）时
  由 `market_agent` 把回调传进采集器。
- **提示词**：`prompts/{plan,collect,extract,profile,synthesis,strategy,compose}/*.md`，
  各 agent 在模块加载时读取（`collect/` 放 `other` 分流与超配额筛选）；
  改提示词不改代码。

### 5.7 模拟面试（`agents/resume/interview/`，LangGraph）

```
profile  简历分析 Agent：简历文本 → ResumeProfile + Anchor[]（代码核对锚点）
   ↓ 用户在页面上确认 / 增删改
pack     问题生成 Agent：按项目 / 综合主题 / 排查题型分组并行结构化生成 → 合并成 QuestionCard[]
   ↓ 用户确认题包（第 3 步）并选择方式（第 4 步）；清单直接展开同一份题包，
     对话用题包走 thread 建场
thread   用已生成题包写初始检查点：不调模型、不重新出题
dialog   action → 图入口分发 → interviewer（评估 / 追问 / 下一题）
                             → teacher（教学讲解）
                             → finish（收尾摘要）
```

目录约定与 `marker/` 一致：`graph.py` 只做编排与事件出口；`*_agent.py` 各负责一次模型
调用；`policy.py` 放追问轮次、动态配额与校验的纯函数；`schemas.py` 是数据结构
唯一出处；`prompts/<阶段>/*.md` 在模块加载时读取。

**简历分析 Agent**（`resume_agent.py` + `prompts/profile/resume.md`）

- 输入只有 `resume_to_plain_text(resume)`；一次结构化调用输出 `ResumeProfile + Anchor[]`，
  `temperature=0.2`、超时 120s。不判断真假、不评价优劣，只抽取用户写下的内容。
- 代码核对：每个锚点的 `quote` 用 `norm_text` 在简历文本里查原文，查不到就丢弃；
  项目 `id` 由代码补全（模型漏给 / 重名时按顺序生成），保证后续问题可关联。
- 输出不含工作年限；技术栈等级只允许「精通 / 熟练 / 掌握」，其余值按「掌握」处理。
- 用户可在页面上编辑画像与锚点；后续问题生成只认用户确认后的结果。

**问题生成 Agent**（`pack_agent.py` + `prompts/pack/*.md`）

- 按分组调用，组内一次 Structured Output，组间并发（最多 3 个）：
  - `project`：所选项目一个组（项目面试）；
  - `comprehensive`：求职动机 / 职业规划 / 薪资 / 稳定性 / 项目真实性五个主题组；
  - `scenario`：故障排查 / 性能优化 / 方案设计三个题型组，三组共用
    `prompts/pack/scene/scenario.md`，由 `task.theme` 选择题型段。分组只用于并发生成，
    对用户不可见，也不出现在题卡字段里。
  - 方式不改变分组；项目面试由模型按证据量决定张数，综合面试每个主题出 1~2 张卡，
    排查面试每个题型出 1~2 张卡。对话与清单共用这份题包，不再追加清单专用提示词或
    按目标题量分配。
- 排查面试从简历技能出发：`primary_techs()` 按技术栈等级、项目使用次数与求职方向排序，
  取前 3 个作为 `task.primaryTechs` 软提示；提示词要求至少 2/3 的卡围绕主技术。
  题面允许编造假设性的指标与系统背景（考的是排查能力），但技术名必须来自画像，
  `projectId` / `anchorId` 可以为空。
- 每张卡一次产出：主问题、L1/L2/L3 追问链、证据锚点、考察意图、至少 2 条露馅信号、
  覆盖维度与优先级。**出题阶段不生成参考答案**，主问题与追问的 `referenceAnswer`
  都不进入结构化输出；即使模型擅自输出，`prepare_cards` 也会清空。
  模块内不分「规划 Agent」和「生成 Agent」。
- `QuestionCard` 的追问链与露馅信号是必填字段（JSON Schema 的 `required` +
  `minItems`），出题时由结构化输出直接校验，不再做额外的卡片校验；追问数量与
  L3 固定分配（4 条 = 1 L1 + 1 L2 + 2 L3）、露馅信号 2~4 条只写在提示词里。
- 问题生成只接收 `ResumeProfile + Anchor[]` 的 JSON，不接收原始简历；题目本身不得
  虚构项目、指标、职责与成果。

**通用答案 / 编辑 Agent**（`general_answer_agent.py` + `prompts/general/`）

- 调用方传入输出实体类（`ReferenceAnswer` / `FollowUpAnswerSet` / `ContentEditOutput`），
  Agent 按实体选择对应的提示词片段，并把该实体的 `model_json_schema(by_alias=True)`
  注入 `prompts/general/base.md` 的 `{{schema}}`；提示词、结构化输出与返回校验
  始终使用同一个实体，不会出现提示词字段和实际 schema 对不上的情况。
- `base.md` 只放通用骨架（角色 / 输入 / 输出 / 约束）与通用规则，任务差异放在
  `answer.md`、`follow_up_answers.md`、`anchor.md` 的四个同名分区；新增任务 =
  注册一个实体类 + 一个片段文件。
- 进入清单后不自动生成答案；用户点击某张卡「AI生成答案」时才调用
  `/reference-answer`，生成后写回题包与清单快照。已生成答案的卡不再重复生成。
- 先判断依据再写答案：能落到画像事实就按事实写；依据不足时 `missingInfo` 保留
  简历缺什么，`assumptions` 逐条标注补了哪些假设，但 `answer` 仍然必须非空。
- 代码复核答案中的数字：画像里找不到依据的数字会被写进 `missingInfo`，
  并把「示范假设」写进 `assumptions`，不装作有依据。
- 追问答案走 `/follow-up-answers`，规则相同；只回答已存在的追问 id，不生成新问题，
  生成结果合并到对应 `FollowUp.referenceAnswer`。
- 锚点编辑走 `/api/interview/edit`（`scene=anchor`），输出 `ContentEditOutput`；
  返回时只接受原对象已有顶层键，`lockedFields` 里的 id、原文引用等字段始终以原值为准。
- 对话面试与教学都不读取参考答案：面试官只看当前卡、锚点与回答，教学只看画像与
  卡本身，避免「有的题有答案、有的题没答案」影响对话体验。

**面试官 Agent**（`interviewer_agent.py` + `prompts/interview/interviewer.md`）

- 每次 `answer` 一次结构化调用，输出 `InterviewerTurn`：`offTopic`、命中的露馅信号、
  反馈、决策（`follow_up | next_card | end`）、所选预设追问 id、可选动态追问文本与
  触发原因、本题小结。不做数值评分；解析层优先读原始 JSON，并兼容常见的扁平 / 别名
  输出。
- Prompt 只带当前问题卡、对应锚点、当前问题、最近 2 条答题记录与 `progressDigest`
  （每题一行：主题 / 反馈摘要 / 标签），不重复拼入整份问题包和全部历史。
- 追问决策由 `policy.resolve_turn` 兜底，模型只给候选，代码决定是否采纳：
  - 单锚点已追问 3 轮、当前卡考察点已覆盖 → 强制下一题；
  - 单场动态问题已达 5 条 → 只允许预设追问，预设用完就下一题；
  - 动态追问必须带触发原因（新锚点 / 矛盾 / 指标异常 / 回答过浅）并关联锚点，
    否则按预设追问处理；动态问题追加到当前卡的 `dynamicQuestions[]` 并记录来源轮次；
  - 连续 2 次答非所问 → 直接下一题；
  - 预设追问 id 不在当前卡剩余追问里 → 视为无效输出，退回预设或下一题，不允许
    模型自造未关联锚点的问题；
  - 当前卡已覆盖完 / 所有卡已完成 → `end`，由 `finish` 节点出摘要。
- 模式差异只走提示词片段：常规模式正常技术交流；深度追问模式追加
  `prompts/interview/deep.md`，要求对漏洞、矛盾、模糊表述继续追问，并核实方案依据、
  数据口径与个人贡献；综合面试围绕动机、规划、薪资、稳定性与项目真实性展开，没有
  追问强度档；排查面试按「现象 / 约束 → 证据 → 根因或瓶颈 → 验证 → 取舍」追问，
  不转回项目经历，也不问泛泛的概念题。

**教学导师 Agent**（`teacher_agent.py` + `prompts/teaching/teacher.md`）

- `teach` 建教学事件并把 phase 切到 `teaching`；输入是当前卡、所选项目背景、技术栈
  与最近 6 轮教学对话，不读取参考答案，也不直接给标准答案，而是用提问和提示引导
  用户自己组织回答。
- 用 `llm.astream` 逐 token 发 `delta` 事件；`teach_message` 继续同一事件，轮次追加到
  `TeachingEvent.turns`。
- `return` 恢复原问题与上下文，phase 回 `interviewing`，之后的回答按 `reanswer` 记录；
  教学事件与主动求助不计入答题记录。
- `skip` 在教学阶段结束教学并跳过当前卡；`TeachingEvent` 保留为 `skipped`。
  `skip_followup` 只记录当前追问并继续本卡追问链，不改主问题与 `skipped_cards`。

**图与状态**

```
START → dispatch（读 action）
  answer                 → interviewer → END
  skip / skip_followup   → 跳过节点   → END
  return                 → interviewer → END
  teach / teach_message  → teacher     → END
  end                    → finish      → END
```

- 对话面试的 `threadId` 是独立 uuid；`/api/interview/thread` 用前端确认过的题包
  `graph.aupdate_state(config, initial_state)` 写入首张卡（`policy.first_card`：
  未答卡片中优先级最高、同优先级按生成顺序）、`ownerSession` 与 phase，不额外跑模型。
  出题（`/pack`）与建场（`/thread`）拆开；第 3 步题包同时服务对话与清单，
  清单不建检查点。之后每次 action 从检查点恢复，只执行一个节点再落盘。
- 检查点单独存 `smartcv-api/interview_checkpoints.sqlite`，与 chat 的检查点分开：
  chat 仍每小时整库清空；面试按线程最后更新时间清理超过 1 小时未活动的线程，
  进行中的面试不会被整库删除误伤。两者共用泛化后的
  `agents/utils/checkpointer.py`（按名字取 saver），现有
  `optimize/utils/checkpointer.py` 保留为 chat 的兼容入口，不改 chat 行为；
  `main.py` 的 lifespan 同时打开两个 saver，清理循环分别调用整库清空与按线程裁剪。
- 结构化输出失败：面试官先做原始 JSON 兼容解析，仍失败再重试一次，最后才发 `error`
  并保持原状态，用户可重新提交；不跳过评估、不伪造反馈。教师失败同样只报错，phase
  仍留在教学，可重试或返回。

**隐私与日志**

- 画像、问题包、参考答案、答题记录不进日志；日志只记 threadId、动作、轮次、耗时和
  卡片数量，不打印简历全文、用户回答与参考答案。
- 服务端不落业务表：画像 / 问题包由前端 IndexedDB 持有，后端只在一次请求内使用；
  进行中面试的状态在 sqlite 检查点里临时保存，空闲 1h 删除。

**落地顺序**（每步都可独立验证，先纯函数后模型）：

1. `schemas.py` + `policy.py`：实体、问题包校验、追问与配额纯函数；
2. 简历分析 Agent + `/api/interview/profile`：用示例简历跑通画像与锚点核对；
3. 问题生成 Agent + `/api/interview/pack`：分组并发、合并校验、对话与清单共用；
4. 图 + 检查点 + `/api/interview/thread` + 面试官 Agent + `/api/interview/stream`：
   用题包建场、对话面试、追问控制、刷新恢复；
5. 教学导师 Agent + 教学模式 + 最近面试回看（对话 / 清单）。

## 6. 前端架构

```
pages/        页面级：HomePage / EditorPage / ReviewPage / ProviderSettingsPage /
              ReferenceExamplesPage / MarketInsightsPage
  ↑ 通过 App.vue 的 currentPage 切换（无 vue-router）
components/   编辑画布、章节卡、布局窗口、内容卡、预览、对比弹窗、图标选择器、
              AskQuestionCard（反问卡片）…
stores/       resume（唯一数据源 + 撤销重做 + 分页方案）/ documents（本地备份）/
              review（对话时间线）/ marketSources（补充网址标签）/ stats
composables/  usePagination（测量 + 计算）/ usePageSize / usePreviewZoom / useSyncScroll /
              useClickPopover / useMarketResearch（采集参数）/ useMarketMotion（光点动效）…
utils/        pagination / resumeDiff / layout / style / markdown / fs/（备份文件夹读写）…
types/        Section / LayoutWindow / Content / 样式等类型定义
styles/       global.css（Design Token）/ naive-theme.ts（naive-ui 主题）
api/          每个后端接口一个模块，统一走 api/http.ts（market.ts 走 fetch 流）
data/         presets（组件库预设）/ icons（品牌 + emoji）/ heroResume（首页演示）
scripts/      （smartcv-web/scripts）gen-example-index.mjs（生成 smartcv-api/example/index.json）
```

### 6.1 市场洞察页（`pages/MarketInsightsPage.vue`）

```
左栏：基础信息（目标岗位 / 简历选择 / AI 反推岗位 / 开始·重新调研）
      + 流程时间线（规划 → 采集 → 各维度 → 简历画像 → 最后是报告）
右侧：页签面板（规划检索 / 采集页面 / 各维度 / 简历画像 / 策略总结）
      + 报告区（章节逐章流式写入，可回看证据）
```

- 页面只让用户填「目标岗位」或选一份简历；城市 / 年限 / 时间窗口由 planner 反问补全，
  反推按钮单独调用 `/api/market/roles`，结果只填进本轮请求，不写回简历。
- 页签、流程节点、报告章节都以 `plan.result.dims` 为准动态重建；固定维度
  `jobs→岗位概览`、`trend→技能要求`，动态方面各自成章，没选的方面不会出现空章节。
- 证据：`sources.index` 建立 `id → {title,url,site,published,kind,excerpt,userTag}`，
  正文 / 面板里的 `J1/T2/E1…` 点击即可看来源；补充网址额外显示「补充 · 备注」。
- 采集页顶部是「来源分布」标题行（总页数 / 站点数 / 维度数），下面分「按站点」
  与「按维度」两块：站点取前 6 名、其余合并成「其余 N 个站点」；每个维度除了页数
  还标出来源构成——原始 SearXNG（抓到正文）/ 补充 SearXNG（失败后退回搜索摘要）/
  补充 URL（`userTag`），前端只看 `sources.index` 的 `excerpt` / `userTag` 字段。
  未采页（`collect.skip`）在站点行显示「未采 N」与原因，避免和分页混淆。
- 动效：光点箭头颜色 / 方向 / 长短 / 速度读 `useMarketMotion`，可在高级设置里调整；
  流程节点边缘由前端计算，后端只给语义节点与边。
- 结果快照：`localStorage['smartcv-market-run']`（800ms 防抖 + `pagehide` 兜底），
  刷新 / 切页后恢复上一轮结果与页签位置；只恢复展示，不重连后端任务，
  仍在运行的节点标记为「刷新中断」。开始新一轮时清空快照。
- 隐私：调研请求只在用户点击开始时发出；简历快照仅随请求发送用于画像 / 反推。

### 6.2 AI 模拟面试页（`pages/InterviewPage.vue`）

```
左栏：步骤条（确认简历 → 选择面试场景 → 生成问题包 → 选择面试方式 → 面试 / 清单）
      + 最近面试（对话 / 清单，最多 5 条）
右栏：当前步骤面板
  确认简历：画像（职业方向 / 技术栈等级 / 项目 / 证据锚点），可改可删可重新解析
  选择面试场景：项目面试（单选项目 + 考察方向 + 普通/压力）/ 综合面试 / 排查面试
  生成问题包：主问题数 + 主问题与 L1/L2/L3 追问链预览，不展示参考答案，
              不展示项目数 / 追问总数 / L3 占比等内部质量统计
  选择面试方式：对话面试 / 清单自测；两种方式复用同一份题包，不重新出题
  对话面试：单题面谈室（进度、当前问题、作答框、三按钮、反馈卡、教学模式）
  清单自测：问题清单（按考察方面筛选、逐题展开答案与追问答案、已看 / 未看）
  最近面试回看：只读展示所选历史（对话 / 清单），可导出单文件 HTML，
              不替换当前活动题包
```

页面状态机（`stores/interview.ts`）：

```
idle → analyzing → profileReady → choosing → generating → packReady
                                                            ├─ 对话面试：interviewing ↔ teaching → finished
                                                            └─ 清单自测：展开同一份题包 → 按卡生成答案
```

- 简历来源只有一个：`stores/resume.ts` 的 `state.resume`。进入页面时计算简历指纹
  （`JSON.stringify(resume)` 的稳定哈希），命中 IndexedDB 里的画像就直接展示，不再
  调模型；指纹变了显示「简历已修改，建议重新解析」，由用户决定，不自动覆盖。
- 画像与问题包都能手动改 / 重新生成；问题包记录它基于哪个 `resumeFingerprint` 与
  `profileRevision` 生成，画像改过之后旧包标记为「基于旧画像」，提示重新生成。
- 对话与清单共用 `PackRecord.cards`：对话从卡的 `followUps` 推进，清单直接
  展开同一批卡；清单只维护独立的已读集合与历史快照，不再保存第二套题卡。
- 流程顺序固定为五步：选场景 → 生成题包 → 选方式 → 作答。第 3 步 `/pack` 按场景
  只出题并落到 `packReady`；第 3 步页面只预览题目，不展示参考答案；
  第 4 步选清单直接进入第 5 步，进入后才后台按卡生成答案（最多并发 3 张），
  选对话才调 `/thread` 建检查点。`canGo` 逐级校验，没有题包不能进第 4 步，
  没有确认方式不能进第 5 步。刷新回到清单时只补 `pending` 的卡。

IndexedDB（`utils/interviewDb.ts`，数据库 `smartcv-interview`，v1）：

| store | key | 内容 |
|---|---|---|
| `profiles` | `resumeFingerprint` | `{ profile, anchors, editedAt, revision, schemaVersion }` |
| `packs` | `pack.id` | `{ cards[], warnings[], useMode, scene, followDepth, focus, projectIds[], resumeFingerprint, profileRevision, seenCardIds[], checklistSeenCardIds[], createdAt }` |
| `sessions` | `threadId` | `{ threadId, packId, useMode, scene, focus, projectNames[], startedAt, endedAt, status, records[], currentIndex, summary, teaching[], checklistCards?, checklistWarnings?, checklistSeenCardIds[], report? }` |

- `sessions` 保留进行中的一场 + 最近 5 条已结束记录；记录分「对话」与「清单」两种：
  对话记录保存 `records` 与讲解轮次 `teaching`，清单记录保存题包快照
  `checklistCards`（与 `packs.cards` 同源），key 为 `checklist:<packId>`。`profiles` 只保留最近 3 份
  指纹，避免无限增长。每收到 `evaluation` / `question` 就把当前进度写回，刷新时
  先读本地记录，再用 `GET /api/interview/state` 对齐；结束摘要只保留在已结束的 5 条里。
- 最近面试只读回看：点击历史只加载 `reviewSession` / `reviewPack`，不改写当前
  `packRecord`，因此查看旧清单不会清掉正在使用的清单内容。对话历史每条作答按
  「你的回答 → 回答评估」展示，评估区统一包含没讲到的关键点、改进建议与 AI 示例
  回答；清单历史按当时的 `checklistCards` 渲染已看 / 未看。示例回答只存浏览器，
  结束或刷新时服务端记录覆盖本地记录，按卡 + 问题 + 回答（同题多答再按次序）回填，
  因此结束后的回看与导出仍能看到。导出 HTML 与回看页共用同一套展示规范：
  回答称呼、评估区整体边框、三个子标题及其顺序保持一致，改任一处须同步另一处。
  服务端检查点已过期时仍可回看本地记录；回看页的「面试报告」仍为占位按钮，但
  「导出」会把当前记录导出为自包含单文件 HTML（内联样式、无外部资源），并固定
  保留「面试报告」章节：已有 `sessions.report` 就渲染，未生成 / 面试未结束则显示
  对应占位，后续报告功能上线不用改导出结构。
- 已看 / 未看分别写 `packs.seenCardIds`（对话）与 `packs.checklistSeenCardIds`（清单），
  刷新后保留；「重新生成」先保留旧包再询问是否替换。
- `localStorage` 只放指针与偏好（`smartcv-interview-last`：最近 threadId / packId、
  上次选择的模式），大对象一律放 IndexedDB，避免 5MB 配额和 JSON 解析抖动。

页面行为：

- 对话面试每次只展示一个问题；提交后先显示「评估中」，`evaluation` 到达后展示命中的
  露馅信号和一句反馈，再展示下一问。当前题下方固定三个入口：
  `提交回答` / `我不会，AI 教我` / `跳过此题`；教学阶段换成
  `返回面试` / `跳过此题`。停在追问时，「跳过此题」提供
  `跳过这条追问` 与 `跳过整道题` 两个选项；主问题只有整道题跳过。
- 教学阶段展示为同一面谈室里的连续消息，导师回复流式写入；返回后原问题、已用追问
  与上下文不变，重新作答按 `reanswer` 记录。
- 清单自测按项目 / 优先级 / 追问层级筛选。答案不自动生成：「追问链」「参考答案」
  标题旁各有「AI生成答案」小角标，点击后才调用对应接口；生成中显示进度。
- 参考答案按「回答思路 / 回答内容 / 缺少证据 / 补充假设」分区展示，整体可折叠；
  没有缺口的答案不显示「缺少证据」「补充假设」。
- 追问链各条没有答案时，点击追问链旁的「AI生成答案」一次调用
  `/follow-up-answers` 补齐缺失项；每条追问的答案使用同一套分区与折叠展示。
- 结束面试时把 `summary` 与讲解轮次写进 `sessions`，页面展示摘要（已答 / 跳过、
  动态追问、求助次数）与「面试报告」占位按钮，暂不做完整报告。
- 刷新恢复：`localStorage` 里有未结束的 threadId 时，先 `GET /api/interview/state`
  对齐当前题与 phase；404（已过期 / 已清理）就提示「上次面试已过期」，保留本地
  问题包并允许重新开始。
- 视觉沿用 Design Token：靛蓝主色、冷灰底、发丝线分界、0.16s 过渡；不放四等大卡片，
  选项用分段控件 / 列表行；问题、回答与参考回答必须完整换行展示，不截断、不加省略号。
- 组件拆分：`components/interview/ProfileReview.vue`、`ScenePicker.vue`（选场景与考察方向）、
  `PackReview.vue`（预览题包）、`ModePicker.vue`（选题包消费方式）、`PackList.vue`、
  `InterviewRoom.vue`、`EvaluationCard.vue`、`TeachingPanel.vue`、
  `HistoryList.vue`、`HistoryDetail.vue`；接口封装在 `api/interview.ts`（SSE 解析方式与
  `api/chat.ts` 一致）。
- `App.vue` 增加 `interview` 页面键与「模拟面试」页签。这一页不像市场洞察那样放进
  `keep-alive`：每条 SSE 只服务一轮操作，切页不会毁掉服务端检查点；回来时用
  `GET /api/interview/state` 重新对齐即可。

### 关键不变量

1. **单一数据源**：所有编辑都改 `resume` store；不存在第二份拷贝。
2. **撤销重做**：`main.ts` 用 `$onAction` 拦截结构操作（每步一快照）与文字编辑
   （同字段 1200ms 内合并），最多 50 步。
3. **自动保存**：`resume` 变化防抖 400ms 写 localStorage；绑定了备份文件夹时再防抖 1s
   写文件；`pagehide` 兜底再存一次。
4. **AI 结果不直接落库**：`resume` 事件 → `pendingDiff` → 用户逐处确认 → 写回。
5. **diff 按 id 对齐**：后端只浅拷贝并就地改文字，id 不变；因此不能对返回值做
   `normalizeResumeData`（会重生成 uid，整份简历被误判为全变）。
6. **代码高亮 / Markdown**：`markdown-it` 开 `html:false`（防 XSS）、`breaks:true`；
   代码块用 highlight.js 常用语言包。
7. **市场洞察以 SSE 为唯一事实来源**：节点状态、页签内容、报告章节都只由事件驱动，
   刷新后从快照恢复展示，但不假装任务仍在跑（进行中节点标「刷新中断」）。
8. **补充网址标签只在本机**：`stores/marketSources.ts` 以备份文件夹的
   `market-sources.json` 为唯一真相，`localStorage` 只是未绑定文件夹时的缓存；
   任何增删改都同步回写文件，请求时只把 `{url,direction,note}` 随本轮调研发出。

## 7. 隐私与安全

| 数据 | 存放位置 | 生命周期 |
|---|---|---|
| 简历 JSON | 浏览器 localStorage | 用户清除前一直在 |
| 简历文件（备份） | 用户自选本地文件夹（File System Access API，句柄存 IndexedDB） | 用户管理 |
| 解析中间结果 | 后端内存 `PDF2ResumeStore` | 请求结束即删 |
| 对话 / 市场洞察检查点 | 服务端 sqlite | 每小时清空 |
| 优秀示例库 | 服务端 `data/reference-examples`（`SMARTCV_REFERENCE_DIR`） | 永久（只增不删，全局共享） |
| 导出计数 | 服务端 `data/stats.json`（`SMARTCV_STATS_FILE`） | 永久 |
| 市场调研任务事件 / 结果 | 服务端内存 `_TASKS`（TTLCache） | 15 分钟 / 进程重启即丢 |
| 抓取的公开网页正文 | 服务端内存（`SourcePage`） | 请求结束即丢；抽取 / 成稿时发给用户自配模型 |
| 市场调研结果快照 | 浏览器 localStorage `smartcv-market-run` | 下一轮开始 / 用户清除前 |
| 补充网址标签 | 备份文件夹 `market-sources.json` + localStorage 缓存 | 用户管理，只在本机 |
| 面试画像 / 问题包 / 参考答案 / 答题记录 / 讲解内容 | 浏览器 IndexedDB `smartcv-interview` | 用户清除前；画像与包各保留最近 3 份 |
| 最近 5 场对话 / 清单记录（含清单快照） | 浏览器 IndexedDB `smartcv-interview.sessions` | 只留最近 5 条已结束记录，用户可清除 |
| 面试检查点（进行中的状态） | 服务端 `interview_checkpoints.sqlite` | 线程空闲 1 小时后按线程删除 |
| API Key | 浏览器 localStorage | 用户清除前一直在 |

- 只有用户主动触发 AI 功能时内容才离开本机（MinerU 解析 / 用户自配模型服务商）。
- 诊断需要外部资料时，`web_search` 只把检索词发往自建 SearXNG（可能再转发上游搜索引擎），
  不发送整份简历。
- 市场洞察的检索词发往自建 SearXNG；抓到的公开网页正文与简历快照会发给用户自配模型
  （抽取 / 合成 / 成稿 / 画像），用于本次调研，不落服务端库。
- 用户补充的网址只在本机保存（`market-sources.json`）；采集时由服务端抓取公开页面，
  正文随本轮调研结束丢弃。抓取实现做了 SSRF 校验（拒绝私网 / 逐跳校验重定向）、
  2MB 读取上限与请求超时。
- 面试画像、问题包、参考答案与答题记录只存浏览器 IndexedDB；只有用户触发「解析简历 /
  生成问题 / 进入清单 / 提交回答 / 教学提问」时才把当次所需内容发给用户自配模型服务商。
- 进行中的面试状态（问题包、答题记录、教学轮次）临时存在服务端检查点 sqlite，
  线程空闲超过 1 小时按线程删除，不是业务持久化；日志只记线程 id、动作、轮次与耗时，
  不打印简历全文、用户回答与参考答案。检查点与答案不会用于训练或跨用户共享。
- 出题阶段不调用答案生成；用户进入清单后，前端才按卡调用 `/reference-answer`，
  追问答案再按需调用 `/follow-up-answers`。答案优先使用确认后的画像事实，代码校验
  数字；信息不足时保留 `missingInfo`，同时生成带 `assumptions` 的示范答案，页面明确
  标注「含 AI 假设」，不能当作简历事实。
- 调研任务事件缓存按会话隔离、15 分钟过期；取消 / 重新调研会立即停掉旧 producer。
- 后端 CORS 全开仅作 dev 兜底；生产由 nginx 同源代理，`proxy_buffering off` 保 SSE。
- 已实现的安全细节：路径穿越校验（示例库、技能加载）、`html:false`、文件名清洗、
  错误信息不泄露内部堆栈。

## 8. 设计与视觉规范

- 主色靛蓝 `#4753c7`（hover `#3c46b2` / pressed `#343da0` / soft `#eceffb`）；
  底 `#f6f7f9`，纸面纯白，发丝线 `#e4e6ec`，文字 `#1c2130 / #596175 / #8a91a6`。
- 字体：正文系统无衬线；衬线（`--font-display`）只用于品牌字标与首页眉标。
- 图标：界面图标统一 `IconGlyph.vue`（手写 Lucide path，不依赖图标库）；品牌图标来自
  `simple-icons`，简历内容图标来自 `data/icons.ts` 的 emoji / 内联 SVG。
- 动效：仅首屏 Hero 一次 staggered rise-in（0.55s，逐项 +0.06s）；其余 0.16s `var(--ease)`；
  弹层过渡全局禁用（历史卡死问题）；`prefers-reduced-motion` 降级。
- 禁忌：玻璃拟态、渐变装饰、循环漂浮、四等大功能卡片、全大写眉标、Notion 风。

## 9. 已知约束与后续方向

| 约束 | 现状 | 可能的演进 |
|---|---|---|
| 列宽 | 等分（`spanForIndex`），不能自由设比例 | 给 `LayoutWindow` 加 `span` 字段 + 渲染器支持 |
| 无行内 HTML | `html:false`，只支持 Markdown 子集 | 保持（安全优先），用组件表达样式 |
| 内容类型固定 7 种 | 无 divider / table | 加类型需同步 `PreviewContent` / `ContentCard` / 预设 / 后端 `resume.py` 文字单元映射 |
| 会话按浏览器隔离 | 多标签页会串进度 | 若要按标签页隔离需换 sessionStorage + 后端区分 |
| 无账号体系 | 示例库全局共享 | 需要权限模型时再引入 |
| 后端无自动化测试 | 仅编译/构建校验 | 优先补 `agents/utils/resume.py`、分页与配额分配的纯函数测试 |
| 市场洞察来源 | SearXNG 聚合 + 用户补充网址；BOSS / 腾讯 / 华为适配器为占位实现（返回空，不降级） | 接真实公开岗位接口时只替换 `tools/adapters/*.py`，流水线不动 |
| 市场报告导出 | 只在页面内展示与快照恢复，未接 PDF / Markdown 下载 | 可复用 `services/html2pdf.py` 或前端导出 |
| 超配额网址筛选 | 一次结构化调用同时判归属与取舍，失败回退按标签归组前 N 条 | 可加结果缓存 |
| 市场任务存储 | 进程内 TTLCache（900s），多实例 / 重启会丢 | 需要水平扩展时换 Redis / DB |
| 采集页数 | `pagesPerDim` 按 jobs / trend / other 三类各配一份，不做比例分配；页数多时靠 `format_pages` 压缩正文 | 若模型窗口更小时调小 `MARKET_GROUP_CHARS` |
| 面试恢复窗口 | 服务端检查点按线程空闲 1h 清理；超时后只能看本地问题包与已存摘要，不能继续原面试 | 需要更长恢复时间时调大 idle 阈值，但仍保持临时存储 |
| 面试报告 | 只做结束摘要与最近 5 场对话 / 清单回看，报告按钮为占位；回看可导出单文件 HTML 并预留报告章节，报告内容本身尚未生成 | 后续把报告写入 `sessions.report`，导出会自动渲染；也可复用报告页与 `html2pdf` |
| 问题包成本 | 每次生成按项目 / 综合主题 / 排查题型分组调模型，只出题；进入清单后按卡生成主问题答案（并发 3），追问答案再按需生成 | 可按简历指纹缓存问题包（仍只在浏览器），或让答案生成也分批懒加载 |
| 面试题库 | 不建通用题库，问题只来自简历与所选项目；排查面试的题面指标是假设场景，不是题库 | 需要刷题时另立模块，不复用本流水线 |
| 面试评价 | 只给命中的露馅信号与一句可执行反馈，不做数值评分 | 需要量化对比时另做独立评估，不改变当前作答记录结构 |

## 10. 变更检查清单

改代码前自问：

1. 是否触碰了 `Section[]` 结构？→ 同步 `types/index.ts`、`presets.ts`、`resume.py` 文字单元映射、
   渲染组件、示例 JSON。
2. 是否新增接口？→ 更新本文件第 4 节 + `src/api/*.ts` + 统一响应格式。
3. 是否改了 AI 行为？→ 更新提示词 md，并在第 5 节说明约束（尤其「不得新增事实」）。
4. 是否影响分页？→ 预览与导出必须同时验证页数。
5. 是否改了市场洞察？→ 同步第 3.4 / 4.3 / 5.6 节：维度与证据前缀、`pagesPerDim` /
   `urlsPerDim` 每维额度、`fetchMode` 抓取方式、SSE 事件名、报告章节、补充网址 `note` 必填。
6. 是否新增注释？→ 对照 AGENT.md「注释规范」。
7. 提交前跑 `npm run typecheck && npm run build` 与后端 `compileall`。
8. 是否改了模拟面试？→ 同步第 3.5 / 4.5 / 5.7 / 6.2 节：对话与清单共用题包、
   `/pack` 只出一次且只出题、`/thread` 只建场、进入清单后才生成答案、
   追问链 / 露馅信号为必填字段、单锚点 ≤3 轮、单场动态 ≤5 条、依据不足时保留缺口
   并标注假设、检查点按空闲 1h 清理、日志不含简历 / 回答全文。
9. 是否新增面试数据？→ 画像 / 问题包 / 答题记录只进 IndexedDB，不进业务表；
   `provider` 每轮随请求带，不写检查点。
