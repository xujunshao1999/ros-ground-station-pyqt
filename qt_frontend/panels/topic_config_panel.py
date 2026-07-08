from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass
class SubscriptionEntry:
    topic: str = ""
    msg_type: str = ""
    freq_limit: float = 0.0
    transport: str = "auto"
    qos: int = 1
    status: str = "pending"
    compression: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "msg_type": self.msg_type,
            "freq_limit": self.freq_limit,
            "transport": self.transport,
            "qos": self.qos,
            "status": self.status,
            "compression": dict(self.compression),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], status: str = "pending") -> "SubscriptionEntry":
        return cls(
            topic=data.get("topic", ""),
            msg_type=data.get("msg_type", ""),
            freq_limit=float(data.get("freq_limit") or 0.0),
            transport=data.get("transport", "auto"),
            qos=int(data.get("qos", 1)),
            status=data.get("status", status),
            compression=dict(data.get("compression") or data.get("options") or {}),
        )


class TopicConfigPanel(QWidget):
    config_changed = pyqtSignal()
    topic_request_requested = pyqtSignal(str, dict)  # (robot_id, request)
    config_sync_requested = pyqtSignal(str, dict)  # (robot_id, config)
    config_query_requested = pyqtSignal(str)  # robot_id
    discover_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._entries: List[SubscriptionEntry] = []
        self._available_topics_by_robot: Dict[str, List[Dict[str, Any]]] = {}
        self._pending_config_operation = ""
        self._pending_topic_operations: Dict[str, str] = {}
        self._editing_topic = ""
        self._transmit_config_path = (
            Path(__file__).resolve().parents[1] / "config" / "transmit_config.yaml"
        )

        layout = QVBoxLayout(self)

        # 机器人选择
        robot_row = QHBoxLayout()
        robot_row.addWidget(QLabel("目标机器人:"))
        self._robot_combo = QComboBox()
        self._robot_combo.currentIndexChanged.connect(self._load_selected_robot_config)
        robot_row.addWidget(self._robot_combo)
        layout.addLayout(robot_row)

        # 订阅表
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["话题", "类型", "频率(Hz)", "传输方式", "状态"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._load_selected_entry_into_form)
        layout.addWidget(self._table)

        # 按钮行
        btn_row1 = QHBoxLayout()
        self._btn_add = QPushButton("+ 添加话题")
        self._btn_delete = QPushButton("删除")
        self._btn_save = QPushButton("保存草稿")
        self._btn_add.clicked.connect(self._show_add_form)
        self._btn_delete.clicked.connect(self._delete_selected_entry)
        self._btn_save.clicked.connect(self._save_config)
        for btn in [self._btn_add, self._btn_delete, self._btn_save]:
            btn_row1.addWidget(btn)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self._btn_deploy = QPushButton("保存并下发")
        self._btn_deploy.setStyleSheet("QPushButton { font-weight: bold; }")
        self._btn_deploy.clicked.connect(self._deploy_config)
        btn_row2.addWidget(self._btn_deploy)
        self._btn_pull = QPushButton("从机器人拉取话题")
        self._btn_pull.clicked.connect(self._pull_config)
        btn_row2.addWidget(self._btn_pull)
        layout.addLayout(btn_row2)

        self._operation_status = QLabel("")
        self._operation_status.setWordWrap(True)
        self._operation_status.setVisible(False)
        layout.addWidget(self._operation_status)

        # 添加/编辑表单（可折叠）
        self._form_group = QGroupBox("添加话题")
        self._form_group.setCheckable(True)
        self._form_group.setChecked(False)
        form = QVBoxLayout(self._form_group)

        available_row = QHBoxLayout()
        available_row.addWidget(QLabel("机器人话题:"))
        self._combo_available_topics = QComboBox()
        self._combo_available_topics.addItem("-- 选择机器人话题 --", None)
        self._combo_available_topics.currentIndexChanged.connect(
            self._on_available_topic_selected
        )
        available_row.addWidget(self._combo_available_topics)
        form.addLayout(available_row)

        f1 = QHBoxLayout()
        f1.addWidget(QLabel("ROS 话题:"))
        self._edit_topic = QLineEdit()
        self._edit_topic.setPlaceholderText("/example/topic")
        f1.addWidget(self._edit_topic)
        form.addLayout(f1)

        f2 = QHBoxLayout()
        f2.addWidget(QLabel("ROS 类型:"))
        self._combo_msg_type = QComboBox()
        self._combo_msg_type.setEditable(True)
        self._combo_msg_type.addItems([
            "sensor_msgs/Imu", "sensor_msgs/NavSatFix", "nav_msgs/Odometry",
            "geometry_msgs/Twist", "sensor_msgs/Image", "sensor_msgs/CompressedImage",
            "sensor_msgs/LaserScan", "sensor_msgs/PointCloud2",
        ])
        f2.addWidget(self._combo_msg_type)
        form.addLayout(f2)

        f3 = QHBoxLayout()
        f3.addWidget(QLabel("传输层级:"))
        self._combo_transport = QComboBox()
        self._combo_transport.addItems([
            "AUTO",
            "LIGHT (mqtt_json)",
            "MEDIUM (mqtt_binary)",
            "HEAVY (http_stream)",
        ])
        f3.addWidget(self._combo_transport)
        form.addLayout(f3)

        self._transport_preview = QLabel("预计传输方式：-")
        self._transport_preview.setWordWrap(True)
        form.addWidget(self._transport_preview)

        f4 = QHBoxLayout()
        f4.addWidget(QLabel("频率上限(Hz):"))
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(0, 1000)
        self._spin_freq.setValue(0)
        self._spin_freq.setSuffix(" Hz")
        self._spin_freq.setSpecialValueText("不限")
        f4.addWidget(self._spin_freq)
        form.addLayout(f4)

        f5 = QHBoxLayout()
        f5.addWidget(QLabel("QoS:"))
        self._combo_qos = QComboBox()
        for label, value in self.qos_options():
            self._combo_qos.addItem(label, value)
        f5.addWidget(self._combo_qos)
        form.addLayout(f5)

        self._btn_confirm = QPushButton("确认")
        self._btn_cancel = QPushButton("取消")
        self._btn_confirm.clicked.connect(self._confirm_entry)
        self._btn_cancel.clicked.connect(self._hide_form)
        self._combo_msg_type.currentTextChanged.connect(self._update_transport_preview)
        self._combo_transport.currentIndexChanged.connect(self._update_transport_preview)
        form_row = QHBoxLayout()
        form_row.addWidget(self._btn_confirm)
        form_row.addWidget(self._btn_cancel)
        form.addLayout(form_row)

        layout.addWidget(self._form_group)
        self._refresh_table()

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def validate_topic(topic: str) -> bool:
        return topic.startswith("/") and len(topic) > 1

    @staticmethod
    def validate_msg_type(msg_type: str) -> bool:
        return "/" in msg_type and len(msg_type) > 3

    @staticmethod
    def transport_from_tier(tier: str) -> str:
        tier_upper = tier.upper()
        if tier_upper == "LIGHT":
            return "mqtt_json"
        elif tier_upper == "MEDIUM":
            return "mqtt_binary"
        elif tier_upper == "HEAVY":
            return "http_stream"
        return "mqtt_json"

    @staticmethod
    def predicted_transport_for_msg_type(msg_type: str) -> str:
        """按协议注册表预测 AUTO 最终会解析成的传输方式。"""
        from protocol.topic_registry import default_registry

        return default_registry.get_transport_type(msg_type)

    @staticmethod
    def qos_options() -> List[Tuple[str, int]]:
        return [
            ("QoS 0 - 最多一次：低延迟，允许丢包，适合高频传感器数据", 0),
            ("QoS 1 - 至少一次：保证到达，可能重复，适合指令和配置", 1),
            ("QoS 2 - 恰好一次：避免重复，开销最大，通常不建议高频使用", 2),
        ]

    @staticmethod
    def build_topic_request(action: str, entry: SubscriptionEntry) -> Dict[str, Any]:
        data = entry.to_dict()
        data["action"] = action
        return data

    @staticmethod
    def replace_entry_for_edit(
        entries: List[SubscriptionEntry],
        original_topic: str,
        updated_entry: SubscriptionEntry,
    ) -> List[SubscriptionEntry]:
        replaced = False
        result: List[SubscriptionEntry] = []
        for entry in entries:
            if entry.topic == original_topic and not replaced:
                result.append(updated_entry)
                replaced = True
                continue
            if entry.topic == updated_entry.topic:
                continue
            result.append(entry)
        if not replaced:
            result.append(updated_entry)
        return result

    @staticmethod
    def build_edit_topic_requests(
        original_topic: str, updated_entry: SubscriptionEntry
    ) -> List[Dict[str, Any]]:
        if original_topic and original_topic != updated_entry.topic:
            return [
                TopicConfigPanel.build_topic_request(
                    "unsubscribe",
                    SubscriptionEntry(topic=original_topic),
                ),
                TopicConfigPanel.build_topic_request("subscribe", updated_entry),
            ]
        return [
            TopicConfigPanel.build_topic_request("subscribe", updated_entry),
        ]

    @staticmethod
    def apply_local_entry_change(
        entries: List[SubscriptionEntry],
        original_topic: str,
        updated_entry: SubscriptionEntry,
    ) -> List[SubscriptionEntry]:
        updated_entry.status = "pending"
        if original_topic:
            return TopicConfigPanel.replace_entry_for_edit(
                entries, original_topic, updated_entry
            )
        return [e for e in entries if e.topic != updated_entry.topic] + [updated_entry]

    @staticmethod
    def entry_to_protocol_dict(entry: SubscriptionEntry) -> Dict[str, Any]:
        return {
            "topic": entry.topic,
            "msg_type": entry.msg_type,
            "freq_limit": entry.freq_limit,
            "transport": entry.transport,
            "qos": entry.qos,
            "compression": dict(entry.compression),
        }

    @staticmethod
    def build_config_sync_payload(entries: List[SubscriptionEntry]) -> Dict[str, Any]:
        return {
            "subscriptions": [
                TopicConfigPanel.entry_to_protocol_dict(entry)
                for entry in entries
            ]
        }

    @staticmethod
    def entries_from_config_response(data: Dict[str, Any]) -> List[SubscriptionEntry]:
        return [
            SubscriptionEntry.from_dict(sub, status="active")
            for sub in data.get("subscriptions", [])
            if sub.get("topic")
        ]

    @staticmethod
    def entries_from_available_topics(topics: List[Dict[str, Any]]) -> List[SubscriptionEntry]:
        return [
            SubscriptionEntry(
                topic=item.get("topic", ""),
                msg_type=item.get("msg_type", ""),
                status="available",
            )
            for item in topics
            if item.get("topic") and item.get("msg_type")
        ]

    @staticmethod
    def update_available_topics_cache(
        cache: Dict[str, List[Dict[str, Any]]],
        robot_id: str,
        data: Dict[str, Any],
    ) -> None:
        topics = [
            {
                "topic": item.get("topic", ""),
                "msg_type": item.get("msg_type") or item.get("type", ""),
            }
            for item in data.get("topics", [])
            if item.get("topic") and (item.get("msg_type") or item.get("type"))
        ]
        cache[robot_id] = topics

    @staticmethod
    def build_transmit_config(
        existing: Dict[str, Any],
        robot_id: str,
        entries: List[SubscriptionEntry],
    ) -> Dict[str, Any]:
        config = dict(existing)
        subscriptions = TopicConfigPanel.normalize_transmit_subscriptions(
            config.get("subscriptions") or {}
        )
        robot_subscriptions = [
            TopicConfigPanel.entry_to_protocol_dict(entry)
            for entry in entries
        ]

        subscriptions[robot_id] = robot_subscriptions
        config["subscriptions"] = subscriptions
        return config

    @staticmethod
    def normalize_transmit_subscriptions(raw: Any) -> Dict[str, List[Dict[str, Any]]]:
        if not isinstance(raw, dict):
            return {}

        normalized: Dict[str, List[Dict[str, Any]]] = {}
        for robot_id, robot_subscriptions in raw.items():
            entries: List[Dict[str, Any]] = []
            if isinstance(robot_subscriptions, list):
                for item in robot_subscriptions:
                    if isinstance(item, dict) and item.get("topic"):
                        entries.append(dict(item))
            elif isinstance(robot_subscriptions, dict):
                for topic, sub_info in robot_subscriptions.items():
                    if not isinstance(sub_info, dict):
                        continue
                    data = dict(sub_info)
                    data["topic"] = topic
                    entries.append(data)
            normalized[robot_id] = entries
        return normalized

    @staticmethod
    def entries_from_transmit_config(
        config: Dict[str, Any], robot_id: str
    ) -> List[SubscriptionEntry]:
        subscriptions = TopicConfigPanel.normalize_transmit_subscriptions(
            config.get("subscriptions") or {}
        )
        robot_subscriptions = subscriptions.get(robot_id, [])
        entries: List[SubscriptionEntry] = []
        for sub_info in robot_subscriptions:
            data = dict(sub_info or {})
            entries.append(SubscriptionEntry.from_dict(data, status="saved"))
        return entries

    @staticmethod
    def load_transmit_config_file(path: Union[str, Path]) -> Dict[str, Any]:
        p = Path(path)
        if not p.exists():
            return {"subscriptions": {}}
        with open(p, "r", encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
        return loaded if isinstance(loaded, dict) else {"subscriptions": {}}

    @staticmethod
    def save_transmit_config_file(
        path: Union[str, Path],
        robot_id: str,
        entries: List[SubscriptionEntry],
    ) -> Dict[str, Any]:
        p = Path(path)
        existing = TopicConfigPanel.load_transmit_config_file(p)
        config = TopicConfigPanel.build_transmit_config(existing, robot_id, entries)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                config,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )
        return config

    @staticmethod
    def apply_topic_response_to_entries(
        entries: List[SubscriptionEntry], data: Dict[str, Any]
    ) -> None:
        topic = data.get("topic", "")
        result = data.get("result", "")
        action = data.get("action", "")
        for entry in entries:
            if entry.topic != topic:
                continue
            if result == "ok" and action == "unsubscribe":
                entry.status = "inactive"
            elif result == "ok":
                entry.status = "active"
            else:
                entry.status = "failed"
            return

    @staticmethod
    def should_reload_saved_config(previous_robot_id: str, current_robot_id: str) -> bool:
        return previous_robot_id != current_robot_id

    @staticmethod
    def target_robot_after_refresh(
        previous_robot_id: str, current_text: str, robot_ids: List[str]
    ) -> str:
        if previous_robot_id:
            return previous_robot_id
        if current_text and not current_text.startswith("--"):
            return current_text
        if len(robot_ids) == 1:
            return robot_ids[0]
        return ""

    @staticmethod
    def should_request_available_topics(
        cache: Dict[str, List[Dict[str, Any]]], robot_id: str
    ) -> bool:
        return bool(robot_id) and not cache.get(robot_id)

    @staticmethod
    def should_load_selected_entry(row: int, count: int) -> bool:
        return 0 <= row < count

    @staticmethod
    def mark_entries_saved(entries: List[SubscriptionEntry]) -> None:
        for entry in entries:
            if entry.status != "failed":
                entry.status = "saved"

    @staticmethod
    def build_operation_result(level: str, message: str) -> Dict[str, str]:
        if level not in ("success", "error", "info"):
            return {
                "level": "error",
                "message": f"未知操作结果：{message}",
            }
        return {"level": level, "message": message}

    @staticmethod
    def config_response_failed(data: Dict[str, Any]) -> str:
        result = str(data.get("result", "")).lower()
        if result not in ("failed", "error"):
            return ""
        return str(data.get("message") or "机器人返回配置失败")

    @staticmethod
    def topic_response_result(
        pending_operations: Dict[str, str], data: Dict[str, Any]
    ) -> Dict[str, str]:
        topic = data.get("topic", "")
        result = data.get("result", "")
        action = data.get("action", "")
        operation = pending_operations.pop(topic, "")

        if result == "ok":
            if operation == "rename_remove":
                return {}
            if action == "unsubscribe":
                return {
                    "level": "success",
                    "message": f"删除话题成功：{topic}",
                }
            if operation == "edit":
                return {
                    "level": "success",
                    "message": f"更新话题成功：{topic}",
                }
            if operation == "add" or action == "subscribe":
                return {
                    "level": "success",
                    "message": f"添加话题成功：{topic}",
                }
        elif result:
            message = data.get("message") or "机器人返回话题配置失败"
            return {
                "level": "error",
                "message": f"话题配置失败：{topic}，{message}",
            }
        return {}

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def on_robot_list_changed(self, robot_ids: List[str]) -> None:
        previous_robot_id = self._selected_robot_id()
        current = self.target_robot_after_refresh(
            previous_robot_id, self._robot_combo.currentText(), robot_ids
        )
        self._robot_combo.blockSignals(True)
        self._robot_combo.clear()
        self._robot_combo.addItem("-- 选择 --", "")
        for robot_id in robot_ids:
            self._robot_combo.addItem(robot_id, robot_id)
        if current:
            idx = self._robot_combo.findData(current)
            if idx >= 0:
                self._robot_combo.setCurrentIndex(idx)
        self._robot_combo.blockSignals(False)
        current_robot_id = self._selected_robot_id()
        if self.should_reload_saved_config(previous_robot_id, current_robot_id):
            self._load_selected_robot_config()
        else:
            self._refresh_available_topics()

    def on_topic_response(self, robot_id: str, data: dict) -> None:
        if robot_id != self._selected_robot_id():
            return
        self.apply_topic_response_to_entries(self._entries, data)
        self._refresh_table()
        response_result = self.topic_response_result(
            self._pending_topic_operations, data
        )
        if response_result:
            self._set_operation_result(
                response_result["level"], response_result["message"]
            )

    def on_config_response(self, robot_id: str, data: dict) -> None:
        if robot_id != self._selected_robot_id():
            return
        failed_message = self.config_response_failed(data)
        if failed_message:
            operation = self._pending_config_operation or "配置同步"
            self._pending_config_operation = ""
            self._set_operation_result("error", f"{operation}失败：{failed_message}")
            return
        self._entries = self.entries_from_config_response(data)
        self._refresh_table()
        self.config_changed.emit()
        count = len(self._entries)
        if self._pending_config_operation == "下发配置":
            self._set_operation_result(
                "success", f"保存并下发成功：{robot_id}，机器人确认 {count} 个话题"
            )
        else:
            self._set_operation_result(
                "success", f"拉取配置成功：{robot_id}，{count} 个话题"
            )
        self._pending_config_operation = ""

    def on_discover_response(self, robot_id: str, data: dict) -> None:
        self.update_available_topics_cache(
            self._available_topics_by_robot, robot_id, data
        )
        if robot_id == self._selected_robot_id():
            self._refresh_available_topics()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _selected_robot_id(self) -> str:
        return self._robot_combo.currentData() or ""

    def _refresh_table(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            values = [
                entry.topic,
                entry.msg_type,
                f"{entry.freq_limit:g}" if entry.freq_limit else "不限",
                entry.transport,
                entry.status,
            ]
            for col, value in enumerate(values):
                self._table.setItem(row, col, QTableWidgetItem(value))
        self._table.blockSignals(False)

    def _refresh_available_topics(self) -> None:
        robot_id = self._selected_robot_id()
        topics = self._available_topics_by_robot.get(robot_id, [])
        if not topics:
            topics = [
                {"topic": entry.topic, "msg_type": entry.msg_type}
                for entry in self._entries
                if entry.topic and entry.msg_type
            ]
        self._combo_available_topics.blockSignals(True)
        self._combo_available_topics.clear()
        self._combo_available_topics.addItem("-- 选择机器人话题 --", None)
        for entry in self.entries_from_available_topics(topics):
            label = f"{entry.topic}  ({entry.msg_type})"
            self._combo_available_topics.addItem(label, entry.to_dict())
        self._combo_available_topics.blockSignals(False)

    def _show_add_form(self) -> None:
        self._editing_topic = ""
        self._form_group.setTitle("添加话题")
        self._btn_confirm.setText("确认")
        self._table.blockSignals(True)
        self._table.clearSelection()
        self._table.setCurrentCell(-1, -1)
        self._table.blockSignals(False)
        self._clear_operation_result()
        self._refresh_available_topics()
        robot_id = self._selected_robot_id()
        if self.should_request_available_topics(
            self._available_topics_by_robot, robot_id
        ):
            self.discover_requested.emit()
            self._set_operation_result(
                "info", f"正在获取 {robot_id} 的可订阅话题"
            )
        self._edit_topic.clear()
        self._combo_msg_type.setCurrentText("")
        self._combo_transport.setCurrentIndex(0)
        self._combo_qos.setCurrentIndex(1)
        self._spin_freq.setValue(0.0)
        self._form_group.setChecked(True)
        self._update_transport_preview()

    def _hide_form(self) -> None:
        self._editing_topic = ""
        self._form_group.setTitle("添加话题")
        self._btn_confirm.setText("确认")
        self._form_group.setChecked(False)

    def _entry_from_form(self) -> Optional[SubscriptionEntry]:
        topic = self._edit_topic.text().strip()
        msg_type = self._combo_msg_type.currentText().strip()
        if not self.validate_topic(topic) or not self.validate_msg_type(msg_type):
            return None

        transport = self._combo_transport.currentText().split()[0].lower()
        if transport == "auto":
            transport_value = "auto"
        else:
            transport_value = self.transport_from_tier(transport)

        qos_data = self._combo_qos.currentData()
        qos = 1 if qos_data is None else int(qos_data)

        return SubscriptionEntry(
            topic=topic,
            msg_type=msg_type,
            freq_limit=float(self._spin_freq.value()),
            transport=transport_value,
            qos=qos,
            status="pending",
            compression={},
        )

    def _on_available_topic_selected(self) -> None:
        data = self._combo_available_topics.currentData()
        if not isinstance(data, dict):
            self._update_transport_preview()
            return
        self._edit_topic.setText(data.get("topic", ""))
        self._combo_msg_type.setCurrentText(data.get("msg_type", ""))
        self._update_transport_preview()

    def _update_transport_preview(self) -> None:
        msg_type = self._combo_msg_type.currentText().strip()
        selected = self._combo_transport.currentText().split()[0].lower()
        if not msg_type:
            self._transport_preview.setText("预计传输方式：-")
            return
        if selected == "auto":
            # AUTO 预览使用协议注册表，和保存/下发时的默认策略保持一致。
            transport = self.predicted_transport_for_msg_type(msg_type)
            self._transport_preview.setText("预计传输方式：%s" % transport)
            return
        self._transport_preview.setText(
            "已手动选择：%s" % self.transport_from_tier(selected)
        )

    def _set_transport_combo(self, transport: str) -> None:
        mapping = {
            "auto": 0,
            "mqtt_json": 1,
            "mqtt_binary": 2,
            "http_stream": 3,
        }
        self._combo_transport.setCurrentIndex(mapping.get(transport, 0))

    def _set_qos_combo(self, qos: int) -> None:
        idx = self._combo_qos.findData(qos)
        self._combo_qos.setCurrentIndex(idx if idx >= 0 else 1)

    def _load_selected_entry_into_form(self) -> None:
        row = self._table.currentRow()
        if not self.should_load_selected_entry(row, len(self._entries)):
            return
        entry = self._entries[row]
        self._editing_topic = entry.topic
        self._form_group.setTitle("编辑话题")
        self._btn_confirm.setText("更新")
        self._edit_topic.setText(entry.topic)
        self._combo_msg_type.setCurrentText(entry.msg_type)
        self._set_transport_combo(entry.transport)
        self._set_qos_combo(entry.qos)
        self._spin_freq.setValue(float(entry.freq_limit or 0.0))
        self._form_group.setChecked(True)
        self._set_operation_result("info", f"正在编辑话题：{entry.topic}")
        self._update_transport_preview()

    def _set_operation_result(self, level: str, message: str) -> None:
        result = self.build_operation_result(level, message)
        styles = {
            "success": "color: #0f7b3f;",
            "error": "color: #b42318;",
            "info": "color: #475467;",
        }
        self._operation_status.setText(result["message"])
        self._operation_status.setStyleSheet(styles.get(result["level"], styles["error"]))
        self._operation_status.setVisible(True)

    def _clear_operation_result(self) -> None:
        self._operation_status.clear()
        self._operation_status.setVisible(False)

    def _confirm_entry(self) -> None:
        entry = self._entry_from_form()
        robot_id = self._selected_robot_id()
        if entry is None or not robot_id:
            self._set_operation_result("error", "添加话题失败：请选择机器人并填写有效话题")
            return

        original_topic = self._editing_topic
        is_edit = bool(original_topic)
        self._entries = self.apply_local_entry_change(
            self._entries, original_topic, entry
        )
        self._refresh_table()
        self._hide_form()
        self.config_changed.emit()
        if is_edit:
            self._set_operation_result("info", f"已更新本地话题配置：{entry.topic}，待下发")
        else:
            self._set_operation_result("info", f"已添加本地话题配置：{entry.topic}，待下发")

    def _delete_selected_entry(self) -> None:
        row = self._table.currentRow()
        robot_id = self._selected_robot_id()
        if row < 0 or row >= len(self._entries) or not robot_id:
            self._set_operation_result("error", "删除话题失败：请选择机器人和话题")
            return
        entry = self._entries.pop(row)
        entry.status = "pending"
        self._refresh_table()
        self.config_changed.emit()
        self._set_operation_result("info", f"已删除本地话题配置：{entry.topic}，待下发")

    def _save_config(self) -> None:
        robot_id = self._selected_robot_id()
        if not robot_id:
            self._set_operation_result("error", "保存草稿失败：请选择目标机器人")
            return
        try:
            self.save_transmit_config_file(
                self._transmit_config_path, robot_id, self._entries
            )
        except Exception as e:
            self._set_operation_result("error", f"保存草稿失败：{e}")
            return
        self.mark_entries_saved(self._entries)
        self._refresh_table()
        self.config_changed.emit()
        self._set_operation_result(
            "success", f"保存草稿成功：{robot_id}，{len(self._entries)} 个话题"
        )

    def _deploy_config(self) -> None:
        robot_id = self._selected_robot_id()
        if not robot_id:
            self._set_operation_result("error", "保存并下发失败：请选择目标机器人")
            return
        try:
            self.config_sync_requested.emit(
                robot_id,
                self.build_config_sync_payload(self._entries),
            )
            self.save_transmit_config_file(
                self._transmit_config_path, robot_id, self._entries
            )
        except Exception as e:
            self._pending_config_operation = ""
            self._set_operation_result("error", f"保存并下发失败：{e}")
            return
        self._pending_config_operation = "下发配置"
        self.mark_entries_saved(self._entries)
        self._refresh_table()
        self._set_operation_result(
            "info", f"保存并下发已发送：{robot_id}，等待机器人确认"
        )

    def _pull_config(self) -> None:
        robot_id = self._selected_robot_id()
        if not robot_id:
            self._set_operation_result("error", "拉取配置失败：请选择目标机器人")
            return
        try:
            self.config_query_requested.emit(robot_id)
        except Exception as e:
            self._pending_config_operation = ""
            self._set_operation_result("error", f"拉取配置失败：{e}")
            return
        self._pending_config_operation = "拉取配置"
        self._set_operation_result(
            "info", f"拉取配置请求已发送：{robot_id}，等待机器人响应"
        )

    def _load_selected_robot_config(self) -> None:
        robot_id = self._selected_robot_id()
        if not robot_id:
            self._entries = []
            self._refresh_table()
            return
        try:
            config = self.load_transmit_config_file(self._transmit_config_path)
        except Exception as e:
            self._set_operation_result("error", f"加载本地配置失败：{e}")
            return
        self._entries = self.entries_from_transmit_config(config, robot_id)
        self._refresh_table()
        self._refresh_available_topics()
