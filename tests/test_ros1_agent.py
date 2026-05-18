from __future__ import annotations

from unittest.mock import MagicMock

from agent.ros1_agent import ROS1Agent


def test_get_available_topics_uses_rospy_published_topics(monkeypatch):
    mock_rospy = MagicMock()
    mock_rospy.is_shutdown.return_value = False
    mock_rospy.get_published_topics.return_value = [
        ("/scan", "sensor_msgs/LaserScan"),
        ("/map", "nav_msgs/OccupancyGrid"),
        ("/tf", "tf2_msgs/TFMessage"),
    ]
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)

    topics = ROS1Agent._get_available_topics(object())

    assert topics == [
        {
            "topic": "/scan",
            "msg_type": "sensor_msgs/LaserScan",
            "description": "ROS topic (sensor_msgs/LaserScan)",
        },
        {
            "topic": "/map",
            "msg_type": "nav_msgs/OccupancyGrid",
            "description": "ROS topic (nav_msgs/OccupancyGrid)",
        },
        {
            "topic": "/tf",
            "msg_type": "tf2_msgs/TFMessage",
            "description": "ROS topic (tf2_msgs/TFMessage)",
        },
    ]
