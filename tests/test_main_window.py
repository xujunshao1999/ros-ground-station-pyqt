from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QDockWidget,
    QLabel,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
)

from qt_frontend.main_window import MainWindow

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def command_window(qt_app, monkeypatch):
    monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
    monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)
    return MainWindow({})


class TestMainWindowCommandIntegration:
    def test_mqtt_connect_is_scheduled_after_window_initialization(
        self,
        qt_app,
        monkeypatch,
    ):
        scheduled = []
        monkeypatch.setattr(
            QTimer,
            "singleShot",
            lambda delay, callback: scheduled.append((delay, callback)),
        )
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)

        window = MainWindow({})

        assert any(
            delay == 0 and callback == window._connect_mqtt
            for delay, callback in scheduled
        )

    def test_connecting_and_connection_error_update_broker_status(
        self,
        command_window,
    ):
        window = command_window
        window._mqtt_client.connect = MagicMock()

        window._connect_mqtt()

        assert window._lb_conn.text() == "● 连接中"
        assert not window._act_connect.isEnabled()
        window._mqtt_client.connect.assert_called_once_with()

        window._mqtt_client.signals.connection_error.emit("Connection refused")

        assert window._lb_conn.text() == "● 连接失败"
        assert window._act_connect.isEnabled()
        assert not window._act_disconnect.isEnabled()
        assert "Connection refused" in window.statusBar().currentMessage()

    def test_command_and_topic_config_share_discover_catalog(self, command_window):
        window = command_window

        assert window._command._topic_catalog is window._topic_catalog
        assert window._topic_config._topic_catalog is window._topic_catalog

        topics = {
            "topics": [
                {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
            ]
        }
        window._on_discover("r1", topics)

        assert window._command._topic_catalog.topics_for("r1") == topics["topics"]
        assert window._topic_config._topic_catalog.topics_for("r1") == topics["topics"]

    def test_online_robot_changes_are_distributed_to_all_consumers(
        self,
        command_window,
    ):
        window = command_window
        window._command.on_robot_list_changed = MagicMock()
        window._topic_config.on_robot_list_changed = MagicMock()
        window._fleet_comm.on_robot_list_changed = MagicMock()
        window._data_sender.on_robot_list_changed = MagicMock()
        window._sensor_panel.retain_robots = MagicMock()

        window._robot_list.on_status_received("r2", {"battery": 90.0})

        for panel_method in (
            window._command.on_robot_list_changed,
            window._topic_config.on_robot_list_changed,
            window._fleet_comm.on_robot_list_changed,
            window._data_sender.on_robot_list_changed,
            window._sensor_panel.retain_robots,
        ):
            panel_method.assert_called_once_with(["r2"])
        assert window._lb_online.text() == "在线: 1"

    def test_custom_batch_begins_before_sending_to_sorted_online_robots(
        self,
        command_window,
    ):
        window = command_window
        window._robot_list.on_status_received("r2", {"battery": 90.0})
        window._robot_list.on_status_received("r1", {"battery": 80.0})
        events = []
        sent = []

        def send_cmd(robot_id, data):
            events.append(("send", robot_id))
            sent.append((robot_id, data))
            data["params"]["data"]["enabled"] = False

        window._mqtt_client = SimpleNamespace(
            is_connected=True,
            send_cmd=send_cmd,
        )
        window._command.begin_command_batch = (
            lambda exec_id, robot_ids: events.append(
                ("begin", exec_id, list(robot_ids))
            )
        )
        params = {
            "topic": "/exploration/control",
            "msg_type": "my_pkg/Control",
            "data": {"enabled": True},
        }

        window._on_batch_command("exec-1", params)

        assert events == [
            ("begin", "exec-1", ["r1", "r2"]),
            ("send", "r1"),
            ("send", "r2"),
        ]
        assert [robot_id for robot_id, _ in sent] == ["r1", "r2"]
        assert {item["exec_id"] for _, item in sent} == {"exec-1"}
        assert all(item["action"] == "custom" for _, item in sent)
        assert sent[0][1]["params"] is not sent[1][1]["params"]
        assert params["data"]["enabled"] is True

    @pytest.mark.parametrize(
        ("is_connected", "online_robot"),
        [(False, "r1"), (True, "")],
    )
    def test_custom_batch_rejects_without_connection_or_online_robot(
        self,
        command_window,
        is_connected,
        online_robot,
    ):
        window = command_window
        if online_robot:
            window._robot_list.on_status_received(online_robot, {"battery": 90.0})
        send_cmd = MagicMock()
        window._mqtt_client = SimpleNamespace(
            is_connected=is_connected,
            send_cmd=send_cmd,
        )
        window._command.reject_command_batch = MagicMock()
        window._command.begin_command_batch = MagicMock()

        window._on_batch_command("exec-rejected", {"topic": "/control"})

        window._command.reject_command_batch.assert_called_once()
        assert window._command.reject_command_batch.call_args.args[0] == "exec-rejected"
        window._command.begin_command_batch.assert_not_called()
        send_cmd.assert_not_called()

    def test_command_schema_and_discover_signals_are_wired_to_mqtt(
        self,
        command_window,
    ):
        window = command_window
        published = []
        window._mqtt_client.publish = lambda *args, **kwargs: published.append(
            (args, kwargs)
        )

        window._command.discover_requested.emit()
        window._command.schema_query_requested.emit(
            "r1",
            "req-1",
            "geometry_msgs/Twist",
        )

        assert published[0][0][0] == "station/discover"
        assert published[1][0][0] == "station/r1/message_schema/query"

        dialog = SimpleNamespace(on_schema_response=MagicMock())
        window._command._settings_dialog = dialog
        data = {"request_id": "req-1", "result": "ok"}
        window._mqtt_client.signals.schema_response_received.emit("r1", data)
        dialog.on_schema_response.assert_called_once_with("r1", data)


class TestMainWindowSubscriptions:
    def test_sensor_summary_subscriptions_only_include_online_robots(self):
        config = {
            "subscriptions": {
                "turtlebot_001": [
                    {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
                ],
                "turtlebot_002": [
                    {"topic": "/odom", "msg_type": "nav_msgs/Odometry"},
                ],
            }
        }

        assert MainWindow.sensor_summary_subscriptions_for_online_robots(
            config,
            ["turtlebot_001"],
        ) == {
            "turtlebot_001": [
                {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
            ],
        }


class TestMainWindowSensorBatching:
    def test_sensor_data_is_batched_before_panel_updates(self, qt_app, monkeypatch):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)

        window = MainWindow({})
        sensor_calls = []
        traffic_calls = []

        class SensorPanel:
            def on_sensor_data_received(self, robot_id, sensor_name, data):
                sensor_calls.append((robot_id, sensor_name, data))

        class TrafficMonitor:
            def on_sensor_data_received(self, robot_id, sensor_name, data, now=None):
                traffic_calls.append((robot_id, sensor_name, data, now))

        window._sensor_panel = SensorPanel()
        window._traffic_monitor = TrafficMonitor()

        window._on_sensor_data("r1", "scan", {"ranges": [1.0]})
        window._on_sensor_data("r1", "scan", {"ranges": [2.0]})

        assert sensor_calls == []
        assert traffic_calls == []

        window._flush_sensor_data()

        assert sensor_calls == [
            ("r1", "scan", {"ranges": [1.0]}),
            ("r1", "scan", {"ranges": [2.0]}),
        ]
        assert [call[:3] for call in traffic_calls] == sensor_calls
        assert all(call[3] is not None for call in traffic_calls)

    def test_sensor_meta_updates_sensor_summary_and_traffic(self, qt_app, monkeypatch):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)

        window = MainWindow({})
        sensor_calls = []
        traffic_calls = []

        class SensorPanel:
            def on_sensor_data_received(self, robot_id, sensor_name, data):
                sensor_calls.append((robot_id, sensor_name, data))

        class TrafficMonitor:
            def on_sensor_data_received(self, robot_id, sensor_name, data, now=None):
                traffic_calls.append((robot_id, sensor_name, data, now))

        window._sensor_panel = SensorPanel()
        window._traffic_monitor = TrafficMonitor()

        meta = {
            "topic": "/velodyne_points",
            "transport": "http_stream",
            "payload_size": 512374,
        }
        window._on_sensor_meta("husky_001", "velodyne_points", meta)

        assert sensor_calls == [("husky_001", "velodyne_points", meta)]
        assert len(traffic_calls) == 1
        assert traffic_calls[0][:3] == ("husky_001", "velodyne_points", meta)
        assert traffic_calls[0][3] is not None

    def test_traffic_only_sensor_data_skips_sensor_summary(self, qt_app, monkeypatch):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)

        window = MainWindow({})
        sensor_calls = []
        traffic_calls = []

        class SensorPanel:
            def on_sensor_data_received(self, robot_id, sensor_name, data):
                sensor_calls.append((robot_id, sensor_name, data))

        class TrafficMonitor:
            def on_sensor_data_received(self, robot_id, sensor_name, data, now=None):
                traffic_calls.append((robot_id, sensor_name, data, now))

        window._sensor_panel = SensorPanel()
        window._traffic_monitor = TrafficMonitor()

        data = {
            "_msg_type": "tf2_msgs/TFMessage",
            "_payload_skipped": True,
            "_payload_bytes": 256,
            "_traffic_only": True,
        }
        window._on_sensor_data("husky_001", "tf", data)
        window._flush_sensor_data()

        assert sensor_calls == []
        assert len(traffic_calls) == 1
        assert traffic_calls[0][:3] == ("husky_001", "tf", data)
        assert traffic_calls[0][3] is not None


class TestMainWindowRosMonitor:
    def test_status_bar_uses_live_diagnostics(self, command_window):
        window = command_window
        window._mqtt_client.traffic_totals = MagicMock(
            return_value=(1536, 512)
        )

        window._refresh_mqtt_traffic()

        labels = [label.text() for label in window.statusBar().findChildren(QLabel)]
        assert "话题: --" not in labels
        assert window._lb_traffic.text() == "MQTT: Rx 1.5 KiB / Tx 512 B"
        assert window._lb_rec_status.text() == "录制: 未启用"
        assert window._lb_rviz.text() == "RViz: 初始化中"

    def test_ros_check_runs_in_background(self, qt_app, monkeypatch):
        original_check_ros = MainWindow._check_ros
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)

        started = []

        class FakeThread:
            def __init__(self, target, daemon):
                self.target = target
                self.daemon = daemon

            def start(self):
                started.append(self)

        monkeypatch.setattr("qt_frontend.main_window.threading.Thread", FakeThread)

        window = MainWindow({})
        original_check_ros(window)

        assert window._ros_check_inflight is True
        assert len(started) == 1
        assert started[0].daemon is True
        assert window._lb_ros.text() == "ROS Master: 检测中..."

        window._on_ros_checked(True)

        assert window._ros_check_inflight is False
        assert window._lb_ros.text() == "ROS Master ✓"


class TestMainWindowLayout:
    def test_display_tab_has_dock_host_for_native_image_panels(self, qt_app, monkeypatch):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)

        window = MainWindow({})

        display_layout = window._display_container.layout()
        display_splitter = window._display_splitter
        display_holder = window._display_panel_holder
        image_container = window._image_panel_container
        image_dock_host = window._image_dock_host

        assert isinstance(display_layout, QVBoxLayout)
        assert isinstance(display_splitter, QSplitter)
        assert display_splitter.orientation() == Qt.Vertical
        assert display_layout.indexOf(display_splitter) == 0
        assert display_splitter.indexOf(display_holder) == 0
        assert display_splitter.indexOf(image_container) == 1
        assert display_holder.layout().indexOf(window._display_placeholder) == 0
        assert display_layout.count() == 1
        assert image_container.layout().indexOf(image_dock_host) == 0
        assert isinstance(image_dock_host, QMainWindow)
        assert image_dock_host.dockOptions() & QMainWindow.AllowTabbedDocks
        assert image_container.isVisible() is False
        assert window.findChildren(QDockWidget) == []
        assert isinstance(window._display_placeholder, QLabel)


class TestMainWindowRvizFrameSwitch:
    def _window_with_fake_rviz(self, qt_app, monkeypatch, config=None):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)
        window = MainWindow(config or {})

        class FakeRvizLib:
            def __init__(self):
                self.frames = []
                self.resolvable = True

            def can_resolve_frame(self, ptr, frame):
                return 1 if self.resolvable else 0

            def set_fixed_frame(self, ptr, frame):
                self.frames.append(frame.decode("utf-8"))

        fake = FakeRvizLib()
        window._rviz_lib = fake
        window._rviz_ptr = 123
        return window, fake

    def test_robot_selection_switches_rviz_frame_when_follow_enabled(
        self,
        qt_app,
        monkeypatch,
    ):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)

        window._on_robot_selected_for_rviz("husky_001")

        assert fake.frames == ["husky_001/base_link"]
        assert window._current_fixed_frame == "husky_001/base_link"
        assert window._robot_list._lb_current_frame.text() == (
            "当前视角: husky_001/base_link"
        )

    def test_robot_selection_does_not_switch_when_follow_disabled(
        self,
        qt_app,
        monkeypatch,
    ):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)
        window._robot_list.set_follow_selected_robot_enabled(False)

        window._on_robot_selected_for_rviz("husky_001")

        assert fake.frames == []

    def test_switch_to_global_frame_sets_global_map(self, qt_app, monkeypatch):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)

        window._switch_to_global_frame()

        assert fake.frames == ["global_map"]
        assert window._current_fixed_frame == "global_map"

    def test_robot_list_frame_signals_are_connected(self, qt_app, monkeypatch):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)
        window._robot_list.on_status_received("husky_001", {"battery": 90.0})
        item = window._robot_list._tree.topLevelItem(0)
        item.setSelected(True)
        fake.frames = []

        window._robot_list.global_frame_requested.emit()
        window._robot_list.robot_selected.emit("husky_001")
        window._robot_list.set_follow_selected_robot_enabled(False)
        window._robot_list.set_follow_selected_robot_enabled(True)

        assert fake.frames == [
            "global_map",
            "husky_001/base_link",
            "husky_001/base_link",
        ]

    def test_rviz_init_applies_pending_fixed_frame_after_dock_host_setup(self):
        import inspect

        source = inspect.getsource(MainWindow._init_rviz)
        apply_call = 'self._set_rviz_fixed_frame(requested_frame, "初始视角")'
        dock_host_call = (
            "lib.set_dock_host(rviz_ptr, ctypes.c_void_p(image_dock_host_ptr))"
        )

        assert "requested_frame = (" in source
        assert (
            "self._pending_fixed_frame or global_fixed_frame_for(self._config)"
            in source
        )
        assert dock_host_call in source
        assert apply_call in source
        assert source.index(dock_host_call) < source.index(apply_call)

    def test_missing_resolve_checker_still_switches_frame(self, qt_app, monkeypatch):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)
        window = MainWindow({})

        class FakeRvizLibWithoutChecker:
            def __init__(self):
                self.frames = []

            def set_fixed_frame(self, ptr, frame):
                self.frames.append(frame.decode("utf-8"))

        fake = FakeRvizLibWithoutChecker()
        window._rviz_lib = fake
        window._rviz_ptr = 123

        ok = window._set_rviz_fixed_frame("global_map", "全局视角")

        assert ok is True
        assert fake.frames == ["global_map"]
        assert window._current_fixed_frame == "global_map"

    def test_missing_rviz_defers_requested_frame(self, qt_app, monkeypatch):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)
        window = MainWindow({})

        ok = window._set_rviz_fixed_frame("global_map", "全局视角")

        assert ok is False
        assert window._pending_fixed_frame == "global_map"
        assert window._robot_list._lb_current_frame.text() == "当前视角: global_map"

    def test_unresolved_frame_still_switches_and_reports_status(
        self,
        qt_app,
        monkeypatch,
    ):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)
        fake.resolvable = False
        messages = []
        monkeypatch.setattr(
            window.statusBar(),
            "showMessage",
            lambda text, timeout=0: messages.append(text),
        )

        ok = window._set_rviz_fixed_frame("husky_001/base_link", "机器人视角")

        assert ok is True
        assert fake.frames == ["husky_001/base_link"]
        assert any("TF 暂不可解析" in text for text in messages)
