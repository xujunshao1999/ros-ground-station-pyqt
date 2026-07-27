"""ROS 消息结构递归解析测试。"""

from __future__ import annotations

import pytest

from agent.message_schema import MessageSchemaError, build_message_schema
from agent.mock_agent import MockAgent
from agent.ros1_agent import ROS1Agent


class FakeHeader:
    __slots__ = ["stamp", "frame_id"]
    _slot_types = ["time", "string"]


class FakePoint:
    __slots__ = ["x", "y"]
    _slot_types = ["float64", "float64"]


class FakeCommand:
    __slots__ = ["header", "points", "enabled", "gains"]
    _slot_types = [
        "test_msgs/Header",
        "test_msgs/Point[]",
        "bool",
        "float64[3]",
    ]


def test_build_message_schema_recurses_nested_and_array_types(monkeypatch):
    classes = {
        "test_msgs/Header": FakeHeader,
        "test_msgs/Point": FakePoint,
        "test_msgs/Command": FakeCommand,
    }
    monkeypatch.setattr(
        "agent.message_schema._get_message_class",
        lambda msg_type: classes.get(msg_type),
    )

    schema = build_message_schema("test_msgs/Command")

    assert schema == {
        "type": "test_msgs/Command",
        "kind": "message",
        "fields": [
            {
                "name": "header",
                "type": "test_msgs/Header",
                "base_type": "test_msgs/Header",
                "kind": "message",
                "is_array": False,
                "array_len": None,
                "fields": [
                    {
                        "name": "stamp",
                        "type": "time",
                        "base_type": "time",
                        "kind": "time",
                        "is_array": False,
                        "array_len": None,
                        "fields": [],
                    },
                    {
                        "name": "frame_id",
                        "type": "string",
                        "base_type": "string",
                        "kind": "primitive",
                        "is_array": False,
                        "array_len": None,
                        "fields": [],
                    },
                ],
            },
            {
                "name": "points",
                "type": "test_msgs/Point[]",
                "base_type": "test_msgs/Point",
                "kind": "message",
                "is_array": True,
                "array_len": None,
                "fields": [
                    {
                        "name": "x",
                        "type": "float64",
                        "base_type": "float64",
                        "kind": "primitive",
                        "is_array": False,
                        "array_len": None,
                        "fields": [],
                    },
                    {
                        "name": "y",
                        "type": "float64",
                        "base_type": "float64",
                        "kind": "primitive",
                        "is_array": False,
                        "array_len": None,
                        "fields": [],
                    },
                ],
            },
            {
                "name": "enabled",
                "type": "bool",
                "base_type": "bool",
                "kind": "primitive",
                "is_array": False,
                "array_len": None,
                "fields": [],
            },
            {
                "name": "gains",
                "type": "float64[3]",
                "base_type": "float64",
                "kind": "primitive",
                "is_array": True,
                "array_len": 3,
                "fields": [],
            },
        ],
    }


def test_build_message_schema_rejects_unknown_type(monkeypatch):
    monkeypatch.setattr(
        "agent.message_schema._get_message_class",
        lambda _msg_type: None,
    )

    with pytest.raises(MessageSchemaError, match="test_msgs/Missing"):
        build_message_schema("test_msgs/Missing")


def test_build_message_schema_rejects_recursive_types(monkeypatch):
    class FakeA:
        __slots__ = ["child"]
        _slot_types = ["test_msgs/B"]

    class FakeB:
        __slots__ = ["parent"]
        _slot_types = ["test_msgs/A"]

    classes = {"test_msgs/A": FakeA, "test_msgs/B": FakeB}
    monkeypatch.setattr(
        "agent.message_schema._get_message_class",
        lambda msg_type: classes.get(msg_type),
    )

    with pytest.raises(MessageSchemaError, match="test_msgs/A"):
        build_message_schema("test_msgs/A")


def test_build_message_schema_rejects_excessive_depth(monkeypatch):
    classes = {}
    for index in range(4):
        type_name = "test_msgs/Depth%d" % index
        child_type = "test_msgs/Depth%d" % (index + 1)
        classes[type_name] = type(
            "FakeDepth%d" % index,
            (),
            {"__slots__": ["child"], "_slot_types": [child_type]},
        )
    monkeypatch.setattr(
        "agent.message_schema._get_message_class",
        lambda msg_type: classes.get(msg_type),
    )

    with pytest.raises(MessageSchemaError, match="test_msgs/Depth3"):
        build_message_schema("test_msgs/Depth0", max_depth=2)


def test_build_message_schema_rejects_excessive_field_count(monkeypatch):
    class FakeWide:
        __slots__ = ["first", "second", "third"]
        _slot_types = ["string", "string", "string"]

    monkeypatch.setattr(
        "agent.message_schema._get_message_class",
        lambda _msg_type: FakeWide,
    )

    with pytest.raises(MessageSchemaError, match="test_msgs/Wide"):
        build_message_schema("test_msgs/Wide", max_fields=2)


def test_build_message_schema_rejects_mismatched_slot_metadata(monkeypatch):
    class FakeBroken:
        __slots__ = ["first", "second"]
        _slot_types = ["string"]

    monkeypatch.setattr(
        "agent.message_schema._get_message_class",
        lambda _msg_type: FakeBroken,
    )

    with pytest.raises(MessageSchemaError, match="test_msgs/Broken"):
        build_message_schema("test_msgs/Broken")


def test_ros1_agent_schema_hook_uses_runtime_builder(monkeypatch):
    expected = {"type": "custom_msgs/Control", "kind": "message", "fields": []}
    monkeypatch.setattr(
        "agent.ros1_agent.build_message_schema",
        lambda msg_type: expected if msg_type == "custom_msgs/Control" else {},
    )

    agent = object.__new__(ROS1Agent)

    assert agent._get_message_schema("custom_msgs/Control") == expected


def test_mock_agent_returns_stable_builtin_and_fallback_schemas():
    agent = object.__new__(MockAgent)

    twist_schema = agent._get_message_schema("geometry_msgs/Twist")
    twist_fields = {field["name"]: field for field in twist_schema["fields"]}
    assert twist_fields["linear"]["base_type"] == "geometry_msgs/Vector3"
    assert [field["name"] for field in twist_fields["linear"]["fields"]] == [
        "x",
        "y",
        "z",
    ]

    bool_schema = agent._get_message_schema("std_msgs/Bool")
    assert bool_schema["fields"][0]["base_type"] == "bool"

    assert agent._get_message_schema("custom_msgs/Unknown") == {
        "type": "custom_msgs/Unknown",
        "kind": "message",
        "fields": [],
    }
