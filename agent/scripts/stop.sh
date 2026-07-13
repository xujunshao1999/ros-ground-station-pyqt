#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PID_FILE="${PID_FILE:-$PROJECT_ROOT/logs/agent.pid}"

is_agent_process() {
    local pid="$1"
    local cmdline_path="/proc/$pid/cmdline"

    if [ ! -r "$cmdline_path" ]; then
        return 1
    fi

    # PID 文件只能作为定位线索，真正停止前还要确认该进程是 Agent。
    local cmdline
    cmdline="$(tr '\0' ' ' < "$cmdline_path")"
    [[ "$cmdline" == *"agent.main"* ]]
}

if [ ! -f "$PID_FILE" ]; then
    echo "[agent] pid file not found: $PID_FILE"
    exit 0
fi

pid="$(cat "$PID_FILE")"
if [ -z "$pid" ]; then
    echo "[agent] empty pid file, removing: $PID_FILE"
    rm -f "$PID_FILE"
    exit 0
fi

if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "[agent] process is not running, removing stale pid file: $PID_FILE"
    rm -f "$PID_FILE"
    exit 0
fi

if ! is_agent_process "$pid"; then
    echo "[agent] pid=$pid does not look like agent.main, removing stale pid file without killing it"
    rm -f "$PID_FILE"
    exit 0
fi

echo "[agent] stopping pid=$pid"
kill "$pid"

for _ in $(seq 1 10); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
        rm -f "$PID_FILE"
        echo "[agent] stopped."
        exit 0
    fi
    sleep 1
done

echo "[agent] pid=$pid did not stop after SIGTERM, sending SIGKILL"
kill -9 "$pid" >/dev/null 2>&1 || true
rm -f "$PID_FILE"
echo "[agent] stopped."
