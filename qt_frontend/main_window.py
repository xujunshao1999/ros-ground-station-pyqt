from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sip
from PyQt5.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QAction,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from qt_frontend.mqtt_client import MqttClient
from qt_frontend.panels import (
    CommandPanel,
    DataSenderPanel,
    EventPanel,
    FleetCommPanel,
    RobotListPanel,
    SensorSummaryPanel,
    TopicConfigPanel,
    TrafficMonitor,
)
from qt_frontend.rviz_frame_policy import (
    follow_selected_robot_default,
    global_fixed_frame_for,
    normalize_frame_id,
    robot_fixed_frame_for,
)
from qt_frontend.theme import DANGER, SUCCESS

logger = logging.getLogger(__name__)


class MainWindowSignals(QObject):
    ros_checked = pyqtSignal(bool)


class MainWindow(QMainWindow):
    def __init__(self, config: dict) -> None:
        super().__init__()
        self._config = config
        self._rviz_ptr = None
        self._rviz_lib = None
        self._current_rviz_config_path: Optional[Path] = None
        self._mqtt_client: Optional[MqttClient] = None
        self._splitter_sizes = [360, 920, 320]
        self._configured_sensor_subscriptions: Dict[str, List[Dict[str, Any]]] = {}
        self._pending_sensor_data: Dict[
            Tuple[str, str],
            List[Tuple[float, object]],
        ] = {}
        self._signals = MainWindowSignals()
        self._ros_check_inflight = False
        self._current_fixed_frame = ""
        self._pending_fixed_frame: Optional[str] = None

        self._init_window()
        self._init_panels()
        self._init_menu_and_toolbar()
        self._init_central_widget()
        self._init_status_bar()
        self._signals.ros_checked.connect(self._on_ros_checked)
        self._init_sensor_batch_timer()
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
        self._robot_list.robot_selected.connect(self._on_robot_selected_for_rviz)
        self._robot_list.global_frame_requested.connect(self._switch_to_global_frame)
        self._robot_list.follow_frame_changed.connect(self._on_follow_frame_changed)
        self._robot_list.set_follow_selected_robot_enabled(
            follow_selected_robot_default(self._config)
        )
        self._robot_list.set_current_fixed_frame(global_fixed_frame_for(self._config))
        self._topic_config.config_changed.connect(
            self._refresh_robot_subscription_counts
        )
        self._refresh_robot_subscription_counts()

    def _init_menu_and_toolbar(self) -> None:
        menubar = self.menuBar()

        # --- 连接 ---
        m = menubar.addMenu("&连接")
        self._act_connect = QAction("连接 Broker", self)
        self._act_disconnect = QAction("断开连接", self)
        self._act_quit = QAction("退出", self)
        self._act_quit.triggered.connect(self.close)
        self._act_disconnect.setEnabled(False)
        m.addAction(self._act_connect)
        m.addAction(self._act_disconnect)
        m.addSeparator()
        m.addAction(self._act_quit)

        # --- 机器人 ---
        m = menubar.addMenu("&机器人")
        self._act_discover = QAction("发现机器人", self)
        self._act_emergency = QAction("全部急停", self)
        m.addAction(self._act_discover)
        m.addSeparator()
        m.addAction(self._act_emergency)

        # --- 录制 ---
        m = menubar.addMenu("&录制")
        self._act_rec_start = QAction("开始录制", self)
        self._act_rec_stop = QAction("停止录制", self)
        self._act_rec_stop.setEnabled(False)
        m.addAction(self._act_rec_start)
        m.addAction(self._act_rec_stop)

        # --- 视图 ---
        m = menubar.addMenu("&视图")
        self._act_reset_layout = QAction("重置布局", self)
        self._act_load_rviz_config = QAction("加载 RViz 配置...", self)
        self._act_save_rviz_config = QAction("保存 RViz 配置...", self)
        self._act_load_rviz_config.triggered.connect(self._load_rviz_config_from_dialog)
        self._act_save_rviz_config.triggered.connect(self._save_rviz_config_from_dialog)
        m.addAction(self._act_reset_layout)
        m.addSeparator()
        m.addAction(self._act_load_rviz_config)
        m.addAction(self._act_save_rviz_config)

        # --- 帮助 ---
        m = menubar.addMenu("&帮助")
        self._act_about = QAction("关于", self)
        m.addAction(self._act_about)

        # --- 工具栏 ---
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        self._lb_conn = QLabel("● 已断开")
        self._lb_conn.setStyleSheet("color: red; font-weight: bold;")
        toolbar.addWidget(self._lb_conn)
        toolbar.addSeparator()

        mqtt_cfg = self._config.get("mqtt", {})
        broker_host = mqtt_cfg.get("broker_host", "localhost")
        broker_port = mqtt_cfg.get("broker_port", 1883)
        toolbar.addWidget(QLabel(f"Broker: {broker_host}:{broker_port}"))
        toolbar.addSeparator()

        self._lb_online = QLabel("在线: 0")
        toolbar.addWidget(self._lb_online)
        toolbar.addSeparator()

        self._lb_fps = QLabel("FPS: --")
        toolbar.addWidget(self._lb_fps)
        toolbar.addSeparator()

        self._lb_rec = QLabel("录制: 00:00:00")
        toolbar.addWidget(self._lb_rec)
        toolbar.addSeparator()

        btn_load_rviz = QPushButton("加载 RViz")
        btn_load_rviz.clicked.connect(self._load_rviz_config_from_dialog)
        toolbar.addWidget(btn_load_rviz)

        btn_save_rviz = QPushButton("保存 RViz")
        btn_save_rviz.clicked.connect(self._save_rviz_config_from_dialog)
        toolbar.addWidget(btn_save_rviz)
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
        robot_tab = QWidget()
        robot_layout = QVBoxLayout(robot_tab)
        robot_layout.setContentsMargins(0, 0, 0, 0)
        robot_layout.addWidget(self._robot_list)
        robot_layout.addWidget(self._command)
        left.addTab(robot_tab, "机器人")

        config_tab = QWidget()
        config_layout = QVBoxLayout(config_tab)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_tabs = QTabWidget()
        config_tabs.addTab(self._topic_config, "传输")
        config_tabs.addTab(self._fleet_comm, "编队")
        config_layout.addWidget(config_tabs)
        left.addTab(config_tab, "配置")
        left.addTab(self._event_panel, "事件")

        # Right tabs
        right = QTabWidget()
        right.setMinimumWidth(280)
        self._display_container = QWidget()
        display_layout = QVBoxLayout(self._display_container)
        display_layout.setContentsMargins(0, 0, 0, 0)
        self._display_splitter = QSplitter(Qt.Vertical)
        self._display_panel_holder = QWidget()
        display_panel_layout = QVBoxLayout(self._display_panel_holder)
        display_panel_layout.setContentsMargins(0, 0, 0, 0)
        self._image_panel_container = QWidget()
        self._image_panel_layout = QVBoxLayout(self._image_panel_container)
        self._image_panel_layout.setContentsMargins(0, 0, 0, 0)
        self._image_dock_host = QMainWindow()
        self._image_dock_host.setDockOptions(
            QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks
        )
        self._image_panel_layout.addWidget(self._image_dock_host)
        self._image_panel_container.setMinimumHeight(160)
        self._image_panel_container.setMaximumHeight(280)
        self._image_panel_container.hide()
        self._display_placeholder = QLabel("RViz 初始化中...")
        display_panel_layout.addWidget(self._display_placeholder)
        self._display_splitter.addWidget(self._display_panel_holder)
        self._display_splitter.addWidget(self._image_panel_container)
        self._display_splitter.setStretchFactor(0, 1)
        self._display_splitter.setStretchFactor(1, 0)
        display_layout.addWidget(self._display_splitter)
        right.addTab(self._display_container, "Display")
        right.addTab(self._sensor_panel, "摘要")
        right.addTab(self._data_sender, "发送")
        right.addTab(self._traffic_monitor, "流量")

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

    def _init_sensor_batch_timer(self) -> None:
        self._sensor_batch_timer = QTimer(self)
        self._sensor_batch_timer.timeout.connect(self._flush_sensor_data)
        self._sensor_batch_timer.start(100)

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
        sig.sensor_meta_received.connect(self._on_sensor_meta)
        sig.discover_response_received.connect(self._on_discover)
        sig.topic_response_received.connect(self._topic_config.on_topic_response)
        sig.config_response_received.connect(self._on_config_response)
        sig.discover_response_received.connect(self._topic_config.on_discover_response)
        sig.discover_response_received.connect(self._fleet_comm.on_discover_response)

        self._act_connect.triggered.connect(self._mqtt_client.connect)
        self._act_disconnect.triggered.connect(self._mqtt_client.disconnect)
        self._act_discover.triggered.connect(self._mqtt_client.send_discover)
        self._robot_list.discover_requested.connect(self._mqtt_client.send_discover)
        self._topic_config.discover_requested.connect(self._mqtt_client.send_discover)
        self._fleet_comm.discover_requested.connect(self._mqtt_client.send_discover)
        self._command.command_sent.connect(self._on_command)
        self._data_sender.send_json.connect(self._on_data_send)
        self._topic_config.topic_request_requested.connect(
            self._mqtt_client.send_topic_request
        )
        self._topic_config.config_sync_requested.connect(
            self._mqtt_client.send_config_sync
        )
        self._topic_config.config_query_requested.connect(
            self._mqtt_client.send_config_query
        )
        self._fleet_comm.config_sync_requested.connect(
            self._mqtt_client.send_config_sync
        )
        self._fleet_comm.config_query_requested.connect(
            self._mqtt_client.send_config_query
        )

    def _init_ros_monitor(self) -> None:
        self._ros_timer = QTimer(self)
        self._ros_timer.timeout.connect(self._check_ros)
        self._ros_timer.start(5000)
        self._check_ros()

    def _check_ros(self) -> None:
        if self._ros_check_inflight:
            return
        self._ros_check_inflight = True
        thread = threading.Thread(target=self._check_ros_worker, daemon=True)
        thread.start()

    def _check_ros_worker(self) -> None:
        try:
            ros_cfg = self._config.get("ros", {})
            r = subprocess.run(
                ["rostopic", "list"],
                capture_output=True,
                text=True,
                timeout=1,
                env={
                    **os.environ,
                    "ROS_MASTER_URI": ros_cfg.get(
                        "master_uri",
                        "http://localhost:11311",
                    ),
                },
            )
            ok = r.returncode == 0
        except Exception:
            ok = False
        self._signals.ros_checked.emit(ok)

    def _on_ros_checked(self, ok: bool) -> None:
        self._ros_check_inflight = False
        self._lb_ros.setText("ROS Master ✓" if ok else "ROS Master ✗")
        self._lb_ros.setStyleSheet(
            f"color: {SUCCESS if ok else DANGER}; font-weight: bold;"
        )

    def _on_robot_selected_for_rviz(self, robot_id: str) -> None:
        if not self._robot_list.follow_selected_robot_enabled():
            return
        frame = robot_fixed_frame_for(robot_id, self._config)
        self._set_rviz_fixed_frame(frame, "机器人视角")

    def _on_follow_frame_changed(self, enabled: bool) -> None:
        if not enabled:
            return
        robot_id = self._robot_list.selected_robot()
        if robot_id:
            self._on_robot_selected_for_rviz(robot_id)

    def _switch_to_global_frame(self) -> None:
        self._set_rviz_fixed_frame(global_fixed_frame_for(self._config), "全局视角")

    def _rviz_frame_is_resolvable(self, frame: str) -> bool:
        if not self._rviz_lib or not self._rviz_ptr:
            return False
        checker = getattr(self._rviz_lib, "can_resolve_frame", None)
        if checker is None:
            return True
        return bool(checker(self._rviz_ptr, frame.encode("utf-8")))

    def _set_rviz_fixed_frame(self, frame: str, source: str) -> bool:
        clean_frame = normalize_frame_id(frame)
        if not clean_frame:
            self.statusBar().showMessage("RViz 视角切换失败：frame 为空", 4000)
            return False

        # RViz 初始化前记录用户意图，初始化完成后再补一次 set_fixed_frame。
        self._robot_list.set_current_fixed_frame(clean_frame)
        if not self._rviz_lib or not self._rviz_ptr:
            self._pending_fixed_frame = clean_frame
            self.statusBar().showMessage(
                "RViz 未就绪，已记录%s：%s" % (source, clean_frame),
                4000,
            )
            return False

        resolvable = self._rviz_frame_is_resolvable(clean_frame)
        self._rviz_lib.set_fixed_frame(self._rviz_ptr, clean_frame.encode("utf-8"))
        self._current_fixed_frame = clean_frame
        self._pending_fixed_frame = None

        if resolvable:
            self.statusBar().showMessage(
                "已切换 RViz %s：%s" % (source, clean_frame),
                3000,
            )
        else:
            self.statusBar().showMessage(
                "已切换 RViz %s：%s，TF 暂不可解析" % (source, clean_frame),
                5000,
            )
        return True

    # ------------------------------------------------------------------
    # RViz
    # ------------------------------------------------------------------

    def _init_rviz(self) -> None:
        lib_path = str(
            Path(__file__).resolve().parent / "native" / "build" / "librviz_widget.so"
        )
        try:
            lib = ctypes.CDLL(lib_path)
            lib.create_rviz_widget.argtypes = [ctypes.c_void_p]
            lib.create_rviz_widget.restype = ctypes.c_void_p
            lib.load_config.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            lib.load_config.restype = ctypes.c_int
            lib.save_config.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            lib.save_config.restype = ctypes.c_int
            lib.has_config_changes.argtypes = [ctypes.c_void_p]
            lib.has_config_changes.restype = ctypes.c_int
            lib.set_fixed_frame.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
            lib.set_fixed_frame.restype = None
            try:
                lib.can_resolve_frame.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
                lib.can_resolve_frame.restype = ctypes.c_int
            except AttributeError:
                logger.warning(
                    "librviz_widget.so does not expose can_resolve_frame; "
                    "RViz frame resolution checks are disabled"
                )
            lib.get_display_panel.argtypes = [ctypes.c_void_p]
            lib.get_display_panel.restype = ctypes.c_void_p
            lib.set_dock_layout.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            lib.set_dock_layout.restype = None
            lib.set_dock_host.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            lib.set_dock_host.restype = None
            self._rviz_lib = lib
        except OSError as e:
            logger.error(f"Failed to load librviz_widget.so: {e}")
            return

        rviz_ptr = lib.create_rviz_widget(None)
        if not rviz_ptr:
            return
        self._rviz_ptr = rviz_ptr

        rviz_widget = sip.wrapinstance(int(rviz_ptr), QWidget)
        rviz_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        old = self._splitter.replaceWidget(1, rviz_widget)
        if old:
            old.deleteLater()
        self._splitter.setStretchFactor(1, 1)
        self._apply_splitter_layout()

        config_path = Path(__file__).resolve().parent / "config" / "default.rviz"
        load_result = lib.load_config(rviz_ptr, str(config_path).encode("utf-8"))
        if load_result != 0:
            logger.warning(
                "Failed to load RViz config %s, using built-in defaults (code %s)",
                config_path,
                load_result,
            )
            lib.set_fixed_frame(rviz_ptr, b"map")
        else:
            self._current_rviz_config_path = config_path

        # Display tab
        disp_ptr = lib.get_display_panel(rviz_ptr)
        if disp_ptr:
            disp_widget = sip.wrapinstance(int(disp_ptr), QWidget)
            display_panel_layout = self._display_panel_holder.layout()
            while display_panel_layout.count():
                item = display_panel_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            display_panel_layout.addWidget(disp_widget)

        # Native RViz Image/Camera panels created by Display checkboxes.
        image_dock_host_ptr = sip.unwrapinstance(self._image_dock_host)
        if image_dock_host_ptr:
            lib.set_dock_host(rviz_ptr, ctypes.c_void_p(image_dock_host_ptr))

        requested_frame = (
            self._pending_fixed_frame or global_fixed_frame_for(self._config)
        )
        self._set_rviz_fixed_frame(requested_frame, "初始视角")

    def _default_rviz_config_path(self) -> Path:
        return Path(__file__).resolve().parent / "config" / "default.rviz"

    def _load_rviz_config(self, path: Path) -> bool:
        if not self._rviz_lib or not self._rviz_ptr:
            QMessageBox.warning(self, "RViz 未就绪", "RViz 还没有初始化完成。")
            return False

        result = self._rviz_lib.load_config(
            self._rviz_ptr,
            str(path).encode("utf-8"),
        )
        if result != 0:
            QMessageBox.warning(
                self,
                "加载失败",
                f"无法加载 RViz 配置：{path}\n错误码：{result}",
            )
            return False

        self.statusBar().showMessage(f"已加载 RViz 配置：{path}", 5000)
        self._current_rviz_config_path = path
        return True

    def _save_rviz_config(self, path: Path) -> bool:
        if not self._rviz_lib or not self._rviz_ptr:
            QMessageBox.warning(self, "RViz 未就绪", "RViz 还没有初始化完成。")
            return False

        result = self._rviz_lib.save_config(
            self._rviz_ptr,
            str(path).encode("utf-8"),
        )
        if result != 0:
            QMessageBox.warning(
                self,
                "保存失败",
                f"无法保存 RViz 配置：{path}\n错误码：{result}",
            )
            return False

        self.statusBar().showMessage(f"已保存 RViz 配置：{path}", 5000)
        self._current_rviz_config_path = path
        return True

    def _rviz_config_has_changes(self) -> bool:
        if not self._rviz_lib or not self._rviz_ptr:
            return False
        return bool(self._rviz_lib.has_config_changes(self._rviz_ptr))

    def _load_rviz_config_from_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "加载 RViz 配置",
            str(self._default_rviz_config_path()),
            "RViz 配置 (*.rviz);;YAML 文件 (*.yaml *.yml);;所有文件 (*)",
        )
        if path:
            self._load_rviz_config(Path(path))

    def _save_rviz_config_from_dialog(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存 RViz 配置",
            str(self._default_rviz_config_path()),
            "RViz 配置 (*.rviz);;YAML 文件 (*.yaml *.yml);;所有文件 (*)",
        )
        if path:
            return self._save_rviz_config(Path(path))
        return False

    # ------------------------------------------------------------------
    # MQTT callbacks
    # ------------------------------------------------------------------

    def _on_robot_status(self, robot_id: str, data: dict) -> None:
        self._robot_list.on_status_received(robot_id, data)
        robots = self._robot_list.get_online_robots()
        self._command.on_robot_list_changed(robots)
        self._topic_config.on_robot_list_changed(robots)
        self._fleet_comm.on_robot_list_changed(robots)
        self._data_sender.on_robot_list_changed(robots)
        self._sensor_panel.retain_robots(robots)
        self._sync_sensor_panel_subscriptions([robot_id])
        self._lb_online.setText(f"在线: {len(robots)}")

    def _on_discover(self, robot_id: str, data: dict) -> None:
        self._robot_list.on_discover_response(robot_id, data)
        robots = self._robot_list.get_online_robots()
        self._command.on_robot_list_changed(robots)
        self._topic_config.on_robot_list_changed(robots)
        self._fleet_comm.on_robot_list_changed(robots)
        self._data_sender.on_robot_list_changed(robots)
        self._sensor_panel.retain_robots(robots)
        self._sync_sensor_panel_subscriptions([robot_id])
        self._lb_online.setText(f"在线: {len(robots)}")

    def _on_config_response(self, robot_id: str, data: dict) -> None:
        self._topic_config.on_config_response(robot_id, data)
        self._fleet_comm.on_config_response(robot_id, data)
        subscriptions = data.get("subscriptions", [])
        if isinstance(subscriptions, list):
            self._robot_list.update_subscription_count(robot_id, len(subscriptions))
            self._configured_sensor_subscriptions[robot_id] = subscriptions
            self._sensor_panel.on_subscriptions_changed(robot_id, subscriptions)
            self._traffic_monitor.on_subscriptions_changed(robot_id, subscriptions)

    def _refresh_robot_subscription_counts(self) -> None:
        try:
            config = TopicConfigPanel.load_transmit_config_file(
                Path(__file__).resolve().parent / "config" / "transmit_config.yaml"
            )
        except Exception as e:
            logger.warning("Failed to load subscription counts: %s", e)
            return
        counts = RobotListPanel.subscription_counts_from_transmit_config(config)
        self._robot_list.update_subscription_counts(counts)
        self._configured_sensor_subscriptions = (
            TopicConfigPanel.normalize_transmit_subscriptions(
                config.get("subscriptions") or {}
            )
        )
        self._sync_sensor_panel_subscriptions(self._robot_list.get_online_robots())

    @staticmethod
    def sensor_summary_subscriptions_for_online_robots(
        config: Dict[str, Any],
        online_robots: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        subscriptions = TopicConfigPanel.normalize_transmit_subscriptions(
            config.get("subscriptions") or {}
        )
        online_robot_set = set(online_robots)
        return {
            robot_id: entries
            for robot_id, entries in subscriptions.items()
            if robot_id in online_robot_set
        }

    def _sync_sensor_panel_subscriptions(self, robot_ids: List[str]) -> None:
        for robot_id in robot_ids:
            entries = self._configured_sensor_subscriptions.get(robot_id)
            if entries is not None:
                self._sensor_panel.on_subscriptions_changed(robot_id, entries)
                self._traffic_monitor.on_subscriptions_changed(robot_id, entries)

    def _on_mqtt_connected(self) -> None:
        self._lb_conn.setText("● 已连接")
        self._lb_conn.setStyleSheet(f"color: {SUCCESS}; font-weight: bold;")
        self._act_connect.setEnabled(False)
        self._act_disconnect.setEnabled(True)

    def _on_mqtt_disconnected(self) -> None:
        self._lb_conn.setText("● 已断开")
        self._lb_conn.setStyleSheet(f"color: {DANGER}; font-weight: bold;")
        self._act_connect.setEnabled(True)
        self._act_disconnect.setEnabled(False)

    def _on_sensor_data(self, robot_id: str, sensor_name: str, data: object) -> None:
        key = (robot_id, sensor_name)
        self._pending_sensor_data.setdefault(key, []).append((time.monotonic(), data))

    def _on_sensor_meta(self, robot_id: str, sensor_name: str, data: object) -> None:
        if isinstance(data, dict):
            # meta 不是完整 ROS 消息，但健康面板需要它展示 HTTP stream 状态。
            self._sensor_panel.on_sensor_data_received(
                robot_id,
                sensor_name,
                data,
            )
        self._traffic_monitor.on_sensor_data_received(
            robot_id,
            sensor_name,
            data,
            now=time.monotonic(),
        )

    def _flush_sensor_data(self) -> None:
        if not self._pending_sensor_data:
            return

        pending = self._pending_sensor_data
        self._pending_sensor_data = {}
        for (robot_id, sensor_name), samples in pending.items():
            for sample_time, data in samples:
                if isinstance(data, dict):
                    self._sensor_panel.on_sensor_data_received(
                        robot_id,
                        sensor_name,
                        data,
                    )
                self._traffic_monitor.on_sensor_data_received(
                    robot_id,
                    sensor_name,
                    data,
                    now=sample_time,
                )

    def _on_command(self, robot_id: str, action: str, params: dict) -> None:
        if self._mqtt_client:
            self._mqtt_client.send_cmd(robot_id, {"action": action, "params": params})

    def _on_data_send(self, robot_id: str, topic: str, json_str: str) -> None:
        if self._mqtt_client:
            self._mqtt_client.publish(
                f"robot/{robot_id}/sensor/{topic.lstrip('/')}",
                json_str,
                qos=0,
            )

    # ------------------------------------------------------------------
    # 事件
    # ------------------------------------------------------------------

    def _on_emergency(self) -> None:
        if (
            QMessageBox.question(self, "确认急停", "向所有在线机器人发送急停？")
            != QMessageBox.Yes
        ):
            return
        if self._mqtt_client:
            self._mqtt_client.send_emergency_stop(
                self._robot_list.get_online_robots() or []
            )

    def closeEvent(self, event) -> None:
        if self._rviz_config_has_changes():
            config_path = self._current_rviz_config_path
            path_text = str(config_path) if config_path else "尚未关联到文件"
            choice = QMessageBox.question(
                self,
                "保存 RViz 配置",
                "RViz Display 配置已发生变化，关闭前是否保存？\n\n"
                f"当前 RViz 配置文件：{path_text}",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if choice == QMessageBox.Cancel:
                event.ignore()
                return
            if choice == QMessageBox.Save:
                saved = (
                    self._save_rviz_config(config_path)
                    if config_path
                    else self._save_rviz_config_from_dialog()
                )
                if not saved:
                    event.ignore()
                    return

        if self._mqtt_client:
            self._mqtt_client.disconnect()
        event.accept()
