from __future__ import annotations

from typing import Any, Dict, List, Optional

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
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class FleetCommPanel(QWidget):
    config_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rules: List[Dict[str, Any]] = []
        self._editing_row: Optional[int] = None

        layout = QVBoxLayout(self)

        # 规则表
        self._table = QTableWidget()
        self._table.setColumnCount(9)
        self._table.setHorizontalHeaderLabels([
            "启用",
            "源机器人",
            "源话题",
            "消息类型",
            "目标机器人",
            "目标话题",
            "频率",
            "Frame 策略",
            "操作",
        ])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
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
        f1.addWidget(self._combo_src)
        f1.addWidget(QLabel("目标:"))
        self._combo_dst = QComboBox()
        f1.addWidget(self._combo_dst)
        form.addLayout(f1)

        f2 = QHBoxLayout()
        f2.addWidget(QLabel("源话题:"))
        self._edit_src_topic = QLineEdit()
        self._edit_src_topic.setPlaceholderText("/odom")
        f2.addWidget(self._edit_src_topic)
        f2.addWidget(QLabel("目标话题:"))
        self._edit_dst_topic = QLineEdit()
        self._edit_dst_topic.setPlaceholderText("/fleet/turtlebot_001/odom")
        f2.addWidget(self._edit_dst_topic)
        form.addLayout(f2)

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

        f4 = QHBoxLayout()
        f4.addWidget(QLabel("频率上限(Hz):"))
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(0, 100)
        self._spin_freq.setValue(1.0)
        f4.addWidget(self._spin_freq)
        form.addLayout(f4)

        f_policy = QHBoxLayout()
        f_policy.addWidget(QLabel("Frame 策略:"))
        self._combo_frame_policy = QComboBox()
        self._combo_frame_policy.addItems(["namespace", "preserve"])
        f_policy.addWidget(self._combo_frame_policy)
        form.addLayout(f_policy)

        f5 = QHBoxLayout()
        f5.addWidget(QLabel("用途:"))
        self._radio_position = QRadioButton("位置共享")
        self._radio_nav = QRadioButton("导航目标")
        self._radio_custom = QRadioButton("自定义")
        self._radio_pointcloud = QRadioButton("点云(重量)")
        self._radio_position.setChecked(True)
        for rb in [
            self._radio_position,
            self._radio_nav,
            self._radio_custom,
            self._radio_pointcloud,
        ]:
            f5.addWidget(rb)
        form.addLayout(f5)

        confirm_row = QHBoxLayout()
        self._btn_confirm = QPushButton("确认")
        self._btn_cancel = QPushButton("取消")
        self._btn_confirm.clicked.connect(self._confirm_rule)
        self._btn_cancel.clicked.connect(self._hide_form)
        confirm_row.addWidget(self._btn_confirm)
        confirm_row.addWidget(self._btn_cancel)
        form.addLayout(confirm_row)

        layout.addWidget(self._form_group)

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
            "transport": rule.get("transport", "mqtt_json"),
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

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def on_robot_list_changed(self, robot_ids: List[str]) -> None:
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

    def _refresh_table(self) -> None:
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
                rule.get("frame_policy", "namespace"),
                "",
            ]
            for col, value in enumerate(values):
                self._table.setItem(row, col, QTableWidgetItem(value))

    def _show_add_form(self) -> None:
        self._editing_row = None
        self._form_group.setTitle("添加/编辑通信规则")
        self._btn_confirm.setText("确认")
        self._clear_form()
        self._form_group.setChecked(True)

    def _hide_form(self) -> None:
        self._editing_row = None
        self._form_group.setChecked(False)

    def _clear_form(self) -> None:
        if self._combo_src.count() > 0:
            self._combo_src.setCurrentIndex(0)
        if self._combo_dst.count() > 1:
            self._combo_dst.setCurrentIndex(1)
        elif self._combo_dst.count() > 0:
            self._combo_dst.setCurrentIndex(0)
        self._edit_src_topic.clear()
        self._edit_dst_topic.clear()
        self._combo_msg_type.setCurrentText("nav_msgs/Odometry")
        self._spin_freq.setValue(1.0)
        self._combo_frame_policy.setCurrentText("namespace")
        self._radio_position.setChecked(True)

    def _rule_from_form(self) -> Optional[Dict[str, Any]]:
        src_robot = self._combo_src.currentText().strip()
        dst_robot = self._combo_dst.currentText().strip()
        src_topic = self._edit_src_topic.text().strip()
        dst_topic = self._edit_dst_topic.text().strip()
        msg_type = self._combo_msg_type.currentText().strip()
        freq_limit = float(self._spin_freq.value())

        if not self.validate_fleet_rule(
            src_robot,
            src_topic,
            msg_type,
            dst_robot,
            dst_topic,
            freq_limit,
        ):
            return None

        return {
            "enabled": True,
            "src_robot": src_robot,
            "src_topic": src_topic,
            "msg_type": msg_type,
            "dst_robot": dst_robot,
            "dst_topic": dst_topic,
            "freq_limit": freq_limit,
            "transport": "mqtt_json",
            "frame_policy": self._combo_frame_policy.currentText(),
        }

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
