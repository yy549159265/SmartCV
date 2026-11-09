# AGENT.md

>本文件是 SmartCV 仓库的 AI 协作总纲，任何 AI 代理改代码前先读本文件。
>正文代码路径相对仓库根目录（Markdown 链接除外）。详细设计见
>[SDD.md](SDD.md)，解析流水线见
>[PIPELINE.md](smartcv-api/agents/md2json/PIPELINE.md)。

## 一句话定位

SmartCV = AI 简历制作与优化工具。前端 Vue 3 + Vite + TS + Pinia + naive-ui
（`smartcv-web`），后端 FastAPI + LangGraph（`smartcv-api`）。整份简历只有一份
`Section[]` JSON，编辑 / 预览 / 导出 / AI 优化共用这一个数据结构。

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
   对话检查点 sqlite 仅临时保存，每小时清空。

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
                        deps.py（从 request.state 取会话 id）
  agents/
    md2json/            MinerU 产物 -> 简历 JSON：清洗 + 一次 LLM 结构化 + 代码排版
    resume/optimize/    LangGraph 流水线 convert -> diagnose -> review -> summarize
                        tools/patch_resume.py 实现 patch_content 与写回校验
    resume/grammar/     全文纠错：一次结构化调用 + 代码校验
    single/             单次 LLM：润色 / 增强 / 分析
    skill/              coordinate / diagnose / review 三份 SKILL.md（运行时按需加载）
    utils/resume.py     简历 JSON 文本化 / 坐标定位 / 写回的唯一实现
  services/             pdf2json（MinerU）| html2pdf（Playwright）| stats | reference_examples
  schemas/              provider（供应商配置）| response（统一 {code,message,data}）
  example/              内置示例简历 JSON + index.json
  data/                 服务端持久化数据（优秀示例库、导出计数），目录可用环境变量覆盖
smartcv-web/            Vue 3 + Vite + TS + Pinia + naive-ui 前端
  src/api/              后端接口封装（统一走 api/http.ts）
  src/components/       编辑器/预览/对比弹窗等组件
  src/pages/            Home / Editor / Review / ProviderSettings / ReferenceExamples
  src/stores/           resume（唯一数据源）/ documents / review / stats
  src/composables/      usePagination / usePageSize / usePreviewZoom / useSyncScroll 等
  src/utils/            pagination（可裁切单元模型）/ resumeDiff / layout / style / markdown / fs/
  src/types/            Section / LayoutWindow / Content 等类型定义
  src/styles/           global.css（Design Token）/ naive-theme.ts
  src/data/             presets / icons / heroResume
  scripts/              gen-example-index.mjs（生成 smartcv-api/example/index.json）
script/                 docker-compose.yml / searxng / smartcv.sh 等部署文件
```

## 启动与验证

```bash
# 后端（默认 9000；SMARTCV_API_PORT 同时控制 vite 代理，两端必须一致）
cd smartcv-api && uvicorn main:app --reload --port 9000

# 前端
cd smartcv-web && npm run dev        # http://localhost:5173，/api 代理到 127.0.0.1:9000

# 内置示例增删后重建清单
cd smartcv-web && npm run examples:index

# 提交前必须通过
cd smartcv-web && npm run typecheck   # vue-tsc -b
cd smartcv-web && npm run build       # vue-tsc -b && vite build
cd smartcv-api && python -m compileall .
```

后端本地默认端口与前端代理都取 `SMARTCV_API_PORT`（默认 9000）；Docker 后端镜像监听
8600，编排文件在 `script/docker-compose.yml`。后端没有测试框架，改完至少
`python -m compileall smartcv-api`（或导入 `main`）确认无语法/导入错误。

## 常见任务入口

| 任务 | 改哪里 |
|---|---|
| 加/改后端接口 | `smartcv-api/routers`，请求模型就近定义，响应走 `smartcv-api/schemas/response.py` |
| 改 AI 提示词 | `smartcv-api/agents/**/system_prompt*.md`、`smartcv-api/agents/single/*_prompt.md`、`smartcv-api/agents/skill/*/SKILL.md` |
| 改优化流水线 | `smartcv-api/agents/resume/optimize/graph.py`（编排）+ `diagnose_agent.py` / `review_agent.py` / `summarize_agent.py` + `tools/patch_resume.py`（`patch_content`） |
| 改前端接口调用 | `smartcv-web/src/api/*.ts`（统一走 `api/http.ts`） |
| 改编辑器 / 预览 | `smartcv-web/src/components`、`smartcv-web/src/pages/EditorPage.vue` |
| 改优化页交互 | `smartcv-web/src/pages/ReviewPage.vue` + `smartcv-web/src/stores/review.ts` |
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
  发往用户自配的模型服务商）。

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
