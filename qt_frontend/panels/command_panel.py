"""机器人速度控制与可配置批量命令面板。"""

from __future__ import annotations

import copy
import math
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from qt_frontend.command_batch import CommandBatchResult, CommandBatchTracker
from qt_frontend.command_button_config import (
    SLOT_IDS,
    CommandButtonConfig,
    CommandButtonConfigError,
    CommandButtonConfigStore,
    empty_command_slots,
)
from qt_frontend.panels.command_button_dialog import CommandButtonSettingsDialog
from qt_frontend.topic_catalog import RobotTopicCatalog


class CommandPanel(QWidget):
    """向单台机器人发送速度命令，并向全部在线机器人发送配置命令。"""

    command_sent = pyqtSignal(str, str, dict)
    batch_command_requested = pyqtSignal(str, dict)
    discover_requested = pyqtSignal()
    schema_query_requested = pyqtSignal(str, str, str)

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

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        config_store: Optional[CommandButtonConfigStore] = None,
        topic_catalog: Optional[RobotTopicCatalog] = None,
    ) -> None:
        super().__init__(parent)
        default_config_path = (
            Path(__file__).resolve().parents[1]
            / "config"
            / "command_buttons.yaml"
        )
        self._config_store = config_store or CommandButtonConfigStore(
            default_config_path
        )
        self._topic_catalog = topic_catalog or RobotTopicCatalog()
        self._command_slots: Dict[
            str, Optional[CommandButtonConfig]
        ] = empty_command_slots()
        self._online_robot_ids: List[str] = []
        self._settings_dialog: Optional[CommandButtonSettingsDialog] = None
        self._batch_tracker = CommandBatchTracker()
        self._visible_exec_id = ""
        self._latest_requested_exec_id = ""

        self._selected_robot: Optional[str] = None
        self._active_direction = ""
        self._direction_buttons: List[QPushButton] = []
        self._speed_buttons: Dict[str, QRadioButton] = {}
        self._repeat_timer = QTimer(self)
        self._repeat_timer.setInterval(self._REPEAT_INTERVAL_MS)
        self._repeat_timer.timeout.connect(self._repeat_active_direction)

        self._build_ui()
        self._load_command_slots()
        self._speed_buttons["medium"].setChecked(True)
        self._update_velocity_preview()
        self.on_robot_selected("")

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

    def on_robot_selected(self, robot_id: str) -> None:
        self._selected_robot = robot_id
        has_target = bool(robot_id)
        for button in self._direction_buttons:
            button.setEnabled(has_target)

    def on_robot_list_changed(self, robot_ids: List[str]) -> None:
        self._online_robot_ids = sorted(set(robot_ids))
        current = self._robot_combo.currentText()
        self._robot_combo.blockSignals(True)
        self._robot_combo.clear()
        self._robot_combo.addItem("-- 选择 --", "")
        for robot_id in robot_ids:
            self._robot_combo.addItem(robot_id, robot_id)
        if current:
            index = self._robot_combo.findText(current)
            if index >= 0:
                self._robot_combo.setCurrentIndex(index)
        self._robot_combo.blockSignals(False)
        self._on_robot_combo_changed(self._robot_combo.currentText())
        self._online_count_label.setText(
            "发送目标：全部在线机器人（当前 {} 台）".format(
                len(self._online_robot_ids)
            )
        )
        if self._settings_dialog is not None:
            self._settings_dialog.set_online_robot_ids(robot_ids)

    def on_cmd_ack(self, robot_id: str, ack_data: dict) -> None:
        exec_id = ack_data.get("exec_id")
        result = ack_data.get("result")
        if not isinstance(exec_id, str) or not isinstance(result, str):
            return
        message = ack_data.get("message", "")
        if not isinstance(message, str):
            message = str(message)
        if not self._batch_tracker.ack(
            exec_id,
            robot_id,
            result,
            message,
        ):
            return
        if exec_id == self._visible_exec_id:
            self._render_batch_result(exec_id)

    def begin_command_batch(self, exec_id: str, robot_ids: List[str]) -> None:
        self._batch_tracker.start(exec_id, robot_ids, time.monotonic())
        self._visible_exec_id = exec_id
        self._render_batch_result(exec_id)
        QTimer.singleShot(
            5000,
            lambda batch_id=exec_id: self._expire_batch(batch_id),
        )

    def reject_command_batch(self, exec_id: str, message: str) -> None:
        if exec_id != self._latest_requested_exec_id:
            return
        self._visible_exec_id = exec_id
        self._result_label.setText("发送失败：{}".format(message))
        self._result_label.setToolTip(message)

    def on_schema_response(self, robot_id: str, data: dict) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.on_schema_response(robot_id, data)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        robot_row = QHBoxLayout()
        robot_row.addWidget(QLabel("目标机器人:"))
        self._robot_combo = QComboBox()
        self._robot_combo.currentTextChanged.connect(
            self._on_robot_combo_changed
        )
        robot_row.addWidget(self._robot_combo)
        layout.addLayout(robot_row)

        velocity_group = QGroupBox("速度控制")
        velocity_layout = QVBoxLayout(velocity_group)
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("速度档位:"))
        for level, text in [
            ("low", "低速"),
            ("medium", "中速"),
            ("high", "高速"),
        ]:
            button = QRadioButton(text)
            button.setProperty("speed_level", level)
            button.toggled.connect(self._update_velocity_preview)
            self._speed_buttons[level] = button
            speed_row.addWidget(button)
        speed_row.addStretch()
        velocity_layout.addLayout(speed_row)

        pad_row = QHBoxLayout()
        pad_grid = QGridLayout()
        pad_grid.setSpacing(6)
        for row, column, text, direction in [
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
            button = QPushButton(text)
            button.setFixedSize(44, 36)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.setToolTip(self._direction_tooltip(direction))
            button.pressed.connect(
                lambda selected=direction: self._start_direction_velocity(
                    selected
                )
            )
            button.released.connect(self._stop_direction_velocity)
            self._direction_buttons.append(button)
            pad_grid.addWidget(button, row, column)
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
        velocity_layout.addLayout(pad_row)
        layout.addWidget(velocity_group)

        mode_group = QGroupBox("模式控制")
        mode_layout = QVBoxLayout(mode_group)
        mode_header = QHBoxLayout()
        self._online_count_label = QLabel(
            "发送目标：全部在线机器人（当前 0 台）"
        )
        self._online_count_label.setProperty("muted", True)
        mode_header.addWidget(self._online_count_label)
        mode_header.addStretch()
        self._settings_button = QToolButton()
        self._settings_button.setFixedSize(32, 32)
        self._settings_button.setText("⚙︎")
        settings_font = self._settings_button.font()
        settings_font.setPointSize(15)
        self._settings_button.setFont(settings_font)
        self._settings_button.setToolTip("设置命令按钮")
        self._settings_button.setAccessibleName("设置命令按钮")
        self._settings_button.clicked.connect(self._open_settings_dialog)
        mode_header.addWidget(self._settings_button)
        mode_layout.addLayout(mode_header)

        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(8)
        mode_grid.setVerticalSpacing(8)
        self._mode_buttons: Dict[str, QPushButton] = {}
        for index, slot_id in enumerate(SLOT_IDS):
            button = QPushButton("未配置")
            button.setMinimumHeight(40)
            button.setEnabled(False)
            button.clicked.connect(
                lambda checked=False, selected=slot_id: self._send_configured_command(
                    selected
                )
            )
            self._mode_buttons[slot_id] = button
            mode_grid.addWidget(button, index // 2, index % 2)
        mode_layout.addLayout(mode_grid)

        self._result_label = QLabel("尚未发送命令")
        self._result_label.setProperty("muted", True)
        self._result_label.setWordWrap(True)
        self._result_label.setOpenExternalLinks(False)
        self._result_label.linkActivated.connect(self._show_batch_details)
        mode_layout.addWidget(self._result_label)
        layout.addWidget(mode_group)
        layout.addStretch()

    def _on_robot_combo_changed(self, text: str) -> None:
        robot_id = self._robot_combo.currentData()
        self.on_robot_selected(robot_id if robot_id else "")

    def _selected_speed_level(self) -> str:
        for level, button in self._speed_buttons.items():
            if button.isChecked():
                return level
        return "medium"

    def _update_velocity_preview(self) -> None:
        linear, angular = self.velocity_step(self._selected_speed_level())
        self._lb_linear.setText("线速度: {:.2f} m/s".format(linear))
        self._lb_angular.setText("角速度: {:.2f} rad/s".format(angular))

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
        linear, angular = self.direction_velocity(
            direction,
            self._selected_speed_level(),
        )
        self.command_sent.emit(
            self._selected_robot,
            "velocity",
            {"linear": linear, "angular": angular},
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

    def _send_configured_command(self, slot_id: str) -> None:
        config = self._command_slots.get(slot_id)
        if config is None:
            return
        exec_id = uuid.uuid4().hex[:12]
        self._latest_requested_exec_id = exec_id
        self._visible_exec_id = exec_id
        self._result_label.setText("正在发送命令...")
        self._result_label.setToolTip("")
        self.batch_command_requested.emit(
            exec_id,
            {
                "topic": config.topic,
                "msg_type": config.msg_type,
                "data": copy.deepcopy(config.data),
            },
        )

    def _load_command_slots(self) -> None:
        try:
            slots = self._config_store.load()
        except (CommandButtonConfigError, OSError) as exc:
            self._command_slots = empty_command_slots()
            self._apply_command_slots()
            self._result_label.setText("配置读取失败：{}".format(exc))
            self._result_label.setToolTip(str(exc))
            return
        self._command_slots = copy.deepcopy(slots)
        self._apply_command_slots()

    def _apply_command_slots(self) -> None:
        for slot_id, button in self._mode_buttons.items():
            config = self._command_slots.get(slot_id)
            if config is None:
                button.setText("未配置")
                button.setToolTip("请先设置此命令按钮")
                button.setEnabled(False)
                continue
            display_label = button.fontMetrics().elidedText(
                config.label,
                Qt.ElideRight,
                150,
            )
            button.setText(display_label)
            button.setToolTip(
                "{}\n{}\n{}".format(
                    config.label,
                    config.topic,
                    config.msg_type,
                )
            )
            button.setEnabled(True)

    def _open_settings_dialog(self) -> None:
        dialog = CommandButtonSettingsDialog(
            store=self._config_store,
            topic_catalog=self._topic_catalog,
            online_robot_ids=self._online_robot_ids,
            parent=self,
        )
        self._settings_dialog = dialog
        dialog.discover_requested.connect(self.discover_requested.emit)
        dialog.schema_query_requested.connect(self.schema_query_requested.emit)
        try:
            result = dialog.exec_()
        finally:
            self._settings_dialog = None
            dialog.deleteLater()
        if result == dialog.Accepted:
            self._load_command_slots()

    def _expire_batch(self, batch_id: str) -> None:
        now = time.monotonic()
        self._batch_tracker.expire(now)
        result = self._batch_tracker.result(batch_id)
        if (
            result is not None
            and now < result.deadline
            and any(
                detail.status == "pending"
                for detail in result.details.values()
            )
        ):
            remaining_ms = max(
                1,
                int(math.ceil((result.deadline - now) * 1000)),
            )
            QTimer.singleShot(
                remaining_ms,
                lambda current_id=batch_id: self._expire_batch(current_id),
            )
        if batch_id == self._visible_exec_id:
            self._render_batch_result(batch_id)

    def _render_batch_result(self, exec_id: str) -> None:
        result = self._batch_tracker.result(exec_id)
        if result is None:
            return
        counts = result.counts()
        pending = len(result.details) - sum(counts.values())
        parts = [
            "成功 {}".format(counts["success"]),
            "失败 {}".format(counts["failed"]),
            "超时 {}".format(counts["timeout"]),
        ]
        if pending:
            parts.append("等待 {}".format(pending))
        text = " / ".join(parts)
        details = self._batch_details(result)
        if counts["failed"] or counts["timeout"]:
            text += ' / <a href="details">查看详情</a>'
        self._result_label.setText(text)
        self._result_label.setToolTip(
            details
            or ("等待机器人确认" if pending else "全部机器人执行成功")
        )

    @staticmethod
    def _batch_details(result: CommandBatchResult) -> str:
        lines = []
        for robot_id, detail in result.details.items():
            if detail.status not in ("failed", "timeout"):
                continue
            message = detail.message or (
                "等待确认超时" if detail.status == "timeout" else "执行失败"
            )
            lines.append("{}: {}".format(robot_id, message))
        return "\n".join(lines)

    def _show_batch_details(self, link: str) -> None:
        if link != "details" or not self._visible_exec_id:
            return
        result = self._batch_tracker.result(self._visible_exec_id)
        if result is None:
            return
        details = self._batch_details(result) or "没有失败或超时的机器人"
        QMessageBox.information(self, "批量命令详情", details)


__all__ = ["CommandPanel"]
