from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_repo_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_agent_start_script_tracks_pid_and_log_file() -> None:
    source = _read_repo_file("agent/scripts/start.sh")

    assert 'CONFIG_PATH="${CONFIG_PATH:-$PROJECT_ROOT/agent/configs/default.yaml}"' in source
    assert 'PID_FILE="${PID_FILE:-$PROJECT_ROOT/logs/agent.pid}"' in source
    assert 'LOG_FILE="${LOG_FILE:-$PROJECT_ROOT/logs/agent.log}"' in source
    assert 'echo "$pid" > "$PID_FILE"' in source
    assert 'python3 -m agent.main --agent-type ros1 --config "$CONFIG_PATH"' in source


def test_agent_main_uses_default_config_under_configs_dir() -> None:
    source = _read_repo_file("agent/main.py")

    assert 'default="agent/configs/default.yaml"' in source
    assert "default: agent/configs/default.yaml" in source


def test_agent_stop_script_uses_pid_file_not_global_pkill() -> None:
    source = _read_repo_file("agent/scripts/stop.sh")

    assert 'PID_FILE="${PID_FILE:-$PROJECT_ROOT/logs/agent.pid}"' in source
    assert 'kill "$pid"' in source
    assert "is_agent_process" in source
    assert 'pkill -f "agent.main"' not in source


def test_agent_stop_script_does_not_kill_unrelated_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "agent.pid"
    unrelated_process = subprocess.Popen(["sleep", "30"])

    try:
        pid_file.write_text(str(unrelated_process.pid), encoding="utf-8")
        env: Dict[str, str] = os.environ.copy()
        env["PID_FILE"] = str(pid_file)
        result = subprocess.run(
            ["bash", str(PROJECT_ROOT / "agent/scripts/stop.sh")],
            check=True,
            capture_output=True,
            env=env,
            text=True,
        )

        assert "does not look like agent.main" in result.stdout
        assert unrelated_process.poll() is None
        assert not pid_file.exists()
    finally:
        unrelated_process.terminate()
        unrelated_process.wait(timeout=5)


def test_agent_scripts_have_valid_bash_syntax() -> None:
    for relative_path in ["agent/scripts/start.sh", "agent/scripts/stop.sh"]:
        subprocess.run(
            ["bash", "-n", str(PROJECT_ROOT / relative_path)],
            check=True,
        )
