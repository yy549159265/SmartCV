# SmartCV SDD（Spec-Driven Design）

> 本文件是 SmartCV 的设计总纲：从需求到实现的可追溯说明。改动涉及接口、数据结构、
> Agent 流水线或隐私边界时，先改本文件再改代码。文中代码路径均相对仓库根目录。
> 配套文件：[AGENT.md](AGENT.md)（AI 协作与注释规范）、
> [PIPELINE.md](smartcv-api/agents/md2json/PIPELINE.md)（解析流水线细节）。

## 1. 目标与非目标

### 目标

1. 把一份 PDF / Word 简历变成可结构化编辑的 JSON，并保证排版不崩。
2. 让用户用「对话」而不是「改文档」来优化简历，且 AI **不得编造事实**。
3. 编辑、预览、导出三处的排版必须一致（页数一致、分页位置一致）。
4. 隐私优先：简历不落服务端库，API Key 只在浏览器。

### 非目标

- 不做账号体系、云存档、多端同步（会破坏 `localStorage` 单机模型）。
- 不做自由画布（简历是线性文档，用「章节 → 布局窗口 → 内容」三层替代）。
- 不让模型负责排版：排版由确定性代码完成，保证同一输入同一输出。
- 不做富文本（内容走 Markdown 子集，`html: false` 防 XSS）。

## 2. 系统总览

```
┌─────────────────── 浏览器（唯一数据持有方）───────────────────┐
│ Vue 3 + Pinia + naive-ui                                      │
│   stores/resume.ts   ← Section[] 唯一真相（localStorage）      │
│   stores/documents.ts← IndexedDB 文件句柄 + localStorage 索引   │
│   pages/Home  Editor  Review  ReferenceExamples  Provider      │
└──────────────┬────────────────────────────────────────────────┘
               │ /api/*（dev 走 vite proxy，生产走 nginx）
┌──────────────▼────────────────────────────────────────────────┐
│ FastAPI                                                        │
│   main.py       lifespan / 会话中间件 / 统一错误包装 / 路由注册 │
│   routers/      business.py | agent.py                         │
│   services/     pdf2json | html2pdf | stats | reference_examples│
│   agents/       md2json | resume/{optimize,grammar} | single   │
└──────────────┬────────────────────────────────────────────────┘
               │
   MinerU 云解析 │ 用户自配 LLM（OpenAI 兼容）│ SearXNG（自建搜索）
```

关键约束：**服务端无状态**。除「优秀示例库」「导出计数」「LangGraph 检查点（1h 清理）」
外，后端不保存任何用户数据。

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
| POST | `/api/chat` | SSE 流式优化对话，见 4.3 |
| POST | `/api/chat/answer` | 回答诊断 agent 的反问；404 任务过期 / 409 已答或 id 不符 |

### 4.3 `/api/chat` SSE 事件

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

## 6. 前端架构

```
pages/        页面级：HomePage / EditorPage / ReviewPage / ProviderSettingsPage / ReferenceExamplesPage
  ↑ 通过 App.vue 的 currentPage 切换（无 vue-router）
components/   编辑画布、章节卡、布局窗口、内容卡、预览、对比弹窗、图标选择器…
stores/       resume（唯一数据源 + 撤销重做 + 分页方案）/ documents（本地备份）/ review（对话时间线）/ stats
composables/  usePagination（测量 + 计算）/ usePageSize / usePreviewZoom / useSyncScroll / useClickPopover…
utils/        pagination / resumeDiff / layout / style / markdown / fs/（备份文件夹读写）…
types/        Section / LayoutWindow / Content / 样式等类型定义
styles/       global.css（Design Token）/ naive-theme.ts（naive-ui 主题）
api/          每个后端接口一个模块，统一走 api/http.ts
data/         presets（组件库预设）/ icons（品牌 + emoji）/ heroResume（首页演示）
scripts/      （smartcv-web/scripts）gen-example-index.mjs（生成 smartcv-api/example/index.json）
```

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

## 7. 隐私与安全

| 数据 | 存放位置 | 生命周期 |
|---|---|---|
| 简历 JSON | 浏览器 localStorage | 用户清除前一直在 |
| 简历文件（备份） | 用户自选本地文件夹（File System Access API，句柄存 IndexedDB） | 用户管理 |
| 解析中间结果 | 后端内存 `PDF2ResumeStore` | 请求结束即删 |
| 对话检查点 | 服务端 sqlite | 每小时清空 |
| 优秀示例库 | 服务端 `data/reference-examples`（`SMARTCV_REFERENCE_DIR`） | 永久（只增不删，全局共享） |
| 导出计数 | 服务端 `data/stats.json`（`SMARTCV_STATS_FILE`） | 永久 |
| API Key | 浏览器 localStorage | 用户清除前一直在 |

- 只有用户主动触发 AI 功能时内容才离开本机（MinerU 解析 / 用户自配模型服务商）。
- 诊断需要外部资料时，`web_search` 只把检索词发往自建 SearXNG（可能再转发上游搜索引擎），
  不发送整份简历。
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
| 后端无自动化测试 | 仅编译/构建校验 | 优先补 `agents/utils/resume.py` 与分页的纯函数测试 |

## 10. 变更检查清单

改代码前自问：

1. 是否触碰了 `Section[]` 结构？→ 同步 `types/index.ts`、`presets.ts`、`resume.py` 文字单元映射、
   渲染组件、示例 JSON。
2. 是否新增接口？→ 更新本文件第 4 节 + `src/api/*.ts` + 统一响应格式。
3. 是否改了 AI 行为？→ 更新提示词 md，并在第 5 节说明约束（尤其「不得新增事实」）。
4. 是否影响分页？→ 预览与导出必须同时验证页数。
5. 是否新增注释？→ 对照 AGENT.md「注释规范」。
6. 提交前跑 `npm run typecheck && npm run build` 与后端 `compileall`。
