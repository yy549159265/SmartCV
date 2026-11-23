# AGENT.md

>本文件是 SmartCV 仓库的 AI 协作总纲，任何 AI 代理改代码前先读本文件。
>正文代码路径相对仓库根目录（Markdown 链接除外）。详细设计见
>[SDD.md](SDD.md)，解析流水线见
>[PIPELINE.md](smartcv-api/agents/md2json/PIPELINE.md)。

## 一句话定位

SmartCV = AI 简历制作与优化工具。前端 Vue 3 + Vite + TS + Pinia + naive-ui
（`smartcv-web`），后端 FastAPI + LangGraph（`smartcv-api`）。整份简历只有一份
`Section[]` JSON，编辑 / 预览 / 导出 / AI 优化共用这一个数据结构。
另有「市场洞察」：用 SearXNG + 用户补充网址采集公开页面，按维度并行抽取，
产出带证据编号的求职市场报告；以及「AI 模拟面试」：基于用户确认的简历画像预生成
问题包，支持对话追问与清单自测。出题阶段只生成问题，进入清单后才生成参考答案。

## 硬约束

1. **注释规范**：见「编码约定 → 注释规范」。不要写复述代码、变更史、`注意：` 式
   凑字数注释；前端默认不写行内注释。
2. **简历 JSON 是唯一真相**：`smartcv-web/src/stores/resume.ts` 的 `state.resume`。
   所有 JSON → 文本、坐标定位、写回都走 `smartcv-api/agents/utils/resume.py`。
3. **坐标模型**：`[s:章节 r:窗口 c:内容 i:文字单元]`。AI 只能按坐标替换文字，
   不增删章节 / 窗口 / 内容，不改样式与图片。
4. **分页模型**：`smartcv-web/src/utils/pagination.ts` 把简历拍平成「可裁切单元」，
   预览与导出共用同一份 `pagePlan`；页数必须一致。
5. **隐私**：简历只存浏览器 localStorage；后端解析结果发完即删；API Key 只在浏览器。
   服务端持久化的只有优秀示例库与导出计数（`smartcv-api/data`，可用环境变量改路径），
   对话 / 市场洞察检查点 sqlite 仅临时保存，每小时清空；面试检查点独立存放，
   按线程空闲 1h 清理。
6. **市场洞察的维度与证据前缀**：固定维度只有 `jobs` / `trend`，其余维度由用户选择，
   不预置也不按关键词归类；证据前缀统一由
   `smartcv-api/agents/resume/marker/utils/dims.py::evidence_prefixes` 生成
   （`J` / `T` / `E1…`），采集与前端溯源必须共用同一份结果，不要手写前缀。
7. **每维独立额度**：`pagesPerDim` 是按维度类别配置的页数，键固定三组：
   `jobs`（招聘矩阵）/ `trend`（技术趋势）/ `other`（其余动态方向，每个方向各用一份），
   不做按比例分配，也没有总预算可挪用；`urlsPerDim` 同理，表示每个方向最多使用的补充
   网址条数。单个维度的网址由三部分构成：SearXNG 结果、内置来源（仅 `jobs`）、用户补充
   网址。补充网址的 `note` 必填，一次结构化调用同时判定归属与取舍。启用任意内置来源后，
   该来源独占 `jobs`，**不回退 SearXNG**（返回 0 页就如实上报空结果并给 `reason`）；
   勾选多个来源时 `jobs` 的页数是这些来源共用的总额度，各来源轮流取，不是每个来源各拿
   一份。动态维度的 id 不固定，统一用 `schemas/market.py::pages_key` 折算到 `other`。
8. **市场工具层不调模型**：`agents/resume/marker/tools/` 不导入 agent / LLM；
   需要模型判断时由 `market_agent.py` 把回调（分流 / 筛选）传进采集器。
9. **市场结论必须可溯源**：所有 findings 带 `evidence_ids`，代码过滤不存在的编号；
   编不出来就留空，不靠模型补写来源。
10. **面试问题包是唯一题源**：对话面试只从当前卡的追问链里选，或按规则生成动态追问，
    不脱离问题包自由出题；单锚点追问 ≤3 轮、单场动态问题 ≤5 条、连续两次答非所问
    进入下一题，全部由 `agents/resume/interview/policy.py` 的纯函数兜底。
11. **面试不得虚构事实**：问题与参考答案只基于用户确认后的 `ResumeProfile + Anchor[]`，
    不把原始简历发给问题生成 Agent；`/pack` 只出题，不生成答案。进入清单后，
    答案能落到画像事实上就按事实写；依据不足时保留 `missingInfo`，同时生成一份
    带 `assumptions` 的示范答案，不把假设伪装成简历事实。每卡至少 2 条露馅信号、
    L3 追问占比 ≥30%，由代码校验。
12. **面试数据只在浏览器**：画像、问题包、参考答案、答题记录、最近 3 次摘要都存
    IndexedDB；进行中的面试状态只进独立的 `interview_checkpoints.sqlite`，按线程空闲
    1h 清理；日志不得打印简历全文、用户回答与参考答案。

## 协作流程

需求按「目标 / 范围 / 验收 / 约束」对齐；缺哪项先问，能从代码或文档确认的不反问，
不要自行补全业务规则。

1. **先对齐**：复述用户可见结果，确认改前端 / 后端 / 两者，列出可改文件与不要动的文件。
2. **先查影响面**：涉及 `Section[]`、分页、接口、AI 流水线或隐私边界时，说明会波及
   哪些文件与行为；方案不唯一时先给方案，确认后再改。
3. **小步改**：复用现有 store / 组件 / `agents/utils/resume.py` / `pagination.ts`，不另起
   一套；不顺手重构，不扩大范围，范围外的问题只记录。
4. **验收后汇报**：跑「启动与验证」中的命令；分页改动同时核对预览与导出页数；AI 改动
   用 `smartcv-api/example` 的样例跑一轮。汇报改了哪些文件、验证结果、未做事项与风险。

单文件小改可直接做；涉及多文件、数据结构、AI 行为或隐私边界时才完整展开以上流程。
用户当前指令与文档冲突时，先指出冲突点，以用户当前指令为准；文档与代码冲突时，
先核对代码实际行为，再决定改文档还是改代码。

## 项目结构

```
smartcv-api/            FastAPI + LangGraph 后端（Python）
  main.py               应用入口：lifespan、会话中间件、异常包装、路由注册
  routers/              business.py（解析/导出/统计/示例）| agent.py（润色/分析/纠错/对话 SSE）
                        market.py（市场洞察 SSE / 反问 / 取消 / 岗位反推）
                        interview.py（面试画像 / 问题包 / 对话面试 SSE / 状态恢复）
                        deps.py（从 request.state 取会话 id）
  agents/
    md2json/            MinerU 产物 -> 简历 JSON：清洗 + 一次 LLM 结构化 + 代码排版
    resume/optimize/    LangGraph 流水线 convert -> diagnose -> review -> summarize
                        tools/patch_resume.py 实现 patch_content 与写回校验
    resume/grammar/     全文纠错：一次结构化调用 + 代码校验
    resume/marker/      市场洞察：plan -> collect -> extract×N -> synthesis -> strategy
                        -> compose；tools/ 下是搜索 / 抓取 / 来源适配器
                        prompts/ 下是各 agent 的提示词 md
    resume/interview/   模拟面试：简历分析 -> 问题包 -> 面试官 / 教学导师（LangGraph）
                        policy.py 管追问轮次、动态配额与问题包校验
                        prompts/ 下是各 agent 的提示词 md
    single/             单次 LLM：润色 / 增强 / 分析
    skill/              coordinate / diagnose / review 三份 SKILL.md（运行时按需加载）
    utils/resume.py     简历 JSON 文本化 / 坐标定位 / 写回的唯一实现
  services/             pdf2json（MinerU）| html2pdf（Playwright）| stats | reference_examples
  schemas/              provider（供应商配置）| response（统一 {code,message,data}）
  example/              内置示例简历 JSON + index.json
  data/                 服务端持久化数据（优秀示例库、导出计数），目录可用环境变量覆盖
smartcv-web/            Vue 3 + Vite + TS + Pinia + naive-ui 前端
  src/api/              后端接口封装（统一走 api/http.ts；market.ts / interview.ts 走 fetch 流）
  src/components/       编辑器/预览/对比弹窗/反问卡片/面试面谈室与反馈卡等组件
  src/pages/            Home / Editor / Review / ProviderSettings / ReferenceExamples /
                        MarketInsights（市场洞察）/ Interview（模拟面试）
  src/stores/           resume（唯一数据源）/ documents / review / marketSources /
                        interview（画像 / 问题包 / 面试状态）/ stats
  src/composables/      usePagination / usePageSize / usePreviewZoom / useSyncScroll /
                        useMarketResearch / useMarketMotion 等
  src/utils/            pagination（可裁切单元模型）/ resumeDiff / layout / style / markdown /
                        interviewDb（IndexedDB）/ fs/
  src/types/            Section / LayoutWindow / Content 等类型定义
  src/styles/           global.css（Design Token）/ naive-theme.ts
  src/data/             presets / icons / heroResume
  scripts/              gen-example-index.mjs（生成 smartcv-api/example/index.json）
script/                 docker-compose.yml / searxng / smartcv.sh 等部署文件
```

市场洞察目录约定（`smartcv-api/agents/resume/marker/`）：`graph.py` 只做编排与事件出口；
`*_agent.py` 各自负责一次模型调用；`tools/collect.py` 负责额度、去重、编号；
`tools/adapters/` 负责具体来源，`tools/collectors/` 负责采集方式（searxng / deepseek），
`tools/fetch/` 负责取正文；`utils/dims.py` 是维度 / 前缀 / 图结构的唯一出处；
`schemas/market.py` 是跨层数据结构的唯一出处。

模拟面试目录约定（`smartcv-api/agents/resume/interview/`）：`graph.py` 只做 action 分发、
检查点与事件出口；`resume_agent.py` / `pack_agent.py` / `interviewer_agent.py` /
`teacher_agent.py` 各自负责一次模型调用（问题包按组并发）；`policy.py` 是追问轮次、
动态配额、下一题与问题包校验的唯一出处；`schemas.py` 是跨层数据结构的唯一出处；
`prompts/<阶段>/*.md` 是提示词。

## 启动与验证

```bash
# 后端（默认 9000；SMARTCV_API_PORT 同时控制 vite 代理，两端必须一致）
cd smartcv-api && uvicorn main:app --reload --port 9000

# 前端
cd smartcv-web && npm run dev        # http://localhost:5173，/api 代理到 127.0.0.1:9000

# 内置示例增删后重建清单
cd smartcv-web && npm run examples:index

# 市场洞察依赖 SearXNG（地址/超时见 smartcv-api/agents/utils/searxng.py，SEARXNG_URL 可覆盖）
# 本机直接跑 searxng-docker-china-main，实例在 http://127.0.0.1:8088；
# script/docker-compose.yml 是服务器 /opt/smartcv 的部署编排（卷都写死在该目录），不要在本机跑
# 只验证后端逻辑时可以跳过 SearXNG：采集会返回空页面，流水线仍会走兜底并出报告

# 提交前必须通过
cd smartcv-web && npm run typecheck   # vue-tsc -b
cd smartcv-web && npm run build       # vue-tsc -b && vite build
cd smartcv-api && python -m compileall .
```

后端本地默认端口与前端代理都取 `SMARTCV_API_PORT`（默认 9000）；Docker 后端镜像监听
8600，编排文件在 `script/docker-compose.yml`。后端没有测试框架，改完至少
`python -m compileall smartcv-api`（或导入 `main`）确认无语法/导入错误。
改市场洞察时再额外 `python -c "import routers.market"`，并用一个岗位跑一轮
（可只检查 `plan.result`、`collect.done`、`report.done` 是否按预期出现）。
改模拟面试时额外 `cd smartcv-api && python -c "import routers.interview"`，并用
`smartcv-api/example` 的样例跑一轮 `profile -> pack`，再提交一次回答，核对
`question` / `evaluation` / `state` / `done` 事件按序出现，且追问轮次与动态问题数量
没有越界。

## 常见任务入口

| 任务 | 改哪里 |
|---|---|
| 加/改后端接口 | `smartcv-api/routers`，请求模型就近定义，响应走 `smartcv-api/schemas/response.py` |
| 改 AI 提示词 | `smartcv-api/agents/**/system_prompt*.md`、`smartcv-api/agents/single/*_prompt.md`、`smartcv-api/agents/skill/*/SKILL.md` |
| 改优化流水线 | `smartcv-api/agents/resume/optimize/graph.py`（编排）+ `diagnose_agent.py` / `review_agent.py` / `summarize_agent.py` + `tools/patch_resume.py`（`patch_content`） |
| 改前端接口调用 | `smartcv-web/src/api/*.ts`（统一走 `api/http.ts`） |
| 改编辑器 / 预览 | `smartcv-web/src/components`、`smartcv-web/src/pages/EditorPage.vue` |
| 改优化页交互 | `smartcv-web/src/pages/ReviewPage.vue` + `smartcv-web/src/stores/review.ts` |
| 改市场洞察流水线 | `smartcv-api/agents/resume/marker/graph.py`（编排 / 事件出口）+ `market_agent.py`（采集 / 抽取）+ 各 `*_agent.py` |
| 改市场采集 / 来源 | `agents/resume/marker/tools/collect.py`（额度 / 去重 / 编号）+ `tools/adapters/`（来源）+ `tools/collectors/`（采集方式）+ `tools/fetch/`（取正文） |
| 改市场提示词 | `smartcv-api/agents/resume/marker/prompts/**/*.md` |
| 改市场页交互 | `smartcv-web/src/pages/MarketInsightsPage.vue` + `api/market.ts` + `stores/marketSources.ts` + `composables/useMarketResearch.ts` / `useMarketMotion.ts` |
| 改市场设置 | `smartcv-web/src/pages/ProviderSettingsPage.vue` 的「市场洞察」页签 |
| 改面试流程 / 追问策略 | `agents/resume/interview/graph.py`（编排）+ `interviewer_agent.py` + `policy.py`（轮次 / 动态配额 / 校验的唯一出处） |
| 改面试问题包 | `agents/resume/interview/pack_agent.py` + `prompts/pack/*.md` + `schemas.py`（校验在 `policy.py`） |
| 改面试提示词 | `agents/resume/interview/prompts/**/*.md` |
| 改面试页交互 | `smartcv-web/src/pages/InterviewPage.vue` + `api/interview.ts` + `stores/interview.ts` + `utils/interviewDb.ts` |
| 改配色 / 视觉 | `smartcv-web/src/styles/global.css`（token）、`smartcv-web/src/styles/naive-theme.ts` |

## 编码约定

### 注释规范

允许写：

1. **模块级 docstring**：模块解决什么问题、对外契约（路由 / 入参 / 出参 / 事件）、
   非显然的设计取舍。仅在代码本身读不出来时写。
2. **函数 / 类 docstring**：一句话职责 + 必要的边界条件。后端函数（尤其 agent 与
   service）保留功能描述与调用链路说明，这是本项目唯一允许的注释密度。
3. **反直觉处的一句「为什么」**：例如某处必须写死 `width/height`、某处必须用
   `requestAnimationFrame` 复位防回环。一句话，不解释背景故事。
4. **被停用代码的备份块**：`services/pdf2json.py` 里 docling 旧实现以 `#` 注释保留，
   成块保留、不要打散删除。

禁止写：

- 逐行复述代码（`// 判断是否为空` 后跟 `if (!x)`）。
- 变更史、旧版本行为、调试过程、commit message 内容。
- `注意：` 开头的凑字数说明；真有坑就写清「为什么」。
- 在 `.vue` 的 `<template>` 里给每个区块贴标签式注释（`<!-- 头部 -->`）。模板结构
  本身已经足够清晰时一律不写。
- 前端（`smartcv-web`）默认**不写行内注释**；用户不熟悉前端，注释应集中在类型定义
  与模块入口的极少量说明上。

类型字段的含义写在类型定义处（JSDoc / `Field(description=...)`），不要在每个调用点重复。

### 后端

- 统一响应：`smartcv-api/schemas/response.py` 的 `ok()` / `error()`，前端用
  `smartcv-web/src/api/error.ts` 解包。
- 供应商配置：字段名前后端一致（`provider/baseUrl/apiKey/model`），后端零转换。
- 会话隔离：前端每个请求带 `X-Agent-Session-Id`（UUID7，见
  `smartcv-web/src/api/session.ts`），后端 `main.py` 中间件解析进 `request.state`，
  路由用 `smartcv-api/routers/deps.py::get_agent_session` 取。
- 简历 JSON 只有一份真相：`Section[]`。所有「把 JSON 拍平成文本 / 按坐标定位写回」
  必须走 `smartcv-api/agents/utils/resume.py`，不要在业务模块里另写一套。
- 坐标写作 `[s:章节 r:窗口 c:内容 i:文字单元]`，`i` 是文字单元序号。改文字只改单元，
  不动结构 / 样式 / 图片。
- LangChain `@tool` 的参数说明写在 `Annotated[..., Field(description=...)]`，
  docstring 不写 `Args:`（LangChain 不解析 docstring 的 Args 段）。
- 隐私约束：简历只在浏览器 localStorage；解析结果发完即删 `store`；检查点 sqlite
  每小时清理；只有用户主动使用 AI 功能时才外发内容（导入解析上传 MinerU，润色 / 对话
  / 市场洞察发往用户自配的模型服务商）。
- 市场洞察的提示词按阶段放在 `agents/resume/marker/prompts/<阶段>/*.md`，模块加载时
  读取；不要写进 Python 字符串。数据结构统一放 `schemas/market.py`，跨层只从这里取。
- 采集额度：`pagesPerDim` 按 `jobs` / `trend` / `other` 三类维度各配一份，
  `tools/collect.py::_dim_pages` 用 `pages_key` 折算成当前维度的页数；`urlsPerDim`
  是每个方向各自的上限。不要引入总预算再按权重切分。
- 抓取方式：所有 URL 统一走 `tools/fetch/` 的 `PageFetcher`（输入 `FetchRequest`，
  输出 `FetchResult`），具体实现由 `fetchMode` 决定；新增抓取方式只需实现子类并注册。
- 市场事件：节点统一发 `node.enter` / `node.exit`，采集发 `collect.*`，抽取发
  `extract.*`，报告发 `report.*`；抓取失败（无正文也无摘要）发 `collect.skip` 并带
  原因，不要混进 `collect.chunk`（箭头数必须等于已采页数）；错误事件 `fatal=false`
  只提示，不允许中断整条流水线。
- 来源适配器：新来源实现 `JobSourceAdapter`（网页型）或 `JobBoardAdapter`（结构化岗位）
  并注册；采集器只认 `SourcePage` / `JobPosting`，不要在 agent 里判断具体站点。
- 模拟面试的数据结构只放 `agents/resume/interview/schemas.py`；追问轮次、动态配额、
  下一题选择与问题包校验只放 `policy.py`，agent 与路由不要各写一套。
- 面试提示词按阶段放 `agents/resume/interview/prompts/<阶段>/*.md`，模块加载时读取；
  答案的事实边界写进提示词，同时由代码做数字 / 项目名校验。
- 面试检查点独立于 chat（`interview_checkpoints.sqlite`），按线程空闲 1h 清理；
  日志只记线程 id、动作、轮次与耗时，不打印简历全文、用户回答与参考答案。

### 前端

- 简历数据唯一来源是 `smartcv-web/src/stores/resume.ts` 的 `state.resume`，改动数据即
  同步视图。
- 分页一律走 `smartcv-web/src/utils/pagination.ts` 的「可裁切单元」模型，预览与导出
  共用同一份 `pagePlan`，否则导出页数与预览不一致。
- 后端返回的简历 JSON 不要经过 `normalizeResumeData`（会重生成 uid，导致 diff
  对不上、整份简历被判为全变）。
- AI 改稿结果先进 `pendingDiff`，由用户确认后才写回简历。
- 视觉规范见 `smartcv-web/src/styles/global.css` 的 Design Token 与
  `smartcv-web/src/styles/naive-theme.ts`；新页面沿用靛蓝主色 + 冷灰底，不引入新的
  配色体系。
- 市场洞察页只由 SSE 事件驱动：页签、流程节点、报告章节都以 `plan.result.dims` 为准
  动态重建；不要在前端写死维度 id 或章节数量。
- 调研结果快照存 `localStorage['smartcv-market-run']`，只用于刷新后恢复展示，
  不重连后端任务；开始新一轮时先清空快照。
- 补充网址以备份文件夹的 `market-sources.json` 为唯一真相，`marketSources` store
  负责读取 / 写回；备注必填，空备注不落库。
- 面试画像 / 问题包 / 参考答案 / 答题记录 / 最近 3 次摘要只进 IndexedDB
  `smartcv-interview`（`utils/interviewDb.ts`），localStorage 只放最近 threadId 等指针。
- 对话面试由 SSE 事件驱动展示，刷新后用 `GET /api/interview/state` 对齐当前题与 phase；
  前端不把整份问题包和历史回传给后端。

### 设计基调

靛蓝 `#4753c7` 主色、冷灰 `#f6f7f9` 底、纯白纸面、发丝线分界、少阴影。界面图标用
`smartcv-web/src/components/IconGlyph.vue`（手写 Lucide path，不依赖图标库）；品牌图标
来自 `simple-icons`，简历内容图标来自 `smartcv-web/src/data/icons.ts` 的 emoji / 内联
SVG。动效只在首屏做一次 staggered rise-in（0.55s，逐项 +0.06s），其余统一 0.16s
`var(--ease)` 过渡；不加玻璃拟态、渐变装饰、循环漂浮。禁忌：Notion 风、后台模板感、
四等大卡片、全大写眉标、字符箭头。

## 历史记忆

- 示例简历结构、渲染器能力边界（无行内 HTML、row 无 style、列宽等分）：
  `smartcv-api/example` + `smartcv-web/src/data/presets.ts`。
- 「优秀示例」是全局共享、只增不删、上传前二次确认的服务端持久化数据；
  诊断时把示例转成**不带坐标**的纯结构 Markdown 给诊断 agent，仅用于提炼写法。
- 市场洞察的结构化招聘来源（BOSS / 腾讯 / 华为）目前都是占位实现，返回空后 `jobs`
  如实上报 0 页并附 `reason`，不回退 SearXNG；接真实来源只需实现 `JobBoardAdapter` 并注册。
- 用户补充网址按 `jobs / trend / other` 三个方向归档，备注必填；一次结构化调用判定
  每条网址归到哪个维度、是否与本轮目标相关，`jobs` / `trend` 的标签模型不能改派。
- 市场调研的页面状态保存在浏览器 localStorage（`smartcv-market-run`），刷新可恢复；
  服务端任务与事件在内存里，15 分钟后过期。
