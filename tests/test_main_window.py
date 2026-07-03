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

    def test_sensor_meta_updates_traffic_without_sensor_summary(self, qt_app, monkeypatch):
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

        assert sensor_calls == []
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
