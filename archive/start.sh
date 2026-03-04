#!/bin/bash
# EAI日志监听服务 - Linux启动脚本
# 用于生产环境(165服务器)部署

set -e

# 配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="eai_log_monitor"
PID_FILE="$SCRIPT_DIR/$SERVICE_NAME.pid"
LOG_FILE="$SCRIPT_DIR/eai_monitor.log"
PYTHON_CMD="python3"

# 设置环境变量
export EAI_MONITOR_ENV=production

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查Python环境
check_python() {
    if ! command -v $PYTHON_CMD &> /dev/null; then
        print_error "未找到Python3，请先安装"
        exit 1
    fi
    print_info "Python版本: $($PYTHON_CMD --version)"
}

# 安装依赖
install_deps() {
    print_info "检查依赖包..."
    cd "$SCRIPT_DIR"
    $PYTHON_CMD -m pip install -r requirements.txt -q
    print_info "依赖安装完成"
}

# 启动服务
start() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            print_warn "服务已在运行中 (PID: $PID)"
            return 1
        fi
        rm -f "$PID_FILE"
    fi

    print_info "启动EAI日志监听服务..."
    cd "$SCRIPT_DIR"

    # 后台启动
    nohup $PYTHON_CMD eai_log_monitor.py >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    sleep 2
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            print_info "服务启动成功 (PID: $PID)"
            print_info "日志文件: $LOG_FILE"
            return 0
        fi
    fi

    print_error "服务启动失败，请查看日志"
    return 1
}

# 停止服务
stop() {
    if [ ! -f "$PID_FILE" ]; then
        print_warn "服务未运行"
        return 0
    fi

    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        print_info "停止服务 (PID: $PID)..."
        kill "$PID"

        # 等待进程退出
        for i in {1..10}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done

        if kill -0 "$PID" 2>/dev/null; then
            print_warn "强制终止进程..."
            kill -9 "$PID"
        fi
    fi

    rm -f "$PID_FILE"
    print_info "服务已停止"
}

# 重启服务
restart() {
    stop
    sleep 2
    start
}

# 查看状态
status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            print_info "服务运行中 (PID: $PID)"

            # 显示进程信息
            echo ""
            ps -p "$PID" -o pid,ppid,%cpu,%mem,etime,cmd
            return 0
        fi
    fi

    print_warn "服务未运行"
    return 1
}

# 查看日志
logs() {
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        print_warn "日志文件不存在"
    fi
}

# 查看最近日志
logs_recent() {
    if [ -f "$LOG_FILE" ]; then
        tail -n 100 "$LOG_FILE"
    else
        print_warn "日志文件不存在"
    fi
}

# 前台运行（调试用）
run() {
    print_info "前台运行服务（调试模式）..."
    cd "$SCRIPT_DIR"
    $PYTHON_CMD eai_log_monitor.py
}

# 帮助信息
usage() {
    echo "EAI日志监听服务管理脚本"
    echo ""
    echo "用法: $0 {start|stop|restart|status|logs|logs-recent|run|install}"
    echo ""
    echo "命令说明:"
    echo "  start       后台启动服务"
    echo "  stop        停止服务"
    echo "  restart     重启服务"
    echo "  status      查看服务状态"
    echo "  logs        实时查看日志"
    echo "  logs-recent 查看最近100条日志"
    echo "  run         前台运行（调试用）"
    echo "  install     安装依赖包"
    echo ""
}

# 主逻辑
case "$1" in
    start)
        check_python
        start
        ;;
    stop)
        stop
        ;;
    restart)
        check_python
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    logs-recent)
        logs_recent
        ;;
    run)
        check_python
        run
        ;;
    install)
        check_python
        install_deps
        ;;
    *)
        usage
        exit 1
        ;;
esac
