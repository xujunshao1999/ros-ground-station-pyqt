"""四槽位命令按钮配置模型和原子持久化。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

CONFIG_VERSION = 1
SLOT_IDS = ("slot_1", "slot_2", "slot_3", "slot_4")
MAX_COMMAND_DATA_BYTES = 256 * 1024
MAX_COMMAND_SCHEMA_BYTES = 256 * 1024
SCHEMA_STATUSES = ("verified", "unverified")
COMMAND_BUTTONS_FILE_HEADER = (
    "# 此文件由 ROS 地面站自动生成，请勿手工编辑。\n"
    "# 字段说明和 YAML 示例见 README.md 的“可配置命令按钮”章节。\n"
    "# 请通过地面站的命令按钮设置窗口修改配置。\n"
    "\n"
)


class CommandButtonConfigError(ValueError):
    """命令按钮配置格式无效。"""


def _json_size(value: Any, field_name: str) -> int:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CommandButtonConfigError(
            "{} 必须可编码为 JSON".format(field_name)
        ) from exc
    return len(encoded)


def _validate_msg_type(msg_type: Any) -> str:
    if not isinstance(msg_type, str):
        raise CommandButtonConfigError("msg_type 必须是字符串")
    normalized = msg_type.strip()
    parts = normalized.split("/")
    if len(parts) != 2 or not all(parts):
        raise CommandButtonConfigError("msg_type 必须使用 package/Type 格式")
    return normalized


def _validate_schema(
    schema: Any,
    msg_type: str,
    schema_status: str,
) -> Dict[str, Any]:
    if not isinstance(schema, dict):
        raise CommandButtonConfigError("schema 必须是 object")
    if _json_size(schema, "schema") > MAX_COMMAND_SCHEMA_BYTES:
        raise CommandButtonConfigError("schema 超过 256 KiB")
    if not schema:
        if schema_status == "verified":
            raise CommandButtonConfigError("verified 配置必须包含有效 schema")
        return {}

    if set(("type", "kind", "fields")) - set(schema):
        raise CommandButtonConfigError("schema 必须包含 type、kind 和 fields")
    if schema.get("type") != msg_type:
        raise CommandButtonConfigError("schema type 必须等于 msg_type")
    if schema.get("kind") != "message":
        raise CommandButtonConfigError("schema kind 必须是 message")
    if not isinstance(schema.get("fields"), list):
        raise CommandButtonConfigError("schema fields 必须是 list")
    return dict(schema)


@dataclass
class CommandButtonConfig:
    """一个固定命令按钮位置的持久化配置。"""

    label: str
    topic: str
    msg_type: str
    data: Dict[str, Any]
    schema: Dict[str, Any] = field(default_factory=dict)
    schema_status: str = "unverified"

    def to_dict(self) -> Dict[str, Any]:
        """校验并转换为可写入 YAML 的 mapping。"""
        if not isinstance(self.label, str):
            raise CommandButtonConfigError("label 必须是字符串")
        label = self.label.strip()
        if not 1 <= len(label) <= 64:
            raise CommandButtonConfigError("label 长度必须为 1 至 64")

        if not isinstance(self.topic, str):
            raise CommandButtonConfigError("topic 必须是字符串")
        topic = self.topic.strip()
        if not topic.startswith("/") or len(topic) > 255:
            raise CommandButtonConfigError("topic 必须以 / 开头且不超过 255 字符")

        msg_type = _validate_msg_type(self.msg_type)
        if not isinstance(self.data, dict):
            raise CommandButtonConfigError("data 必须是 object")
        if _json_size(self.data, "data") > MAX_COMMAND_DATA_BYTES:
            raise CommandButtonConfigError("data 超过 256 KiB")

        if self.schema_status not in SCHEMA_STATUSES:
            raise CommandButtonConfigError(
                "schema_status 必须是 verified 或 unverified"
            )
        schema = _validate_schema(self.schema, msg_type, self.schema_status)
        return {
            "label": label,
            "topic": topic,
            "msg_type": msg_type,
            "data": dict(self.data),
            "schema": schema,
            "schema_status": self.schema_status,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "CommandButtonConfig":
        """从 YAML mapping 构建并校验配置。"""
        if not isinstance(value, dict):
            raise CommandButtonConfigError("slot 配置必须是 object 或 null")
        required_fields = {"label", "topic", "msg_type", "data"}
        missing_fields = required_fields - set(value)
        if missing_fields:
            raise CommandButtonConfigError(
                "slot 配置缺少字段: {}".format(
                    ", ".join(sorted(missing_fields))
                )
            )
        config = cls(
            label=value["label"],
            topic=value["topic"],
            msg_type=value["msg_type"],
            data=value["data"],
            schema=value.get("schema", {}),
            schema_status=value.get("schema_status", "unverified"),
        )
        normalized = config.to_dict()
        return cls(**normalized)


def empty_command_slots() -> Dict[str, Optional[CommandButtonConfig]]:
    """返回顺序稳定的四个未配置位置。"""
    return {slot_id: None for slot_id in SLOT_IDS}


class CommandButtonConfigStore:
    """加载和原子保存命令按钮配置。"""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def load(self) -> Dict[str, Optional[CommandButtonConfig]]:
        if not self._path.exists():
            return empty_command_slots()
        return self._load_path(self._path)

    def save(
        self,
        slots: Mapping[str, Optional[CommandButtonConfig]],
    ) -> None:
        serialized_slots = self._serialize_complete_slots(slots)
        document = {
            "version": CONFIG_VERSION,
            "slots": serialized_slots,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=str(self._path.parent),
                prefix=".{}-".format(self._path.name),
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(COMMAND_BUTTONS_FILE_HEADER)
                yaml.safe_dump(
                    document,
                    handle,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

            # 临时文件必须走与正式加载相同的解析路径，避免替换进不可读配置。
            self._load_path(temp_path)
            os.replace(str(temp_path), str(self._path))
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _serialize_complete_slots(
        slots: Mapping[str, Optional[CommandButtonConfig]],
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        if not isinstance(slots, Mapping):
            raise CommandButtonConfigError("slots 必须是 mapping")
        unknown_slots = set(slots) - set(SLOT_IDS)
        if unknown_slots:
            raise CommandButtonConfigError(
                "未知 slot: {}".format(", ".join(sorted(unknown_slots)))
            )
        missing_slots = set(SLOT_IDS) - set(slots)
        if missing_slots:
            raise CommandButtonConfigError(
                "缺少 slot: {}".format(", ".join(sorted(missing_slots)))
            )

        serialized: Dict[str, Optional[Dict[str, Any]]] = {}
        for slot_id in SLOT_IDS:
            config = slots[slot_id]
            if config is not None and not isinstance(config, CommandButtonConfig):
                raise CommandButtonConfigError(
                    "{} 必须是 CommandButtonConfig 或 null".format(slot_id)
                )
            serialized[slot_id] = None if config is None else config.to_dict()
        return serialized

    @staticmethod
    def _load_path(
        path: Path,
    ) -> Dict[str, Optional[CommandButtonConfig]]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                document = yaml.safe_load(handle)
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise CommandButtonConfigError("无法读取命令按钮配置") from exc

        if not isinstance(document, dict):
            raise CommandButtonConfigError("配置根节点必须是 mapping")
        version = document.get("version")
        if type(version) is not int or version != CONFIG_VERSION:
            raise CommandButtonConfigError("不支持的配置 version")
        raw_slots = document.get("slots")
        if not isinstance(raw_slots, dict):
            raise CommandButtonConfigError("slots 必须是 mapping")

        unknown_slots = set(raw_slots) - set(SLOT_IDS)
        if unknown_slots:
            raise CommandButtonConfigError(
                "未知 slot: {}".format(", ".join(sorted(unknown_slots)))
            )

        loaded = empty_command_slots()
        for slot_id in SLOT_IDS:
            value = raw_slots.get(slot_id)
            if value is not None:
                loaded[slot_id] = CommandButtonConfig.from_dict(value)
        return loaded
