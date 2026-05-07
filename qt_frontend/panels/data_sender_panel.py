from __future__ import annotations

import json
import logging
from typing import List, Optional

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


class DataSenderPanel(QWidget):
    send_json = pyqtSignal(str, str, str)  # (robot_id, topic, json_str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)

        # 目标机器人
        robot_row = QHBoxLayout()
        robot_row.addWidget(QLabel("目标机器人:"))
        self._robot_combo = QComboBox()
        robot_row.addWidget(self._robot_combo)
        layout.addLayout(robot_row)

        # ROS 话题
        topic_row = QHBoxLayout()
        topic_row.addWidget(QLabel("ROS 话题:"))
        self._topic_edit = QLineEdit()
        self._topic_edit.setPlaceholderText("/example/topic")
        topic_row.addWidget(self._topic_edit)
        layout.addLayout(topic_row)

        # JSON 内容
        layout.addWidget(QLabel("JSON 内容:"))
        self._json_edit = QTextEdit()
        self._json_edit.setPlaceholderText('{"key": "value"}')
        layout.addWidget(self._json_edit)

        # 按钮
        btn_row = QHBoxLayout()
        btn_json = QPushButton("发送 JSON")
        btn_json.clicked.connect(self._send_json)
        btn_row.addWidget(btn_json)

        btn_file = QPushButton("发送二进制")
        btn_file.clicked.connect(self._send_binary_file)
        btn_row.addWidget(btn_file)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _send_json(self) -> None:
        robot_id = self._robot_combo.currentData()
        if not robot_id:
            return
        topic = self._topic_edit.text().strip()
        if not topic:
            return
        content = self._json_edit.toPlainText().strip()
        if not content:
            return

        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(f"[DataSender] Invalid JSON: {e}")
            self._json_edit.setStyleSheet("QTextEdit { border: 2px solid red; }")
            return

        self._json_edit.setStyleSheet("")
        self.send_json.emit(robot_id, topic, content)

    def _send_binary_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择二进制文件", "", "All Files (*)"
        )
        if path:
            logger.info(f"[DataSender] Selected file: {path}")
