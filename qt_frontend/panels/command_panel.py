from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class CommandPanel(QWidget):
    command_sent = pyqtSignal(str, str, dict)  # (robot_id, action, params)

    _SPEED_STEPS: Dict[str, Tuple[float, float]] = {
        "low": (0.15, 0.40),
        "medium": (0.30, 0.75),
        "high": (0.50, 1.20),
    }
    _DIRECTION_FACTORS: Dict[str, Tuple[float, float]] = {
        "forward_left": (1.0, 1.0),
        "forward": (1.0, 0.0),
        "forward_right": (1.0, -1.0),
        "left": (0.0, 1.0),
        "stop": (0.0, 0.0),
        "right": (0.0, -1.0),
        "backward_left": (-1.0, 1.0),
        "backward": (-1.0, 0.0),
        "backward_right": (-1.0, -1.0),
    }
    _REPEAT_INTERVAL_MS = 200

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._selected_robot: Optional[str] = None
        self._active_direction = ""
        self._direction_buttons: List[QPushButton] = []
        self._speed_buttons: Dict[str, QRadioButton] = {}
        self._repeat_timer = QTimer(self)
        self._repeat_timer.setInterval(self._REPEAT_INTERVAL_MS)
        self._repeat_timer.timeout.connect(self._repeat_active_direction)

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

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("速度档位:"))
        for level, text in [
            ("low", "低速"),
            ("medium", "中速"),
            ("high", "高速"),
        ]:
            btn = QRadioButton(text)
            btn.setProperty("speed_level", level)
            btn.toggled.connect(self._update_velocity_preview)
            self._speed_buttons[level] = btn
            speed_row.addWidget(btn)
        speed_row.addStretch()
        vel_layout.addLayout(speed_row)

        pad_row = QHBoxLayout()
        pad_grid = QGridLayout()
        pad_grid.setSpacing(6)
        for row, col, text, direction in [
            (0, 0, "↖", "forward_left"),
            (0, 1, "↑", "forward"),
            (0, 2, "↗", "forward_right"),
            (1, 0, "←", "left"),
            (1, 1, "■", "stop"),
            (1, 2, "→", "right"),
            (2, 0, "↙", "backward_left"),
            (2, 1, "↓", "backward"),
            (2, 2, "↘", "backward_right"),
        ]:
            btn = QPushButton(text)
            btn.setFixedSize(44, 36)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setToolTip(self._direction_tooltip(direction))
            btn.pressed.connect(lambda d=direction: self._start_direction_velocity(d))
            btn.released.connect(self._stop_direction_velocity)
            self._direction_buttons.append(btn)
            pad_grid.addWidget(btn, row, col)
        pad_row.addLayout(pad_grid)

        preview_layout = QVBoxLayout()
        self._lb_linear = QLabel("线速度: 0.30 m/s")
        self._lb_angular = QLabel("角速度: 0.75 rad/s")
        self._lb_hint = QLabel("按住方向按钮，松开停车")
        self._lb_hint.setProperty("muted", True)
        for label in [self._lb_linear, self._lb_angular, self._lb_hint]:
            preview_layout.addWidget(label)
        preview_layout.addStretch()
        pad_row.addLayout(preview_layout)
        vel_layout.addLayout(pad_row)

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
        self._speed_buttons["medium"].setChecked(True)
        self._update_velocity_preview()
        self.on_robot_selected("")

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def velocity_step(level: str) -> Tuple[float, float]:
        return CommandPanel._SPEED_STEPS.get(
            level,
            CommandPanel._SPEED_STEPS["medium"],
        )

    @staticmethod
    def direction_velocity(direction: str, level: str) -> Tuple[float, float]:
        linear_base, angular_base = CommandPanel.velocity_step(level)
        linear_factor, angular_factor = CommandPanel._DIRECTION_FACTORS.get(
            direction,
            (0.0, 0.0),
        )
        return (
            round(linear_base * linear_factor, 2),
            round(angular_base * angular_factor, 2),
        )

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def on_robot_selected(self, robot_id: str) -> None:
        self._selected_robot = robot_id
        has_target = robot_id is not None and robot_id != ""
        for btn in self._direction_buttons:
            btn.setEnabled(has_target)
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

    def _selected_speed_level(self) -> str:
        for level, btn in self._speed_buttons.items():
            if btn.isChecked():
                return level
        return "medium"

    def _update_velocity_preview(self) -> None:
        linear, angular = self.velocity_step(self._selected_speed_level())
        self._lb_linear.setText(f"线速度: {linear:.2f} m/s")
        self._lb_angular.setText(f"角速度: {angular:.2f} rad/s")

    def _start_direction_velocity(self, direction: str) -> None:
        self._active_direction = direction
        self._send_direction_velocity(direction)
        if direction == "stop":
            self._repeat_timer.stop()
            return
        self._repeat_timer.start()

    def _repeat_active_direction(self) -> None:
        if self._active_direction:
            self._send_direction_velocity(self._active_direction)

    def _send_direction_velocity(self, direction: str) -> None:
        if not self._selected_robot:
            return
        lin, ang = self.direction_velocity(direction, self._selected_speed_level())
        self.command_sent.emit(
            self._selected_robot,
            "velocity",
            {"linear": lin, "angular": ang},
        )

    def _stop_direction_velocity(self) -> None:
        self._repeat_timer.stop()
        self._active_direction = ""
        if not self._selected_robot:
            return
        self.command_sent.emit(
            self._selected_robot,
            "velocity",
            {"linear": 0.0, "angular": 0.0},
        )

    @staticmethod
    def _direction_tooltip(direction: str) -> str:
        labels = {
            "forward_left": "前进左转",
            "forward": "前进",
            "forward_right": "前进右转",
            "left": "原地左转",
            "stop": "停止",
            "right": "原地右转",
            "backward_left": "后退左转",
            "backward": "后退",
            "backward_right": "后退右转",
        }
        return labels.get(direction, "")

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
