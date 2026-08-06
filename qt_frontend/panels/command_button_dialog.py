"""四槽位命令按钮设置对话框。"""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from qt_frontend.command_button_config import (
    MAX_COMMAND_SCHEMA_BYTES,
    SLOT_IDS,
    CommandButtonConfig,
    CommandButtonConfigError,
    CommandButtonConfigStore,
    empty_command_slots,
)
from qt_frontend.message_schema import validate_message_data
from qt_frontend.panels.message_form import MessageFormWidget
from qt_frontend.topic_catalog import RobotTopicCatalog


@dataclass
class _SlotDraft:
    label: str = ""
    topic: str = ""
    msg_type: str = ""
    json_text: str = "{}"
    schema: Dict[str, Any] = field(default_factory=dict)
    schema_status: str = "unverified"
    schema_error: str = ""
    active_tab: int = 1


@dataclass(frozen=True)
class _SchemaRequestContext:
    robot_id: str
    slot_id: str
    msg_type: str


class CommandButtonSettingsDialog(QDialog):
    """编辑四个固定命令按钮，并在保存时整批原子写入。"""

    discover_requested = pyqtSignal()
    schema_query_requested = pyqtSignal(str, str, str)

    def __init__(
        self,
        store: CommandButtonConfigStore,
        topic_catalog: RobotTopicCatalog,
        online_robot_ids: List[str],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._topic_catalog = topic_catalog
        self._online_robot_ids = sorted(set(online_robot_ids))
        self._pending_schema_requests: Dict[str, _SchemaRequestContext] = {}
        self._latest_schema_request_by_slot: Dict[str, str] = {}
        self._refreshed_slots: Set[str] = set()
        self._discover_requested_for_robot: Set[str] = set()
        self._cleared_slots: Set[str] = set()
        self._loading = False
        self._initializing = True
        self._current_slot_id = ""

        try:
            loaded_slots = self._store.load()
            self._load_error = ""
        except CommandButtonConfigError as exc:
            loaded_slots = empty_command_slots()
            self._load_error = str(exc)
        self._saved_slots = copy.deepcopy(loaded_slots)
        self._drafts = self._drafts_from_configs(loaded_slots)
        if not self._online_robot_ids:
            for draft in self._drafts.values():
                if draft is not None:
                    draft.schema_status = "unverified"

        self._build_ui()
        self._topic_catalog.topics_changed.connect(self._on_topics_changed)
        self._refresh_topic_options()
        self._slot_list.setCurrentRow(0)
        self._initializing = False

        QTimer.singleShot(0, self._initial_refresh)

    def select_slot(self, slot_id: str) -> None:
        for row in range(self._slot_list.count()):
            item = self._slot_list.item(row)
            if item.data(Qt.UserRole) == slot_id:
                self._slot_list.setCurrentRow(row)
                return

    def set_message_type(self, msg_type: str) -> None:
        self._msg_type_combo.setEditText(msg_type)
        self._on_message_type_finished()

    def current_message_type(self) -> str:
        return self._msg_type_combo.currentText().strip()

    def set_online_robot_ids(self, robot_ids: List[str]) -> None:
        old_representative = self._representative_robot()
        if old_representative and not robot_ids:
            self._capture_current_draft()
        self._online_robot_ids = sorted(set(robot_ids))
        representative = self._representative_robot()
        self._refresh_topic_options()
        if not representative:
            for draft in self._drafts.values():
                if draft is None:
                    continue
                draft.schema_status = "unverified"
                if draft.schema.get("type") != draft.msg_type:
                    draft.schema = {}
                    draft.active_tab = 1
            self._pending_schema_requests.clear()
            self._latest_schema_request_by_slot.clear()
            self._load_current_draft()
            return
        self._request_discover_if_needed(representative, deferred=False)
        if not old_representative and self._current_slot_id:
            self._refreshed_slots.discard(self._current_slot_id)
            self._refresh_slot_schema_once(self._current_slot_id)

    def on_schema_response(self, robot_id: str, data: Dict[str, Any]) -> None:
        request_id = data.get("request_id")
        if not isinstance(request_id, str):
            return
        context = self._pending_schema_requests.get(request_id)
        if context is None:
            return
        if context.slot_id == self._current_slot_id:
            self._capture_current_draft()
        draft = self._drafts.get(context.slot_id)
        response_type = data.get("msg_type")
        if (
            robot_id != context.robot_id
            or response_type != context.msg_type
            or draft is None
            or draft.msg_type != context.msg_type
            or self._latest_schema_request_by_slot.get(context.slot_id)
            != request_id
        ):
            return

        self._consume_request(request_id, context.slot_id)
        if data.get("result") != "ok":
            error = data.get("error")
            message = error if isinstance(error, str) and error else "消息结构查询失败"
            self._mark_schema_failure(context, message)
            return

        schema = data.get("schema")
        schema_error = self._schema_error(schema, context.msg_type)
        if schema_error:
            self._mark_schema_failure(context, schema_error)
            return

        draft.schema = copy.deepcopy(schema)
        draft.schema_status = "verified"
        draft.schema_error = ""
        if context.slot_id == self._current_slot_id:
            self._load_current_draft()

    def expire_schema_request(self, request_id: str) -> None:
        context = self._pending_schema_requests.get(request_id)
        if context is None:
            return
        if self._latest_schema_request_by_slot.get(context.slot_id) != request_id:
            self._pending_schema_requests.pop(request_id, None)
            return
        if context.slot_id == self._current_slot_id:
            self._capture_current_draft()
        self._consume_request(request_id, context.slot_id)
        self._mark_schema_failure(context, "消息结构查询超时")

    def current_schema(self) -> Dict[str, Any]:
        if self._current_slot_id:
            self._capture_current_draft()
        draft = self._drafts.get(self._current_slot_id)
        return copy.deepcopy(draft.schema if draft is not None else {})

    def saved_slots(self) -> Dict[str, Optional[CommandButtonConfig]]:
        return copy.deepcopy(self._saved_slots)

    def _build_ui(self) -> None:
        self.setWindowTitle("命令按钮设置")
        self.setMinimumSize(820, 580)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        body = QHBoxLayout()
        body.setSpacing(12)
        self._slot_list = QListWidget()
        self._slot_list.setFixedWidth(150)
        for index, slot_id in enumerate(SLOT_IDS, start=1):
            item = QListWidgetItem("位置 {}".format(index))
            item.setData(Qt.UserRole, slot_id)
            self._slot_list.addItem(item)
        self._slot_list.currentRowChanged.connect(self._on_slot_row_changed)
        body.addWidget(self._slot_list)

        editor = QWidget()
        editor_layout = QVBoxLayout(editor)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)
        metadata = QFormLayout()
        metadata.setHorizontalSpacing(12)
        metadata.setVerticalSpacing(7)
        metadata.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        self._label_edit = QLineEdit()
        self._label_edit.setMinimumHeight(30)
        self._label_edit.setPlaceholderText("按钮显示文字")
        metadata.addRow("显示字样", self._label_edit)

        self._topic_combo = QComboBox()
        self._topic_combo.setEditable(True)
        self._topic_combo.setMinimumHeight(30)
        self._topic_combo.setInsertPolicy(QComboBox.NoInsert)
        self._topic_combo.currentIndexChanged.connect(self._on_topic_selected)
        metadata.addRow("ROS 话题", self._topic_combo)

        self._msg_type_combo = QComboBox()
        self._msg_type_combo.setEditable(True)
        self._msg_type_combo.setMinimumHeight(30)
        self._msg_type_combo.setInsertPolicy(QComboBox.NoInsert)
        self._msg_type_combo.currentIndexChanged.connect(
            self._on_message_type_selected
        )
        self._msg_type_combo.lineEdit().editingFinished.connect(
            self._on_message_type_finished
        )
        metadata.addRow("消息类型", self._msg_type_combo)
        editor_layout.addLayout(metadata)

        self._status_label = QLabel()
        self._status_label.setWordWrap(True)
        self._status_label.setMinimumHeight(24)
        self._status_label.setProperty("muted", True)
        editor_layout.addWidget(self._status_label)

        self._tabs = QTabWidget()
        self._form = MessageFormWidget()
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QScrollArea.NoFrame)
        form_scroll.setWidget(self._form)
        self._json_edit = QPlainTextEdit()
        self._json_edit.setMinimumHeight(260)
        self._json_edit.setPlaceholderText("{}")
        self._tabs.addTab(form_scroll, "结构化表单")
        self._tabs.addTab(self._json_edit, "JSON")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        editor_layout.addWidget(self._tabs, 1)

        self._clear_button = QPushButton("清除此位置")
        self._clear_button.setToolTip("将当前按钮位置恢复为未配置状态")
        self._clear_button.clicked.connect(self._clear_current_slot)
        editor_layout.addWidget(self._clear_button, 0, Qt.AlignRight)
        body.addWidget(editor, 1)
        root.addLayout(body, 1)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        self._button_box.button(QDialogButtonBox.Save).setText("保存全部设置")
        self._button_box.button(QDialogButtonBox.Cancel).setText("取消")
        self._button_box.accepted.connect(self._save_all)
        self._button_box.rejected.connect(self.reject)
        root.addWidget(self._button_box)

    @staticmethod
    def _drafts_from_configs(
        slots: Dict[str, Optional[CommandButtonConfig]],
    ) -> Dict[str, Optional[_SlotDraft]]:
        drafts: Dict[str, Optional[_SlotDraft]] = {}
        for slot_id in SLOT_IDS:
            config = slots.get(slot_id)
            if config is None:
                drafts[slot_id] = None
                continue
            drafts[slot_id] = _SlotDraft(
                label=config.label,
                topic=config.topic,
                msg_type=config.msg_type,
                json_text=json.dumps(config.data, ensure_ascii=False, indent=2),
                schema=copy.deepcopy(config.schema),
                schema_status=config.schema_status,
                active_tab=0 if config.schema else 1,
            )
        return drafts

    def _on_slot_row_changed(self, row: int) -> None:
        if row < 0:
            return
        if self._current_slot_id:
            self._capture_current_draft()
        item = self._slot_list.item(row)
        self._current_slot_id = item.data(Qt.UserRole)
        self._load_current_draft()
        if not self._initializing:
            self._refresh_slot_schema_once(self._current_slot_id)

    def _capture_current_draft(self) -> None:
        if self._loading or not self._current_slot_id:
            return
        existing = self._drafts.get(self._current_slot_id)
        draft = copy.deepcopy(existing) if existing is not None else _SlotDraft()
        draft.label = self._label_edit.text()
        draft.topic = self._topic_combo.currentText()
        draft.msg_type = self._msg_type_combo.currentText()
        draft.active_tab = self._tabs.currentIndex()
        if draft.active_tab == 0:
            draft.json_text = json.dumps(
                self._form.data(),
                ensure_ascii=False,
                indent=2,
            )
        else:
            draft.json_text = self._json_edit.toPlainText()
        self._drafts[self._current_slot_id] = draft
        if not self._draft_is_empty(draft):
            self._cleared_slots.discard(self._current_slot_id)

    def _load_current_draft(self) -> None:
        draft = self._drafts.get(self._current_slot_id)
        data_error = ""
        self._loading = True
        try:
            self._label_edit.setText(draft.label if draft else "")
            self._topic_combo.setEditText(draft.topic if draft else "")
            self._msg_type_combo.setEditText(draft.msg_type if draft else "")
            self._json_edit.setPlainText(draft.json_text if draft else "{}")
            if draft and draft.schema:
                data = self._parse_json_object(draft.json_text)
                errors = (
                    validate_message_data(draft.schema, data)
                    if data is not None
                    else ["JSON 顶层必须是 object"]
                )
                if not errors:
                    self._form.set_schema(draft.schema, data)
                else:
                    self._form.set_schema(draft.schema, {})
                    draft.active_tab = 1
                    data_error = errors[0]
            else:
                self._form.set_schema({"fields": []}, {})
            tab_index = draft.active_tab if draft is not None else 1
            if not draft or not draft.schema:
                tab_index = 1
            self._tabs.setCurrentIndex(tab_index)
            self._update_status_label(draft)
            if data_error:
                self._status_label.setText(data_error)
        finally:
            self._loading = False

    def _on_tab_changed(self, index: int) -> None:
        if self._loading:
            return
        draft = self._drafts.get(self._current_slot_id)
        if draft is None:
            draft = _SlotDraft(
                label=self._label_edit.text(),
                topic=self._topic_combo.currentText(),
                msg_type=self._msg_type_combo.currentText(),
            )
            self._drafts[self._current_slot_id] = draft

        if index == 1:
            self._loading = True
            try:
                self._json_edit.setPlainText(
                    json.dumps(self._form.data(), ensure_ascii=False, indent=2)
                )
            finally:
                self._loading = False
            draft.json_text = self._json_edit.toPlainText()
            draft.active_tab = 1
            return

        draft.json_text = self._json_edit.toPlainText()
        if not draft.schema:
            self._restore_json_tab("没有可用的消息结构")
            return
        data = self._parse_json_object(draft.json_text)
        if data is None:
            self._restore_json_tab("JSON 顶层必须是 object")
            return
        errors = validate_message_data(draft.schema, data)
        if errors:
            self._restore_json_tab(errors[0])
            return
        self._form.set_schema(draft.schema, data)
        draft.active_tab = 0
        self._update_status_label(draft)

    def _restore_json_tab(self, message: str) -> None:
        self._loading = True
        try:
            self._tabs.setCurrentIndex(1)
        finally:
            self._loading = False
        draft = self._drafts.get(self._current_slot_id)
        if draft is not None:
            draft.active_tab = 1
        self._status_label.setText(message)

    def _on_topic_selected(self, index: int) -> None:
        if self._loading or index < 0:
            return
        msg_type = self._topic_combo.itemData(index)
        if isinstance(msg_type, str) and msg_type:
            self.set_message_type(msg_type)

    def _on_message_type_selected(self, index: int) -> None:
        if self._loading or index < 0:
            return
        self._on_message_type_finished()

    def _on_message_type_finished(self) -> None:
        if self._loading or not self._current_slot_id:
            return
        self._capture_current_draft()
        draft = self._drafts.get(self._current_slot_id)
        if draft is None:
            return
        draft.label = self._label_edit.text()
        draft.topic = self._topic_combo.currentText()
        draft.msg_type = self.current_message_type()
        if draft.schema.get("type") != draft.msg_type:
            draft.schema = {}
            draft.schema_status = "unverified"
            draft.active_tab = 1
        draft.schema_error = ""
        self._request_schema(self._current_slot_id, draft.msg_type)
        self._load_current_draft()

    def _request_schema(self, slot_id: str, msg_type: str) -> None:
        if not msg_type:
            return
        draft = self._drafts.get(slot_id)
        representative = self._representative_robot()
        if not representative:
            if draft is not None:
                draft.schema_status = "unverified"
                if draft.schema.get("type") != msg_type:
                    draft.schema = {}
                    draft.active_tab = 1
            return

        old_request = self._latest_schema_request_by_slot.get(slot_id)
        if old_request:
            self._pending_schema_requests.pop(old_request, None)
        request_id = uuid.uuid4().hex[:12]
        self._pending_schema_requests[request_id] = _SchemaRequestContext(
            robot_id=representative,
            slot_id=slot_id,
            msg_type=msg_type,
        )
        self._latest_schema_request_by_slot[slot_id] = request_id
        self.schema_query_requested.emit(representative, request_id, msg_type)
        QTimer.singleShot(
            5000,
            lambda rid=request_id: self.expire_schema_request(rid),
        )

    def _refresh_slot_schema_once(self, slot_id: str) -> None:
        if slot_id in self._refreshed_slots:
            return
        draft = self._drafts.get(slot_id)
        if draft is None or not draft.msg_type:
            return
        self._refreshed_slots.add(slot_id)
        self._request_schema(slot_id, draft.msg_type)

    def _initial_refresh(self) -> None:
        representative = self._representative_robot()
        if representative:
            self._request_discover_if_needed(representative, deferred=False)
        if self._current_slot_id:
            self._refresh_slot_schema_once(self._current_slot_id)

    def _representative_robot(self) -> str:
        return self._topic_catalog.representative_robot(self._online_robot_ids)

    def _request_discover_if_needed(self, robot_id: str, deferred: bool) -> None:
        if (
            not robot_id
            or self._topic_catalog.topics_for(robot_id)
            or robot_id in self._discover_requested_for_robot
        ):
            return
        self._discover_requested_for_robot.add(robot_id)
        if deferred:
            QTimer.singleShot(0, self.discover_requested.emit)
        else:
            self.discover_requested.emit()

    def _on_topics_changed(self, robot_id: str) -> None:
        if robot_id == self._representative_robot():
            self._refresh_topic_options()

    def _refresh_topic_options(self) -> None:
        topic_text = self._topic_combo.currentText() if hasattr(self, "_topic_combo") else ""
        type_text = (
            self._msg_type_combo.currentText()
            if hasattr(self, "_msg_type_combo")
            else ""
        )
        topics = self._topic_catalog.topics_for(self._representative_robot())
        if not hasattr(self, "_topic_combo"):
            return
        self._loading = True
        try:
            self._topic_combo.clear()
            self._msg_type_combo.clear()
            seen_types = set()
            for item in topics:
                topic = item["topic"]
                msg_type = item["msg_type"]
                self._topic_combo.addItem(topic, msg_type)
                if msg_type not in seen_types:
                    self._msg_type_combo.addItem(msg_type)
                    seen_types.add(msg_type)
            self._topic_combo.setCurrentIndex(-1)
            self._msg_type_combo.setCurrentIndex(-1)
            self._topic_combo.setEditText(topic_text)
            self._msg_type_combo.setEditText(type_text)
        finally:
            self._loading = False

    def _consume_request(self, request_id: str, slot_id: str) -> None:
        self._pending_schema_requests.pop(request_id, None)
        if self._latest_schema_request_by_slot.get(slot_id) == request_id:
            self._latest_schema_request_by_slot.pop(slot_id, None)

    def _mark_schema_failure(
        self,
        context: _SchemaRequestContext,
        message: str,
    ) -> None:
        draft = self._drafts.get(context.slot_id)
        if draft is None:
            return
        draft.schema_status = "unverified"
        draft.schema_error = message
        if draft.schema.get("type") != context.msg_type:
            draft.schema = {}
            draft.active_tab = 1
        if context.slot_id == self._current_slot_id:
            self._load_current_draft()

    @staticmethod
    def _schema_error(schema: Any, msg_type: str) -> str:
        if not isinstance(schema, dict):
            return "消息结构根节点必须是 object"
        try:
            size = len(
                json.dumps(
                    schema,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
        except (TypeError, ValueError):
            return "消息结构必须可编码为 JSON"
        if size > MAX_COMMAND_SCHEMA_BYTES:
            return "消息结构超过 256 KiB"
        if schema.get("type") != msg_type:
            return "消息结构 type 与请求类型不一致"
        if schema.get("kind") != "message":
            return "消息结构 kind 必须是 message"
        if not isinstance(schema.get("fields"), list):
            return "消息结构 fields 必须是 list"
        return ""

    def _update_status_label(self, draft: Optional[_SlotDraft]) -> None:
        if self._load_error:
            self._status_label.setText(self._load_error)
        elif draft is None:
            self._status_label.setText("未配置")
        elif draft.schema_error:
            self._status_label.setText(draft.schema_error)
        elif draft.schema_status == "verified":
            self._status_label.setText("已在线校验")
        elif draft.schema:
            self._status_label.setText("未经在线校验，使用缓存消息结构")
        else:
            self._status_label.setText("未经在线校验")

    def _clear_current_slot(self) -> None:
        if not self._current_slot_id:
            return
        request_id = self._latest_schema_request_by_slot.pop(
            self._current_slot_id, None
        )
        if request_id:
            self._pending_schema_requests.pop(request_id, None)
        self._drafts[self._current_slot_id] = None
        self._cleared_slots.add(self._current_slot_id)
        self._refreshed_slots.discard(self._current_slot_id)
        self._load_current_draft()

    def _save_all(self) -> None:
        self._capture_current_draft()
        slots = empty_command_slots()
        for slot_id in SLOT_IDS:
            draft = self._drafts.get(slot_id)
            if slot_id in self._cleared_slots or draft is None:
                slots[slot_id] = None
                continue
            if self._draft_is_empty(draft):
                slots[slot_id] = None
                continue
            try:
                data = json.loads(draft.json_text)
                if not isinstance(data, dict):
                    raise CommandButtonConfigError("JSON 顶层必须是 object")
                if draft.schema:
                    errors = validate_message_data(draft.schema, data)
                    if errors:
                        raise CommandButtonConfigError(errors[0])
                config = CommandButtonConfig(
                    label=draft.label,
                    topic=draft.topic,
                    msg_type=draft.msg_type,
                    data=data,
                    schema=copy.deepcopy(draft.schema),
                    schema_status=draft.schema_status,
                )
                config.to_dict()
                slots[slot_id] = config
            except (CommandButtonConfigError, TypeError, ValueError) as exc:
                self.select_slot(slot_id)
                self._status_label.setText(str(exc))
                return

        try:
            self._store.save(slots)
        except (CommandButtonConfigError, OSError) as exc:
            self._status_label.setText(str(exc))
            return
        self._saved_slots = copy.deepcopy(slots)
        self.accept()

    @staticmethod
    def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
        try:
            value = json.loads(text)
        except (TypeError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _draft_is_empty(draft: _SlotDraft) -> bool:
        if draft.label.strip() or draft.topic.strip() or draft.msg_type.strip():
            return False
        text = draft.json_text.strip()
        if not text:
            return True
        try:
            return json.loads(text) == {}
        except (TypeError, ValueError):
            return False


__all__ = ["CommandButtonSettingsDialog"]
