"""消息 schema 数据校验和递归 Qt 表单测试。"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QGroupBox,
    QLineEdit,
    QPlainTextEdit,
)

from qt_frontend.message_schema import (  # noqa: E402
    default_data_for_schema,
    validate_message_data,
)
from qt_frontend.panels.message_form import MessageFormWidget  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _field(
    name,
    base_type,
    *,
    kind="primitive",
    is_array=False,
    array_len=None,
    fields=None,
):
    type_name = base_type
    if is_array:
        suffix = "[]" if array_len is None else "[{}]".format(array_len)
        type_name += suffix
    return {
        "name": name,
        "type": type_name,
        "base_type": base_type,
        "kind": kind,
        "is_array": is_array,
        "array_len": array_len,
        "fields": fields or [],
    }


@pytest.fixture
def sample_schema():
    return {
        "type": "test_msgs/Command",
        "kind": "message",
        "fields": [
            _field("enabled", "bool"),
            _field("name", "string"),
            _field(
                "pose",
                "test_msgs/Pose",
                kind="message",
                fields=[
                    _field("x", "float64"),
                    _field("count", "int32"),
                ],
            ),
            _field("tags", "string", is_array=True),
        ],
    }


def test_default_data_and_validation_follow_nested_schema(sample_schema):
    data = default_data_for_schema(sample_schema)

    assert data == {
        "enabled": False,
        "name": "",
        "pose": {"x": 0.0, "count": 0},
        "tags": [],
    }
    assert validate_message_data(sample_schema, data) == []
    assert validate_message_data(sample_schema, {"pose": {"x": "bad"}}) == [
        "pose.x: 需要浮点数"
    ]


def test_validation_allows_missing_fields_and_rejects_unknown_fields(sample_schema):
    assert validate_message_data(sample_schema, {}) == []
    assert validate_message_data(
        sample_schema,
        {"zeta": 1, "alpha": 2},
    ) == [
        "alpha: 未知字段",
        "zeta: 未知字段",
    ]


def test_validation_rejects_non_object_root_and_nested_message(sample_schema):
    assert validate_message_data(sample_schema, []) == ["$: 需要 object"]
    assert validate_message_data(sample_schema, {"pose": []}) == [
        "pose: 需要 object"
    ]


def test_validation_distinguishes_bool_integer_float_and_string(sample_schema):
    assert validate_message_data(
        sample_schema,
        {
            "enabled": 1,
            "name": False,
            "pose": {"x": True, "count": True},
        },
    ) == [
        "enabled: 需要布尔值",
        "name: 需要字符串",
        "pose.x: 需要浮点数",
        "pose.count: 需要整数",
    ]
    assert validate_message_data(sample_schema, {"pose": {"x": 2}}) == []


def test_fixed_array_defaults_and_validates_length_and_items():
    schema = {
        "type": "test_msgs/Arrays",
        "kind": "message",
        "fields": [
            _field("gains", "float64", is_array=True, array_len=2),
            _field(
                "poses",
                "test_msgs/Pose",
                kind="message",
                is_array=True,
                fields=[_field("x", "float64")],
            ),
        ],
    }

    assert default_data_for_schema(schema) == {
        "gains": [0.0, 0.0],
        "poses": [],
    }
    assert validate_message_data(schema, {"gains": [1.0]}) == [
        "gains: 固定数组长度必须为 2"
    ]
    assert validate_message_data(schema, {"gains": [1.0, "bad"]}) == [
        "gains[1]: 需要浮点数"
    ]
    assert validate_message_data(schema, {"poses": [{"x": "bad"}]}) == [
        "poses[0].x: 需要浮点数"
    ]


def test_time_and_duration_use_integer_secs_and_nsecs_objects():
    schema = {
        "type": "test_msgs/Timing",
        "kind": "message",
        "fields": [
            _field("stamp", "time", kind="time"),
            _field("delay", "duration", kind="duration"),
        ],
    }

    assert default_data_for_schema(schema) == {
        "stamp": {"secs": 0, "nsecs": 0},
        "delay": {"secs": 0, "nsecs": 0},
    }
    assert validate_message_data(
        schema,
        {
            "stamp": {"secs": 1, "nsecs": "bad", "extra": 3},
            "delay": 1.5,
        },
    ) == [
        "stamp.nsecs: 需要整数",
        "stamp.extra: 未知字段",
        "delay: 需要 object",
    ]


def test_form_round_trip_uses_typed_widgets(qt_app, sample_schema):
    form = MessageFormWidget()
    form.set_schema(
        sample_schema,
        {
            "enabled": True,
            "name": "robot",
            "pose": {"x": 1.5, "count": 2},
            "tags": ["initial"],
        },
    )

    assert isinstance(form.field_widget("enabled"), QCheckBox)
    assert isinstance(form.field_widget("name"), QLineEdit)
    assert isinstance(form.field_widget("pose"), QGroupBox)
    assert isinstance(form.field_widget("pose.x"), QLineEdit)
    assert isinstance(form.field_widget("tags"), QPlainTextEdit)
    assert form.field_widget("missing") is None

    form.field_widget("enabled").setChecked(False)
    form.field_widget("name").setText("updated")
    form.field_widget("pose.x").setText("2.75")
    form.field_widget("pose.count").setText("-3")
    form.field_widget("tags").setPlainText('["one", "two"]')
    qt_app.processEvents()

    assert form.data() == {
        "enabled": False,
        "name": "updated",
        "pose": {"x": 2.75, "count": -3},
        "tags": ["one", "two"],
    }
    assert form.validation_errors() == []


def test_form_builds_time_fields_and_fixed_array_defaults(qt_app):
    schema = {
        "type": "test_msgs/Timing",
        "kind": "message",
        "fields": [
            _field("stamp", "time", kind="time"),
            _field("gains", "float64", is_array=True, array_len=2),
        ],
    }
    form = MessageFormWidget()

    form.set_schema(schema, {})

    assert isinstance(form.field_widget("stamp"), QGroupBox)
    assert isinstance(form.field_widget("stamp.secs"), QLineEdit)
    assert isinstance(form.field_widget("stamp.nsecs"), QLineEdit)
    assert form.field_widget("gains").toPlainText() == "[\n  0.0,\n  0.0\n]"
    assert form.data() == {
        "stamp": {"secs": 0, "nsecs": 0},
        "gains": [0.0, 0.0],
    }


def test_form_reports_array_json_and_numeric_errors_with_paths(
    qt_app, sample_schema
):
    form = MessageFormWidget()
    form.set_schema(sample_schema, {})

    form.field_widget("tags").setPlainText("not json")
    form.field_widget("pose.count").setText("1.5")
    qt_app.processEvents()

    assert form.validation_errors() == [
        "pose.count: 需要整数",
        "tags: 需要有效的 JSON 数组",
    ]


def test_form_emits_data_changed_and_uses_stable_editor_heights(
    qt_app, sample_schema
):
    form = MessageFormWidget()
    form.set_schema(sample_schema, {})
    changes = []
    form.data_changed.connect(lambda: changes.append(True))

    form.field_widget("name").setText("changed")
    qt_app.processEvents()

    assert changes
    assert form.field_widget("name").minimumHeight() >= 28
    assert form.field_widget("tags").minimumHeight() >= 72
