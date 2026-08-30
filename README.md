<div align="center">

# 🧠 SmartCV

**AI 驱动的简历制作与优化工具**

`导入解析` `·` `可视化编辑` `·` `多 Agent 对话优化` `·` `导出 JSON / PDF`

<br />

<div>
  <img src="https://img.shields.io/badge/Vue-3-42b883?style=for-the-badge&logo=vuedotjs&logoColor=white" alt="Vue 3" />
  <img src="https://img.shields.io/badge/Vite-646cff?style=for-the-badge&logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/TypeScript-3178c6?style=for-the-badge&logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Python-3776ab?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/LangGraph-1e90ff?style=for-the-badge" alt="LangGraph" />
  <img src="https://img.shields.io/badge/LangChain-1c3c3c?style=for-the-badge&logo=langchain&logoColor=white" alt="LangChain" />
  <img src="https://img.shields.io/badge/SQLite-003b57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite" />
</div>

<br />
<br />

**从一份 PDF / Word 到「AI 智能优化」的一站式简历工具**，前端 Vue 3，后端 FastAPI + LangGraph 多 Agent，简历正文统一存一份 JSON，编辑、预览、优化三处共用同一数据源。

<br />

<sub>⚡ 前端代码全程由 AI 生成</sub>

</div>

---

## ✨ 功能特性

- **🗂 导入解析** — 上传 PDF / Word，docling 解析成结构化简历 JSON（章节/窗口/内容层级），进度可轮询。
- **🖌 可视化编辑** — 组件库拖拽排布（7 种内容类型 + 命名预设），右侧实时预览 A4 成品，红线分页。
- **🤖 AI 优化对话** — SSE 流式。诊断 → 按坐标就地改 JSON → 摘要，全程展示「思考过程 / 工具调用 / 回答」。
  - **按坐标改**：`patch_content(s, r, c, i, text)` 只替换文字、不增删结构，排版永远不乱。
  - **全过程可见**：`agent_start / delta(thinking|answer) / tool_call / tool_result / agent_end` 全量推成事件，前端分卡片展示。
- **📤 导出** — JSON 文件；PDF（后端无头 Chromium 打印，与预览排版一致）。

## 🧱 技术栈

| 端 | 技术 |
|---|---|
| 前端 | Vue 3 · Vite · Pinia · VueUse · naive-ui · vue-draggable-plus |
| 后端 | FastAPI · Pydantic · LangGraph · LangChain（OpenAI 兼容 / DeepSeek） |
| Agent | 多 Agent：解析（md2json）、诊断、优化、摘要、润色 |
| 持久化 | SQLite checkpoint（LangGraph）· SSE · UUID7 会话 id |
| 派生服务 | docling（PDF 解析）· Playwright（HTML→PDF） |

## 📁 目录结构

```text
SmartCV
├── smartcv-api/            # 后端 FastAPI（接口都写在 main.py）
│   ├── main.py             # 应用入口 + 全部接口 + 定时清理任务
│   ├── agents/             # 多 Agent
│   │   ├── md2json/        #   解析 Agent
│   │   ├── optimize/       #   诊断 / 优化 / 摘要 + graph + checkpointer
│   │   ├── polish/         #   润色 Agent
│   │   ├── skill/          #   可按需加载的技能（SKILL.md）
│   │   └── utils/          #   choose_llm、skillmiddleware
│   ├── services/           # pdf2json（解析）、html2pdf（导出）
│   ├── schemas/            # provider、response（统一 {code,message,data}）
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .dockerignore
├── smartcv-web/            # 前端 Vue 3
│   ├── src/
│   │   ├── pages/          # 主页 / 编辑简历 / 优化简历 / Agent 设置
│   │   ├── stores/         # resume（简历 JSON）、optimize（对话）
│   │   ├── api/            # 各接口封装
│   │   └── components/     # 编辑 / 预览组件
│   ├── Dockerfile
│   ├── nginx.conf          # 托管静态 + /api 反向代理
│   └── .dockerignore
├── docker-compose.yml
└── docs/                   # 技术文档（backend-agents.md 等）
```

## 🚀 快速开始

> 前置：Python 3.14+（后端）、Node 18+（前端）。

```bash
# 1) 后端
cd smartcv-api
python -m pip install -r requirements.txt
python -m playwright install chromium        # 导出 PDF 用
uvicorn main:app --port 8600                  # 端口 8600（8000 在 Windows 预留端口段里）

# 2) 前端（另开一个终端）
cd smartcv-web
npm install
npm run dev                                   # http://localhost:5173，/api 自动代理到 8600
```

> 若后端机器连不上 huggingface.co，`main.py` 已默认把 `HF_ENDPOINT` 指到 `https://hf-mirror.com` 下载 docling 模型。

## 🐳 Docker 部署

前后端各一个镜像，用 compose 一键编排：

```bash
docker compose up -d --build
```

- 前端 `http://localhost:5173`（nginx 托管静态文件，`/api` 反向代理到后端容器）。
- 后端 `http://localhost:8600`（可直接访问接口）。

> 首次构建较慢（后端 docling / playwright 依赖大）；首次解析会从 HF 镜像下模型。检查点 sqlite 在容器内 `/app`，容器重建即重置（它本就会每小时被清空，属临时态）。

## 🖥️ 使用流程

1. **主页** — 导入 PDF / Word / JSON，或新建空白简历。
2. **编辑简历** — 右侧实时预览 A4 成品，组件库拖拽排版。
3. **优化简历** — 右侧 AI 对话栏输入要求，左侧「当前简历」按 A4 分页显示；对话流式展示诊断思考 → 优化改稿 → 摘要回答。
4. **Agent 设置** — 左侧标签页：「供应商设置」（配模型）、「md预览」（只读查看后端提示词与技能）。

## 🔌 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/resume/parse` | 上传 PDF/Word → 简历 JSON（章节数组） |
| GET | `/api/resume/parse/status` | 轮询解析进度（按 `X-Agent-Session-Id`） |
| POST | `/api/resume/pdf` | HTML → 导出 PDF 文件 |
| POST | `/api/polish` | 批量润色列表文本 |
| POST | `/api/chat` | 优化对话（**SSE 流式**），改好的简历 JSON 一并返回 |
| GET | `/api/agent/md` | 返回后端 agent 的提示词与技能 md（只读） |

## 📖 更多文档

- [后端 Agent 技术文档](docs/backend-agents.md) — 流程、事件、工具、坐标、技能、检查点、流式实现。

---

<div align="center">
  <sub>前端代码全程由 AI 生成 · Made with ❤️</sub>
</div>
