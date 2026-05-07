#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------------
# Qt+Rviz 地面站启动脚本
# ------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_green()  { echo -e "${GREEN}[OK]${NC} $1"; }
echo_fail()   { echo -e "${RED}[FAIL]${NC} $1"; }
echo_warn()   { echo -e "${YELLOW}[WARN]${NC} $1"; }

# ------------------------------------------------------------------
# 1. Python 版本检查
# ------------------------------------------------------------------
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')
if [ "$PYTHON_MINOR" -lt 8 ]; then
    echo_fail "Python >= 3.8 required, found: $(python3 --version)"
    exit 1
fi
echo_green "Python $(python3 --version)"

# ------------------------------------------------------------------
# 2. librviz_widget.so 检查
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
# 3. roscore 检查 + 自动启动
# ------------------------------------------------------------------
if ! command -v rostopic &>/dev/null; then
    echo_fail "rostopic not found. Source ROS setup first."
    exit 1
fi

if ! rostopic list &>/dev/null; then
    echo_warn "roscore is not running. Starting..."
    roscore &
    sleep 3
    if ! rostopic list &>/dev/null; then
        echo_fail "Failed to start roscore"
        exit 1
    fi
fi
echo_green "roscore OK"

# ------------------------------------------------------------------
# 4. Mosquitto Broker 检查
# ------------------------------------------------------------------
if ! pgrep -x mosquitto >/dev/null 2>&1; then
    echo_warn "Mosquitto broker is not running. Starting..."
    if [ -f "$PROJECT_ROOT/broker/start.sh" ]; then
        bash "$PROJECT_ROOT/broker/start.sh" &
        sleep 2
    else
        mosquitto -d
        sleep 1
    fi
fi

if pgrep -x mosquitto >/dev/null 2>&1; then
    echo_green "Mosquitto broker running"
else
    echo_fail "Failed to start Mosquitto broker"
    exit 1
fi

# ------------------------------------------------------------------
# 5. transmit_config.yaml 检查
# ------------------------------------------------------------------
CONFIG_PATH="$PROJECT_ROOT/qt_frontend/config/transmit_config.yaml"
if [ ! -f "$CONFIG_PATH" ]; then
    echo_warn "transmit_config.yaml not found, creating default"
    echo "robots: {}" > "$CONFIG_PATH"
fi
echo_green "transmit_config.yaml OK"

# ------------------------------------------------------------------
# 6. Source ROS setup
# ------------------------------------------------------------------
ROS_SETUP="/opt/ros/noetic/setup.bash"
if [ -f "$ROS_SETUP" ]; then
    source "$ROS_SETUP"
    echo_green "ROS Noetic sourced"
fi

# ------------------------------------------------------------------
# 7. 启动 bridge（后台）
# ------------------------------------------------------------------
echo_green "Starting MQTT-ROS bridge..."
cd "$PROJECT_ROOT"
python3 -m bridge.mqtt_ros_bridge &
BRIDGE_PID=$!
sleep 2

if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
    echo_fail "Bridge failed to start"
    exit 1
fi
echo_green "Bridge PID: $BRIDGE_PID"

# ------------------------------------------------------------------
# 8. 启动 Qt 前端（前台）
# ------------------------------------------------------------------
echo_green "Starting Qt frontend..."
cleanup() {
    echo ""
    echo "Shutting down..."
    kill "$BRIDGE_PID" 2>/dev/null || true
    wait "$BRIDGE_PID" 2>/dev/null || true
    echo "Done."
}
trap cleanup SIGINT SIGTERM

cd "$PROJECT_ROOT"
python3 qt_frontend/main.py

cleanup
