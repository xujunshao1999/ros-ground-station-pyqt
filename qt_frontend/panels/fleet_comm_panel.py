from __future__ import annotations

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
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qt_frontend.panels.topic_config_panel import TopicConfigPanel


class FleetCommPanel(QWidget):
    config_changed = pyqtSignal()
    discover_requested = pyqtSignal()
    config_sync_requested = pyqtSignal(str, dict)
    config_query_requested = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rules: List[Dict[str, Any]] = []
        self._editing_row: Optional[int] = None
        self._robot_ids: List[str] = []
        self._available_topics_by_robot: Dict[str, List[Dict[str, str]]] = {}
        self._pending_discover_robot_ids: set = set()
        self._transmit_config_path = (
            Path(__file__).resolve().parents[1] / "config" / "transmit_config.yaml"
        )

        layout = QVBoxLayout(self)

        # 规则表
        self._table = QTableWidget()
        self._table.setColumnCount(11)
        self._table.setHorizontalHeaderLabels([
            "启用",
            "源机器人",
            "源话题",
            "消息类型",
            "目标机器人",
            "目标话题",
            "频率",
            "传输方式",
            "QoS",
            "Frame 策略",
            "操作",
        ])
        header = self._table.horizontalHeader()
        # 保留稳定的最小列宽，避免 QoS 等短表头被压缩到难以点选。
        header.setMinimumSectionSize(56)
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.itemSelectionChanged.connect(
            self._load_selected_rule_into_form
        )
        layout.addWidget(self._table)

        # 按钮行
        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("+ 添加规则")
        self._btn_delete = QPushButton("删除")
        self._btn_toggle = QPushButton("暂停/恢复")
        self._btn_add.clicked.connect(self._show_add_form)
        self._btn_delete.clicked.connect(self._delete_selected_rule)
        self._btn_toggle.clicked.connect(self._toggle_selected_rule)
        for btn in [self._btn_add, self._btn_delete, self._btn_toggle]:
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        self._btn_deploy = QPushButton("下发全部规则")
        self._btn_pull = QPushButton("拉取当前规则")
        self._btn_deploy.clicked.connect(self._deploy_rules)
        self._btn_pull.clicked.connect(self._pull_rules)
        btn_row2.addWidget(self._btn_deploy)
        btn_row2.addWidget(self._btn_pull)
        layout.addLayout(btn_row2)

        # 添加/编辑表单
        self._form_group = QGroupBox("添加/编辑通信规则")
        self._form_group.setCheckable(True)
        self._form_group.setChecked(False)
        form = QVBoxLayout(self._form_group)

        f1 = QHBoxLayout()
        f1.addWidget(QLabel("源机器人:"))
        self._combo_src = QComboBox()
        self._combo_src.currentTextChanged.connect(
            lambda _text: self._refresh_source_topics()
        )
        f1.addWidget(self._combo_src)
        f1.addWidget(QLabel("目标:"))
        self._combo_dst = QComboBox()
        f1.addWidget(self._combo_dst)
        form.addLayout(f1)

        self._source_topic_row = QHBoxLayout()
        self._source_topic_row.setObjectName("sourceTopicRow")
        self._source_topic_row.addWidget(QLabel("源话题:"))
        self._combo_src_topic = QComboBox()
        self._combo_src_topic.setEditable(True)
        self._combo_src_topic.currentTextChanged.connect(
            self._on_source_topic_selected
        )
        self._source_topic_row.addWidget(self._combo_src_topic)
        form.addLayout(self._source_topic_row)

        self._destination_topic_row = QHBoxLayout()
        self._destination_topic_row.setObjectName("destinationTopicRow")
        self._destination_topic_row.addWidget(QLabel("目标话题:"))
        self._edit_dst_topic = QLineEdit()
        self._edit_dst_topic.setPlaceholderText("/fleet/turtlebot_001/odom")
        self._destination_topic_row.addWidget(self._edit_dst_topic)
        form.addLayout(self._destination_topic_row)

        f3 = QHBoxLayout()
        f3.addWidget(QLabel("消息类型:"))
        self._combo_msg_type = QComboBox()
        self._combo_msg_type.setEditable(True)
        self._combo_msg_type.addItems([
            "nav_msgs/Odometry", "geometry_msgs/Twist",
            "sensor_msgs/LaserScan", "sensor_msgs/PointCloud2",
        ])
        f3.addWidget(self._combo_msg_type)
        form.addLayout(f3)

        self._frequency_policy_row = QHBoxLayout()
        self._frequency_policy_row.setObjectName("frequencyPolicyRow")
        self._frequency_policy_row.addWidget(QLabel("频率上限(Hz):"))
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(0, 100)
        self._spin_freq.setValue(1.0)
        self._frequency_policy_row.addWidget(self._spin_freq)
        self._frequency_policy_row.addWidget(QLabel("Frame 策略:"))
        self._combo_frame_policy = QComboBox()
        self._combo_frame_policy.addItems(["namespace", "preserve"])
        self._frequency_policy_row.addWidget(self._combo_frame_policy)
        form.addLayout(self._frequency_policy_row)

        self._transport_qos_row = QHBoxLayout()
        self._transport_qos_row.setObjectName("transportQosRow")
        self._transport_qos_row.addWidget(QLabel("传输方式:"))
        self._combo_transport = QComboBox()
        self._combo_transport.addItem("MQTT JSON", "mqtt_json")
        self._combo_transport.addItem("MQTT Binary", "mqtt_binary")
        self._transport_qos_row.addWidget(self._combo_transport)
        self._transport_qos_row.addWidget(QLabel("QoS:"))
        self._combo_qos = QComboBox()
        # 编队链路仅支持 QoS 0/1，不向用户暴露不必要的 QoS 2。
        for label, value in TopicConfigPanel.qos_options()[:2]:
            self._combo_qos.addItem(label, value)
        self._transport_qos_row.addWidget(self._combo_qos)
        form.addLayout(self._transport_qos_row)

        confirm_row = QHBoxLayout()
        self._btn_confirm = QPushButton("确认")
        self._btn_cancel = QPushButton("取消")
        self._btn_confirm.clicked.connect(self._confirm_rule)
        self._btn_cancel.clicked.connect(self._hide_form)
        confirm_row.addWidget(self._btn_confirm)
        confirm_row.addWidget(self._btn_cancel)
        form.addLayout(confirm_row)

        layout.addWidget(self._form_group)
        self._load_saved_rules()

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def validate_fleet_rule(
        src_robot: str,
        src_topic: str,
        msg_type: str,
        dst_robot: str,
        dst_topic: str,
        freq_limit: float,
    ) -> bool:
        return (
            src_robot != ""
            and dst_robot != ""
            and src_robot != dst_robot
            and src_topic.startswith("/")
            and dst_topic.startswith("/")
            and msg_type != ""
            and freq_limit >= 0.0
        )

    @staticmethod
    def rule_to_protocol_dict(rule: Dict[str, Any]) -> Dict[str, Any]:
        transport = rule.get("transport")
        qos_data = rule.get("qos")
        return {
            "enabled": bool(rule.get("enabled", True)),
            "src_topic": rule.get("src_topic", ""),
            "msg_type": rule.get("msg_type", ""),
            "targets": [
                {
                    "robot_id": rule.get("dst_robot", ""),
                    "dst_topic": rule.get("dst_topic", ""),
                }
            ],
            "freq_limit": float(rule.get("freq_limit") or 0.0),
            "transport": "mqtt_json" if transport is None else transport,
            # QoS 0 是有效值，必须只对缺失值使用 QoS 1 兼容默认。
            "qos": 1 if qos_data is None else int(qos_data),
            "frame_policy": rule.get("frame_policy", "namespace"),
        }

    @staticmethod
    def build_config_sync_payload(rules: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "fleet_rules": [
                FleetCommPanel.rule_to_protocol_dict(rule)
                for rule in rules
            ]
        }

    @staticmethod
    def rules_from_config_response(
        src_robot: str,
        data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        rules: List[Dict[str, Any]] = []
        for rule in data.get("fleet_rules", []):
            if not isinstance(rule, dict):
                continue
            targets = rule.get("targets", [])
            if not isinstance(targets, list):
                continue
            transport = rule.get("transport")
            qos_data = rule.get("qos")
            for target in targets:
                if not isinstance(target, dict):
                    continue
                dst_robot = target.get("robot_id", "")
                dst_topic = target.get("dst_topic", "")
                if not dst_robot or not dst_topic:
                    continue
                rules.append({
                    "enabled": bool(rule.get("enabled", True)),
                    "src_robot": src_robot,
                    "src_topic": rule.get("src_topic", ""),
                    "msg_type": rule.get("msg_type", ""),
                    "dst_robot": dst_robot,
                    "dst_topic": dst_topic,
                    "freq_limit": float(rule.get("freq_limit") or 0.0),
                    "transport": (
                        "mqtt_json" if transport is None else transport
                    ),
                    "qos": 1 if qos_data is None else int(qos_data),
                    "frame_policy": rule.get("frame_policy", "namespace"),
                })
        return [
            rule for rule in rules
            if FleetCommPanel.validate_fleet_rule(
                rule["src_robot"],
                rule["src_topic"],
                rule["msg_type"],
                rule["dst_robot"],
                rule["dst_topic"],
                rule["freq_limit"],
            )
        ]

    @staticmethod
    def normalize_transmit_rules(raw: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw, list):
            return []

        rules: List[Dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            transport = item.get("transport")
            qos_data = item.get("qos")
            rule = {
                "enabled": bool(item.get("enabled", True)),
                "src_robot": item.get("src_robot", ""),
                "src_topic": item.get("src_topic", ""),
                "msg_type": item.get("msg_type", ""),
                "dst_robot": item.get("dst_robot", ""),
                "dst_topic": item.get("dst_topic", ""),
                "freq_limit": float(item.get("freq_limit") or 0.0),
                "transport": "mqtt_json" if transport is None else transport,
                "qos": 1 if qos_data is None else int(qos_data),
                "frame_policy": item.get("frame_policy", "namespace"),
            }
            if FleetCommPanel.validate_fleet_rule(
                rule["src_robot"],
                rule["src_topic"],
                rule["msg_type"],
                rule["dst_robot"],
                rule["dst_topic"],
                rule["freq_limit"],
            ):
                rules.append(rule)
        return rules

    @staticmethod
    def build_transmit_config(
        existing: Dict[str, Any],
        rules: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        config = dict(existing)
        config["fleet_rules"] = FleetCommPanel.normalize_transmit_rules(rules)
        return config

    @staticmethod
    def rules_from_transmit_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
        return FleetCommPanel.normalize_transmit_rules(config.get("fleet_rules", []))

    @staticmethod
    def save_transmit_config_file(
        path: Union[str, Path],
        rules: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        p = Path(path)
        existing = TopicConfigPanel.load_transmit_config_file(p)
        config = FleetCommPanel.build_transmit_config(existing, rules)
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

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def on_robot_list_changed(self, robot_ids: List[str]) -> None:
        self._robot_ids = list(robot_ids)
        current_src = self._combo_src.currentText()
        current_dst = self._combo_dst.currentText()
        for combo in [self._combo_src, self._combo_dst]:
            combo.blockSignals(True)
            combo.clear()
            for rid in robot_ids:
                combo.addItem(rid)
            combo.blockSignals(False)
        if current_src:
            idx = self._combo_src.findText(current_src)
            if idx >= 0:
                self._combo_src.setCurrentIndex(idx)
        if current_dst:
            idx = self._combo_dst.findText(current_dst)
            if idx >= 0:
                self._combo_dst.setCurrentIndex(idx)
        self._refresh_source_topics()

    def on_discover_response(self, robot_id: str, data: Dict[str, Any]) -> None:
        TopicConfigPanel.update_available_topics_cache(
            self._available_topics_by_robot, robot_id, data
        )
        self._pending_discover_robot_ids.discard(robot_id)
        if robot_id == self._combo_src.currentText():
            self._refresh_source_topics()

    def on_config_response(self, robot_id: str, data: Dict[str, Any]) -> None:
        if "fleet_rules" not in data:
            return
        other_rules = [
            rule for rule in self._rules
            if rule.get("src_robot", "") != robot_id
        ]
        self._rules = other_rules + self.rules_from_config_response(robot_id, data)
        self._refresh_table()
        self._save_rules()
        self.config_changed.emit()

    def _refresh_table(self) -> None:
        # 规则列表变化后原行号可能已失效，统一结束当前编辑。
        self._hide_form()
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._rules))
        for row, rule in enumerate(self._rules):
            values = [
                "是" if rule.get("enabled", True) else "否",
                rule.get("src_robot", ""),
                rule.get("src_topic", ""),
                rule.get("msg_type", ""),
                rule.get("dst_robot", ""),
                rule.get("dst_topic", ""),
                f"{float(rule.get('freq_limit') or 0.0):g}",
                rule.get("transport", "mqtt_json"),
                str(1 if rule.get("qos") is None else int(rule["qos"])),
                rule.get("frame_policy", "namespace"),
                "",
            ]
            for col, value in enumerate(values):
                self._table.setItem(row, col, QTableWidgetItem(value))
        self._table.resizeColumnsToContents()
        self._table.blockSignals(False)

    def _show_add_form(self) -> None:
        self._editing_row = None
        self._form_group.setTitle("添加/编辑通信规则")
        self._btn_confirm.setText("确认")
        self._table.blockSignals(True)
        self._table.clearSelection()
        self._table.setCurrentCell(-1, -1)
        self._table.blockSignals(False)
        self._clear_form()
        self._form_group.setChecked(True)
        self._request_source_topics_if_missing()

    def _hide_form(self) -> None:
        self._editing_row = None
        self._form_group.setTitle("添加/编辑通信规则")
        self._btn_confirm.setText("确认")
        self._table.blockSignals(True)
        self._table.clearSelection()
        self._table.setCurrentCell(-1, -1)
        self._table.blockSignals(False)
        self._form_group.setChecked(False)

    def _clear_form(self) -> None:
        if self._combo_src.count() > 0:
            self._combo_src.setCurrentIndex(0)
        if self._combo_dst.count() > 1:
            self._combo_dst.setCurrentIndex(1)
        elif self._combo_dst.count() > 0:
            self._combo_dst.setCurrentIndex(0)
        self._refresh_source_topics()
        self._combo_src_topic.setCurrentText("")
        self._edit_dst_topic.clear()
        self._combo_msg_type.setCurrentText("nav_msgs/Odometry")
        self._spin_freq.setValue(1.0)
        self._combo_transport.setCurrentIndex(
            self._combo_transport.findData("mqtt_json")
        )
        self._combo_qos.setCurrentIndex(self._combo_qos.findData(1))
        self._combo_frame_policy.setCurrentText("namespace")

    def _refresh_source_topics(self) -> None:
        current_topic = self._combo_src_topic.currentText()
        src_robot = self._combo_src.currentText()
        topics = self._available_topics_by_robot.get(src_robot, [])
        self._combo_src_topic.blockSignals(True)
        self._combo_src_topic.clear()
        for entry in topics:
            self._combo_src_topic.addItem(entry["topic"], entry)
        if current_topic:
            idx = self._combo_src_topic.findText(current_topic)
            if idx >= 0:
                self._combo_src_topic.setCurrentIndex(idx)
            else:
                self._combo_src_topic.setCurrentText(current_topic)
        self._combo_src_topic.blockSignals(False)
        self._on_source_topic_selected()
        self._request_source_topics_if_missing()

    def _request_source_topics_if_missing(self) -> None:
        src_robot = self._combo_src.currentText()
        if TopicConfigPanel.should_request_available_topics(
            self._available_topics_by_robot, src_robot
        ) and src_robot not in self._pending_discover_robot_ids:
            self._pending_discover_robot_ids.add(src_robot)
            self.discover_requested.emit()

    def _on_source_topic_selected(self) -> None:
        topic = self._combo_src_topic.currentText().strip()
        data = self._combo_src_topic.currentData()
        if isinstance(data, dict):
            self._combo_msg_type.setCurrentText(data.get("msg_type", ""))
        if topic:
            self._edit_dst_topic.setText(
                self.default_dst_topic(self._combo_src.currentText(), topic)
            )

    @staticmethod
    def default_dst_topic(src_robot: str, src_topic: str) -> str:
        robot = src_robot.strip().strip("/")
        topic = src_topic.strip().lstrip("/")
        if not robot or not topic:
            return ""
        return f"/fleet/{robot}/{topic}"

    def _rule_from_form(self) -> Optional[Dict[str, Any]]:
        src_robot = self._combo_src.currentText().strip()
        dst_robot = self._combo_dst.currentText().strip()
        src_topic = self._combo_src_topic.currentText().strip()
        dst_topic = self._edit_dst_topic.text().strip()
        msg_type = self._combo_msg_type.currentText().strip()
        freq_limit = float(self._spin_freq.value())
        transport = self._combo_transport.currentData()
        qos_data = self._combo_qos.currentData()

        if not self.validate_fleet_rule(
            src_robot,
            src_topic,
            msg_type,
            dst_robot,
            dst_topic,
            freq_limit,
        ):
            return None

        enabled = True
        if self._editing_row is not None and 0 <= self._editing_row < len(self._rules):
            # 表单不编辑启用状态，更新时保留暂停/恢复按钮管理的值。
            enabled = bool(self._rules[self._editing_row].get("enabled", True))

        return {
            "enabled": enabled,
            "src_robot": src_robot,
            "src_topic": src_topic,
            "msg_type": msg_type,
            "dst_robot": dst_robot,
            "dst_topic": dst_topic,
            "freq_limit": freq_limit,
            "transport": (
                "mqtt_json" if transport is None else str(transport)
            ),
            "qos": 1 if qos_data is None else int(qos_data),
            "frame_policy": self._combo_frame_policy.currentText(),
        }

    def _load_selected_rule_into_form(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._rules):
            return

        rule = self._rules[row]
        self._editing_row = row
        self._form_group.setTitle("编辑通信规则")
        self._btn_confirm.setText("更新")
        self._combo_src.setCurrentText(str(rule.get("src_robot", "")))
        self._combo_dst.setCurrentText(str(rule.get("dst_robot", "")))
        self._combo_src_topic.setCurrentText(str(rule.get("src_topic", "")))
        self._edit_dst_topic.setText(str(rule.get("dst_topic", "")))
        self._combo_msg_type.setCurrentText(str(rule.get("msg_type", "")))
        self._spin_freq.setValue(float(rule.get("freq_limit") or 0.0))

        transport = rule.get("transport")
        transport_index = self._combo_transport.findData(
            "mqtt_json" if transport is None else transport
        )
        self._combo_transport.setCurrentIndex(
            transport_index if transport_index >= 0 else 0
        )
        qos_data = rule.get("qos")
        qos = 1 if qos_data is None else int(qos_data)
        qos_index = self._combo_qos.findData(qos)
        default_qos_index = self._combo_qos.findData(1)
        self._combo_qos.setCurrentIndex(
            qos_index if qos_index >= 0 else default_qos_index
        )
        self._combo_frame_policy.setCurrentText(
            str(rule.get("frame_policy", "namespace"))
        )
        self._form_group.setChecked(True)

    def _confirm_rule(self) -> None:
        rule = self._rule_from_form()
        if rule is None:
            return
        if self._editing_row is None:
            self._rules.append(rule)
        elif 0 <= self._editing_row < len(self._rules):
            self._rules[self._editing_row] = rule
        else:
            return
        self._refresh_table()
        self._hide_form()
        self.config_changed.emit()

    def _delete_selected_rule(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._rules):
            return
        self._rules.pop(row)
        self._refresh_table()
        self.config_changed.emit()

    def _toggle_selected_rule(self) -> None:
        row = self._table.currentRow()
        if row < 0 or row >= len(self._rules):
            return
        self._rules[row]["enabled"] = not bool(self._rules[row].get("enabled", True))
        self._refresh_table()
        self.config_changed.emit()

    def _load_saved_rules(self) -> None:
        config = TopicConfigPanel.load_transmit_config_file(self._transmit_config_path)
        self._rules = self.rules_from_transmit_config(config)
        self._refresh_table()

    def _save_rules(self) -> None:
        self.save_transmit_config_file(self._transmit_config_path, self._rules)

    def _deploy_rules(self) -> None:
        self._save_rules()
        rules_by_source: Dict[str, List[Dict[str, Any]]] = {}
        for rule in self._rules:
            robot_id = rule.get("src_robot", "")
            if robot_id:
                rules_by_source.setdefault(robot_id, []).append(rule)
        for robot_id in sorted(rules_by_source):
            self.config_sync_requested.emit(
                robot_id,
                self.build_config_sync_payload(rules_by_source[robot_id]),
            )

    def _pull_rules(self) -> None:
        for robot_id in self._robot_ids:
            if robot_id:
                self.config_query_requested.emit(robot_id)
