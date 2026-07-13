#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# Qt+Rviz 地面站启动脚本
# ------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
PID_DIR="$LOG_DIR/pids"
ROSCORE_LOG="$LOG_DIR/roscore.log"
BROKER_LOG="$LOG_DIR/mosquitto-start.log"
STATION_LAUNCH_LOG="$LOG_DIR/station.launch.log"
BRIDGE_LOG="$LOG_DIR/bridge.log"
STATION_LAUNCH_PID_FILE="$PID_DIR/station.launch.pid"
BRIDGE_PID_FILE="$PID_DIR/bridge.pid"
FRONTEND_PID_FILE="$PID_DIR/qt_frontend.pid"

mkdir -p "$LOG_DIR" "$PID_DIR"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_green()  { echo -e "${GREEN}[OK]${NC} $1"; }
echo_fail()   { echo -e "${RED}[FAIL]${NC} $1"; }
echo_warn()   { echo -e "${YELLOW}[WARN]${NC} $1"; }

STATION_LAUNCH_PID=""
BRIDGE_PID=""
FRONTEND_PID=""
CLEANED_UP=0

stop_child_process() {
    local pid="$1"
    local name="$2"

    if [ -z "$pid" ]; then
        return
    fi

    if kill -0 "$pid" 2>/dev/null; then
        echo_warn "Stopping $name pid=$pid"
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    fi
}

cleanup() {
    if [ "$CLEANED_UP" -eq 1 ]; then
        return
    fi
    CLEANED_UP=1

    echo ""
    echo "正在清理地面站本地进程..."
    stop_child_process "$FRONTEND_PID" "Qt frontend"
    stop_child_process "$BRIDGE_PID" "MQTT-ROS bridge"
    stop_child_process "$STATION_LAUNCH_PID" "station launch"
    rm -f "$FRONTEND_PID_FILE" "$BRIDGE_PID_FILE" "$STATION_LAUNCH_PID_FILE"
    echo "清理完成。"
}

trap cleanup EXIT
trap 'exit 130' SIGINT
trap 'exit 143' SIGTERM

# ------------------------------------------------------------------
# 1. Python 版本检查
# ------------------------------------------------------------------
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_MINOR" -lt 8 ]; then
    echo_fail "Python >= 3.8 required, found: $(python3 --version)"
    exit 1
fi
echo_green "Python $(python3 --version)"
echo_green "Background logs: $LOG_DIR"

# ------------------------------------------------------------------
# 2. Source ROS setup
# 新地面站终端通常不会提前 source ROS，这里先准备 rostopic/roslaunch 等命令环境。
# ------------------------------------------------------------------
# 默认使用 ROS Noetic 标准安装路径；非标准环境可通过 ROS_SETUP 覆盖。
ROS_SETUP="${ROS_SETUP:-/opt/ros/noetic/setup.bash}"
if [ -f "$ROS_SETUP" ]; then
    source "$ROS_SETUP"
    echo_green "ROS Noetic sourced"
else
    echo_fail "ROS Noetic setup not found: $ROS_SETUP"
    exit 1
fi

# ------------------------------------------------------------------
# 3. librviz_widget.so 检查
# ------------------------------------------------------------------
SO_PATH="$PROJECT_ROOT/qt_frontend/native/build/librviz_widget.so"
if [ ! -f "$SO_PATH" ]; then
    echo_fail "librviz_widget.so not found at $SO_PATH"
    echo "  Build it: cd qt_frontend/native && mkdir -p build && cd build && cmake .. && make -j\$(nproc)"
    exit 1
fi

# 验证可加载
python3 -c "
import ctypes
try:
    lib = ctypes.CDLL('$SO_PATH')
    assert lib.create_rviz_widget is not None
except Exception as e:
    print(f'FAIL: {e}')
    exit(1)
" 2>/dev/null
echo_green "librviz_widget.so OK"

# ------------------------------------------------------------------
# 4. roscore 检查 + 自动启动
# ------------------------------------------------------------------
if ! command -v rostopic &>/dev/null; then
    echo_fail "rostopic not found after sourcing ROS setup."
    exit 1
fi

if ! rostopic list &>/dev/null; then
    echo_warn "roscore is not running. Starting..."
    roscore > "$ROSCORE_LOG" 2>&1 &
    sleep 3
    if ! rostopic list &>/dev/null; then
        echo_fail "Failed to start roscore. See: $ROSCORE_LOG"
        exit 1
    fi
fi
echo_green "roscore OK"

# ------------------------------------------------------------------
# 5. Mosquitto Broker 检查
# ------------------------------------------------------------------
if ! pgrep -x mosquitto >/dev/null 2>&1; then
    echo_warn "Mosquitto broker is not running. Starting..."
    if [ -f "$PROJECT_ROOT/broker/start.sh" ]; then
        bash "$PROJECT_ROOT/broker/start.sh" > "$BROKER_LOG" 2>&1 &
        sleep 2
    else
        mosquitto -d
        sleep 1
    fi
fi

if pgrep -x mosquitto >/dev/null 2>&1; then
    echo_green "Mosquitto broker running"
else
    echo_fail "Failed to start Mosquitto broker. See: $BROKER_LOG"
    exit 1
fi

# ------------------------------------------------------------------
# 6. transmit_config.yaml 检查
# ------------------------------------------------------------------
CONFIG_PATH="$PROJECT_ROOT/qt_frontend/config/transmit_config.yaml"
if [ ! -f "$CONFIG_PATH" ]; then
    echo_warn "transmit_config.yaml not found, creating default"
    echo "robots: {}" > "$CONFIG_PATH"
fi
echo_green "transmit_config.yaml OK"

# ------------------------------------------------------------------
# 7. 静态 TF（通过 launch 文件）
# ------------------------------------------------------------------
roslaunch "$PROJECT_ROOT/qt_frontend/launch/station.launch" > "$STATION_LAUNCH_LOG" 2>&1 &
STATION_LAUNCH_PID=$!
echo "$STATION_LAUNCH_PID" > "$STATION_LAUNCH_PID_FILE"
sleep 1
echo_green "Station launch PID: $STATION_LAUNCH_PID (log: $STATION_LAUNCH_LOG)"

# ------------------------------------------------------------------
# 8. 启动 bridge（后台）
# ------------------------------------------------------------------
echo_green "Starting MQTT-ROS bridge..."
cd "$PROJECT_ROOT"
python3 -m bridge.mqtt_ros_bridge > "$BRIDGE_LOG" 2>&1 &
BRIDGE_PID=$!
echo "$BRIDGE_PID" > "$BRIDGE_PID_FILE"
sleep 2

if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
    echo_fail "Bridge failed to start. See: $BRIDGE_LOG"
    exit 1
fi
echo_green "Bridge PID: $BRIDGE_PID (log: $BRIDGE_LOG)"

# ------------------------------------------------------------------
# 9. 启动 Qt 前端
# Qt 仍然作为主进程等待；额外写入 PID，方便 stop.sh 从另一个终端停止。
# ------------------------------------------------------------------
echo_green "Starting Qt frontend..."
cd "$PROJECT_ROOT"
python3 qt_frontend/main.py &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"

FRONTEND_EXIT=0
wait "$FRONTEND_PID" || FRONTEND_EXIT=$?
exit "$FRONTEND_EXIT"
