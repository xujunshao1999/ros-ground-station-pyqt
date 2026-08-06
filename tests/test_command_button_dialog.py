"""四槽位命令按钮设置对话框测试。"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import QApplication, QDialog  # noqa: E402

from qt_frontend.command_button_config import (  # noqa: E402
    CommandButtonConfig,
    CommandButtonConfigStore,
    empty_command_slots,
)
from qt_frontend.panels.command_button_dialog import (  # noqa: E402
    CommandButtonSettingsDialog,
)
from qt_frontend.topic_catalog import RobotTopicCatalog  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _bool_schema(msg_type="my_pkg/First"):
    return {
        "type": msg_type,
        "kind": "message",
        "fields": [
            {
                "name": "enabled",
                "type": "bool",
                "base_type": "bool",
                "kind": "primitive",
                "is_array": False,
                "array_len": None,
                "fields": [],
            }
        ],
    }


def _config(
    *,
    label="启动",
    topic="/cmd",
    msg_type="my_pkg/First",
    data=None,
    schema=None,
    schema_status="verified",
):
    return CommandButtonConfig(
        label=label,
        topic=topic,
        msg_type=msg_type,
        data={"enabled": True} if data is None else data,
        schema=_bool_schema(msg_type) if schema is None else schema,
        schema_status=schema_status,
    )


def _build_dialog(
    qt_app,
    tmp_path,
    online_robot_ids,
    *,
    catalog_topics=True,
    initial_slots=None,
):
    catalog = RobotTopicCatalog()
    if catalog_topics:
        catalog.update_from_discover(
            "r1",
            {"topics": [{"topic": "/cmd", "msg_type": "my_pkg/First"}]},
        )
    store = CommandButtonConfigStore(tmp_path / "command_buttons.yaml")
    if initial_slots is not None:
        store.save(initial_slots)
    original_save = store.save
    store.save = MagicMock(side_effect=original_save)
    requests = []
    discovers = []
    dialog = CommandButtonSettingsDialog(
        store=store,
        topic_catalog=catalog,
        online_robot_ids=online_robot_ids,
    )
    dialog.schema_query_requested.connect(
        lambda robot_id, request_id, msg_type: requests.append(
            (robot_id, request_id, msg_type)
        )
    )
    dialog.discover_requested.connect(lambda: discovers.append(True))
    return dialog, store, catalog, requests, discovers


def _fill_manual_slot(dialog, msg_type="my_pkg/Manual", json_text='{"mode": 1}'):
    dialog._label_edit.setText("手工命令")
    dialog._topic_combo.setEditText("/manual")
    dialog._msg_type_combo.setEditText(msg_type)
    dialog._tabs.setCurrentIndex(1)
    dialog._json_edit.setPlainText(json_text)


def test_switching_slots_preserves_independent_raw_drafts(qt_app, tmp_path):
    dialog, _, _, _, _ = _build_dialog(qt_app, tmp_path, [])

    assert dialog._slot_list.count() == 4
    _fill_manual_slot(dialog, json_text="{not valid")
    dialog.select_slot("slot_2")
    dialog._label_edit.setText("第二命令")
    dialog._topic_combo.setEditText("/second")
    dialog._msg_type_combo.setEditText("my_pkg/Second")
    dialog._json_edit.setPlainText('{"value": 2}')

    dialog.select_slot("slot_1")

    assert dialog._label_edit.text() == "手工命令"
    assert dialog._topic_combo.currentText() == "/manual"
    assert dialog.current_message_type() == "my_pkg/Manual"
    assert dialog._tabs.currentIndex() == 1
    assert dialog._json_edit.toPlainText() == "{not valid"


def test_topic_options_use_representative_robot_and_fill_message_type(
    qt_app, tmp_path
):
    dialog, _, _, requests, _ = _build_dialog(qt_app, tmp_path, ["r2", "r1"])

    assert [dialog._topic_combo.itemText(i) for i in range(dialog._topic_combo.count())] == [
        "/cmd"
    ]

    dialog._topic_combo.setCurrentIndex(0)

    assert dialog.current_message_type() == "my_pkg/First"
    assert requests[-1][0] == "r1"
    assert requests[-1][2] == "my_pkg/First"


def test_selecting_message_type_option_requests_schema(qt_app, tmp_path):
    dialog, _, _, requests, _ = _build_dialog(qt_app, tmp_path, ["r1"])

    dialog._msg_type_combo.setCurrentIndex(0)

    assert requests[-1][0] == "r1"
    assert requests[-1][2] == "my_pkg/First"


def test_dialog_ignores_stale_and_mismatched_schema_responses(qt_app, tmp_path):
    dialog, _, _, requests, _ = _build_dialog(qt_app, tmp_path, ["r1"])
    dialog.set_message_type("my_pkg/First")
    old_request = requests[-1][1]
    dialog.set_message_type("my_pkg/Second")
    current_request = requests[-1][1]

    dialog.on_schema_response(
        "r1",
        {
            "request_id": old_request,
            "msg_type": "my_pkg/First",
            "result": "ok",
            "schema": _bool_schema("my_pkg/First"),
        },
    )
    dialog.on_schema_response(
        "r2",
        {
            "request_id": current_request,
            "msg_type": "my_pkg/Second",
            "result": "ok",
            "schema": _bool_schema("my_pkg/Second"),
        },
    )
    dialog.on_schema_response(
        "r1",
        {
            "request_id": current_request,
            "msg_type": "my_pkg/Wrong",
            "result": "ok",
            "schema": _bool_schema("my_pkg/Wrong"),
        },
    )

    assert dialog.current_message_type() == "my_pkg/Second"
    assert dialog.current_schema() == {}

    dialog.on_schema_response(
        "r1",
        {
            "request_id": current_request,
            "msg_type": "my_pkg/Second",
            "result": "ok",
            "schema": _bool_schema("my_pkg/Second"),
        },
    )
    assert dialog.current_schema()["type"] == "my_pkg/Second"


def test_concurrent_schema_responses_update_their_own_slots(qt_app, tmp_path):
    dialog, _, _, requests, _ = _build_dialog(qt_app, tmp_path, ["r1"])
    dialog.set_message_type("my_pkg/First")
    first_request = requests[-1][1]
    dialog.select_slot("slot_2")
    dialog.set_message_type("my_pkg/Second")
    second_request = requests[-1][1]

    dialog.on_schema_response(
        "r1",
        {
            "request_id": first_request,
            "msg_type": "my_pkg/First",
            "result": "ok",
            "schema": _bool_schema("my_pkg/First"),
        },
    )
    assert dialog.current_schema() == {}

    dialog.on_schema_response(
        "r1",
        {
            "request_id": second_request,
            "msg_type": "my_pkg/Second",
            "result": "ok",
            "schema": _bool_schema("my_pkg/Second"),
        },
    )
    assert dialog.current_schema()["type"] == "my_pkg/Second"

    dialog.select_slot("slot_1")
    assert dialog.current_schema()["type"] == "my_pkg/First"


def test_form_and_json_tabs_synchronize_valid_data(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config()
    dialog, _, _, _, _ = _build_dialog(
        qt_app,
        tmp_path,
        [],
        initial_slots=slots,
    )

    dialog._form.field_widget("enabled").setChecked(False)
    dialog._tabs.setCurrentIndex(1)
    assert dialog._json_edit.toPlainText() == '{\n  "enabled": false\n}'

    dialog._json_edit.setPlainText('{"enabled": true}')
    dialog._tabs.setCurrentIndex(0)

    assert dialog._tabs.currentIndex() == 0
    assert dialog._form.data() == {"enabled": True}


def test_offline_cached_schema_is_immediately_unverified(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config()

    dialog, _, _, _, _ = _build_dialog(
        qt_app,
        tmp_path,
        [],
        initial_slots=slots,
    )

    assert dialog._drafts["slot_1"].schema_status == "unverified"
    assert dialog.current_schema() == _bool_schema()


def test_cached_schema_with_invalid_data_opens_json(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config(data={"enabled": "bad"})

    dialog, _, _, _, _ = _build_dialog(
        qt_app,
        tmp_path,
        [],
        initial_slots=slots,
    )

    assert dialog._tabs.currentIndex() == 1
    assert dialog._json_edit.toPlainText() == '{\n  "enabled": "bad"\n}'
    assert "enabled" in dialog._status_label.text()


def test_invalid_json_or_schema_data_does_not_save(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config()
    dialog, store, _, _, _ = _build_dialog(
        qt_app,
        tmp_path,
        [],
        initial_slots=slots,
    )
    store.save.reset_mock()

    dialog._tabs.setCurrentIndex(1)
    dialog._json_edit.setPlainText("[]")
    dialog._save_all()
    assert store.save.call_count == 0
    assert dialog.result() != QDialog.Accepted

    dialog._json_edit.setPlainText('{"enabled": "yes"}')
    dialog._save_all()
    assert store.save.call_count == 0
    assert "enabled" in dialog._status_label.text()


def test_offline_manual_json_saves_as_unverified(qt_app, tmp_path):
    dialog, store, _, _, _ = _build_dialog(qt_app, tmp_path, [])
    store.save.reset_mock()
    _fill_manual_slot(dialog)

    dialog._save_all()

    assert dialog.result() == QDialog.Accepted
    assert store.save.call_count == 1
    saved = CommandButtonConfigStore(store._path).load()["slot_1"]
    assert saved.schema_status == "unverified"
    assert saved.schema == {}
    assert saved.data == {"mode": 1}


def test_empty_catalog_requests_discover_and_catalog_update_refreshes_topics(
    qt_app, tmp_path
):
    dialog, _, catalog, _, discovers = _build_dialog(
        qt_app,
        tmp_path,
        ["r1"],
        catalog_topics=False,
    )

    qt_app.processEvents()
    assert discovers == [True]

    dialog._topic_combo.setEditText("/manual-kept")
    catalog.update_from_discover(
        "r1",
        {"topics": [{"topic": "/new", "msg_type": "my_pkg/New"}]},
    )

    assert dialog._topic_combo.findText("/new") >= 0
    assert dialog._topic_combo.currentText() == "/manual-kept"


def test_schema_timeout_keeps_cached_schema_unverified(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config()
    dialog, _, _, requests, _ = _build_dialog(
        qt_app,
        tmp_path,
        ["r1"],
        initial_slots=slots,
    )
    qt_app.processEvents()
    request_id = requests[-1][1]
    cached = dialog.current_schema()

    dialog.expire_schema_request(request_id)

    assert dialog.current_schema() == cached
    assert dialog._drafts["slot_1"].schema_status == "unverified"
    assert "超时" in dialog._status_label.text()


def test_late_response_after_timeout_is_ignored(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config()
    dialog, _, _, requests, _ = _build_dialog(
        qt_app,
        tmp_path,
        ["r1"],
        initial_slots=slots,
    )
    qt_app.processEvents()
    request_id = requests[-1][1]
    dialog.expire_schema_request(request_id)

    dialog.on_schema_response(
        "r1",
        {
            "request_id": request_id,
            "msg_type": "my_pkg/First",
            "result": "ok",
            "schema": {"type": "my_pkg/First", "kind": "message", "fields": []},
        },
    )

    assert dialog.current_schema() == _bool_schema()
    assert dialog._drafts["slot_1"].schema_status == "unverified"


def test_schema_error_without_cache_switches_to_json(qt_app, tmp_path):
    dialog, _, _, requests, _ = _build_dialog(qt_app, tmp_path, ["r1"])
    dialog.set_message_type("my_pkg/First")
    request_id = requests[-1][1]

    dialog.on_schema_response(
        "r1",
        {
            "request_id": request_id,
            "msg_type": "my_pkg/First",
            "result": "error",
            "schema": {},
            "error": "消息包未安装",
        },
    )

    assert dialog.current_schema() == {}
    assert dialog._tabs.currentIndex() == 1
    assert "消息包未安装" in dialog._status_label.text()


def test_opening_cached_slot_refreshes_schema_once(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_2"] = _config()
    dialog, _, _, requests, _ = _build_dialog(
        qt_app,
        tmp_path,
        ["r1"],
        initial_slots=slots,
    )

    dialog.select_slot("slot_2")
    assert len(requests) == 1
    dialog.select_slot("slot_1")
    dialog.select_slot("slot_2")
    assert len(requests) == 1


def test_robot_coming_online_refreshes_selected_slot(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config()
    dialog, _, _, requests, _ = _build_dialog(
        qt_app,
        tmp_path,
        [],
        initial_slots=slots,
    )

    dialog.set_online_robot_ids(["r2", "r1", "r1"])

    assert requests[-1][0] == "r1"
    assert requests[-1][2] == "my_pkg/First"


def test_all_robots_going_offline_marks_cache_unverified(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config()
    dialog, _, _, _, _ = _build_dialog(
        qt_app,
        tmp_path,
        ["r1"],
        initial_slots=slots,
    )

    dialog.set_online_robot_ids([])

    assert dialog._drafts["slot_1"].schema_status == "unverified"
    assert dialog.current_schema() == _bool_schema()
    assert dialog._pending_schema_requests == {}


def test_clear_current_slot_persists_none(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config()
    dialog, store, _, _, _ = _build_dialog(
        qt_app,
        tmp_path,
        [],
        initial_slots=slots,
    )
    store.save.reset_mock()

    dialog._clear_current_slot()
    dialog._save_all()

    assert store.save.call_count == 1
    assert CommandButtonConfigStore(store._path).load()["slot_1"] is None
    assert dialog.saved_slots()["slot_1"] is None


def test_cancel_does_not_modify_disk_and_accessors_are_defensive(qt_app, tmp_path):
    slots = empty_command_slots()
    slots["slot_1"] = _config()
    dialog, store, _, _, _ = _build_dialog(
        qt_app,
        tmp_path,
        [],
        initial_slots=slots,
    )
    store.save.reset_mock()

    schema_copy = dialog.current_schema()
    schema_copy["type"] = "mutated"
    saved_copy = dialog.saved_slots()
    saved_copy["slot_1"].label = "mutated"
    dialog._label_edit.setText("未保存")
    dialog.reject()

    assert store.save.call_count == 0
    assert dialog.current_schema()["type"] == "my_pkg/First"
    assert dialog.saved_slots()["slot_1"].label == "启动"
    assert CommandButtonConfigStore(store._path).load()["slot_1"].label == "启动"
