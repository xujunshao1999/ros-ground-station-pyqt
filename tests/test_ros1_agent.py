from __future__ import annotations

from unittest.mock import MagicMock

from agent.ros1_agent import ROS1Agent
from protocol.messages import FleetData


class _SerializableRosMsg:
    def __init__(self, payload: bytes):
        self.payload = payload

    def serialize(self, buff):
        buff.write(self.payload)


def test_ros1_agent_uses_agent_local_dict_to_ros_msg():
    import agent.ros1_agent as ros1_agent

    assert ros1_agent.dict_to_ros_msg.__module__ == "agent.dict_to_ros_msg"


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


def test_on_topic_subscribed_replays_tf_static_latched_message(monkeypatch):
    mock_rospy = MagicMock()
    mock_msg = object()
    mock_rospy.Subscriber.return_value = MagicMock()
    mock_rospy.wait_for_message.return_value = mock_msg
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: {"transforms": [{"child_frame_id": "base_scan"}]},
    )

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.default_freq_limit = 10.0
    agent._ros_subscribers = {}
    agent._sensor_data = {}
    agent._sensor_lock = MagicMock()
    agent._get_ros_msg_class = MagicMock(return_value=object)
    agent.publish_sensor_data = MagicMock()

    ROS1Agent._on_topic_subscribed(
        agent,
        "/tf_static",
        "tf2_msgs/TFMessage",
        {"freq_limit": 10.0},
    )

    mock_rospy.wait_for_message.assert_called_once_with(
        "/tf_static",
        object,
        timeout=2.0,
    )
    agent.publish_sensor_data.assert_called_once_with(
        "/tf_static",
        "tf2_msgs/TFMessage",
        {"transforms": [{"child_frame_id": "base_scan"}]},
        bypass_rate_limit=True,
        retain=True,
    )


def test_tf_static_callback_merges_multiple_latched_messages(monkeypatch):
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    mock_rospy.wait_for_message.side_effect = Exception("timeout")
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)

    payloads = iter([
        {"transforms": [{"child_frame_id": "base_link"}]},
        {"transforms": [{"child_frame_id": "base_scan"}]},
    ])
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: next(payloads),
    )

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.default_freq_limit = 10.0
    agent._ros_subscribers = {}
    agent._sensor_data = {}
    agent._sensor_lock = MagicMock()
    agent._get_ros_msg_class = MagicMock(return_value=object)
    agent.publish_sensor_data = MagicMock()

    ROS1Agent._on_topic_subscribed(
        agent,
        "/tf_static",
        "tf2_msgs/TFMessage",
        {"freq_limit": 10.0},
    )
    captured_callback["callback"](object())
    captured_callback["callback"](object())

    published = agent.publish_sensor_data.call_args_list[-1]
    assert published[0][0] == "/tf_static"
    assert published[0][1] == "tf2_msgs/TFMessage"
    assert published[1]["bypass_rate_limit"] is True
    assert published[1]["retain"] is True
    assert [
        transform["child_frame_id"]
        for transform in published[0][2]["transforms"]
    ] == ["base_link", "base_scan"]


def test_dynamic_tf_callback_uses_binary_fast_path(monkeypatch):
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)

    def fail_ros_msg_to_dict(msg):
        raise AssertionError("dynamic /tf should not use dict JSON conversion")

    monkeypatch.setattr("agent.ros1_agent.ros_msg_to_dict", fail_ros_msg_to_dict)

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.default_freq_limit = 100.0
    agent._ros_subscribers = {}
    agent._sensor_data = {}
    agent._sensor_lock = MagicMock()
    agent._get_ros_msg_class = MagicMock(return_value=object)
    agent.publish_sensor_binary_data = MagicMock()

    ROS1Agent._on_topic_subscribed(
        agent,
        "/tf",
        "tf2_msgs/TFMessage",
        {"freq_limit": 100.0},
    )
    captured_callback["callback"](_SerializableRosMsg(b"tf-raw"))

    agent.publish_sensor_binary_data.assert_called_once()
    assert agent.publish_sensor_binary_data.call_args[0][:3] == (
        "/tf",
        "tf2_msgs/TFMessage",
        b"tf-raw",
    )


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


def test_on_fleet_message_ros_topic_publishes_typed_dst_topic(monkeypatch):
    mock_rospy = MagicMock()
    typed_pub = MagicMock()
    debug_pub = MagicMock()
    mock_rospy.Publisher.side_effect = [typed_pub, debug_pub]
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.dict_to_ros_msg",
        lambda payload, msg_type: {"msg_type": msg_type, "payload": payload},
    )

    agent = object.__new__(ROS1Agent)
    agent._fleet_publishers = {}

    ROS1Agent._on_fleet_message(agent, "turtlebot_001", FleetData(
        data_type="ros_topic",
        src_topic="/odom",
        dst_topic="/fleet/turtlebot_001/odom",
        msg_type="nav_msgs/Odometry",
        payload={"header": {"frame_id": "odom"}},
    ))

    assert mock_rospy.Publisher.call_args_list[0][0][0] == "/fleet/turtlebot_001/odom"
    assert mock_rospy.Publisher.call_args_list[0][0][1] is dict
    typed_pub.publish.assert_called_once_with({
        "msg_type": "nav_msgs/Odometry",
        "payload": {"header": {"frame_id": "odom"}},
    })
    debug_pub.publish.assert_called_once()


def test_on_fleet_message_namespaces_payload_when_requested(monkeypatch):
    mock_rospy = MagicMock()
    typed_pub = MagicMock()
    debug_pub = MagicMock()
    mock_rospy.Publisher.side_effect = [typed_pub, debug_pub]
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)

    captured_payloads = []

    def fake_dict_to_ros_msg(payload, msg_type):
        captured_payloads.append(payload)
        return object()

    monkeypatch.setattr("agent.ros1_agent.dict_to_ros_msg", fake_dict_to_ros_msg)

    agent = object.__new__(ROS1Agent)
    agent._fleet_publishers = {}

    ROS1Agent._on_fleet_message(agent, "turtlebot_001", FleetData(
        data_type="ros_topic",
        dst_topic="/fleet/turtlebot_001/odom",
        msg_type="nav_msgs/Odometry",
        frame_policy="namespace",
        payload={
            "header": {"frame_id": "odom"},
            "child_frame_id": "base_footprint",
        },
    ))

    assert captured_payloads[0]["header"]["frame_id"] == "turtlebot_001/odom"
    assert captured_payloads[0]["child_frame_id"] == "turtlebot_001/base_footprint"


def test_on_fleet_message_reuses_typed_publisher(monkeypatch):
    mock_rospy = MagicMock()
    typed_pub = MagicMock()
    debug_pub_1 = MagicMock()
    debug_pub_2 = MagicMock()
    mock_rospy.Publisher.side_effect = [typed_pub, debug_pub_1, debug_pub_2]
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr("agent.ros1_agent.dict_to_ros_msg", lambda payload, msg_type: object())

    agent = object.__new__(ROS1Agent)
    agent._fleet_publishers = {}
    data = FleetData(
        data_type="ros_topic",
        dst_topic="/fleet/turtlebot_001/odom",
        msg_type="nav_msgs/Odometry",
        payload={"header": {"frame_id": "odom"}},
    )

    ROS1Agent._on_fleet_message(agent, "turtlebot_001", data)
    ROS1Agent._on_fleet_message(agent, "turtlebot_001", data)

    typed_topic_calls = [
        call for call in mock_rospy.Publisher.call_args_list
        if call[0][0] == "/fleet/turtlebot_001/odom"
    ]
    assert len(typed_topic_calls) == 1
    assert typed_pub.publish.call_count == 2
