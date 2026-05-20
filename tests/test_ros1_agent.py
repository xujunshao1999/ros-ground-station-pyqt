from __future__ import annotations

from unittest.mock import MagicMock

from agent.ros1_agent import ROS1Agent
from protocol.messages import FleetData


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


def test_apply_fleet_rules_subscribes_enabled_ros_topics(monkeypatch):
    mock_rospy = MagicMock()
    mock_sub = MagicMock()
    mock_rospy.Subscriber.return_value = mock_sub
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.robot_id = "turtlebot_001"
    agent._fleet_subscribers = {}
    agent._get_ros_msg_class = MagicMock(return_value=object)

    ROS1Agent._apply_fleet_rules(agent, [
        {
            "enabled": True,
            "src_topic": "/odom",
            "msg_type": "nav_msgs/Odometry",
            "targets": [
                {
                    "robot_id": "turtlebot_002",
                    "dst_topic": "/fleet/turtlebot_001/odom",
                }
            ],
            "freq_limit": 10.0,
            "transport": "mqtt_json",
            "frame_policy": "namespace",
        }
    ])

    mock_rospy.Subscriber.assert_called_once()
    assert mock_rospy.Subscriber.call_args[0][0] == "/odom"
    assert mock_rospy.Subscriber.call_args[0][1] is object
    assert agent._fleet_subscribers["/odom"] is mock_sub


def test_fleet_rule_callback_sends_fleet_data(monkeypatch):
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: {"header": {"frame_id": "odom"}},
    )

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.robot_id = "turtlebot_001"
    sent = []
    agent.send_to_robot = lambda target_id, data: sent.append((target_id, data))

    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        src_topic="/odom",
        msg_type="nav_msgs/Odometry",
        targets=[
            {
                "robot_id": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
            }
        ],
        frame_policy="namespace",
        freq_limit=0.0,
    )

    callback(object())

    assert sent[0][0] == "turtlebot_002"
    assert isinstance(sent[0][1], FleetData)
    assert sent[0][1].data_type == "ros_topic"
    assert sent[0][1].src_topic == "/odom"
    assert sent[0][1].dst_topic == "/fleet/turtlebot_001/odom"
    assert sent[0][1].msg_type == "nav_msgs/Odometry"
    assert sent[0][1].frame_policy == "namespace"
    assert sent[0][1].payload == {"header": {"frame_id": "odom"}}


def test_fleet_rule_callback_respects_freq_limit(monkeypatch):
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: {"header": {"frame_id": "odom"}},
    )
    times = iter([100.0, 100.05, 100.11])
    monkeypatch.setattr("agent.ros1_agent.time.time", lambda: next(times))

    agent = object.__new__(ROS1Agent)
    sent = []
    agent.send_to_robot = lambda target_id, data: sent.append((target_id, data))

    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        src_topic="/odom",
        msg_type="nav_msgs/Odometry",
        targets=[
            {
                "robot_id": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
            }
        ],
        frame_policy="preserve",
        freq_limit=10.0,
    )

    callback(object())
    callback(object())
    callback(object())

    assert len(sent) == 2
