from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass
class BandwidthEntry:
    topic: str = ""
    robot_id: str = ""
    transport: str = "mqtt_json"
    bytes_received: int = 0
    last_bytes: int = 0
    last_time: float = 0.0
    current_bps: float = 0.0


class TrafficMonitor(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._entries: Dict[Tuple[str, str, str], BandwidthEntry] = {}

        layout = QVBoxLayout(self)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["话题", "机器人", "传输方式", "带宽", "频率"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self._table)

        # 底部状态
        bottom_row = QHBoxLayout()
        self._lb_total = QLabel("总带宽: 0.00 B/s")
        bottom_row.addWidget(self._lb_total)
        bottom_row.addStretch()

        bottom_row.addWidget(QLabel("刷新:"))
        self._refresh_combo = QComboBox()
        self._refresh_combo.addItems(["0.5s", "1s", "2s", "5s"])
        self._refresh_combo.setCurrentIndex(1)
        self._refresh_combo.currentIndexChanged.connect(self._on_refresh_changed)
        bottom_row.addWidget(self._refresh_combo)

        btn_reset = QPushButton("重置计数")
        btn_reset.clicked.connect(self._reset_counts)
        bottom_row.addWidget(btn_reset)
        layout.addLayout(bottom_row)

        # 定时刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_stats)
        self._start_timer()

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_bandwidth(bytes_diff: int, time_diff: float) -> float:
        if time_diff <= 0:
            return 0.0
        return bytes_diff / time_diff

    @staticmethod
    def ema_smooth(old: float, new: float, alpha: float = 0.3) -> float:
        return old * (1 - alpha) + new * alpha

    # ------------------------------------------------------------------
    # Slot
    # ------------------------------------------------------------------

    def on_sensor_data_received(self, robot_id: str, sensor_name: str, data: dict) -> None:
        key = (sensor_name, robot_id, "mqtt_json")

        if key not in self._entries:
            self._entries[key] = BandwidthEntry(
                topic=sensor_name,
                robot_id=robot_id,
                transport="mqtt_json",
                last_time=time.monotonic(),
            )

        entry = self._entries[key]
        import sys
        entry.bytes_received += sys.getsizeof(str(data))

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        text = self._refresh_combo.currentText()
        interval_ms = int(float(text.replace("s", "")) * 1000)
        self._timer.start(interval_ms)

    def _on_refresh_changed(self) -> None:
        self._start_timer()

    def _update_stats(self) -> None:
        now = time.monotonic()
        total_bps = 0.0

        self._table.setRowCount(len(self._entries))
        for row, (key, entry) in enumerate(sorted(self._entries.items())):
            time_diff = now - entry.last_time
            bytes_diff = entry.bytes_received - entry.last_bytes
            raw_bps = self.calculate_bandwidth(bytes_diff, time_diff)
            entry.current_bps = self.ema_smooth(entry.current_bps, raw_bps)
            if raw_bps == 0:
                entry.current_bps = self.ema_smooth(entry.current_bps, 0.0, 0.5)

            entry.last_bytes = entry.bytes_received
            entry.last_time = now
            total_bps += entry.current_bps

            self._table.setItem(row, 0, QTableWidgetItem(entry.topic))
            self._table.setItem(row, 1, QTableWidgetItem(entry.robot_id))
            self._table.setItem(row, 2, QTableWidgetItem(entry.transport))

            bar = QProgressBar()
            bar.setMaximum(1_000_000)
            bar.setValue(min(int(entry.current_bps), 1_000_000))
            bar.setFormat(f"{entry.current_bps / 1024:.1f} KB/s")
            self._table.setCellWidget(row, 3, bar)

            freq = 0.0
            if time_diff > 0 and bytes_diff > 0:
                freq = 1.0 / time_diff
            self._table.setItem(row, 4, QTableWidgetItem(f"{freq:.1f} Hz"))

        total_label = f"总带宽: {total_bps / 1024:.1f} KB/s"
        if total_bps > 1_000_000:
            total_label = f"总带宽: {total_bps / 1_000_000:.2f} MB/s"
        self._lb_total.setText(total_label)

    def _reset_counts(self) -> None:
        for entry in self._entries.values():
            entry.bytes_received = 0
            entry.last_bytes = 0
            entry.current_bps = 0.0
