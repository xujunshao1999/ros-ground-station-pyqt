from __future__ import annotations

from qt_frontend.rviz_frame_policy import (
    follow_selected_robot_default,
    global_fixed_frame_for,
    normalize_frame_id,
    robot_fixed_frame_for,
)


def test_normalize_frame_id_strips_space_and_leading_slash() -> None:
    assert normalize_frame_id(" /husky_001/base_link ") == "husky_001/base_link"


def test_global_fixed_frame_defaults_to_global_map() -> None:
    assert global_fixed_frame_for({}) == "global_map"


def test_global_fixed_frame_prefers_explicit_global_frame() -> None:
    config = {"rviz": {"fixed_frame": "map", "global_frame": "global_map"}}

    assert global_fixed_frame_for(config) == "global_map"


def test_robot_fixed_frame_uses_default_template() -> None:
    assert robot_fixed_frame_for("husky_001", {}) == "husky_001/base_link"


def test_robot_fixed_frame_uses_robot_override() -> None:
    config = {
        "rviz": {
            "robot_frame_template": "{robot_id}/base_link",
            "robot_fixed_frames": {
                "husky_001": "husky_001/base_footprint",
            },
        }
    }

    assert robot_fixed_frame_for("husky_001", config) == "husky_001/base_footprint"
    assert robot_fixed_frame_for("turtlebot_001", config) == "turtlebot_001/base_link"


def test_robot_fixed_frame_falls_back_when_template_is_invalid() -> None:
    config = {"rviz": {"robot_frame_template": "base_link"}}

    assert robot_fixed_frame_for("husky_001", config) == "husky_001/base_link"


def test_robot_fixed_frame_falls_back_when_template_has_unknown_field() -> None:
    config = {"rviz": {"robot_frame_template": "{robot_id}/{bad_field}"}}

    assert robot_fixed_frame_for("husky_001", config) == "husky_001/base_link"


def test_follow_selected_robot_defaults_to_enabled() -> None:
    assert follow_selected_robot_default({}) is True
    assert follow_selected_robot_default(
        {"rviz": {"follow_selected_robot_frame": False}}
    ) is False
