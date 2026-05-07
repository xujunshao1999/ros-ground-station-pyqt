from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5.QtWidgets import (
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class SensorSummaryPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("选中已订阅话题后，此处显示最新一帧摘要："))

        self._browser = QTextBrowser()
        self._browser.setOpenExternalLinks(False)
        layout.addWidget(self._browser)

        self._current_data: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def summarize_laserscan(data: dict) -> List[str]:
        ranges = data.get("ranges", [])
        if not ranges:
            return ["LaserScan: 无数据"]
        valid = [r for r in ranges if r != float("inf") and r != float("-inf")]
        return [
            f"LaserScan: {len(valid)} 个有效读数 (共 {len(ranges)})",
            f"最近: {min(valid):.2f}m, 最远: {max(valid):.2f}m",
            f"角度范围: {data.get('angle_min', 0):.2f} ~ {data.get('angle_max', 0):.2f} rad",
        ]

    @staticmethod
    def summarize_image(data: dict) -> List[str]:
        return [
            f"Image: {data.get('width', '?')}×{data.get('height', '?')} px",
            f"编码: {data.get('encoding', 'unknown')}",
        ]

    @staticmethod
    def summarize_odometry(data: dict) -> List[str]:
        pose = data.get("pose", {}).get("pose", {})
        pos = pose.get("position", {})
        orient = pose.get("orientation", {})
        child = data.get("child_frame_id", "")
        return [
            f"Odometry",
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
            f"角速度: x={ang.get('x', 0):.3f}, y={ang.get('y', 0):.3f}, z={ang.get('z', 0):.3f} rad/s",
            f"线加速度: x={lin.get('x', 0):.3f}, y={lin.get('y', 0):.3f}, z={lin.get('z', 0):.3f} m/s²",
        ]

    @staticmethod
    def summarize_data(data: dict, msg_type_hint: str = "") -> List[str]:
        if "ranges" in data:
            return SensorSummaryPanel.summarize_laserscan(data)
        elif "encoding" in data or "image" in msg_type_hint.lower():
            return SensorSummaryPanel.summarize_image(data)
        elif "pose" in data and "twist" in data:
            return SensorSummaryPanel.summarize_odometry(data)
        elif "fields" in data and "point_step" in data:
            return SensorSummaryPanel.summarize_pointcloud(data)
        elif "angular_velocity" in data:
            return SensorSummaryPanel.summarize_imu(data)
        return ["未知数据类型"]

    # ------------------------------------------------------------------
    # Slot
    # ------------------------------------------------------------------

    def on_sensor_data_received(self, robot_id: str, sensor_name: str, data: dict) -> None:
        lines = self.summarize_data(data)
        lines.insert(0, f"机器人: {robot_id}  话题: {sensor_name}")
        self._browser.setPlainText("\n".join(lines))
