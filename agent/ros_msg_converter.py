from __future__ import annotations
"""
通用 ROS 消息序列化器

利用 __slots__ 内省递归遍历 ROS 消息字段，
将任意 ROS 消息转为 JSON 可序列化的 dict。
"""

import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# 基础类型：原样返回
_PRIMITIVES = (int, float, str, bool, type(None))


def ros_msg_to_dict(msg) -> Dict[str, Any]:
    """将任意 ROS 消息转为 JSON 可序列化的字典

    Args:
        msg: 包含 __slots__ 属性的 ROS 消息对象

    Returns:
        JSON 可序列化的字典
    """
    # 有 __slots__ 的消息对象 → 遍历槽位
    if hasattr(msg, "__slots__"):
        result: Dict[str, Any] = {}
        for slot in msg.__slots__:
            result[slot] = _serialize_value(getattr(msg, slot))
        return result

    # 回退：尝试转 str 再解析
    try:
        return json.loads(str(msg))
    except Exception:
        return {"raw": str(msg)}


def _serialize_value(val: Any) -> Any:
    """递归序列化单个字段值"""
    if isinstance(val, _PRIMITIVES):
        return val

    if isinstance(val, bytes):
        return list(val)

    if isinstance(val, (list, tuple)):
        return [_serialize_value(v) for v in val]

    if isinstance(val, dict):
        return {k: _serialize_value(v) for k, v in val.items()}

    # ROS time (有 secs 和 nsecs)
    if hasattr(val, "secs") and hasattr(val, "nsecs"):
        return {"secs": val.secs, "nsecs": val.nsecs}

    # ROS duration (有 to_sec 方法)
    if hasattr(val, "to_sec"):
        try:
            return val.to_sec()
        except Exception:
            pass

    # 嵌套 ROS 消息或有 __slots__ 的对象
    if hasattr(val, "__slots__"):
        return ros_msg_to_dict(val)

    # 未知类型兜底
    try:
        return str(val)
    except Exception:
        return repr(val)
