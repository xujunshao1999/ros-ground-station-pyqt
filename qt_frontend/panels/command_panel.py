from __future__ import annotations

from typing import List, Optional

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class CommandPanel(QWidget):
    command_sent = pyqtSignal(str, str, dict)  # (robot_id, action, params)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._selected_robot: Optional[str] = None

        layout = QVBoxLayout(self)

        # 目标机器人选择
        robot_row = QHBoxLayout()
        robot_row.addWidget(QLabel("目标机器人:"))
        self._robot_combo = QComboBox()
        self._robot_combo.currentTextChanged.connect(self._on_robot_combo_changed)
        robot_row.addWidget(self._robot_combo)
        layout.addLayout(robot_row)

        # 速度控制
        vel_group = QGroupBox("速度控制")
        vel_layout = QVBoxLayout(vel_group)

        linear_row = QHBoxLayout()
        linear_row.addWidget(QLabel("线速度:"))
        self._linear_slider = QSlider(Qt.Horizontal)
        self._linear_slider.setRange(-100, 100)
        self._linear_slider.setValue(0)
        self._linear_slider.valueChanged.connect(self._on_linear_changed)
        linear_row.addWidget(self._linear_slider)
        self._lb_linear = QLabel("0.00 m/s")
        self._lb_linear.setFixedWidth(80)
        linear_row.addWidget(self._lb_linear)
        vel_layout.addLayout(linear_row)

        angular_row = QHBoxLayout()
        angular_row.addWidget(QLabel("角速度:"))
        self._angular_slider = QSlider(Qt.Horizontal)
        self._angular_slider.setRange(-100, 100)
        self._angular_slider.setValue(0)
        self._angular_slider.valueChanged.connect(self._on_angular_changed)
        angular_row.addWidget(self._angular_slider)
        self._lb_angular = QLabel("0.00 rad/s")
        self._lb_angular.setFixedWidth(80)
        angular_row.addWidget(self._lb_angular)
        vel_layout.addLayout(angular_row)

        self._btn_send_vel = QPushButton("发送速度")
        self._btn_send_vel.clicked.connect(self._send_velocity)
        self._btn_send_vel.setEnabled(False)
        vel_layout.addWidget(self._btn_send_vel)

        layout.addWidget(vel_group)

        # 模式控制
        mode_group = QGroupBox("模式控制")
        mode_layout = QVBoxLayout(mode_group)

        mode_btn_row = QHBoxLayout()
        self._btn_manual = QPushButton("手动")
        self._btn_auto = QPushButton("自动")
        self._btn_stop = QPushButton("停止")
        self._btn_manual.clicked.connect(lambda: self._send_mode("manual"))
        self._btn_auto.clicked.connect(lambda: self._send_mode("auto"))
        self._btn_stop.clicked.connect(lambda: self._send_mode("stop"))
        self._btn_manual.setEnabled(False)
        self._btn_auto.setEnabled(False)
        self._btn_stop.setEnabled(False)
        for btn in [self._btn_manual, self._btn_auto, self._btn_stop]:
            mode_btn_row.addWidget(btn)
        mode_layout.addLayout(mode_btn_row)

        self._btn_emergency = QPushButton("急停")
        self._btn_emergency.setObjectName("dangerButton")
        self._btn_emergency.clicked.connect(self._send_emergency)
        mode_layout.addWidget(self._btn_emergency)

        self._btn_home = QPushButton("回家")
        self._btn_home.setEnabled(False)
        self._btn_home.clicked.connect(self._send_home)
        mode_layout.addWidget(self._btn_home)

        layout.addWidget(mode_group)
        layout.addStretch()

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def slider_to_value(slider_val: int) -> float:
        return slider_val / 100.0

    @staticmethod
    def value_to_slider(value: float) -> int:
        return max(-100, min(100, int(value * 100)))

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def on_robot_selected(self, robot_id: str) -> None:
        self._selected_robot = robot_id
        has_target = robot_id is not None and robot_id != ""
        self._btn_send_vel.setEnabled(has_target)
        self._btn_manual.setEnabled(has_target)
        self._btn_auto.setEnabled(has_target)
        self._btn_stop.setEnabled(has_target)
        self._btn_home.setEnabled(has_target)

    def on_robot_list_changed(self, robot_ids: List[str]) -> None:
        current = self._robot_combo.currentText()
        self._robot_combo.blockSignals(True)
        self._robot_combo.clear()
        self._robot_combo.addItem("-- 选择 --", "")
        for rid in robot_ids:
            self._robot_combo.addItem(rid, rid)
        if current:
            idx = self._robot_combo.findText(current)
            if idx >= 0:
                self._robot_combo.setCurrentIndex(idx)
        self._robot_combo.blockSignals(False)

    def on_cmd_ack(self, robot_id: str, ack_data: dict) -> None:
        pass

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _on_robot_combo_changed(self, text: str) -> None:
        robot_id = self._robot_combo.currentData()
        if robot_id:
            self.on_robot_selected(robot_id)
        else:
            self.on_robot_selected("")

    def _on_linear_changed(self, val: int) -> None:
        self._lb_linear.setText(f"{self.slider_to_value(val):.2f} m/s")

    def _on_angular_changed(self, val: int) -> None:
        self._lb_angular.setText(f"{self.slider_to_value(val):.2f} rad/s")

    def _send_velocity(self) -> None:
        if not self._selected_robot:
            return
        lin = self.slider_to_value(self._linear_slider.value())
        ang = self.slider_to_value(self._angular_slider.value())
        self.command_sent.emit(
            self._selected_robot,
            "velocity",
            {"linear": lin, "angular": ang},
        )

    def _send_mode(self, mode: str) -> None:
        if not self._selected_robot:
            return
        self.command_sent.emit(
            self._selected_robot, "mode", {"mode": mode}
        )

    def _send_emergency(self) -> None:
        self.command_sent.emit(
            self._selected_robot or "all", "mode", {"mode": "stop"}
        )
        self.command_sent.emit(
            self._selected_robot or "all",
            "velocity",
            {"linear": 0.0, "angular": 0.0},
        )

    def _send_home(self) -> None:
        if not self._selected_robot:
            return
        self.command_sent.emit(
            self._selected_robot, "nav_goal", {"x": 0.0, "y": 0.0, "theta": 0.0}
        )
