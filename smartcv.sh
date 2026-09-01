#!/bin/bash
# smartcv.sh - 管理 SmartCV 前后端容器
# 用法: ./smartcv.sh {start|stop|restart|pull|status|logs|help}

set -e

COMPOSE_FILE="docker-compose.yaml"
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

# 拉取最新镜像（从阿里云仓库）
pull() {
    check_docker
    check_compose_file
    echo -e "${YELLOW}正在从远程仓库拉取最新镜像...${NC}"
    $COMPOSE_CMD -f "$COMPOSE_FILE" pull
    echo -e "${GREEN}拉取完成。如需应用新镜像，请执行 restart。${NC}"
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
  pull            从阿里云镜像仓库拉取最新镜像
  status          查看容器当前运行状态
  logs [service]  查看容器日志（可指定服务名: backend 或 frontend）
  help            显示此帮助信息

示例:
  $0 start
  $0 logs backend
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
