from __future__ import annotations

"""
ROS 消息通用反序列化器

将 ros_msg_to_dict 生成的 dict 还原为 ROS 消息对象。
利用 rospy.msg.get_message_class 动态加载消息类，然后递归填充字段。
"""

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_WARNING_COUNTS: Dict[str, int] = {}
_MAX_WARNINGS = 3


def dict_to_ros_msg(data: dict, msg_type: str):
    """将 dict 还原为 ROS 消息对象。

    Args:
        data: ros_msg_to_dict 生成的 dict（或从 MQTT 接收的 dict）
        msg_type: ROS 消息类型名，例如 "sensor_msgs/Imu"

    Returns:
        填充了 data 中字段的 ROS 消息实例

    Raises:
        ValueError: 如果 msg_type 无法通过 rospy.msg.get_message_class 解析
    """
    from genpy.message import get_message_class

    msg_class = get_message_class(msg_type)
    if msg_class is None:
        raise ValueError(f"Unknown ROS message type: '{msg_type}'")

    msg = msg_class()
    slot_types_list = getattr(msg_class, "_slot_types", [])
    slot_names = msg.__slots__
    slots_set = frozenset(slot_names)

    # 遍历消息槽位，从 data 中读取对应值
    for i, slot in enumerate(slot_names):
        if slot not in data:
            continue
        val = data[slot]
        type_str = slot_types_list[i] if i < len(slot_types_list) else ""
        converted = _convert_value(val, type_str)
        setattr(msg, slot, converted)

    # 警告 data 中的未知字段（不在 __slots__ 中）
    for key in data:
        if key not in slots_set:
            _throttled_warn(
                f"Unknown field '{key}' in data for message type '{msg_type}'"
            )

    return msg


def _convert_value(val: Any, type_str: str) -> Any:
    """根据 ROS 类型字符串将 Python 值转换为对应的 ROS 类型。"""
    import rospy

    if val is None:
        return None

    base_type, is_array, fixed_length = _parse_type_str(type_str)

    if is_array:
        if not isinstance(val, (list, tuple)):
            return val

        # uint8[] / char[] / byte[] may be represented as bytes in genpy.
        # int8[] must remain a list/tuple because signed values such as
        # OccupancyGrid.data can contain -1.
        if base_type in ("uint8", "char", "byte") and fixed_length is None:
            return bytes(b & 0xFF for b in val)

        # 嵌套消息数组
        if "/" in base_type:
            return [dict_to_ros_msg(item, base_type) for item in val]

        # 定长数组 → tuple (ROS 定长数组存储为 tuple)
        if fixed_length is not None:
            return tuple(_convert_value(v, base_type) for v in val)

        # 变长数组 → list
        return [_convert_value(v, base_type) for v in val]

    # time
    if type_str == "time":
        if isinstance(val, dict):
            return rospy.Time(
                secs=val.get("secs", 0), nsecs=val.get("nsecs", 0)
            )
        return rospy.Time(secs=int(val))

    # duration
    if type_str == "duration":
        if isinstance(val, dict):
            return rospy.Duration(
                secs=val.get("secs", 0), nsecs=val.get("nsecs", 0)
            )
        return rospy.Duration.from_sec(val)

    # 嵌套消息
    if "/" in type_str:
        if isinstance(val, dict):
            return dict_to_ros_msg(val, type_str)
        return val

    # 基本类型
    if type_str == "string":
        try:
            return str(val)
        except Exception:
            return val
    if type_str == "bool":
        try:
            return bool(val)
        except Exception:
            return val
    if type_str in ("float64", "float32", "float", "double"):
        try:
            return float(val)
        except (TypeError, ValueError):
            _throttled_warn(
                f"Cannot convert {type(val).__name__} to float for type '{type_str}'"
            )
            return val
    if type_str in (
        "int8",
        "uint8",
        "int16",
        "uint16",
        "int32",
        "uint32",
        "int64",
        "uint64",
        "char",
        "byte",
    ):
        try:
            return int(val)
        except (TypeError, ValueError):
            _throttled_warn(
                f"Cannot convert {type(val).__name__} to int for type '{type_str}'"
            )
            return val

    # 未知类型 → 透传 + 警告
    _throttled_warn(
        f"Unknown ROS type '{type_str}' for value of type {type(val).__name__}"
    )
    return val


def _parse_type_str(type_str: str) -> Tuple[str, bool, Optional[int]]:
    """解析 ROS 类型字符串。

    Examples:
        'float64'             → ('float64', False, None)
        'float64[]'           → ('float64', True,  None)
        'float64[36]'         → ('float64', True,  36)
        'sensor_msgs/Imu[]'   → ('sensor_msgs/Imu', True, None)
        'uint8[3]'            → ('uint8', True, 3)
    """
    if "[" in type_str:
        bracket_pos = type_str.index("[")
        base = type_str[:bracket_pos]
        rest = type_str[bracket_pos:]
        length_str = rest.strip("[]")
        if length_str:
            return base, True, int(length_str)
        return base, True, None
    return type_str, False, None


def _throttled_warn(msg: str, max_count: int = _MAX_WARNINGS) -> None:
    """限频警告，防止日志刷屏。"""
    if msg not in _WARNING_COUNTS:
        _WARNING_COUNTS[msg] = 0
    _WARNING_COUNTS[msg] += 1
    count = _WARNING_COUNTS[msg]
    if count <= max_count:
        logger.warning(msg)
    elif count == max_count + 1:
        logger.warning("%s (suppressing further warnings)", msg)
