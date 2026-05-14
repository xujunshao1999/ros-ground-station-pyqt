from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

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
    QSpinBox,
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
    status: str = "pending"
    compression: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "msg_type": self.msg_type,
            "freq_limit": self.freq_limit,
            "transport": self.transport,
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
            status=data.get("status", status),
            compression=dict(data.get("compression") or data.get("options") or {}),
        )


class TopicConfigPanel(QWidget):
    config_changed = pyqtSignal()
    topic_request_requested = pyqtSignal(str, dict)  # (robot_id, request)
    config_sync_requested = pyqtSignal(str, dict)  # (robot_id, config)
    config_query_requested = pyqtSignal(str)  # robot_id

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._entries: List[SubscriptionEntry] = []
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
        layout.addWidget(self._table)

        # 按钮行
        btn_row1 = QHBoxLayout()
        self._btn_add = QPushButton("+ 添加话题")
        self._btn_delete = QPushButton("删除")
        self._btn_save = QPushButton("保存配置")
        self._btn_add.clicked.connect(self._show_add_form)
        self._btn_delete.clicked.connect(self._delete_selected_entry)
        self._btn_save.clicked.connect(self._save_config)
        for btn in [self._btn_add, self._btn_delete, self._btn_save]:
            btn_row1.addWidget(btn)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        self._btn_deploy = QPushButton("下发配置到机器人")
        self._btn_deploy.setStyleSheet("QPushButton { font-weight: bold; }")
        self._btn_deploy.clicked.connect(self._deploy_config)
        btn_row2.addWidget(self._btn_deploy)
        self._btn_pull = QPushButton("从机器人拉取话题")
        self._btn_pull.clicked.connect(self._pull_config)
        btn_row2.addWidget(self._btn_pull)
        layout.addLayout(btn_row2)

        # 添加/编辑表单（可折叠）
        self._form_group = QGroupBox("添加/编辑话题")
        self._form_group.setCheckable(True)
        self._form_group.setChecked(False)
        form = QVBoxLayout(self._form_group)

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
        self._combo_transport.addItems(["AUTO", "LIGHT (mqtt_json)", "MEDIUM (mqtt_binary)", "HEAVY (http_stream)"])
        f3.addWidget(self._combo_transport)
        form.addLayout(f3)

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
        self._combo_qos.addItems(["AtMostOnce (0)", "AtLeastOnce (1)"])
        f5.addWidget(self._combo_qos)
        form.addLayout(f5)

        self._btn_confirm = QPushButton("确认")
        self._btn_cancel = QPushButton("取消")
        self._btn_confirm.clicked.connect(self._confirm_entry)
        self._btn_cancel.clicked.connect(self._hide_form)
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
    def build_topic_request(action: str, entry: SubscriptionEntry) -> Dict[str, Any]:
        data = entry.to_dict()
        data["action"] = action
        return data

    @staticmethod
    def entries_from_config_response(data: Dict[str, Any]) -> List[SubscriptionEntry]:
        return [
            SubscriptionEntry.from_dict(sub, status="active")
            for sub in data.get("subscriptions", [])
            if sub.get("topic")
        ]

    @staticmethod
    def build_transmit_config(
        existing: Dict[str, Any],
        robot_id: str,
        entries: List[SubscriptionEntry],
    ) -> Dict[str, Any]:
        config = dict(existing)
        subscriptions = dict(config.get("subscriptions") or {})
        robot_subscriptions: Dict[str, Dict[str, Any]] = {}

        for entry in entries:
            data = entry.to_dict()
            robot_subscriptions[entry.topic] = {
                "msg_type": data.get("msg_type", ""),
                "freq_limit": data.get("freq_limit", 0.0),
                "transport": data.get("transport", "auto"),
                "compression": dict(data.get("compression") or {}),
            }

        subscriptions[robot_id] = robot_subscriptions
        config["subscriptions"] = subscriptions
        return config

    @staticmethod
    def entries_from_transmit_config(
        config: Dict[str, Any], robot_id: str
    ) -> List[SubscriptionEntry]:
        robot_subscriptions = (config.get("subscriptions") or {}).get(robot_id, {})
        entries: List[SubscriptionEntry] = []
        for topic, sub_info in robot_subscriptions.items():
            data = dict(sub_info or {})
            data["topic"] = topic
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
            yaml.safe_dump(config, f, default_flow_style=False, allow_unicode=True)
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

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def on_robot_list_changed(self, robot_ids: List[str]) -> None:
        current = self._robot_combo.currentData() or self._robot_combo.currentText()
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
        self._load_selected_robot_config()

    def on_topic_response(self, robot_id: str, data: dict) -> None:
        if robot_id != self._selected_robot_id():
            return
        self.apply_topic_response_to_entries(self._entries, data)
        self._refresh_table()

    def on_config_response(self, robot_id: str, data: dict) -> None:
        if robot_id != self._selected_robot_id():
            return
        self._entries = self.entries_from_config_response(data)
        self._refresh_table()
        self.config_changed.emit()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _selected_robot_id(self) -> str:
        return self._robot_combo.currentData() or ""

    def _refresh_table(self) -> None:
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

    def _show_add_form(self) -> None:
        self._edit_topic.clear()
        self._combo_msg_type.setCurrentText("")
        self._combo_transport.setCurrentIndex(0)
        self._spin_freq.setValue(0.0)
        self._form_group.setChecked(True)

    def _hide_form(self) -> None:
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

        return SubscriptionEntry(
            topic=topic,
            msg_type=msg_type,
            freq_limit=float(self._spin_freq.value()),
            transport=transport_value,
            status="pending",
            compression={},
        )

    def _confirm_entry(self) -> None:
        entry = self._entry_from_form()
        robot_id = self._selected_robot_id()
        if entry is None or not robot_id:
            return

        self._entries = [e for e in self._entries if e.topic != entry.topic]
        self._entries.append(entry)
        self._refresh_table()
        self._hide_form()
        self.config_changed.emit()
        self.topic_request_requested.emit(
            robot_id, self.build_topic_request("subscribe", entry)
        )

    def _delete_selected_entry(self) -> None:
        row = self._table.currentRow()
        robot_id = self._selected_robot_id()
        if row < 0 or row >= len(self._entries) or not robot_id:
            return
        entry = self._entries.pop(row)
        self._refresh_table()
        self.config_changed.emit()
        self.topic_request_requested.emit(
            robot_id, self.build_topic_request("unsubscribe", entry)
        )

    def _save_config(self) -> None:
        robot_id = self._selected_robot_id()
        if not robot_id:
            return
        self.save_transmit_config_file(
            self._transmit_config_path, robot_id, self._entries
        )
        for entry in self._entries:
            if entry.status == "pending":
                entry.status = "saved"
        self._refresh_table()
        self.config_changed.emit()

    def _deploy_config(self) -> None:
        robot_id = self._selected_robot_id()
        if not robot_id:
            return
        self.config_sync_requested.emit(
            robot_id,
            {"subscriptions": [entry.to_dict() for entry in self._entries]},
        )

    def _pull_config(self) -> None:
        robot_id = self._selected_robot_id()
        if robot_id:
            self.config_query_requested.emit(robot_id)

    def _load_selected_robot_config(self) -> None:
        robot_id = self._selected_robot_id()
        if not robot_id:
            self._entries = []
            self._refresh_table()
            return
        try:
            config = self.load_transmit_config_file(self._transmit_config_path)
        except Exception:
            return
        self._entries = self.entries_from_transmit_config(config, robot_id)
        self._refresh_table()
