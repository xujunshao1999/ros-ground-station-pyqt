from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
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
    message_count: int = 0
    last_message_count: int = 0
    current_hz: float = 0.0
    sample_times: List[float] = field(default_factory=list)


class TrafficMonitor(QWidget):
    _HZ_WINDOW_SECONDS = 5.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._entries: Dict[Tuple[str, str], BandwidthEntry] = {}
        self._topic_config: Dict[Tuple[str, str], Dict[str, Any]] = {}

        layout = QVBoxLayout(self)

        # 表格
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["话题", "机器人", "传输方式", "带宽", "频率"])
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
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

    @staticmethod
    def normalize_sensor_name(topic: str) -> str:
        return topic.strip().lstrip("/")

    @staticmethod
    def estimate_payload_bytes(data: object) -> int:
        import sys
        return sys.getsizeof(str(data))

    @classmethod
    def calculate_hz(cls, sample_times: List[float]) -> float:
        if len(sample_times) < 2:
            return 0.0
        elapsed = sample_times[-1] - sample_times[0]
        if elapsed <= 0:
            return 0.0
        return (len(sample_times) - 1) / elapsed

    @classmethod
    def prune_sample_times(cls, sample_times: List[float], now: float) -> List[float]:
        cutoff = now - cls._HZ_WINDOW_SECONDS
        return [
            sample_time
            for sample_time in sample_times
            if sample_time >= cutoff
        ]

    # ------------------------------------------------------------------
    # Slot
    # ------------------------------------------------------------------

    def on_subscriptions_changed(
        self,
        robot_id: str,
        subscriptions: List[Dict[str, Any]],
    ) -> None:
        for item in subscriptions:
            topic = str(item.get("topic", ""))
            sensor_name = self.normalize_sensor_name(topic)
            if not sensor_name:
                continue
            key = (sensor_name, robot_id)
            self._topic_config[key] = dict(item)
            entry = self._entries.get(key)
            if entry is not None:
                entry.transport = str(item.get("transport") or entry.transport)

    def on_sensor_data_received(
        self,
        robot_id: str,
        sensor_name: str,
        data: object,
        now: Optional[float] = None,
    ) -> None:
        now = time.monotonic() if now is None else now
        normalized_sensor_name = self.normalize_sensor_name(sensor_name)
        key = (normalized_sensor_name, robot_id)
        config = self._topic_config.get(key, {})
        transport = str(config.get("transport") or "mqtt_json")

        if key not in self._entries:
            self._entries[key] = BandwidthEntry(
                topic=normalized_sensor_name,
                robot_id=robot_id,
                transport=transport,
                last_time=now,
            )

        entry = self._entries[key]
        entry.transport = transport
        entry.bytes_received += self.estimate_payload_bytes(data)
        entry.message_count += 1
        entry.sample_times.append(now)
        entry.sample_times = self.prune_sample_times(entry.sample_times, now)
        entry.current_hz = self.calculate_hz(entry.sample_times)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _start_timer(self) -> None:
        text = self._refresh_combo.currentText()
        interval_ms = int(float(text.replace("s", "")) * 1000)
        self._timer.start(interval_ms)

    def _on_refresh_changed(self) -> None:
        self._start_timer()

    def _update_stats(self, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
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
            entry.last_message_count = entry.message_count
            entry.last_time = now
            entry.sample_times = self.prune_sample_times(entry.sample_times, now)
            entry.current_hz = self.calculate_hz(entry.sample_times)
            total_bps += entry.current_bps

            self._table.setItem(row, 0, QTableWidgetItem(entry.topic))
            self._table.setItem(row, 1, QTableWidgetItem(entry.robot_id))
            self._table.setItem(row, 2, QTableWidgetItem(entry.transport))

            bar = QProgressBar()
            bar.setMaximum(1_000_000)
            bar.setValue(min(int(entry.current_bps), 1_000_000))
            bar.setFormat(f"{entry.current_bps / 1024:.1f} KB/s")
            self._table.setCellWidget(row, 3, bar)

            self._table.setItem(row, 4, QTableWidgetItem(f"{entry.current_hz:.1f} Hz"))

        total_label = f"总带宽: {total_bps / 1024:.1f} KB/s"
        if total_bps > 1_000_000:
            total_label = f"总带宽: {total_bps / 1_000_000:.2f} MB/s"
        self._lb_total.setText(total_label)

    def _reset_counts(self) -> None:
        for entry in self._entries.values():
            entry.bytes_received = 0
            entry.last_bytes = 0
            entry.current_bps = 0.0
            entry.message_count = 0
            entry.last_message_count = 0
            entry.current_hz = 0.0
            entry.sample_times = []
