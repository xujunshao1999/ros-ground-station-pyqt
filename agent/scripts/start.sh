#!/usr/bin/env bash
set -euo pipefail

# 物理机器人端 ROS1 Agent 启动脚本。
# 默认从 agent/config.yaml 读取 robot_id、broker_host、broker_port 和订阅配置。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_PATH="${CONFIG_PATH:-$PROJECT_ROOT/agent/config.yaml}"
ROBOT_WS_SETUP="${ROBOT_WS_SETUP:-$HOME/catkin_ws/devel/setup.bash}"
PID_FILE="${PID_FILE:-$PROJECT_ROOT/logs/agent.pid}"
LOG_FILE="${LOG_FILE:-$PROJECT_ROOT/logs/agent.log}"

mkdir -p "$(dirname "$PID_FILE")" "$(dirname "$LOG_FILE")"

is_agent_process() {
    local pid="$1"
    local cmdline_path="/proc/$pid/cmdline"

    if [ ! -r "$cmdline_path" ]; then
        return 1
    fi

    # PID 可能被系统复用，启动前先确认旧 PID 确实来自本项目 Agent。
    local cmdline
    cmdline="$(tr '\0' ' ' < "$cmdline_path")"
    [[ "$cmdline" == *"agent.main"* ]]
}

if [ -f "$PID_FILE" ]; then
    old_pid="$(cat "$PID_FILE")"
    if [ -n "$old_pid" ] && kill -0 "$old_pid" >/dev/null 2>&1 && is_agent_process "$old_pid"; then
        echo "[agent] already running, pid=$old_pid"
        exit 0
    fi
    echo "[agent] removing stale pid file: $PID_FILE"
    rm -f "$PID_FILE"
fi

if [ ! -f "$CONFIG_PATH" ]; then
    echo "[agent] config not found: $CONFIG_PATH" >&2
    exit 1
fi

source /opt/ros/noetic/setup.bash

if [ -f "$ROBOT_WS_SETUP" ]; then
    source "$ROBOT_WS_SETUP"
fi

until rostopic list >/dev/null 2>&1; do
    echo "[agent] waiting for ROS master..."
    sleep 1
done

cd "$PROJECT_ROOT"
python3 -m agent.main --agent-type ros1 --config "$CONFIG_PATH" >> "$LOG_FILE" 2>&1 &
pid="$!"
echo "$pid" > "$PID_FILE"

echo "[agent] started, pid=$pid"
echo "[agent] log: $LOG_FILE"
