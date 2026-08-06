"""从 ROS 消息类元数据生成有界递归字段结构。"""

from __future__ import annotations

from typing import Any, Dict, List

from agent.dict_to_ros_msg import _get_message_class, _parse_type_str

MAX_SCHEMA_DEPTH = 12
MAX_SCHEMA_FIELDS = 512


class MessageSchemaError(ValueError):
    """ROS 消息类型无法转换为安全 schema。"""


def build_message_schema(
    msg_type: str,
    max_depth: int = MAX_SCHEMA_DEPTH,
    max_fields: int = MAX_SCHEMA_FIELDS,
) -> Dict[str, Any]:
    """递归解析 ROS 消息字段，并限制深度与展开后的字段总数。"""
    field_count = 0
    stack: List[str] = []

    def build(type_name: str, depth: int) -> Dict[str, Any]:
        nonlocal field_count

        if depth > max_depth:
            raise MessageSchemaError(
                "schema depth exceeds %d at %s" % (max_depth, type_name)
            )
        if type_name in stack:
            raise MessageSchemaError("recursive message type: %s" % type_name)

        msg_class = _get_message_class(type_name)
        if msg_class is None:
            raise MessageSchemaError("unknown ROS message type: %s" % type_name)

        try:
            names = list(getattr(msg_class, "__slots__", []))
            types = list(getattr(msg_class, "_slot_types", []))
        except TypeError as exc:
            raise MessageSchemaError(
                "invalid slot metadata: %s" % type_name
            ) from exc
        if len(names) != len(types):
            raise MessageSchemaError("slot metadata mismatch: %s" % type_name)

        stack.append(type_name)
        fields: List[Dict[str, Any]] = []
        try:
            for name, raw_type in zip(names, types):
                if not isinstance(name, str) or not isinstance(raw_type, str):
                    raise MessageSchemaError(
                        "invalid slot metadata: %s" % type_name
                    )

                field_count += 1
                if field_count > max_fields:
                    raise MessageSchemaError(
                        "schema fields exceed %d at %s"
                        % (max_fields, type_name)
                    )

                try:
                    base_type, is_array, array_len = _parse_type_str(raw_type)
                except (TypeError, ValueError) as exc:
                    raise MessageSchemaError(
                        "invalid slot type %s in %s" % (raw_type, type_name)
                    ) from exc

                if base_type in {"time", "duration"}:
                    kind = base_type
                    nested_fields: List[Dict[str, Any]] = []
                elif "/" in base_type:
                    kind = "message"
                    nested_fields = build(base_type, depth + 1)["fields"]
                else:
                    kind = "primitive"
                    nested_fields = []

                fields.append({
                    "name": name,
                    "type": raw_type,
                    "base_type": base_type,
                    "kind": kind,
                    "is_array": is_array,
                    "array_len": array_len,
                    "fields": nested_fields,
                })
        finally:
            stack.pop()

        return {"type": type_name, "kind": "message", "fields": fields}

    return build(msg_type, 0)


__all__ = [
    "MAX_SCHEMA_DEPTH",
    "MAX_SCHEMA_FIELDS",
    "MessageSchemaError",
    "build_message_schema",
]
