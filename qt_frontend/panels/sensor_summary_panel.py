from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

TopicKey = Tuple[str, str]
TOPIC_KEY_SEPARATOR = "\x1f"


@dataclass
class TopicSnapshot:
    robot_id: str
    sensor_name: str
    msg_type: str
    summary_lines: List[str]
    first_time: float
    last_time: float
    frame_count: int = 1
    sample_times: List[float] = field(default_factory=list)

    @property
    def hz(self) -> float:
        if len(self.sample_times) < 2:
            return 0.0
        elapsed = self.sample_times[-1] - self.sample_times[0]
        if elapsed <= 0:
            return 0.0
        return (len(self.sample_times) - 1) / elapsed

    def age(self, now: float) -> float:
        return max(0.0, now - self.last_time)

    def is_stale(self, now: float, threshold: float = 2.0) -> bool:
        return self.age(now) > threshold


@dataclass
class ObservedTopic:
    robot_id: str
    sensor_name: str
    msg_type: str = ""
    status: str = "pending"


class SensorSummaryPanel(QWidget):
    _HZ_WINDOW_SECONDS = 5.0
    _STALE_THRESHOLD_SECONDS = 2.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        self._snapshots: Dict[TopicKey, TopicSnapshot] = {}
        self._observed_topics: Dict[TopicKey, ObservedTopic] = {}
        self._selected_key: Optional[TopicKey] = None
        self._user_selected_topic = False
        self._updating_combo = False
        self._last_rendered_summary_key: Optional[Tuple[TopicKey, int, bool]] = None
        self._topic_options_dirty = False
        self._topic_table_dirty = False
        self._pending_data: Dict[TopicKey, Tuple[str, Dict[str, Any], List[float]]] = {}

        layout = QVBoxLayout(self)

        header = QLabel("话题状态面板")
        header.setStyleSheet("font-weight: 700; font-size: 14px;")
        layout.addWidget(header)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("观察对象:"))
        self._topic_combo = QComboBox()
        self._topic_combo.currentIndexChanged.connect(self._on_topic_selected)
        selector_row.addWidget(self._topic_combo, 1)
        layout.addLayout(selector_row)

        metric_grid = QGridLayout()
        self._lb_status = self._build_metric_label("状态: 等待数据")
        self._lb_hz = self._build_metric_label("Hz: --")
        self._lb_age = self._build_metric_label("更新: --")
        self._lb_frames = self._build_metric_label("帧数: 0")
        metric_grid.addWidget(self._lb_status, 0, 0)
        metric_grid.addWidget(self._lb_hz, 0, 1)
        metric_grid.addWidget(self._lb_age, 1, 0)
        metric_grid.addWidget(self._lb_frames, 1, 1)
        layout.addLayout(metric_grid)

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        layout.addWidget(self._browser, 1)

        self._topic_table = QTableWidget()
        self._topic_table.setColumnCount(6)
        self._topic_table.setHorizontalHeaderLabels(
            ["话题", "机器人", "状态", "Hz", "更新", "摘要"]
        )
        self._topic_table.setMaximumHeight(190)
        header_view = self._topic_table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.Stretch)
        self._topic_table.itemSelectionChanged.connect(self._on_table_selection_changed)
        layout.addWidget(self._topic_table)
        self._render_empty_state()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_current_view)
        self._refresh_timer.start(1000)

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def build_topic_snapshot(
        robot_id: str,
        sensor_name: str,
        data: Dict[str, Any],
        now: float,
        previous: Optional[TopicSnapshot],
        msg_type_hint: str = "",
        sample_times_to_add: Optional[List[float]] = None,
    ) -> TopicSnapshot:
        msg_type = SensorSummaryPanel.infer_msg_type(data, msg_type_hint)
        summary_lines = SensorSummaryPanel.summarize_data(data, msg_type)
        new_sample_times = sample_times_to_add or [now]
        if previous is None:
            sample_times = list(new_sample_times)
            return TopicSnapshot(
                robot_id=robot_id,
                sensor_name=sensor_name,
                msg_type=msg_type,
                summary_lines=summary_lines,
                first_time=sample_times[0],
                last_time=now,
                frame_count=len(new_sample_times),
                sample_times=sample_times,
            )

        sample_times = list(previous.sample_times) + list(new_sample_times)
        cutoff = now - SensorSummaryPanel._HZ_WINDOW_SECONDS
        sample_times = [t for t in sample_times if t >= cutoff]
        return TopicSnapshot(
            robot_id=robot_id,
            sensor_name=sensor_name,
            msg_type=msg_type,
            summary_lines=summary_lines,
            first_time=previous.first_time,
            last_time=now,
            frame_count=previous.frame_count + len(new_sample_times),
            sample_times=sample_times,
        )

    @staticmethod
    def infer_msg_type(data: Dict[str, Any], msg_type_hint: str = "") -> str:
        if msg_type_hint:
            return msg_type_hint
        embedded_msg_type = data.get("_msg_type")
        if isinstance(embedded_msg_type, str) and embedded_msg_type:
            return embedded_msg_type
        protocol_msg_type = data.get("msg_type")
        if isinstance(protocol_msg_type, str) and protocol_msg_type:
            return protocol_msg_type
        if "ranges" in data:
            return "sensor_msgs/LaserScan"
        if "encoding" in data:
            return "sensor_msgs/Image"
        if "format" in data and "data" in data:
            return "sensor_msgs/CompressedImage"
        if "pose" in data and "twist" in data:
            return "nav_msgs/Odometry"
        if "fields" in data and "point_step" in data:
            return "sensor_msgs/PointCloud2"
        if "angular_velocity" in data:
            return "sensor_msgs/Imu"
        if "latitude" in data and "longitude" in data:
            return "sensor_msgs/NavSatFix"
        if "linear" in data and "angular" in data:
            return "geometry_msgs/Twist"
        if "transforms" in data:
            return "tf2_msgs/TFMessage"
        if "name" in data and "position" in data:
            return "sensor_msgs/JointState"
        if "info" in data and "data" in data:
            return "nav_msgs/OccupancyGrid"
        return "custom/Unknown"

    @staticmethod
    def summarize_laserscan(data: dict) -> List[str]:
        ranges = data.get("ranges", [])
        if not ranges:
            return ["LaserScan: 无数据"]
        valid = [
            r for r in ranges
            if isinstance(r, (int, float)) and math.isfinite(float(r))
        ]
        if not valid:
            return [
                f"LaserScan: 0 个有效读数 (共 {len(ranges)})",
                "角度范围: "
                f"{data.get('angle_min', 0):.2f} ~ "
                f"{data.get('angle_max', 0):.2f} rad",
            ]
        return [
            f"LaserScan: {len(valid)} 个有效读数 (共 {len(ranges)})",
            f"最近: {min(valid):.2f}m, 最远: {max(valid):.2f}m",
            "角度范围: "
            f"{data.get('angle_min', 0):.2f} ~ "
            f"{data.get('angle_max', 0):.2f} rad",
        ]

    @staticmethod
    def summarize_image(data: dict) -> List[str]:
        return [
            f"Image: {data.get('width', '?')}×{data.get('height', '?')} px",
            f"编码: {data.get('encoding', 'unknown')}",
        ]

    @staticmethod
    def summarize_compressed_image(data: dict) -> List[str]:
        payload = data.get("data", [])
        payload_length = len(payload) if isinstance(payload, list) else "?"
        return [
            "CompressedImage",
            f"格式: {data.get('format', 'unknown')}",
            f"数据长度: {payload_length}",
        ]

    @staticmethod
    def summarize_odometry(data: dict) -> List[str]:
        pose = data.get("pose", {}).get("pose", {})
        pos = pose.get("position", {})
        child = data.get("child_frame_id", "")
        return [
            "Odometry",
            f"位姿: x={pos.get('x', 0):.3f}, y={pos.get('y', 0):.3f}",
            f"child_frame: {child}",
        ]

    @staticmethod
    def summarize_pointcloud(data: dict) -> List[str]:
        return [
            f"PointCloud2: {data.get('width', 0)}×{data.get('height', 0)} 点",
            f"字段: {[f.get('name', '') for f in data.get('fields', [])]}",
        ]

    @staticmethod
    def summarize_imu(data: dict) -> List[str]:
        ang = data.get("angular_velocity", {})
        lin = data.get("linear_acceleration", {})
        return [
            "IMU",
            "角速度: "
            f"x={ang.get('x', 0):.3f}, "
            f"y={ang.get('y', 0):.3f}, "
            f"z={ang.get('z', 0):.3f} rad/s",
            "线加速度: "
            f"x={lin.get('x', 0):.3f}, "
            f"y={lin.get('y', 0):.3f}, "
            f"z={lin.get('z', 0):.3f} m/s²",
        ]

    @staticmethod
    def summarize_navsatfix(data: dict) -> List[str]:
        return [
            "NavSatFix",
            f"纬度: {data.get('latitude', 0):.7f}",
            f"经度: {data.get('longitude', 0):.7f}",
            f"高度: {data.get('altitude', 0):.2f} m",
        ]

    @staticmethod
    def summarize_twist(data: dict) -> List[str]:
        linear = data.get("linear", {})
        angular = data.get("angular", {})
        return [
            "Twist",
            "线速度: "
            f"x={linear.get('x', 0):.3f}, "
            f"y={linear.get('y', 0):.3f}, "
            f"z={linear.get('z', 0):.3f} m/s",
            "角速度: "
            f"x={angular.get('x', 0):.3f}, "
            f"y={angular.get('y', 0):.3f}, "
            f"z={angular.get('z', 0):.3f} rad/s",
        ]

    @staticmethod
    def summarize_tf(data: dict) -> List[str]:
        transforms = data.get("transforms", [])
        frames = []
        for item in transforms[:5]:
            header = item.get("header", {}) if isinstance(item, dict) else {}
            child = item.get("child_frame_id", "") if isinstance(item, dict) else ""
            parent = header.get("frame_id", "")
            frames.append(f"{parent} -> {child}")
        return [
            f"TFMessage: {len(transforms)} 个 transform",
            f"前几项: {', '.join(frames) if frames else '-'}",
        ]

    @staticmethod
    def summarize_joint_state(data: dict) -> List[str]:
        names = data.get("name", [])
        positions = data.get("position", [])
        velocities = data.get("velocity", [])
        efforts = data.get("effort", [])
        preview = ", ".join(str(name) for name in names[:5]) if isinstance(names, list) else "-"
        return [
            f"JointState: {len(names) if isinstance(names, list) else 0} 个关节",
            f"关节: {preview or '-'}",
            f"position: {len(positions) if isinstance(positions, list) else 0}",
            f"velocity: {len(velocities) if isinstance(velocities, list) else 0}",
            f"effort: {len(efforts) if isinstance(efforts, list) else 0}",
        ]

    @staticmethod
    def summarize_occupancy_grid(data: dict) -> List[str]:
        info = data.get("info", {})
        width = info.get("width", 0) if isinstance(info, dict) else 0
        height = info.get("height", 0) if isinstance(info, dict) else 0
        resolution = info.get("resolution", 0.0) if isinstance(info, dict) else 0.0
        values = data.get("data", [])
        return [
            f"OccupancyGrid: {width}×{height}",
            f"resolution: {resolution:.3f} m",
            f"数据长度: {len(values) if isinstance(values, list) else 0}",
        ]

    @staticmethod
    def summarize_generic(data: dict, msg_type_hint: str = "") -> List[str]:
        header = data.get("header", {})
        lines = [
            f"通用摘要: {msg_type_hint or 'custom/Unknown'}",
            f"字段: {len(data)}",
        ]
        if isinstance(header, dict):
            frame_id = header.get("frame_id")
            if frame_id:
                lines.append(f"frame_id: {frame_id}")
            stamp = header.get("stamp")
            if stamp:
                lines.append(f"stamp: {stamp}")
        preview_keys = list(data.keys())[:8]
        lines.append(f"顶层字段: {', '.join(preview_keys) if preview_keys else '-'}")
        return lines

    @staticmethod
    def summarize_data(data: dict, msg_type_hint: str = "") -> List[str]:
        effective_type = SensorSummaryPanel.infer_msg_type(data, msg_type_hint)
        if "JointState" in effective_type:
            return SensorSummaryPanel.summarize_joint_state(data)
        elif "OccupancyGrid" in effective_type:
            return SensorSummaryPanel.summarize_occupancy_grid(data)
        elif "LaserScan" in effective_type or "ranges" in data:
            return SensorSummaryPanel.summarize_laserscan(data)
        elif "CompressedImage" in effective_type or ("format" in data and "data" in data):
            return SensorSummaryPanel.summarize_compressed_image(data)
        elif "Image" in effective_type or "encoding" in data:
            return SensorSummaryPanel.summarize_image(data)
        elif "Odometry" in effective_type or ("pose" in data and "twist" in data):
            return SensorSummaryPanel.summarize_odometry(data)
        elif "PointCloud2" in effective_type or ("fields" in data and "point_step" in data):
            return SensorSummaryPanel.summarize_pointcloud(data)
        elif "Imu" in effective_type or "angular_velocity" in data:
            return SensorSummaryPanel.summarize_imu(data)
        elif "NavSatFix" in effective_type or ("latitude" in data and "longitude" in data):
            return SensorSummaryPanel.summarize_navsatfix(data)
        elif "Twist" in effective_type or ("linear" in data and "angular" in data):
            return SensorSummaryPanel.summarize_twist(data)
        elif "TFMessage" in effective_type or "transforms" in data:
            return SensorSummaryPanel.summarize_tf(data)
        return SensorSummaryPanel.summarize_generic(data, effective_type)

    @staticmethod
    def format_rate(value: float) -> str:
        return f"{value:.1f} Hz" if value >= 0.05 else "--"

    @staticmethod
    def format_age(value: float) -> str:
        if value < 1.0:
            return f"{value * 1000:.0f} ms"
        return f"{value:.1f} s"

    @staticmethod
    def encode_topic_key(key: TopicKey) -> str:
        return f"{key[0]}{TOPIC_KEY_SEPARATOR}{key[1]}"

    @staticmethod
    def decode_topic_key(value: str) -> Optional[TopicKey]:
        if TOPIC_KEY_SEPARATOR not in value:
            return None
        robot_id, sensor_name = value.split(TOPIC_KEY_SEPARATOR, 1)
        if not robot_id or not sensor_name:
            return None
        return (robot_id, sensor_name)

    @staticmethod
    def normalize_sensor_name(topic: str) -> str:
        return topic.strip().lstrip("/")

    # ------------------------------------------------------------------
    # Slot
    # ------------------------------------------------------------------

    def on_sensor_data_received(self, robot_id: str, sensor_name: str, data: dict) -> None:
        if not isinstance(data, dict):
            data = {"raw": data}

        normalized_sensor_name = self.normalize_sensor_name(sensor_name)
        key = (robot_id, normalized_sensor_name)
        now = time.monotonic()
        msg_type = self.infer_msg_type(data)
        pending = self._pending_data.get(key)
        sample_times = list(pending[2]) if pending is not None else []
        sample_times.append(now)
        self._pending_data[key] = (msg_type, data, sample_times)

        previous_topic = self._observed_topics.get(key)
        self._observed_topics[key] = ObservedTopic(
            robot_id=robot_id,
            sensor_name=normalized_sensor_name,
            msg_type=msg_type or (previous_topic.msg_type if previous_topic else ""),
            status="active",
        )
        if previous_topic is None or previous_topic.msg_type != msg_type:
            self._topic_options_dirty = True
        self._topic_table_dirty = True

        selected_snapshot = (
            self._snapshots.get(self._selected_key)
            if self._selected_key is not None
            else None
        )
        if self._selected_key is None or (
            selected_snapshot is None and not self._user_selected_topic
        ):
            self._select_topic(key)
        elif self._selected_key == key:
            self._last_rendered_summary_key = None

    def on_subscriptions_changed(
        self,
        robot_id: str,
        subscriptions: List[Dict[str, Any]],
    ) -> None:
        existing_keys = [
            key for key in self._observed_topics
            if key[0] == robot_id and key not in self._snapshots
        ]
        for key in existing_keys:
            self._observed_topics.pop(key, None)

        for item in subscriptions:
            topic = str(item.get("topic", ""))
            sensor_name = self.normalize_sensor_name(topic)
            if not sensor_name:
                continue
            status = str(item.get("status") or "pending")
            if status in ("inactive", "deleted"):
                continue
            key = (robot_id, sensor_name)
            snapshot = self._snapshots.get(key)
            msg_type = str(
                item.get("msg_type") or (snapshot.msg_type if snapshot else "")
            )
            self._observed_topics[key] = ObservedTopic(
                robot_id=robot_id,
                sensor_name=sensor_name,
                msg_type=msg_type,
                status=status,
            )

        self._topic_options_dirty = True
        self._topic_table_dirty = True
        self._refresh_topic_options()
        self._refresh_topic_table()
        if self._selected_key is None and self._observed_topics:
            self._select_topic(sorted(self._observed_topics.keys())[0])
        elif self._selected_key not in self._observed_topics:
            self._selected_key = None
            self._render_empty_state()

    def retain_robots(self, robot_ids: List[str]) -> None:
        robot_id_set = set(robot_ids)
        removed = False
        for key in list(self._observed_topics.keys()):
            if key[0] not in robot_id_set:
                self._observed_topics.pop(key, None)
                self._snapshots.pop(key, None)
                removed = True

        if not removed:
            return

        self._topic_options_dirty = True
        self._topic_table_dirty = True
        if self._selected_key not in self._observed_topics:
            self._selected_key = None
            self._user_selected_topic = False
        self._refresh_topic_options()
        self._refresh_topic_table()
        if self._observed_topics:
            self._select_topic(sorted(self._observed_topics.keys())[0], force=True)
        else:
            self._render_empty_state()

    # ------------------------------------------------------------------
    # 内部 UI
    # ------------------------------------------------------------------

    def _build_metric_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        label.setStyleSheet(self._metric_style())
        return label

    def _refresh_topic_options(self) -> None:
        current_key = self._selected_key
        self._updating_combo = True
        self._topic_combo.clear()
        for key, topic in sorted(self._observed_topics.items()):
            label = f"{topic.robot_id} / {topic.sensor_name}"
            if topic.msg_type:
                label = f"{label}  ({topic.msg_type})"
            self._topic_combo.addItem(label, self.encode_topic_key(key))
        if current_key is not None:
            index = self._topic_combo.findData(self.encode_topic_key(current_key))
            if index >= 0:
                self._topic_combo.setCurrentIndex(index)
        self._updating_combo = False
        self._topic_options_dirty = False

    def _select_topic(self, key: TopicKey, force: bool = False) -> None:
        index = self._topic_combo.findData(self.encode_topic_key(key))
        if index < 0:
            return
        self._selected_key = key
        self._updating_combo = True
        self._topic_combo.setCurrentIndex(index)
        self._updating_combo = False
        if not force and not self.isVisible():
            return
        snapshot = self._snapshots.get(key)
        if snapshot:
            self._render_snapshot(snapshot)
        else:
            self._render_waiting_topic(key)

    def _on_topic_selected(self, index: int) -> None:
        if self._updating_combo:
            return
        encoded_key = self._topic_combo.itemData(index)
        if not isinstance(encoded_key, str):
            return
        key = self.decode_topic_key(encoded_key)
        if key is None:
            return
        self._user_selected_topic = True
        self._selected_key = key
        snapshot = self._snapshots.get(key)
        if snapshot:
            self._render_snapshot(snapshot)
        else:
            self._render_waiting_topic(key)

    def _on_table_selection_changed(self) -> None:
        selected = self._topic_table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        item = self._topic_table.item(row, 0)
        if not item:
            return
        key = item.data(Qt.UserRole)
        if key:
            self._select_topic(key)

    def _render_snapshot(self, snapshot: TopicSnapshot) -> None:
        now = time.monotonic()
        stale = snapshot.is_stale(now, self._STALE_THRESHOLD_SECONDS)
        snapshot_key = (snapshot.robot_id, snapshot.sensor_name)
        summary_key = (snapshot_key, snapshot.frame_count, stale)
        status = "断流" if stale else "正常"
        self._lb_status.setText(f"状态: {status}")
        self._lb_status.setStyleSheet(
            self._metric_style("#3a2f18" if stale else "#193323")
        )
        self._lb_hz.setText(f"Hz: {self.format_rate(snapshot.hz)}")
        self._lb_age.setText(f"更新: {self.format_age(snapshot.age(now))}")
        self._lb_frames.setText(f"帧数: {snapshot.frame_count}")

        if self._last_rendered_summary_key != summary_key:
            lines = [
                f"机器人: {snapshot.robot_id}  话题: {snapshot.sensor_name}",
                f"类型: {snapshot.msg_type}",
                "统计口径: 当前订阅话题的轻量入站状态",
                "",
            ]
            lines.extend(snapshot.summary_lines)
            lines.extend(["", "诊断:"])
            if stale:
                lines.append(
                    f"- {self.format_age(snapshot.age(now))} 未收到新消息，可能断流或已取消订阅"
                )
            elif snapshot.hz <= 0 and snapshot.frame_count < 2:
                lines.append("- 已收到首帧，等待更多样本计算 Hz")
            else:
                lines.append("- 消息持续到达")
            self._browser.setPlainText("\n".join(lines))
            self._last_rendered_summary_key = summary_key

    def _render_empty_state(self) -> None:
        self._last_rendered_summary_key = None
        self._browser.setPlainText(
            "等待传感器数据...\n\n"
            "收到 MQTT 入站数据后，这里会按当前订阅话题显示状态、Hz 和最新帧摘要。"
        )

    def _render_waiting_topic(self, key: TopicKey) -> None:
        topic = self._observed_topics.get(key)
        if topic is None:
            self._render_empty_state()
            return
        self._last_rendered_summary_key = None
        self._lb_status.setText("状态: 等待数据")
        self._lb_status.setStyleSheet(self._metric_style())
        self._lb_hz.setText("Hz: --")
        self._lb_age.setText("更新: --")
        self._lb_frames.setText("帧数: 0")
        self._browser.setPlainText(
            f"机器人: {topic.robot_id}  话题: {topic.sensor_name}\n"
            f"类型: {topic.msg_type or 'unknown'}\n"
            "状态: 等待数据\n\n"
            "该话题已在当前订阅列表中，但地面站还没有收到对应 MQTT 数据。"
        )

    def _refresh_current_view(self, force: bool = False) -> None:
        if not force and not self.isVisible():
            return
        self._process_pending_data()
        if not self._snapshots:
            if self._topic_options_dirty:
                self._refresh_topic_options()
            if self._topic_table_dirty:
                self._refresh_topic_table()
            return
        if self._topic_options_dirty:
            self._refresh_topic_options()
        if self._topic_table_dirty:
            self._refresh_topic_table()
        if self._selected_key is None and self._observed_topics:
            self._select_topic(sorted(self._observed_topics.keys())[0], force=force)
        if self._selected_key is None:
            return
        snapshot = self._snapshots.get(self._selected_key)
        if snapshot:
            self._render_snapshot(snapshot)
        else:
            self._render_waiting_topic(self._selected_key)

    def _process_pending_data(self) -> None:
        if not self._pending_data:
            return

        pending_items = list(self._pending_data.items())
        self._pending_data.clear()
        for key, (msg_type, data, arrival_times) in pending_items:
            if not arrival_times:
                continue
            robot_id, sensor_name = key
            previous = self._snapshots.get(key)
            snapshot = self.build_topic_snapshot(
                robot_id=robot_id,
                sensor_name=sensor_name,
                data=data,
                now=arrival_times[-1],
                previous=previous,
                msg_type_hint=msg_type,
                sample_times_to_add=arrival_times,
            )
            if snapshot is not None:
                self._snapshots[key] = snapshot
                topic = self._observed_topics.get(key)
                if topic is not None and topic.msg_type != snapshot.msg_type:
                    self._observed_topics[key] = ObservedTopic(
                        robot_id=topic.robot_id,
                        sensor_name=topic.sensor_name,
                        msg_type=snapshot.msg_type,
                        status=topic.status,
                    )
                    self._topic_options_dirty = True
                if self._selected_key == key:
                    self._last_rendered_summary_key = None
        self._topic_table_dirty = True

    def _metric_style(self, background: str = "#202838") -> str:
        return (
            "QLabel { border: 1px solid #394355; border-radius: 5px; "
            f"padding: 6px; background-color: {background}; }}"
        )

    def _refresh_topic_table(self) -> None:
        now = time.monotonic()
        items = sorted(self._observed_topics.items())
        self._topic_table.setRowCount(len(items))
        for row, (key, topic) in enumerate(items):
            snapshot = self._snapshots.get(key)
            if snapshot is None:
                status = "等待数据"
                hz = "--"
                age = "--"
                summary = topic.msg_type or "-"
            else:
                status = (
                    "断流"
                    if snapshot.is_stale(now, self._STALE_THRESHOLD_SECONDS)
                    else "正常"
                )
                hz = self.format_rate(snapshot.hz)
                age = self.format_age(snapshot.age(now))
                summary = snapshot.summary_lines[0] if snapshot.summary_lines else "-"
            values = [
                topic.sensor_name,
                topic.robot_id,
                status,
                hz,
                age,
                summary,
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setData(Qt.UserRole, key)
                self._topic_table.setItem(row, col, item)
        self._topic_table_dirty = False
