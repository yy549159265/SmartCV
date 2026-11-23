<div align="center">

# 🧠 SmartCV

**AI 驱动的简历制作与优化工具**：导入 PDF / Word，可视化编辑，多 Agent 对话优化，导出 JSON / PDF。

<br />

<img src="https://img.shields.io/badge/Vue-3-42b883?style=for-the-badge&logo=vuedotjs&logoColor=white" alt="Vue 3" />
<img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
<img src="https://img.shields.io/badge/LangGraph-1e90ff?style=for-the-badge" alt="LangGraph" />

</div>

> 🔒 简历只存在你自己的浏览器本地，后端不存档；只有你主动使用 AI 时，内容才会发给你自己配置的模型服务商。

## 🚀 快速开始

需要 Python 3.12+ 和 Node 18+。

**1. 启动后端**（终端一）

```bash
cd smartcv-api
pip install -r requirements.txt
playwright install chromium        # 导出 PDF 需要
uvicorn main:app --port 8700
```

**2. 启动前端**（终端二）

```bash
cd smartcv-web
npm install
npm run dev
```

**3. 打开浏览器**

访问 http://localhost:5173 ，在「Agent 设置」里填入你自己的模型 API Key 即可开始。

> Playwright 下载慢时，先执行 `export PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright` 再安装。

## 🐳 Docker 部署

镜像已发布到阿里云公开仓库，服务器上不需要源码，也不需要登录：

```bash
cd script
docker compose up -d
```

启动后访问 **https://localhost**（自签证书，首次需信任 `smartcv-web/certs/smartcv-ca.crt`）。

`docker-compose.yml` 中一共 5 个服务：

| 服务 | 作用 | 地址 |
|---|---|---|
| `frontend` | 前端页面（nginx + HTTPS） | https://localhost |
| `backend` | 后端 API | http://localhost:8600 |
| `asr` | 语音输入识别 | 仅本机 6006，经 nginx `/asr` 转发 |
| `searxng` | 自建搜索，供 AI 查资料 | 仅本机 8088 |
| `valkey` | searxng 的缓存 | 容器内网 |

数据持久化在服务器 `/opt/smartcv/{backend,frontend,searxng}` 下。停止：`docker compose down`。
