from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class EventPanel(QWidget):
    MAX_EVENTS = 1000

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)

        # 筛选行
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("机器人:"))
        self._robot_filter = QComboBox()
        self._robot_filter.addItem("全部", "")
        self._robot_filter.currentTextChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._robot_filter)
        filter_row.addStretch()

        self._chk_autoscroll = QCheckBox("自动滚动")
        self._chk_autoscroll.setChecked(True)
        filter_row.addWidget(self._chk_autoscroll)

        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self._clear_events)
        filter_row.addWidget(btn_clear)
        layout.addLayout(filter_row)

        # 事件列表
        self._event_list = QListWidget()
        self._event_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._event_list.customContextMenuRequested.connect(self._show_context_menu)
        layout.addWidget(self._event_list)

        self._all_events: List[Tuple[str, str, str, str, dict]] = []

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def level_to_color(level: str) -> QColor:
        level_lower = level.lower()
        if level_lower == "critical":
            return QColor("#8b0000")  # dark red bg
        elif level_lower == "error":
            return QColor("#ffcccc")  # light red bg
        elif level_lower == "warning":
            return QColor("#fff3cd")  # amber bg
        return QColor("#ffffff")  # default white bg

    @staticmethod
    def level_to_text_color(level: str) -> QColor:
        if level.lower() == "critical":
            return QColor("#ffffff")  # white text on dark red
        return QColor("#000000")

    @staticmethod
    def format_event(robot_id: str, level: str, code: str, message: str, timestamp: float = 0.0) -> str:
        import datetime
        ts = datetime.datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")
        return f"[{ts}] [{robot_id}] [{level.upper()}] {code}: {message}"

    @staticmethod
    def trim_events(events: list, max_count: int = MAX_EVENTS) -> list:
        if len(events) <= max_count:
            return events
        return events[-max_count:]

    # ------------------------------------------------------------------
    # 公共方法
    # ------------------------------------------------------------------

    def add_robot_filter(self, robot_id: str) -> None:
        if self._robot_filter.findText(robot_id) < 0:
            self._robot_filter.addItem(robot_id, robot_id)

    # ------------------------------------------------------------------
    # Slot
    # ------------------------------------------------------------------

    def on_event_received(self, robot_id: str, data: dict) -> None:
        import time
        level = data.get("level", "info")
        code = data.get("code", "")
        message = data.get("message", "")
        details = data.get("details", {})
        timestamp = data.get("ts", time.time())

        self._all_events.append((robot_id, level, code, message, details))
        self._all_events = self.trim_events(self._all_events, self.MAX_EVENTS)

        if self._should_show(robot_id):
            self._add_event_item(robot_id, level, code, message, timestamp)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _should_show(self, robot_id: str) -> bool:
        current_filter = self._robot_filter.currentData()
        if not current_filter:
            return True
        return current_filter == robot_id

    def _add_event_item(self, robot_id: str, level: str, code: str, message: str, timestamp: float) -> None:
        text = self.format_event(robot_id, level, code, message, timestamp)
        item = QListWidgetItem(text)
        item.setBackground(self.level_to_color(level))
        item.setForeground(self.level_to_text_color(level))
        item.setToolTip(f"Level: {level}\nCode: {code}\nMessage: {message}")

        self._event_list.addItem(item)

        if self._chk_autoscroll.isChecked():
            self._event_list.scrollToBottom()

    def _on_filter_changed(self, text: str) -> None:
        self._event_list.clear()
        for robot_id, level, code, message, details in self._all_events[-200:]:
            if self._should_show(robot_id):
                self._add_event_item(robot_id, level, code, message, 0.0)

    def _clear_events(self) -> None:
        self._all_events.clear()
        self._event_list.clear()

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction("复制消息")
        copy_all_action = menu.addAction("复制全部")
        clear_action = menu.addAction("清空")

        action = menu.exec_(self._event_list.mapToGlobal(pos))
        if action == copy_action:
            item = self._event_list.currentItem()
            if item:
                QApplication.clipboard().setText(item.text())
        elif action == copy_all_action:
            lines = [
                self._event_list.item(i).text()
                for i in range(self._event_list.count())
            ]
            QApplication.clipboard().setText("\n".join(lines))
        elif action == clear_action:
            self._clear_events()
