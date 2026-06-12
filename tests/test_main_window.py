from __future__ import annotations

import os

import pytest
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QDockWidget, QLabel, QSplitter, QVBoxLayout

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


class TestMainWindowLayout:
    def test_display_tab_has_bottom_host_for_native_image_panels(self, qt_app, monkeypatch):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)

        window = MainWindow({})

        display_layout = window._display_container.layout()
        display_splitter = window._display_splitter
        display_holder = window._display_panel_holder
        image_container = window._image_panel_container

        assert isinstance(display_layout, QVBoxLayout)
        assert isinstance(display_splitter, QSplitter)
        assert display_splitter.orientation() == Qt.Vertical
        assert display_layout.indexOf(display_splitter) == 0
        assert display_splitter.indexOf(display_holder) == 0
        assert display_splitter.indexOf(image_container) == 1
        assert display_holder.layout().indexOf(window._display_placeholder) == 0
        assert display_layout.count() == 1
        assert image_container.layout() is window._image_panel_layout
        assert image_container.isVisible() is False
        assert window.findChildren(QDockWidget) == []
        assert isinstance(window._display_placeholder, QLabel)
