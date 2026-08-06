"""根据 ROS 消息 schema 生成默认数据并校验用户输入。"""

from __future__ import annotations

from typing import Any, Dict, List

_FLOAT_TYPES = {"float32", "float64", "float", "double"}
_INTEGER_TYPES = {
    "byte",
    "char",
    "int8",
    "uint8",
    "int16",
    "uint16",
    "int32",
    "uint32",
    "int64",
    "uint64",
}


def _default_scalar(field: Dict[str, Any]) -> Any:
    kind = field.get("kind")
    base_type = field.get("base_type")
    if kind == "message":
        return _default_fields(field.get("fields", []))
    if kind in ("time", "duration") or base_type in ("time", "duration"):
        return {"secs": 0, "nsecs": 0}
    if base_type == "bool":
        return False
    if base_type == "string":
        return ""
    if base_type in _FLOAT_TYPES:
        return 0.0
    if base_type in _INTEGER_TYPES:
        return 0
    return None


def _default_field(field: Dict[str, Any]) -> Any:
    if not field.get("is_array"):
        return _default_scalar(field)
    array_len = field.get("array_len")
    if not isinstance(array_len, int) or isinstance(array_len, bool):
        return []
    return [_default_scalar(field) for _ in range(array_len)]


def _default_fields(fields: Any) -> Dict[str, Any]:
    if not isinstance(fields, list):
        return {}
    defaults: Dict[str, Any] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        if isinstance(name, str) and name:
            defaults[name] = _default_field(field)
    return defaults


def default_data_for_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """为 schema 中每个字段递归生成 ROS 兼容的默认 Python 值。"""
    if not isinstance(schema, dict):
        return {}
    return _default_fields(schema.get("fields", []))


def _field_path(prefix: str, name: str) -> str:
    return "{}.{}".format(prefix, name) if prefix else name


def _validate_integer(path: str, value: Any, errors: List[str]) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        errors.append("{}: 需要整数".format(path))


def _validate_time_value(path: str, value: Any, errors: List[str]) -> None:
    if not isinstance(value, dict):
        errors.append("{}: 需要 object".format(path))
        return
    for name in ("secs", "nsecs"):
        if name in value:
            _validate_integer(_field_path(path, name), value[name], errors)
    for name in sorted(set(value) - {"secs", "nsecs"}, key=str):
        errors.append("{}: 未知字段".format(_field_path(path, str(name))))


def _validate_scalar(
    field: Dict[str, Any],
    value: Any,
    path: str,
    errors: List[str],
) -> None:
    kind = field.get("kind")
    base_type = field.get("base_type")
    if kind == "message":
        if not isinstance(value, dict):
            errors.append("{}: 需要 object".format(path))
            return
        _validate_fields(field.get("fields", []), value, path, errors)
        return
    if kind in ("time", "duration") or base_type in ("time", "duration"):
        _validate_time_value(path, value, errors)
        return
    if base_type == "bool":
        if not isinstance(value, bool):
            errors.append("{}: 需要布尔值".format(path))
        return
    if base_type == "string":
        if not isinstance(value, str):
            errors.append("{}: 需要字符串".format(path))
        return
    if base_type in _FLOAT_TYPES:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append("{}: 需要浮点数".format(path))
        return
    if base_type in _INTEGER_TYPES:
        _validate_integer(path, value, errors)
        return
    errors.append("{}: 不支持字段类型 {}".format(path, base_type))


def _validate_field(
    field: Dict[str, Any],
    value: Any,
    path: str,
    errors: List[str],
) -> None:
    if not field.get("is_array"):
        _validate_scalar(field, value, path, errors)
        return
    if not isinstance(value, list):
        errors.append("{}: 需要数组".format(path))
        return

    array_len = field.get("array_len")
    if isinstance(array_len, int) and not isinstance(array_len, bool):
        if len(value) != array_len:
            errors.append(
                "{}: 固定数组长度必须为 {}".format(path, array_len)
            )
    for index, item in enumerate(value):
        _validate_scalar(
            field,
            item,
            "{}[{}]".format(path, index),
            errors,
        )


def _validate_fields(
    fields: Any,
    data: Dict[str, Any],
    prefix: str,
    errors: List[str],
) -> None:
    if not isinstance(fields, list):
        return
    known_names = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = field.get("name")
        if not isinstance(name, str) or not name:
            continue
        known_names.add(name)
        if name in data:
            _validate_field(
                field,
                data[name],
                _field_path(prefix, name),
                errors,
            )
    for name in sorted(set(data) - known_names, key=str):
        errors.append("{}: 未知字段".format(_field_path(prefix, str(name))))


def validate_message_data(
    schema: Dict[str, Any],
    data: object,
) -> List[str]:
    """按 schema 递归校验 data，返回顺序稳定的中文字段路径错误。"""
    if not isinstance(data, dict):
        return ["$: 需要 object"]
    fields = schema.get("fields", []) if isinstance(schema, dict) else []
    errors: List[str] = []
    _validate_fields(fields, data, "", errors)
    return errors


__all__ = ["default_data_for_schema", "validate_message_data"]
