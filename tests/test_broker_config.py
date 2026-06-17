from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _non_comment_lines(path: Path):
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_mosquitto_default_config_avoids_per_message_logging():
    lines = _non_comment_lines(PROJECT_ROOT / "broker" / "mosquitto.conf")

    assert "log_type information" not in lines
    assert "log_dest stdout" not in lines
    assert "log_type error" in lines
    assert "log_type warning" in lines
    assert "log_type notice" in lines


def test_mosquitto_start_scripts_do_not_force_verbose_logging():
    start_sh = (PROJECT_ROOT / "broker" / "start.sh").read_text(encoding="utf-8")
    start_bat = (PROJECT_ROOT / "broker" / "start.bat").read_text(encoding="utf-8")

    assert "mosquitto -c \"$CONFIG_PATH\" -v" not in start_sh
    assert "%MOSQUITTO_PATH% -c broker\\mosquitto.conf -v" not in start_bat


def test_mosquitto_start_script_creates_persistence_directory():
    start_sh = (PROJECT_ROOT / "broker" / "start.sh").read_text(encoding="utf-8")

    assert "mkdir -p \"$PROJECT_ROOT/data\"" in start_sh
