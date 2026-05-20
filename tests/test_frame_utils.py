from __future__ import annotations

from agent.frame_utils import namespace_frame_id, namespace_message_frames


def test_namespace_frame_id_adds_robot_prefix() -> None:
    assert namespace_frame_id("base_scan", "turtlebot_001") == "turtlebot_001/base_scan"


def test_namespace_frame_id_strips_leading_slash() -> None:
    assert namespace_frame_id("/base_scan", "turtlebot_001") == "turtlebot_001/base_scan"


def test_namespace_frame_id_is_idempotent() -> None:
    assert namespace_frame_id("turtlebot_001/odom", "turtlebot_001") == "turtlebot_001/odom"


def test_namespace_frame_id_keeps_empty_values() -> None:
    assert namespace_frame_id("", "turtlebot_001") == ""
    assert namespace_frame_id("base_link", "") == "base_link"


def test_namespace_header_frame_id() -> None:
    data = {"header": {"frame_id": "base_scan"}}

    namespace_message_frames(data, "turtlebot_001")

    assert data["header"]["frame_id"] == "turtlebot_001/base_scan"


def test_namespace_child_frame_id() -> None:
    data = {"child_frame_id": "base_link"}

    namespace_message_frames(data, "turtlebot_001")

    assert data["child_frame_id"] == "turtlebot_001/base_link"


def test_namespace_tf_message_frames() -> None:
    data = {
        "transforms": [
            {
                "header": {"frame_id": "odom"},
                "child_frame_id": "base_footprint",
            }
        ]
    }

    namespace_message_frames(data, "turtlebot_001")

    transform = data["transforms"][0]
    assert transform["header"]["frame_id"] == "turtlebot_001/odom"
    assert transform["child_frame_id"] == "turtlebot_001/base_footprint"


def test_namespace_message_frames_is_idempotent() -> None:
    data = {
        "header": {"frame_id": "turtlebot_001/odom"},
        "child_frame_id": "turtlebot_001/base_link",
    }

    namespace_message_frames(data, "turtlebot_001")

    assert data["header"]["frame_id"] == "turtlebot_001/odom"
    assert data["child_frame_id"] == "turtlebot_001/base_link"


def test_namespace_message_frames_ignores_non_dict_transforms() -> None:
    data = {"transforms": ["bad", None, {"header": {"frame_id": "map"}}]}

    namespace_message_frames(data, "turtlebot_001")

    assert data["transforms"][0] == "bad"
    assert data["transforms"][1] is None
    assert data["transforms"][2]["header"]["frame_id"] == "turtlebot_001/map"
