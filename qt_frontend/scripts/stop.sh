#!/usr/bin/env bash
set -euo pipefail

# 停止地面站本地进程。
# 这里只处理 Qt 前端、MQTT-ROS Bridge 和地面站 station.launch。
# 不停止 roscore、rosmaster 或 Mosquitto，因为它们可能被 Gazebo、仿真容器或其他 ROS 程序复用。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOG_DIR="$PROJECT_ROOT/logs"
DEFAULT_PID_DIR="$LOG_DIR/pids"
PID_DIR="${PID_DIR:-$DEFAULT_PID_DIR}"

FRONTEND_PID_FILE="$PID_DIR/qt_frontend.pid"
BRIDGE_PID_FILE="$PID_DIR/bridge.pid"
STATION_LAUNCH_PID_FILE="$PID_DIR/station.launch.pid"

cmdline_matches() {
    local pid="$1"
    local pattern="$2"
    local cmdline_path="/proc/$pid/cmdline"

    if [ ! -r "$cmdline_path" ]; then
        return 1
    fi

    local cmdline
    cmdline="$(tr '\0' ' ' < "$cmdline_path")"
    [[ "$cmdline" == *"$pattern"* ]]
}

process_is_alive() {
    local pid="$1"
    local stat_path="/proc/$pid/stat"

    if ! kill -0 "$pid" >/dev/null 2>&1; then
        return 1
    fi

    if [ -r "$stat_path" ]; then
        local state
        state="$(awk '{print $3}' "$stat_path")"
        if [ "$state" = "Z" ]; then
            return 1
        fi
    fi

    return 0
}

stop_from_pid_file() {
    local name="$1"
    local pid_file="$2"
    local pattern="$3"

    if [ ! -f "$pid_file" ]; then
        return 1
    fi

    local pid
    pid="$(cat "$pid_file")"
    if [ -z "$pid" ]; then
        echo "[地面站] $name PID 文件为空，删除: $pid_file"
        rm -f "$pid_file"
        return 0
    fi

    if ! process_is_alive "$pid"; then
        echo "[地面站] $name 进程不存在，删除过期 PID 文件: $pid_file"
        rm -f "$pid_file"
        return 0
    fi

    if ! cmdline_matches "$pid" "$pattern"; then
        echo "[地面站] pid=$pid 不像地面站进程，删除过期 PID 文件但不杀进程: $pid_file"
        rm -f "$pid_file"
        return 0
    fi

    echo "[地面站] 停止 $name pid=$pid"
    kill "$pid" >/dev/null 2>&1 || true

    for _ in $(seq 1 10); do
        if ! process_is_alive "$pid"; then
            rm -f "$pid_file"
            return 0
        fi
        sleep 1
    done

    echo "[地面站] $name pid=$pid 未在 10 秒内退出，发送 SIGKILL"
    kill -9 "$pid" >/dev/null 2>&1 || true
    rm -f "$pid_file"
}

stop_from_pid_file "Qt 前端" "$FRONTEND_PID_FILE" "qt_frontend/main.py" || true
stop_from_pid_file "MQTT-ROS Bridge" "$BRIDGE_PID_FILE" "bridge.mqtt_ros_bridge" || true
stop_from_pid_file "station launch" "$STATION_LAUNCH_PID_FILE" "qt_frontend/launch/station.launch" || true

if [ "$PID_DIR" = "$DEFAULT_PID_DIR" ]; then
    # 兼容旧版 start.sh 启动但没有 PID 文件的进程；只作为兜底清理。
    pkill -f "qt_frontend/main.py" 2>/dev/null || true
    pkill -f "mqtt_ros_bridge" 2>/dev/null || true
    pkill -f "qt_frontend/launch/station.launch" 2>/dev/null || true
    pkill -f "static_transform_publisher" 2>/dev/null || true
fi

echo "[地面站] 本地前端链路已停止。"
