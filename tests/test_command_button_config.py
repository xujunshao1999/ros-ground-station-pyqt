"""命令按钮配置模型和持久化测试。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from qt_frontend.command_button_config import (
    CONFIG_VERSION,
    MAX_COMMAND_DATA_BYTES,
    MAX_COMMAND_SCHEMA_BYTES,
    SLOT_IDS,
    CommandButtonConfig,
    CommandButtonConfigError,
    CommandButtonConfigStore,
    empty_command_slots,
)


def _schema(msg_type: str = "my_pkg/Control") -> Dict[str, Any]:
    return {
        "type": msg_type,
        "kind": "message",
        "fields": [],
    }


def _config(**overrides: Any) -> CommandButtonConfig:
    values = {
        "label": "开始探索",
        "topic": "/exploration/control",
        "msg_type": "my_pkg/Control",
        "data": {"command": "start"},
        "schema": _schema(),
        "schema_status": "verified",
    }
    values.update(overrides)
    return CommandButtonConfig(**values)


def _write_config(
    path: Path,
    slots: Dict[str, Any],
    version: Any = CONFIG_VERSION,
) -> None:
    path.write_text(
        yaml.safe_dump(
            {"version": version, "slots": slots},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_load_missing_file_returns_four_empty_slots(tmp_path):
    store = CommandButtonConfigStore(tmp_path / "command_buttons.yaml")

    assert store.load() == empty_command_slots()
    assert list(store.load()) == list(SLOT_IDS)


def test_store_round_trip_preserves_four_slots(tmp_path):
    path = tmp_path / "command_buttons.yaml"
    store = CommandButtonConfigStore(path)
    slots = empty_command_slots()
    slots["slot_1"] = _config()

    store.save(slots)

    assert store.load() == slots
    assert list(slots) == ["slot_1", "slot_2", "slot_3", "slot_4"]


def test_save_writes_generated_file_header_comment(tmp_path):
    path = tmp_path / "command_buttons.yaml"
    slots = empty_command_slots()
    slots["slot_1"] = _config()

    CommandButtonConfigStore(path).save(slots)

    content = path.read_text(encoding="utf-8")
    assert content.startswith("# 此文件由 ROS 地面站自动生成，请勿手工编辑。\n")
    assert "README.md" in content.split("version:", 1)[0]


def test_load_fills_missing_known_slots(tmp_path):
    path = tmp_path / "command_buttons.yaml"
    _write_config(path, {"slot_2": _config().to_dict()})

    loaded = CommandButtonConfigStore(path).load()

    assert loaded == {
        "slot_1": None,
        "slot_2": _config(),
        "slot_3": None,
        "slot_4": None,
    }


def test_load_rejects_malformed_yaml(tmp_path):
    path = tmp_path / "command_buttons.yaml"
    path.write_text("version: [\n", encoding="utf-8")

    with pytest.raises(CommandButtonConfigError, match="无法读取"):
        CommandButtonConfigStore(path).load()


@pytest.mark.parametrize("version", [0, 2, "1", None])
def test_load_rejects_unsupported_version(tmp_path, version):
    path = tmp_path / "command_buttons.yaml"
    _write_config(path, {}, version=version)

    with pytest.raises(CommandButtonConfigError, match="version"):
        CommandButtonConfigStore(path).load()


def test_load_rejects_unknown_slot(tmp_path):
    path = tmp_path / "command_buttons.yaml"
    _write_config(path, {"slot_5": None})

    with pytest.raises(CommandButtonConfigError, match="slot_5"):
        CommandButtonConfigStore(path).load()


@pytest.mark.parametrize(
    ("overrides", "error_match"),
    [
        ({"label": "   "}, "label"),
        ({"label": "x" * 65}, "label"),
        ({"topic": "relative/topic"}, "topic"),
        ({"topic": "/" + "x" * 255}, "topic"),
        ({"msg_type": "Control"}, "msg_type"),
        ({"msg_type": "pkg/sub/Control"}, "msg_type"),
        ({"data": []}, "data"),
        ({"schema": []}, "schema"),
        ({"schema_status": "stale"}, "schema_status"),
    ],
)
def test_save_rejects_invalid_slot_fields(tmp_path, overrides, error_match):
    slots = empty_command_slots()
    slots["slot_1"] = _config(**overrides)

    with pytest.raises(CommandButtonConfigError, match=error_match):
        CommandButtonConfigStore(tmp_path / "command_buttons.yaml").save(slots)


def test_save_rejects_oversized_data(tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config(data={"payload": "x" * MAX_COMMAND_DATA_BYTES})

    with pytest.raises(CommandButtonConfigError, match="data"):
        CommandButtonConfigStore(tmp_path / "command_buttons.yaml").save(slots)


def test_save_rejects_oversized_schema(tmp_path):
    schema = _schema()
    schema["padding"] = "x" * MAX_COMMAND_SCHEMA_BYTES
    slots = empty_command_slots()
    slots["slot_1"] = _config(schema=schema)

    with pytest.raises(CommandButtonConfigError, match="schema"):
        CommandButtonConfigStore(tmp_path / "command_buttons.yaml").save(slots)


@pytest.mark.parametrize(
    "schema",
    [
        {"type": "my_pkg/Control", "kind": "message"},
        {"type": "my_pkg/Control", "kind": "service", "fields": []},
        {"type": "my_pkg/Control", "kind": "message", "fields": {}},
    ],
)
def test_save_rejects_invalid_nonempty_schema_root(tmp_path, schema):
    slots = empty_command_slots()
    slots["slot_1"] = _config(schema=schema)

    with pytest.raises(CommandButtonConfigError, match="schema"):
        CommandButtonConfigStore(tmp_path / "command_buttons.yaml").save(slots)


def test_save_rejects_schema_type_mismatch(tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config(schema=_schema("other_pkg/Control"))

    with pytest.raises(CommandButtonConfigError, match="msg_type"):
        CommandButtonConfigStore(tmp_path / "command_buttons.yaml").save(slots)


def test_save_rejects_verified_config_without_schema(tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config(schema={})

    with pytest.raises(CommandButtonConfigError, match="verified"):
        CommandButtonConfigStore(tmp_path / "command_buttons.yaml").save(slots)


@pytest.mark.parametrize("schema", [{}, _schema()])
def test_unverified_config_allows_empty_or_matching_cached_schema(tmp_path, schema):
    path = tmp_path / "command_buttons.yaml"
    slots = empty_command_slots()
    slots["slot_1"] = _config(schema=schema, schema_status="unverified")

    CommandButtonConfigStore(path).save(slots)

    assert CommandButtonConfigStore(path).load() == slots


def test_save_rejects_incomplete_or_unknown_slot_mapping(tmp_path):
    store = CommandButtonConfigStore(tmp_path / "command_buttons.yaml")

    with pytest.raises(CommandButtonConfigError, match="slot"):
        store.save({"slot_1": None})
    with pytest.raises(CommandButtonConfigError, match="slot_5"):
        store.save({**empty_command_slots(), "slot_5": None})


def test_replace_failure_preserves_old_file_and_removes_temp_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "command_buttons.yaml"
    old_content = "version: 1\nslots:\n  slot_1: null\n"
    path.write_text(old_content, encoding="utf-8")
    slots = empty_command_slots()
    slots["slot_1"] = _config()

    def fail_replace(source, destination):
        assert Path(source).parent == tmp_path
        assert Path(destination) == path
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        CommandButtonConfigStore(path).save(slots)

    assert path.read_text(encoding="utf-8") == old_content
    assert list(tmp_path.iterdir()) == [path]
