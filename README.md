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

- **🗂 导入解析** — 上传 PDF / Word，AI 解析成结构化简历 JSON，进度实时可见。
- **🖌 可视化编辑** — 组件拖拽排版，右侧实时预览 A4 成品。
- **🤖 AI 优化对话** — 流式对话，诊断 → 改稿 → 摘要，思考过程与工具调用全程展示。
- **📤 导出** — JSON 文件，或导出与预览排版一致的 PDF。

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

## 🐳 Docker 部署

### 方式一：拉镜像（推荐）

镜像已推送到阿里云 ACR 公开仓库，无需登录、无需克隆源码：

```bash
docker compose up -d                    # 一键起前后端
```

| 服务 | 镜像 | 访问 |
|---|---|---|
| 前端 `frontend` | `registry.cn-hangzhou.aliyuncs.com/smartcv/smartcv-frontend:v1` | http://localhost:5173 |
| 后端 `backend` | `registry.cn-hangzhou.aliyuncs.com/smartcv/smartcv-backend:v1` | http://localhost:8600 |

停止：`docker compose down`。

### 方式二：源码构建

```bash
docker build -t 镜像名称:版本号  smartcv-api/
docker build -t 镜像名称:版本号  smartcv-web/
```

推送自己的仓库：

```bash
docker tag 镜像名称:版本号 <你的仓库地址>/镜像名称:版本号
docker push <你的仓库地址>/镜像名称:版本号
```

> 首次构建 / 拉取较慢属正常；后端镜像较大（含 Playwright Chromium 与 LangChain 全家桶）。

## 🔒 隐私与数据安全

SmartCV **不收集你的任何数据**：

- **简历数据只存在你自己的浏览器本地**（localStorage，刷新 / 关闭页面都不丢）。没有账号系统，也没有云端存档、埋点或使用统计。
- **后端不落库存档**：你上传的文档和简历内容只做「当前这次」的临时处理（解析 / 优化），处理完即用即丢；对话检查点数据每小时自动清理。
- **只有你主动使用 AI 功能时，内容才会离开你的电脑**：
  - **导入解析**：使用 `MinerU` 云解析，会把文档上传到 MinerU 服务。
  - **AI 优化对话 / 润色**：简历内容会发送到你在「Agent 设置」里自己填写的模型服务商（如 DeepSeek / GLM / 通义等）。
- **API Key 只存在你自己的浏览器里**，仅用于你发起请求时调用你填写的服务商接口；后端不存储、也不用作任何其它用途。
- **会话状态按「浏览器」隔离，而非按标签页**：SmartCV 用浏览器本地存储记录当前会话，同一个浏览器（同一站点）的所有标签页共用同一个会话标记，且不会随新开标签页 / 窗口而变化。因此：
  - 在同一浏览器里**多开标签页**同时「解析 / 对话」时，后发起的请求会覆盖前一个的会话状态（如解析进度），可能出现两个标签页互相串进度的现象——建议避免同一浏览器多标签同时操作。
  - **多人共用同一台电脑 / 同一浏览器**时也会共享同一会话状态；建议各自使用独立浏览器或无痕窗口，避免读到对方的操作。
