"""Custom ROS 指令的 Agent 侧协议边界校验。"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

MAX_CUSTOM_COMMAND_DATA_BYTES = 256 * 1024
_ROS_MESSAGE_TYPE_PATTERN = re.compile(
    r"^[A-Za-z][A-Za-z0-9_]*/[A-Za-z][A-Za-z0-9_]*$"
)


def validate_custom_command_params(
    topic: Any,
    msg_type: Any,
    data: Any,
) -> Optional[str]:
    """返回 custom 参数错误；合法时返回 None。"""
    if not isinstance(topic, str) or not topic.startswith("/"):
        return "Custom command topic must be a non-empty absolute ROS topic"
    if not isinstance(msg_type, str) or not _ROS_MESSAGE_TYPE_PATTERN.fullmatch(
        msg_type
    ):
        return "Custom command msg_type must use package/Message format"
    if not isinstance(data, dict):
        return "Custom command data must be an object"
    try:
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        return f"Custom command data must be JSON serializable: {exc}"
    if len(encoded) > MAX_CUSTOM_COMMAND_DATA_BYTES:
        return "Custom command data exceeds 256 KiB"
    return None


__all__ = [
    "MAX_CUSTOM_COMMAND_DATA_BYTES",
    "validate_custom_command_params",
]
