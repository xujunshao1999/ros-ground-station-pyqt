from __future__ import annotations

from typing import Any, Dict


def namespace_frame_id(frame_id: str, robot_id: str) -> str:
    """Prefix a ROS frame id with the robot namespace."""
    if not frame_id or not robot_id:
        return frame_id

    prefix = f"{robot_id}/"
    normalized = frame_id[1:] if frame_id.startswith("/") else frame_id
    if normalized.startswith(prefix):
        return normalized
    return prefix + normalized


def namespace_message_frames(data: Dict[str, Any], robot_id: str) -> None:
    """Namespace common frame fields in a ROS-message-like dictionary."""
    if not isinstance(data, dict):
        return

    header = data.get("header")
    if isinstance(header, dict):
        frame_id = header.get("frame_id")
        if isinstance(frame_id, str):
            header["frame_id"] = namespace_frame_id(frame_id, robot_id)

    child_frame_id = data.get("child_frame_id")
    if isinstance(child_frame_id, str):
        data["child_frame_id"] = namespace_frame_id(child_frame_id, robot_id)

    transforms = data.get("transforms")
    if isinstance(transforms, list):
        for transform in transforms:
            if isinstance(transform, dict):
                namespace_message_frames(transform, robot_id)
