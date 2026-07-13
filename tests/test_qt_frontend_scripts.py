from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read_repo_file(relative_path: str) -> str:
    return (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")


def test_frontend_start_script_sources_ros_before_rostopic_check() -> None:
    source = _read_repo_file("qt_frontend/scripts/start.sh")

    # 新地面站终端通常没有提前 source ROS，启动脚本需要自己准备 ROS 环境。
    assert 'ROS_SETUP="${ROS_SETUP:-/opt/ros/noetic/setup.bash}"' in source
    assert source.index('source "$ROS_SETUP"') < source.index("command -v rostopic")


def test_frontend_start_script_tracks_local_process_pids() -> None:
    source = _read_repo_file("qt_frontend/scripts/start.sh")

    assert 'PID_DIR="$LOG_DIR/pids"' in source
    assert 'BRIDGE_PID_FILE="$PID_DIR/bridge.pid"' in source
    assert 'STATION_LAUNCH_PID_FILE="$PID_DIR/station.launch.pid"' in source
    assert 'FRONTEND_PID_FILE="$PID_DIR/qt_frontend.pid"' in source
    assert 'echo "$BRIDGE_PID" > "$BRIDGE_PID_FILE"' in source
    assert 'echo "$STATION_LAUNCH_PID" > "$STATION_LAUNCH_PID_FILE"' in source
    assert 'echo "$FRONTEND_PID" > "$FRONTEND_PID_FILE"' in source


def test_frontend_stop_script_is_ground_station_only() -> None:
    source = _read_repo_file("qt_frontend/scripts/stop.sh")

    assert "agent/" not in source.lower()
    assert "机器人端" not in source
    assert "地面站" in source
    assert "stop_from_pid_file" in source


def test_frontend_stop_script_does_not_kill_unrelated_pid(tmp_path: Path) -> None:
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    frontend_pid_file = pid_dir / "qt_frontend.pid"
    unrelated_process = subprocess.Popen(["sleep", "30"])

    try:
        frontend_pid_file.write_text(str(unrelated_process.pid), encoding="utf-8")
        env: Dict[str, str] = os.environ.copy()
        env["PID_DIR"] = str(pid_dir)

        result = subprocess.run(
            ["bash", str(PROJECT_ROOT / "qt_frontend/scripts/stop.sh")],
            check=True,
            capture_output=True,
            env=env,
            text=True,
        )

        assert "不像地面站进程" in result.stdout
        assert unrelated_process.poll() is None
        assert not frontend_pid_file.exists()
    finally:
        unrelated_process.terminate()
        unrelated_process.wait(timeout=5)


def test_frontend_stop_script_stops_pid_file_process(tmp_path: Path) -> None:
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    frontend_pid_file = pid_dir / "qt_frontend.pid"
    frontend_process = subprocess.Popen(
        ["bash", "-c", 'exec -a "python3 qt_frontend/main.py" sleep 30']
    )

    try:
        frontend_pid_file.write_text(str(frontend_process.pid), encoding="utf-8")
        env: Dict[str, str] = os.environ.copy()
        env["PID_DIR"] = str(pid_dir)

        subprocess.run(
            ["bash", str(PROJECT_ROOT / "qt_frontend/scripts/stop.sh")],
            check=True,
            capture_output=True,
            env=env,
            text=True,
        )

        frontend_process.wait(timeout=5)
        assert frontend_process.poll() is not None
        assert not frontend_pid_file.exists()
    finally:
        if frontend_process.poll() is None:
            frontend_process.terminate()
            frontend_process.wait(timeout=5)


def test_frontend_scripts_have_valid_bash_syntax() -> None:
    for relative_path in [
        "qt_frontend/scripts/start.sh",
        "qt_frontend/scripts/stop.sh",
        "qt_frontend/scripts/build_rviz_widget.sh",
    ]:
        subprocess.run(
            ["bash", "-n", str(PROJECT_ROOT / relative_path)],
            check=True,
        )


def test_rviz_widget_build_script_is_documented_and_referenced() -> None:
    script = _read_repo_file("qt_frontend/scripts/build_rviz_widget.sh")
    readme = _read_repo_file("README.md")
    deployment = _read_repo_file("DEPLOYMENT.md")
    start_script = _read_repo_file("qt_frontend/scripts/start.sh")

    assert 'BUILD_DIR="$PROJECT_ROOT/qt_frontend/native/build"' in script
    assert "cmake .." in script
    assert "make -j\"$JOBS\"" in script
    assert "./qt_frontend/scripts/build_rviz_widget.sh" in readme
    assert "./qt_frontend/scripts/build_rviz_widget.sh" in deployment
    assert "./qt_frontend/scripts/build_rviz_widget.sh" in start_script
