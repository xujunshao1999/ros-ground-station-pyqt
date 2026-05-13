from __future__ import annotations

import ctypes
import logging
import os
import sip
import subprocess
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAction, QDockWidget, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QSizePolicy, QSplitter, QStatusBar, QTabWidget,
    QToolBar, QVBoxLayout, QWidget,
)

from qt_frontend.mqtt_client import MqttClient
from qt_frontend.panels import (
    CommandPanel, DataSenderPanel, EventPanel, FleetCommPanel,
    RobotListPanel, SensorSummaryPanel, TopicConfigPanel, TrafficMonitor,
)
from qt_frontend.theme import DANGER, SUCCESS

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, config: dict) -> None:
        super().__init__()
        self._config = config
        self._rviz_ptr = None
        self._rviz_lib = None
        self._mqtt_client: Optional[MqttClient] = None
        self._splitter_sizes = [360, 920, 320]

        self._init_window()
        self._init_panels()
        self._init_menu_and_toolbar()
        self._init_central_widget()
        self._init_status_bar()
        self._init_mqtt()
        self._init_ros_monitor()

        QTimer.singleShot(200, self._init_rviz)
        QTimer.singleShot(350, self._apply_splitter_layout)

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _init_window(self) -> None:
        self.setWindowTitle("ROS Ground Station")
        self.resize(1600, 900)

    def _init_panels(self) -> None:
        self._robot_list = RobotListPanel()
        self._command = CommandPanel()
        self._event_panel = EventPanel()
        self._topic_config = TopicConfigPanel()
        self._fleet_comm = FleetCommPanel()
        self._sensor_panel = SensorSummaryPanel()
        self._data_sender = DataSenderPanel()
        self._traffic_monitor = TrafficMonitor()

        self._robot_list.robot_selected.connect(self._command.on_robot_selected)
        self._robot_list.robot_deselected.connect(lambda: self._command.on_robot_selected(""))

    def _init_menu_and_toolbar(self) -> None:
        menubar = self.menuBar()

        # --- 连接 ---
        m = menubar.addMenu("&连接")
        self._act_connect = QAction("连接 Broker", self)
        self._act_disconnect = QAction("断开连接", self)
        self._act_quit = QAction("退出", self)
        self._act_quit.triggered.connect(self.close)
        self._act_disconnect.setEnabled(False)
        m.addAction(self._act_connect); m.addAction(self._act_disconnect)
        m.addSeparator(); m.addAction(self._act_quit)

        # --- 机器人 ---
        m = menubar.addMenu("&机器人")
        self._act_discover = QAction("发现机器人", self)
        self._act_emergency = QAction("全部急停", self)
        m.addAction(self._act_discover); m.addSeparator(); m.addAction(self._act_emergency)

        # --- 录制 ---
        m = menubar.addMenu("&录制")
        self._act_rec_start = QAction("开始录制", self)
        self._act_rec_stop = QAction("停止录制", self); self._act_rec_stop.setEnabled(False)
        m.addAction(self._act_rec_start); m.addAction(self._act_rec_stop)

        # --- 视图 ---
        m = menubar.addMenu("&视图")
        self._act_reset_layout = QAction("重置布局", self)
        m.addAction(self._act_reset_layout)

        # --- 帮助 ---
        m = menubar.addMenu("&帮助")
        self._act_about = QAction("关于", self)
        m.addAction(self._act_about)

        # --- 工具栏 ---
        toolbar = QToolBar("主工具栏"); toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._lb_conn = QLabel("● 已断开")
        self._lb_conn.setStyleSheet("color: red; font-weight: bold;")
        toolbar.addWidget(self._lb_conn); toolbar.addSeparator()

        mqtt_cfg = self._config.get("mqtt", {})
        toolbar.addWidget(QLabel(f"Broker: {mqtt_cfg.get('broker_host','localhost')}:{mqtt_cfg.get('broker_port',1883)}"))
        toolbar.addSeparator()

        self._lb_online = QLabel("在线: 0"); toolbar.addWidget(self._lb_online)
        toolbar.addSeparator()

        self._lb_fps = QLabel("FPS: --"); toolbar.addWidget(self._lb_fps)
        toolbar.addSeparator()

        self._lb_rec = QLabel("录制: 00:00:00"); toolbar.addWidget(self._lb_rec)
        toolbar.addSeparator()

        btn = QPushButton("全部急停")
        btn.setObjectName("dangerButton")
        btn.setMinimumWidth(112)
        btn.clicked.connect(self._on_emergency)
        toolbar.addWidget(btn)

    def _init_central_widget(self) -> None:
        # Left tabs
        left = QTabWidget()
        left.setMinimumWidth(320)
        t = QWidget(); l = QVBoxLayout(t); l.setContentsMargins(0,0,0,0)
        l.addWidget(self._robot_list); l.addWidget(self._command)
        left.addTab(t, "机器人")
        t2 = QWidget(); l2 = QVBoxLayout(t2); l2.setContentsMargins(0,0,0,0)
        sub = QTabWidget(); sub.addTab(self._topic_config, "传输"); sub.addTab(self._fleet_comm, "编队")
        l2.addWidget(sub); left.addTab(t2, "配置")
        left.addTab(self._event_panel, "事件")

        # Right tabs
        right = QTabWidget()
        right.setMinimumWidth(280)
        self._display_container = QWidget()
        dl = QVBoxLayout(self._display_container); dl.setContentsMargins(0,0,0,0)
        dl.addWidget(QLabel("RViz 初始化中..."))
        right.addTab(self._display_container, "Display")
        right.addTab(self._sensor_panel, "摘要")
        right.addTab(self._data_sender, "发送")
        right.addTab(self._traffic_monitor, "流量")

        # Camera dock
        self._camera_dock = QDockWidget("摄像头", self)
        cam_container = QWidget()
        self._camera_dock_layout = QVBoxLayout(cam_container)
        self._camera_dock_layout.setContentsMargins(0,0,0,0)
        self._camera_dock.setWidget(cam_container)
        self.addDockWidget(Qt.RightDockWidgetArea, self._camera_dock)

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(True)
        self._splitter.addWidget(left)
        self._splitter.addWidget(QLabel("加载中..."))
        self._splitter.addWidget(right)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._apply_splitter_layout()
        self.setCentralWidget(self._splitter)

    def _apply_splitter_layout(self) -> None:
        self._splitter.setSizes(self._splitter_sizes)

    def _init_status_bar(self) -> None:
        sb = QStatusBar()
        self._lb_topics = QLabel("话题: --")
        self._lb_traffic = QLabel("MQTT: 0 B / 0 B")
        self._lb_rec_status = QLabel("录制: ○")
        self._lb_ros = QLabel("ROS Master: 检测中...")
        for w in [self._lb_topics, self._lb_traffic, self._lb_rec_status, self._lb_ros]:
            sb.addWidget(w)
        self.setStatusBar(sb)

    def _init_mqtt(self) -> None:
        mqtt_cfg = self._config.get("mqtt", {})
        self._mqtt_client = MqttClient(
            broker_host=mqtt_cfg.get("broker_host", "localhost"),
            broker_port=mqtt_cfg.get("broker_port", 1883),
            client_id=mqtt_cfg.get("client_id", "qt_frontend"),
        )
        sig = self._mqtt_client.signals
        sig.connected.connect(self._on_mqtt_connected)
        sig.disconnected.connect(self._on_mqtt_disconnected)
        sig.status_received.connect(self._on_robot_status)
        sig.event_received.connect(self._event_panel.on_event_received)
        sig.cmd_ack_received.connect(self._command.on_cmd_ack)
        sig.sensor_data_received.connect(self._on_sensor_data)
        sig.discover_response_received.connect(self._on_discover)

        self._act_connect.triggered.connect(self._mqtt_client.connect)
        self._act_disconnect.triggered.connect(self._mqtt_client.disconnect)
        self._act_discover.triggered.connect(self._mqtt_client.send_discover)
        self._robot_list.discover_requested.connect(self._mqtt_client.send_discover)
        self._command.command_sent.connect(self._on_command)
        self._data_sender.send_json.connect(self._on_data_send)

    def _init_ros_monitor(self) -> None:
        self._ros_timer = QTimer(self); self._ros_timer.timeout.connect(self._check_ros)
        self._ros_timer.start(5000); self._check_ros()

    def _check_ros(self) -> None:
        try:
            r = subprocess.run(["rostopic","list"], capture_output=True, text=True, timeout=3,
                env={**os.environ, "ROS_MASTER_URI": self._config.get("ros",{}).get("master_uri","http://localhost:11311")})
            ok = r.returncode == 0
        except Exception:
            ok = False
        self._lb_ros.setText("ROS Master ✓" if ok else "ROS Master ✗")
        self._lb_ros.setStyleSheet(
            f"color: {SUCCESS if ok else DANGER}; font-weight: bold;"
        )

    # ------------------------------------------------------------------
    # RViz
    # ------------------------------------------------------------------

    def _init_rviz(self) -> None:
        lib_path = str(Path(__file__).resolve().parent / "native" / "build" / "librviz_widget.so")
        try:
            lib = ctypes.CDLL(lib_path)
            lib.create_rviz_widget.argtypes = [ctypes.c_void_p]
            lib.create_rviz_widget.restype = ctypes.c_void_p
            lib.set_fixed_frame.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            lib.set_fixed_frame.restype = None
            lib.get_display_panel.argtypes = [ctypes.c_void_p]
            lib.get_display_panel.restype = ctypes.c_void_p
            lib.set_dock_layout.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            lib.set_dock_layout.restype = None
            self._rviz_lib = lib
        except OSError as e:
            logger.error(f"Failed to load librviz_widget.so: {e}")
            return

        rviz_ptr = lib.create_rviz_widget(None)
        if not rviz_ptr: return
        self._rviz_ptr = rviz_ptr

        rviz_widget = sip.wrapinstance(int(rviz_ptr), QWidget)
        rviz_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        old = self._splitter.replaceWidget(1, rviz_widget)
        if old:
            old.deleteLater()
        self._splitter.setStretchFactor(1, 1)
        self._apply_splitter_layout()

        lib.set_fixed_frame(rviz_ptr, b"map")

        # Display tab
        disp_ptr = lib.get_display_panel(rviz_ptr)
        if disp_ptr:
            disp_widget = sip.wrapinstance(int(disp_ptr), QWidget)
            dl = self._display_container.layout()
            while dl.count():
                w = dl.takeAt(0).widget()
                if w: w.deleteLater()
            dl.addWidget(disp_widget)

        # Camera dock layout for RViz Image/Camera panels
        layout_ptr = sip.unwrapinstance(self._camera_dock_layout)
        if layout_ptr:
            lib.set_dock_layout(rviz_ptr, ctypes.c_void_p(layout_ptr))

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_robot_status(self, robot_id: str, data: dict) -> None:
        self._robot_list.on_status_received(robot_id, data)
        robots = self._robot_list.get_online_robots()
        self._command.on_robot_list_changed(robots)
        self._lb_online.setText(f"在线: {len(robots)}")

    def _on_discover(self, robot_id: str, data: dict) -> None:
        self._robot_list.on_discover_response(robot_id, data)
        robots = self._robot_list.get_online_robots()
        self._command.on_robot_list_changed(robots)
        self._lb_online.setText(f"在线: {len(robots)}")

    def _on_mqtt_connected(self) -> None:
        self._lb_conn.setText("● 已连接")
        self._lb_conn.setStyleSheet(f"color: {SUCCESS}; font-weight: bold;")
        self._act_connect.setEnabled(False); self._act_disconnect.setEnabled(True)

    def _on_mqtt_disconnected(self) -> None:
        self._lb_conn.setText("● 已断开")
        self._lb_conn.setStyleSheet(f"color: {DANGER}; font-weight: bold;")
        self._act_connect.setEnabled(True); self._act_disconnect.setEnabled(False)

    def _on_sensor_data(self, robot_id: str, sensor_name: str, data: object) -> None:
        if isinstance(data, dict):
            self._sensor_panel.on_sensor_data_received(robot_id, sensor_name, data)
        self._traffic_monitor.on_sensor_data_received(robot_id, sensor_name, data)

    def _on_command(self, robot_id: str, action: str, params: dict) -> None:
        if self._mqtt_client:
            self._mqtt_client.send_cmd(robot_id, {"action": action, "params": params})

    def _on_data_send(self, robot_id: str, topic: str, json_str: str) -> None:
        if self._mqtt_client:
            self._mqtt_client.publish(f"robot/{robot_id}/sensor/{topic.lstrip('/')}", json_str, qos=0)

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def _on_emergency(self) -> None:
        if QMessageBox.question(self, "确认急停", "向所有在线机器人发送急停？") != QMessageBox.Yes:
            return
        if self._mqtt_client:
            self._mqtt_client.send_emergency_stop(self._robot_list.get_online_robots() or [])

    def closeEvent(self, event) -> None:
        if self._mqtt_client:
            self._mqtt_client.disconnect()
        event.accept()
