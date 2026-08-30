# SmartCV 前端镜像（Vite 构建 + nginx 托管）
# ============================================================================
# 构建上下文 = smartcv-web/（docker build -f smartcv-web/Dockerfile smartcv-web）
# 分两阶段：
#   1. build：Node 构建出静态产物 dist/
#   2. serve：nginx 托管静态文件，并把 /api 反向代理到后端容器 backend:8600
# ============================================================================

# ---- 1) 构建 ----
FROM node:20-alpine AS build
WORKDIR /app
# npm 用淘宝镜像（registry.npmmirror.com），国内装包快
ENV NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- 2) 托管 ----
FROM nginx:1.30
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
