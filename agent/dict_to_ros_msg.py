from __future__ import annotations

# ROS 消息通用反序列化器
#
# 将 ros_msg_to_dict 生成的 dict 还原为 ROS 消息对象。
# 利用 genpy.message.get_message_class 动态加载消息类，然后递归填充字段。
import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_WARNING_COUNTS: Dict[str, int] = {}
_MAX_WARNINGS = 3


def dict_to_ros_msg(
    data: dict,
    msg_type: str,
    strict: bool = False,
    field_path: str = "",
):
    """将 dict 还原为 ROS 消息对象。

    Args:
        data: ros_msg_to_dict 生成的 dict（或从 MQTT 接收的 dict）
        msg_type: ROS 消息类型名，例如 "sensor_msgs/Imu"
        strict: 是否拒绝无法安全转换的输入
        field_path: 递归转换时使用的字段路径

    Returns:
        填充了 data 中字段的 ROS 消息实例

    Raises:
        ValueError: 如果 msg_type 无法通过 genpy.message.get_message_class 解析
    """
    current_path = field_path or msg_type
    if strict and not isinstance(data, dict):
        raise ValueError(f"{current_path}: expected object")

    msg_class = _get_message_class(msg_type)
    if msg_class is None:
        raise ValueError(f"Unknown ROS message type: '{msg_type}'")

    msg = msg_class()
    slot_types_list = getattr(msg_class, "_slot_types", [])
    slot_names = msg.__slots__
    slots_set = frozenset(slot_names)

    if strict:
        for key in data:
            if key not in slots_set:
                raise ValueError(f"{current_path}.{key}: unknown field")

    for i, slot in enumerate(slot_names):
        if slot not in data:
            continue
        val = data[slot]
        type_str = slot_types_list[i] if i < len(slot_types_list) else ""
        converted = _convert_value(
            val,
            type_str,
            strict=strict,
            field_path=f"{current_path}.{slot}",
        )
        setattr(msg, slot, converted)

    for key in data:
        if key not in slots_set:
            _throttled_warn(
                f"Unknown field '{key}' in data for message type '{msg_type}'"
            )

    return msg


def _get_message_class(msg_type: str):
    """解析 ROS 消息类，并兼容测试中的 rospy mock。"""
    from genpy.message import get_message_class

    msg_class = get_message_class(msg_type)
    if msg_class is not None:
        return msg_class

    try:
        import rospy
    except ImportError:
        return None

    rospy_msg = getattr(rospy, "msg", None)
    rospy_get_message_class = getattr(rospy_msg, "get_message_class", None)
    if rospy_get_message_class is None:
        return None
    return rospy_get_message_class(msg_type)


def _convert_value(
    val: Any,
    type_str: str,
    strict: bool = False,
    field_path: str = "",
) -> Any:
    """根据 ROS 类型字符串将 Python 值转换为对应的 ROS 类型。"""
    import rospy

    if val is None:
        return None

    base_type, is_array, fixed_length = _parse_type_str(type_str)

    if is_array:
        if not isinstance(val, (list, tuple)):
            if strict:
                raise ValueError(f"{field_path}: expected array for '{type_str}'")
            return val

        if strict and fixed_length is not None and len(val) != fixed_length:
            raise ValueError(
                f"{field_path}: expected {fixed_length} items for '{type_str}', "
                f"got {len(val)}"
            )

        if base_type in ("uint8", "char", "byte") and fixed_length is None:
            if strict:
                for index, item in enumerate(val):
                    if isinstance(item, bool):
                        raise ValueError(
                            f"{field_path}[{index}]: bool is not valid for "
                            f"'{base_type}'"
                        )
            try:
                return bytes(b & 0xFF for b in val)
            except (TypeError, ValueError) as exc:
                if strict:
                    raise ValueError(
                        f"{field_path}: cannot convert value to '{type_str}'"
                    ) from exc
                return val

        if "/" in base_type:
            return [
                dict_to_ros_msg(
                    item,
                    base_type,
                    strict=strict,
                    field_path=f"{field_path}[{index}]",
                )
                for index, item in enumerate(val)
            ]

        if fixed_length is not None:
            return tuple(
                _convert_value(
                    item,
                    base_type,
                    strict=strict,
                    field_path=f"{field_path}[{index}]",
                )
                for index, item in enumerate(val)
            )

        return [
            _convert_value(
                item,
                base_type,
                strict=strict,
                field_path=f"{field_path}[{index}]",
            )
            for index, item in enumerate(val)
        ]

    if type_str == "time":
        if isinstance(val, dict):
            return rospy.Time(
                secs=val.get("secs", 0), nsecs=val.get("nsecs", 0)
            )
        return rospy.Time(secs=int(val))

    if type_str == "duration":
        if isinstance(val, dict):
            return rospy.Duration(
                secs=val.get("secs", 0), nsecs=val.get("nsecs", 0)
            )
        return rospy.Duration.from_sec(val)

    if "/" in type_str:
        if isinstance(val, dict):
            return dict_to_ros_msg(
                val,
                type_str,
                strict=strict,
                field_path=field_path,
            )
        if strict:
            raise ValueError(f"{field_path}: expected object for '{type_str}'")
        return val

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
        if strict and isinstance(val, bool):
            raise ValueError(f"{field_path}: bool is not valid for '{type_str}'")
        try:
            return float(val)
        except (TypeError, ValueError) as exc:
            if strict:
                raise ValueError(
                    f"{field_path}: cannot convert value to '{type_str}'"
                ) from exc
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
        if strict and isinstance(val, bool):
            raise ValueError(f"{field_path}: bool is not valid for '{type_str}'")
        try:
            return int(val)
        except (TypeError, ValueError) as exc:
            if strict:
                raise ValueError(
                    f"{field_path}: cannot convert value to '{type_str}'"
                ) from exc
            _throttled_warn(
                f"Cannot convert {type(val).__name__} to int for type '{type_str}'"
            )
            return val

    _throttled_warn(
        f"Unknown ROS type '{type_str}' for value of type {type(val).__name__}"
    )
    return val


def _parse_type_str(type_str: str) -> Tuple[str, bool, Optional[int]]:
    """解析 ROS 类型字符串。"""
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


__all__ = [
    "_WARNING_COUNTS",
    "_convert_value",
    "_parse_type_str",
    "dict_to_ros_msg",
]
