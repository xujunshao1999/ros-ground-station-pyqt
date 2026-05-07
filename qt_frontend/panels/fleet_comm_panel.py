from __future__ import annotations

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
    QRadioButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class FleetCommPanel(QWidget):
    config_changed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._rules: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)

        # 规则表
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(["源", "目标", "话题", "类型", "频率", "状态", "操作"])
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self._table)

        # 按钮行
        btn_row = QHBoxLayout()
        for text in ["+ 添加规则", "删除", "暂停/恢复"]:
            btn_row.addWidget(QPushButton(text))
        layout.addLayout(btn_row)

        btn_row2 = QHBoxLayout()
        btn_row2.addWidget(QPushButton("下发全部规则"))
        btn_row2.addWidget(QPushButton("拉取当前规则"))
        layout.addLayout(btn_row2)

        # 添加/编辑表单
        self._form_group = QGroupBox("添加/编辑通信规则")
        self._form_group.setCheckable(True)
        self._form_group.setChecked(False)
        form = QVBoxLayout(self._form_group)

        f1 = QHBoxLayout()
        f1.addWidget(QLabel("源机器人:"))
        self._combo_src = QComboBox()
        f1.addWidget(self._combo_src)
        f1.addWidget(QLabel("目标:"))
        self._combo_dst = QComboBox()
        f1.addWidget(self._combo_dst)
        form.addLayout(f1)

        f2 = QHBoxLayout()
        f2.addWidget(QLabel("ROS 话题:"))
        self._edit_topic = QLineEdit()
        self._edit_topic.setPlaceholderText("/odom")
        f2.addWidget(self._edit_topic)
        form.addLayout(f2)

        f3 = QHBoxLayout()
        f3.addWidget(QLabel("消息类型:"))
        self._combo_msg_type = QComboBox()
        self._combo_msg_type.setEditable(True)
        self._combo_msg_type.addItems([
            "nav_msgs/Odometry", "geometry_msgs/Twist",
            "sensor_msgs/LaserScan", "sensor_msgs/PointCloud2",
        ])
        f3.addWidget(self._combo_msg_type)
        form.addLayout(f3)

        f4 = QHBoxLayout()
        f4.addWidget(QLabel("频率上限(Hz):"))
        self._spin_freq = QDoubleSpinBox()
        self._spin_freq.setRange(0, 100)
        self._spin_freq.setValue(1.0)
        f4.addWidget(self._spin_freq)
        form.addLayout(f4)

        f5 = QHBoxLayout()
        f5.addWidget(QLabel("用途:"))
        self._radio_position = QRadioButton("位置共享")
        self._radio_nav = QRadioButton("导航目标")
        self._radio_custom = QRadioButton("自定义")
        self._radio_pointcloud = QRadioButton("点云(重量)")
        self._radio_position.setChecked(True)
        for rb in [self._radio_position, self._radio_nav, self._radio_custom, self._radio_pointcloud]:
            f5.addWidget(rb)
        form.addLayout(f5)

        confirm_row = QHBoxLayout()
        confirm_row.addWidget(QPushButton("确认"))
        confirm_row.addWidget(QPushButton("取消"))
        form.addLayout(confirm_row)

        layout.addWidget(self._form_group)

    # ------------------------------------------------------------------
    # 纯逻辑方法（可测试）
    # ------------------------------------------------------------------

    @staticmethod
    def validate_fleet_rule(src: str, dst: str, topic: str) -> bool:
        return src != "" and dst != "" and src != dst and topic.startswith("/")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def on_robot_list_changed(self, robot_ids: List[str]) -> None:
        current_src = self._combo_src.currentText()
        current_dst = self._combo_dst.currentText()
        for combo in [self._combo_src, self._combo_dst]:
            combo.blockSignals(True)
            combo.clear()
            for rid in robot_ids:
                combo.addItem(rid)
            combo.blockSignals(False)
        if current_src:
            idx = self._combo_src.findText(current_src)
            if idx >= 0:
                self._combo_src.setCurrentIndex(idx)
        if current_dst:
            idx = self._combo_dst.findText(current_dst)
            if idx >= 0:
                self._combo_dst.setCurrentIndex(idx)
