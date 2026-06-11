from __future__ import annotations

from qt_frontend.main_window import MainWindow


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
