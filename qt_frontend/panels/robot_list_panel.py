from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass
class RobotInfo:
    robot_id: str = ""
    online: bool = False
    battery: float = 0.0
    mode: str = "stop"
    position: tuple = (0.0, 0.0, 0.0)
    velocity: tuple = (0.0, 0.0)
    last_seen: float = 0.0
    subscriptions_count: int = 0


class RobotListPanel(QWidget):
    robot_selected = pyqtSignal(str)
    robot_deselected = pyqtSignal()
    online_robots_changed = pyqtSignal(list)
    discover_requested = pyqtSignal()
    global_frame_requested = pyqtSignal()
    follow_frame_changed = pyqtSignal(bool)

    _HEARTBEAT_TIMEOUT = 30.0

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._robots: dict[str, RobotInfo] = {}
        self._subscription_counts: Dict[str, int] = {}
        self._last_online_robot_ids: List[str] = []

        layout = QVBoxLayout(self)

        # 视角控制和发现操作放在同一行，减少用户在机器人面板内寻找入口的成本。
        btn_row = QHBoxLayout()
        btn_discover = QPushButton("发现机器人")
        btn_discover.clicked.connect(self.discover_requested.emit)
        btn_row.addWidget(btn_discover)

        self._btn_global_frame = QPushButton("全局视角")
        self._btn_global_frame.clicked.connect(self.global_frame_requested.emit)
        btn_row.addWidget(self._btn_global_frame)

        self._chk_follow_frame = QCheckBox("跟随选中")
        self._chk_follow_frame.setChecked(True)
        self._chk_follow_frame.toggled.connect(self.follow_frame_changed.emit)
        btn_row.addWidget(self._chk_follow_frame)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # 机器人树
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["", "机器人 ID", "电量", "模式", "订阅数"])
        self._tree.setColumnWidth(0, 24)
        self._tree.setColumnWidth(1, 120)
        self._tree.setColumnWidth(2, 60)
        self._tree.setColumnWidth(3, 60)
        self._tree.setColumnWidth(4, 50)
        self._tree.header().setStretchLastSection(True)
        self._tree.setRootIsDecorated(False)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        self._tree.itemPressed.connect(self._on_item_pressed)
        self._tree.setAlternatingRowColors(True)
        layout.addWidget(self._tree)

        # 空状态
        self._empty_label = QLabel("未发现机器人")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setStyleSheet("color: #888;")
        layout.addWidget(self._empty_label)

        # 选中机器人详情
        detail_group = QGroupBox("选中机器人详情")
        detail_layout = QVBoxLayout(detail_group)

        self._lb_position = QLabel("位姿: --")
        self._lb_velocity = QLabel("速度: --")
        self._battery_bar = QProgressBar()
        self._battery_bar.setRange(0, 100)
        self._battery_bar.setFormat("电量 %v%")
        detail_layout.addWidget(self._lb_position)
        detail_layout.addWidget(self._lb_velocity)
        self._lb_current_frame = QLabel("当前视角: --")
        detail_layout.addWidget(self._lb_current_frame)
        detail_layout.addWidget(self._battery_bar)

        layout.addWidget(detail_group)

        # 心跳检查定时器
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._check_heartbeats)
        self._heartbeat_timer.start(5000)

        self._update_empty_state()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def selected_robot(self) -> Optional[str]:
        items = self._tree.selectedItems()
        if items:
            return items[0].data(0, Qt.UserRole)
        return None

    def get_online_robots(self) -> List[str]:
        return [r.robot_id for r in self._robots.values() if r.online]

    def follow_selected_robot_enabled(self) -> bool:
        return self._chk_follow_frame.isChecked()

    def set_follow_selected_robot_enabled(self, enabled: bool) -> None:
        self._chk_follow_frame.setChecked(enabled)

    def set_current_fixed_frame(self, frame: str) -> None:
        text = frame.strip() if frame.strip() else "--"
        self._lb_current_frame.setText("当前视角: %s" % text)

    # ------------------------------------------------------------------
    # MQTT 回调 slots
    # ------------------------------------------------------------------

    def on_status_received(self, robot_id: str, data: dict) -> None:
        import time
        now = time.monotonic()

        if robot_id not in self._robots:
            self._robots[robot_id] = RobotInfo(robot_id=robot_id)

        info = self._robots[robot_id]
        info.subscriptions_count = self._subscription_counts.get(
            robot_id, info.subscriptions_count
        )
        info.online = True
        info.last_seen = now
        info.battery = data.get("battery", 0.0)
        info.mode = data.get("mode", "stop")

        pos = data.get("position", {})
        info.position = (pos.get("x", 0.0), pos.get("y", 0.0), pos.get("theta", 0.0))

        vel = data.get("velocity", {})
        info.velocity = (vel.get("linear", 0.0), vel.get("angular", 0.0))

        self._update_tree_item(robot_id, info)
        self._emit_online_robots_changed_if_needed()

    def on_discover_response(self, robot_id: str, data: dict) -> None:
        import time
        now = time.monotonic()

        if robot_id not in self._robots:
            self._robots[robot_id] = RobotInfo(robot_id=robot_id)

        info = self.info_after_discover_response(
            self._robots[robot_id], data, now
        )
        info.subscriptions_count = self._subscription_counts.get(
            robot_id, info.subscriptions_count
        )
        self._robots[robot_id] = info
        self._update_tree_item(robot_id, info)
        self._emit_online_robots_changed_if_needed()

    def update_subscription_counts(self, counts: Dict[str, int]) -> None:
        self._subscription_counts = dict(counts)
        for robot_id, count in self._subscription_counts.items():
            if robot_id not in self._robots:
                continue
            self._robots[robot_id].subscriptions_count = count
            self._update_tree_item(robot_id, self._robots[robot_id])

    def update_subscription_count(self, robot_id: str, count: int) -> None:
        self._subscription_counts[robot_id] = count
        if robot_id not in self._robots:
            return
        self._robots[robot_id].subscriptions_count = count
        self._update_tree_item(robot_id, self._robots[robot_id])

    @staticmethod
    def info_after_discover_response(
        info: RobotInfo, data: dict, now: float
    ) -> RobotInfo:
        info.online = True
        info.last_seen = now
        return info

    @staticmethod
    def subscription_counts_from_transmit_config(
        config: Dict[str, Any]
    ) -> Dict[str, int]:
        raw = config.get("subscriptions") or {}
        if not isinstance(raw, dict):
            return {}
        counts: Dict[str, int] = {}
        for robot_id, subscriptions in raw.items():
            if isinstance(subscriptions, list):
                counts[robot_id] = len([
                    item for item in subscriptions if isinstance(item, dict)
                ])
            elif isinstance(subscriptions, dict):
                counts[robot_id] = len(subscriptions)
        return counts

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _update_tree_item(self, robot_id: str, info: RobotInfo) -> None:
        item = self._find_tree_item(robot_id)
        if item is None:
            item = QTreeWidgetItem(self._tree)
            item.setData(0, Qt.UserRole, robot_id)

        status_indicator = "●" if info.online else "○"
        item.setText(0, status_indicator)
        item.setForeground(0, Qt.green if info.online else Qt.gray)
        item.setText(1, robot_id)
        item.setText(2, f"{info.battery:.0f}%")
        item.setText(3, info.mode)
        item.setText(4, str(info.subscriptions_count))

        self._update_empty_state()
        if self.selected_robot() == robot_id:
            self._update_detail(info)

    def _find_tree_item(self, robot_id: str) -> Optional[QTreeWidgetItem]:
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, Qt.UserRole) == robot_id:
                return item
        return None

    def _update_empty_state(self) -> None:
        has_robots = self._tree.topLevelItemCount() > 0
        self._empty_label.setVisible(not has_robots)
        self._tree.setVisible(has_robots)

    def _on_selection_changed(self) -> None:
        robot_id = self.selected_robot()
        if robot_id and robot_id in self._robots:
            self._update_detail(self._robots[robot_id])
            self.robot_selected.emit(robot_id)
        else:
            self._clear_detail()
            self.robot_deselected.emit()

    def _on_item_pressed(self, item: QTreeWidgetItem, column: int) -> None:
        _ = column
        robot_id = item.data(0, Qt.UserRole)
        if not item.isSelected() or not robot_id or robot_id not in self._robots:
            return
        # 已选中的同一行再次点击不会触发 selectionChanged，但仍代表用户重新选择该机器人。
        self._update_detail(self._robots[robot_id])
        self.robot_selected.emit(robot_id)

    def _update_detail(self, info: RobotInfo) -> None:
        x, y, theta = info.position
        lin, ang = info.velocity
        self._lb_position.setText(f"位姿: x={x:.2f}, y={y:.2f}, θ={theta:.2f}")
        self._lb_velocity.setText(f"速度: linear={lin:.2f}, angular={ang:.2f}")
        self._battery_bar.setValue(self._battery_percent(info.battery))

    def _clear_detail(self) -> None:
        self._lb_position.setText("位姿: --")
        self._lb_velocity.setText("速度: --")
        self._battery_bar.setValue(0)

    @staticmethod
    def _battery_percent(value: float) -> int:
        return max(0, min(100, int(round(value))))

    def _check_heartbeats(self) -> None:
        import time
        now = time.monotonic()
        for info in self._robots.values():
            if info.online and (now - info.last_seen) > self._HEARTBEAT_TIMEOUT:
                info.online = False
                self._update_tree_item(info.robot_id, info)
        self._emit_online_robots_changed_if_needed()

    def _emit_online_robots_changed_if_needed(self) -> None:
        robot_ids = sorted(self.get_online_robots())
        if robot_ids == self._last_online_robot_ids:
            return
        self._last_online_robot_ids = robot_ids
        self.online_robots_changed.emit(list(robot_ids))
