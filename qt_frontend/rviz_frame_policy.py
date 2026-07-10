from __future__ import annotations

from typing import Any, Dict

DEFAULT_GLOBAL_FRAME = "global_map"
DEFAULT_ROBOT_FRAME_TEMPLATE = "{robot_id}/base_link"


def _rviz_config(config: Dict[str, Any]) -> Dict[str, Any]:
    raw = config.get("rviz", {})
    if isinstance(raw, dict):
        return raw
    return {}


def normalize_frame_id(frame: str) -> str:
    # TF frame ID 不使用开头斜杠，避免 RViz/TF2 对同一 frame 出现两种写法。
    return frame.strip().lstrip("/")


def global_fixed_frame_for(config: Dict[str, Any]) -> str:
    rviz_cfg = _rviz_config(config)
    frame = rviz_cfg.get("global_frame") or rviz_cfg.get("fixed_frame")
    if isinstance(frame, str) and frame.strip():
        return normalize_frame_id(frame)
    return DEFAULT_GLOBAL_FRAME


def follow_selected_robot_default(config: Dict[str, Any]) -> bool:
    rviz_cfg = _rviz_config(config)
    value = rviz_cfg.get("follow_selected_robot_frame", True)
    return bool(value)


def robot_fixed_frame_for(robot_id: str, config: Dict[str, Any]) -> str:
    clean_robot_id = robot_id.strip()
    if not clean_robot_id:
        return ""

    rviz_cfg = _rviz_config(config)
    robot_frames = rviz_cfg.get("robot_fixed_frames", {})
    if isinstance(robot_frames, dict):
        override = robot_frames.get(clean_robot_id)
        if isinstance(override, str) and override.strip():
            return normalize_frame_id(override)

    template = rviz_cfg.get("robot_frame_template", DEFAULT_ROBOT_FRAME_TEMPLATE)
    if not isinstance(template, str) or "{robot_id}" not in template:
        template = DEFAULT_ROBOT_FRAME_TEMPLATE

    try:
        formatted = template.format(robot_id=clean_robot_id)
    except (KeyError, IndexError, ValueError):
        # 配置模板只能引用 robot_id；误写其他占位符时回退到稳定默认值。
        formatted = DEFAULT_ROBOT_FRAME_TEMPLATE.format(robot_id=clean_robot_id)
    return normalize_frame_id(formatted)
