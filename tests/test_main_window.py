from __future__ import annotations

import os

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


class TestMainWindowRosMonitor:
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
