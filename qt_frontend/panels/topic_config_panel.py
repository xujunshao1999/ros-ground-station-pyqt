from __future__ import annotations

from dataclasses import dataclass, field
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass
class SubscriptionEntry:
    topic: str = ""
    msg_type: str = ""
    freq_limit: float = 0.0
    transport: str = "auto"
    status: str = "pending"
    compression: Dict[str, Any] = field(default_factory=dict)


class TopicConfigPanel(QWidget):
    config_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._entries: List[SubscriptionEntry] = []

        layout = QVBoxLayout(self)

        # 机器人选择
        robot_row = QHBoxLayout()
        robot_row.addWidget(QLabel("目标机器人:"))
        self._robot_combo = QComboBox()
        robot_row.addWidget(self._robot_combo)
        layout.addLayout(robot_row)

        # 订阅表
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["话题", "类型", "频率(Hz)", "传输方式", "状态"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self._table)

        # 按钮行
        btn_row1 = QHBoxLayout()
        for text in ["+ 添加话题", "删除", "保存配置"]:
            btn = QPushButton(text)
            btn_row1.addWidget(btn)
        layout.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        btn_deploy = QPushButton("下发配置到机器人")
        btn_deploy.setStyleSheet("QPushButton { font-weight: bold; }")
        btn_row2.addWidget(btn_deploy)
        btn_pull = QPushButton("从机器人拉取话题")
        btn_row2.addWidget(btn_pull)
        layout.addLayout(btn_row2)

        # 添加/编辑表单（可折叠）
        self._form_group = QGroupBox("添加/编辑话题")
        self._form_group.setCheckable(True)
        self._form_group.setChecked(False)
        form = QVBoxLayout(self._form_group)

        f1 = QHBoxLayout()
        f1.addWidget(QLabel("ROS 话题:"))
        self._edit_topic = QLineEdit()
        self._edit_topic.setPlaceholderText("/example/topic")
        f1.addWidget(self._edit_topic)
        form.addLayout(f1)

        f2 = QHBoxLayout()
        f2.addWidget(QLabel("ROS 类型:"))
        self._combo_msg_type = QComboBox()
        self._combo_msg_type.setEditable(True)
        self._combo_msg_type.addItems([
            "sensor_msgs/Imu", "sensor_msgs/NavSatFix", "nav_msgs/Odometry",
            "geometry_msgs/Twist", "sensor_msgs/Image", "sensor_msgs/CompressedImage",
            "sensor_msgs/LaserScan", "sensor_msgs/PointCloud2",
        ])
        f2.addWidget(self._combo_msg_type)
        form.addLayout(f2)

        f3 = QHBoxLayout()
        f3.addWidget(QLabel("传输层级:"))
        self._combo_transport = QComboBox()
        self._combo_transport.addItems(["AUTO", "LIGHT (mqtt_json)", "MEDIUM (mqtt_binary)", "HEAVY (http_stream)"])
        f3.addWidget(self._combo_transport)
        form.addLayout(f3)

        f4 = QHBoxLayout()
        f4.addWidget(QLabel("频率上限(Hz):"))
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(0, 1000)
        self._spin_freq.setValue(0)
        self._spin_freq.setSuffix(" Hz")
        self._spin_freq.setSpecialValueText("不限")
        f4.addWidget(self._spin_freq)
        form.addLayout(f4)

        f5 = QHBoxLayout()
        f5.addWidget(QLabel("QoS:"))
        self._combo_qos = QComboBox()
        self._combo_qos.addItems(["AtMostOnce (0)", "AtLeastOnce (1)"])
        f5.addWidget(self._combo_qos)
        form.addLayout(f5)

        btn_confirm = QPushButton("确认")
        btn_cancel = QPushButton("取消")
        form_row = QHBoxLayout()
        form_row.addWidget(btn_confirm)
        form_row.addWidget(btn_cancel)
        form.addLayout(form_row)

        layout.addWidget(self._form_group)

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def validate_topic(topic: str) -> bool:
        return topic.startswith("/") and len(topic) > 1

    @staticmethod
    def validate_msg_type(msg_type: str) -> bool:
        return "/" in msg_type and len(msg_type) > 3

    @staticmethod
    def transport_from_tier(tier: str) -> str:
        tier_upper = tier.upper()
        if tier_upper == "LIGHT":
            return "mqtt_json"
        elif tier_upper == "MEDIUM":
            return "mqtt_binary"
        elif tier_upper == "HEAVY":
            return "http_stream"
        return "mqtt_json"
