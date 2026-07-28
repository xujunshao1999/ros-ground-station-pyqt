"""根据 ROS 消息 schema 递归生成结构化参数表单。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QLocale, QRegularExpression, pyqtSignal
from PyQt5.QtGui import QDoubleValidator, QRegularExpressionValidator
from PyQt5.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from qt_frontend.message_schema import (
    default_data_for_schema,
    validate_message_data,
)

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


def _path(prefix: str, name: str) -> str:
    return "{}.{}".format(prefix, name) if prefix else name


def _merge_defaults(defaults: Any, data: Any) -> Any:
    if not isinstance(defaults, dict) or not isinstance(data, dict):
        return data
    merged = dict(defaults)
    for key, value in data.items():
        if key in merged:
            merged[key] = _merge_defaults(merged[key], value)
    return merged


class MessageFormWidget(QWidget):
    """将消息 schema 映射为可递归编辑的 Qt 表单。"""

    data_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._schema: Dict[str, Any] = {"fields": []}
        self._field_widgets: Dict[str, QWidget] = {}
        self._content: Optional[QWidget] = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)

    def set_schema(
        self,
        schema: Dict[str, Any],
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """替换 schema，并用默认值补齐未提供的字段。"""
        self._schema = dict(schema) if isinstance(schema, dict) else {"fields": []}
        defaults = default_data_for_schema(self._schema)
        initial = _merge_defaults(defaults, data or {})
        if not isinstance(initial, dict):
            initial = defaults

        if self._content is not None:
            self._layout.removeWidget(self._content)
            self._content.deleteLater()
        self._field_widgets = {}
        self._content = QWidget(self)
        content_layout = QFormLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setHorizontalSpacing(10)
        content_layout.setVerticalSpacing(6)
        content_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self._build_fields(
            content_layout,
            self._schema.get("fields", []),
            initial,
            "",
        )
        self._layout.addWidget(self._content)

    def data(self) -> Dict[str, Any]:
        """读取当前控件值；语法无效的数组字段不会进入结果。"""
        data, _ = self._read_fields(self._schema.get("fields", []), "")
        return data

    def validation_errors(self) -> List[str]:
        """返回控件解析错误和 schema 数据错误。"""
        data, parsing_errors = self._read_fields(
            self._schema.get("fields", []), ""
        )
        return validate_message_data(self._schema, data) + parsing_errors

    def field_widget(self, path: str) -> Optional[QWidget]:
        return self._field_widgets.get(path)

    def _build_fields(
        self,
        layout: QFormLayout,
        fields: Any,
        data: Dict[str, Any],
        prefix: str,
    ) -> None:
        if not isinstance(fields, list):
            return
        for field in fields:
            if not isinstance(field, dict):
                continue
            name = field.get("name")
            if not isinstance(name, str) or not name:
                continue
            field_path = _path(prefix, name)
            value = data.get(name)

            if field.get("is_array"):
                editor = self._array_editor(value)
                self._field_widgets[field_path] = editor
                layout.addRow(self._label(field_path, field, editor), editor)
                continue

            kind = field.get("kind")
            base_type = field.get("base_type")
            if kind == "message":
                group, nested_layout = self._group(field_path, field)
                nested_data = value if isinstance(value, dict) else {}
                self._build_fields(
                    nested_layout,
                    field.get("fields", []),
                    nested_data,
                    field_path,
                )
                self._field_widgets[field_path] = group
                layout.addRow(group)
                continue
            if kind in ("time", "duration") or base_type in ("time", "duration"):
                group, nested_layout = self._group(field_path, field)
                time_data = value if isinstance(value, dict) else {}
                for part in ("secs", "nsecs"):
                    part_path = _path(field_path, part)
                    editor = self._numeric_editor(
                        time_data.get(part, 0),
                        "int32",
                    )
                    self._field_widgets[part_path] = editor
                    nested_layout.addRow(
                        self._label(part_path, {"type": "int32"}, editor),
                        editor,
                    )
                self._field_widgets[field_path] = group
                layout.addRow(group)
                continue

            editor = self._primitive_editor(field, value)
            self._field_widgets[field_path] = editor
            layout.addRow(self._label(field_path, field, editor), editor)

    def _label(
        self,
        field_path: str,
        field: Dict[str, Any],
        buddy: QWidget,
    ) -> QLabel:
        label = QLabel(field_path.rsplit(".", 1)[-1])
        label.setWordWrap(True)
        label.setToolTip(
            "{} ({})".format(field_path, field.get("type", "unknown"))
        )
        label.setBuddy(buddy)
        return label

    def _group(
        self,
        field_path: str,
        field: Dict[str, Any],
    ) -> Tuple[QGroupBox, QFormLayout]:
        group = QGroupBox(field_path.rsplit(".", 1)[-1])
        group.setToolTip(
            "{} ({})".format(field_path, field.get("type", "unknown"))
        )
        group.setCheckable(True)
        group.setChecked(True)
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(8, 8, 8, 8)
        content = QWidget(group)
        nested_layout = QFormLayout(content)
        nested_layout.setContentsMargins(0, 0, 0, 0)
        nested_layout.setHorizontalSpacing(10)
        nested_layout.setVerticalSpacing(6)
        nested_layout.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        group_layout.addWidget(content)
        group.toggled.connect(content.setVisible)
        return group, nested_layout

    def _array_editor(self, value: Any) -> QPlainTextEdit:
        editor = QPlainTextEdit()
        editor.setMinimumHeight(72)
        editor.setMaximumHeight(140)
        editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        try:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            text = "[]"
        editor.setPlainText(text)
        editor.textChanged.connect(self.data_changed)
        return editor

    def _numeric_editor(self, value: Any, base_type: str) -> QLineEdit:
        editor = QLineEdit(str(value))
        editor.setMinimumHeight(28)
        if base_type in _INTEGER_TYPES:
            expression = QRegularExpression(r"[+-]?\d+")
            editor.setValidator(QRegularExpressionValidator(expression, editor))
        else:
            validator = QDoubleValidator(editor)
            validator.setLocale(QLocale.c())
            validator.setNotation(QDoubleValidator.ScientificNotation)
            editor.setValidator(validator)
        editor.textChanged.connect(self.data_changed)
        return editor

    def _primitive_editor(
        self,
        field: Dict[str, Any],
        value: Any,
    ) -> QWidget:
        base_type = field.get("base_type")
        if base_type == "bool":
            editor = QCheckBox()
            editor.setMinimumHeight(28)
            editor.setChecked(bool(value))
            editor.toggled.connect(self.data_changed)
            return editor
        if base_type in _INTEGER_TYPES or base_type in _FLOAT_TYPES:
            return self._numeric_editor(value, base_type)

        editor = QLineEdit("" if value is None else str(value))
        editor.setMinimumHeight(28)
        if base_type != "string":
            editor.setPlaceholderText("不支持此类型，请使用 JSON 编辑")
        editor.textChanged.connect(self.data_changed)
        return editor

    def _read_fields(
        self,
        fields: Any,
        prefix: str,
    ) -> Tuple[Dict[str, Any], List[str]]:
        data: Dict[str, Any] = {}
        errors: List[str] = []
        if not isinstance(fields, list):
            return data, errors

        for field in fields:
            if not isinstance(field, dict):
                continue
            name = field.get("name")
            if not isinstance(name, str) or not name:
                continue
            field_path = _path(prefix, name)
            widget = self._field_widgets.get(field_path)
            if widget is None:
                continue

            if field.get("is_array"):
                text = widget.toPlainText()
                try:
                    data[name] = json.loads(text)
                except (TypeError, ValueError):
                    errors.append(
                        "{}: 需要有效的 JSON 数组".format(field_path)
                    )
                continue

            kind = field.get("kind")
            base_type = field.get("base_type")
            if kind == "message":
                nested, nested_errors = self._read_fields(
                    field.get("fields", []),
                    field_path,
                )
                data[name] = nested
                errors.extend(nested_errors)
            elif kind in ("time", "duration") or base_type in (
                "time",
                "duration",
            ):
                time_data: Dict[str, Any] = {}
                for part in ("secs", "nsecs"):
                    part_widget = self._field_widgets[_path(field_path, part)]
                    time_data[part] = self._line_value(part_widget, "int32")
                data[name] = time_data
            elif base_type == "bool":
                data[name] = widget.isChecked()
            elif base_type in _INTEGER_TYPES or base_type in _FLOAT_TYPES:
                data[name] = self._line_value(widget, base_type)
            else:
                data[name] = widget.text()
        return data, errors

    @staticmethod
    def _line_value(widget: QWidget, base_type: str) -> Any:
        text = widget.text()
        try:
            if base_type in _INTEGER_TYPES:
                return int(text)
            if base_type in _FLOAT_TYPES:
                return float(text)
        except ValueError:
            return text
        return text


__all__ = ["MessageFormWidget"]
