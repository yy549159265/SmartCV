#!/bin/bash
# smartcv.sh - 管理 SmartCV 前后端容器
# 用法: ./smartcv.sh {start|stop|restart|pull|status|logs|help}

set -e

# 仓库里的文件名是 docker-compose.yml（不是 .yaml）
COMPOSE_FILE="docker-compose.yml"
COMPOSE_CMD="docker compose"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查 docker compose 是否可用
check_docker() {
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}错误: docker 未安装或不在 PATH 中${NC}"
        exit 1
    fi
    if ! $COMPOSE_CMD version &> /dev/null; then
        echo -e "${RED}错误: docker compose 插件未安装或不可用${NC}"
        exit 1
    fi
}

# 检查 compose 文件是否存在
check_compose_file() {
    if [ ! -f "$COMPOSE_FILE" ]; then
        echo -e "${RED}错误: 找不到 $COMPOSE_FILE，请确保在正确的目录下执行${NC}"
        exit 1
    fi
}

# 启动容器（后台运行）
start() {
    check_docker
    check_compose_file
    echo -e "${GREEN}正在启动 SmartCV 服务...${NC}"
    $COMPOSE_CMD -f "$COMPOSE_FILE" up -d
    echo -e "${GREEN}启动完成。查看状态: ./smartcv.sh status${NC}"
}

# 停止容器
stop() {
    check_docker
    check_compose_file
    echo -e "${YELLOW}正在停止 SmartCV 服务...${NC}"
    $COMPOSE_CMD -f "$COMPOSE_FILE" down
    echo -e "${GREEN}已停止。${NC}"
}

# 重启容器
restart() {
    stop
    start
}

# 当前 compose 各服务镜像在本地对应的镜像 ID（去重；本地还没有的镜像跳过）
compose_image_ids() {
    $COMPOSE_CMD -f "$COMPOSE_FILE" config --images 2>/dev/null \
        | sort -u \
        | while read -r img; do
            docker image inspect --format '{{.Id}}' "$img" 2>/dev/null || true
        done \
        | sort -u
}

# 拉取最新镜像 → 用新镜像重建容器 → 删除被替换的旧镜像
# 注意顺序：必须先重建容器再删旧镜像，容器还在用旧镜像时 docker rmi 会拒绝。
pull() {
    check_docker
    check_compose_file

    # 拉之前先记下当前镜像 ID；pull 之后同 tag 的旧镜像会变成 <none>
    local old_ids
    old_ids=$(compose_image_ids)

    echo -e "${YELLOW}正在从远程仓库拉取最新镜像（searxng 来自 Docker Hub，国内可能较慢）...${NC}"
    $COMPOSE_CMD -f "$COMPOSE_FILE" pull

    echo -e "${YELLOW}正在用新镜像重建容器...${NC}"
    $COMPOSE_CMD -f "$COMPOSE_FILE" up -d

    echo -e "${YELLOW}正在清理被替换的旧镜像...${NC}"
    local new_ids id short removed=0
    new_ids=$(compose_image_ids)
    for id in $old_ids; do
        # 新镜像里还有这个 ID：说明本次没更新，保留
        if printf '%s\n' "$new_ids" | grep -qx "$id"; then
            continue
        fi
        short="${id#sha256:}"
        short="${short:0:12}"
        if docker rmi "$id" >/dev/null 2>&1; then
            echo -e "  已删除旧镜像 ${short}"
            removed=$((removed + 1))
        else
            echo -e "${YELLOW}  跳过 ${short}（仍被其他容器或 tag 使用）${NC}"
        fi
    done
    if [ "$removed" -eq 0 ]; then
        echo -e "  没有需要清理的旧镜像。"
    fi

    echo -e "${GREEN}完成：镜像已更新，容器已重启。${NC}"
}

# 查看容器状态
status() {
    check_docker
    check_compose_file
    $COMPOSE_CMD -f "$COMPOSE_FILE" ps
}

# 查看容器日志（可选跟服务名）
logs() {
    check_docker
    check_compose_file
    if [ -z "$1" ]; then
        $COMPOSE_CMD -f "$COMPOSE_FILE" logs --tail=100 -f
    else
        $COMPOSE_CMD -f "$COMPOSE_FILE" logs --tail=100 -f "$1"
    fi
}

# 显示帮助信息
usage() {
    cat << EOF
用法: $0 {start|stop|restart|pull|status|logs [service]|help}

命令说明:
  start           启动所有容器（后台运行，等同于 docker compose up -d）
  stop            停止所有容器（docker compose down）
  restart         重新启动所有容器（先 stop 再 start）
  pull            拉取最新镜像 → 用新镜像重建容器 → 删除被替换的旧镜像
                  （backend/frontend 走阿里云，searxng 走 Docker Hub）
  status          查看容器当前运行状态
  logs [service]  查看容器日志（可指定服务名: backend、frontend 或 searxng）
  help            显示此帮助信息

服务:
  backend         FastAPI 后端（8600）
  frontend        nginx 前端（5173）
  searxng         自建搜索，诊断 agent 的 web_search 用（仅本机 8080）
                  配置在 ./searxng/settings.yml，首次启动会自动生成其余默认配置

示例:
  $0 start
  $0 pull                 # 更新镜像并重启（不用再手动 restart）
  $0 logs backend
  $0 logs searxng
EOF
}

# 主入口
case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    pull)
        pull
        ;;
    status)
        status
        ;;
    logs)
        logs "$2"
        ;;
    help|--help|-h)
        usage
        ;;
    *)
        echo -e "${RED}未知命令: $1${NC}"
        usage
        exit 1
        ;;
esac

exit 0
