from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent.ros1_agent import ROS1Agent, _FleetRoute
from protocol.messages import FleetBinaryEnvelopeData, FleetData


class _SerializableRosMsg:
    _md5sum = "test-md5"

    def __init__(self, payload: bytes):
        self.payload = payload
        self.serialize_count = 0

    def serialize(self, buff):
        self.serialize_count += 1
        buff.write(self.payload)


class _UnserializableRosMsg:
    _md5sum = "test-md5"

    def serialize(self, buff):
        raise RuntimeError("serialize failed")


class _DeserializableRosMsg:
    _md5sum = "test-md5"

    def __init__(self):
        self.payload = b""
        self.header = type("Header", (), {"frame_id": "odom"})()
        self.child_frame_id = "base_link"

    def deserialize(self, payload):
        self.payload = payload


def build_fleet_rule(
    src_topic,
    msg_type,
    target_id,
    dst_topic,
    transport="mqtt_json",
    qos=1,
):
    """构造源端 route 聚合测试使用的最小规范化规则。"""
    return {
        "enabled": True,
        "src_topic": src_topic,
        "msg_type": msg_type,
        "targets": [{"robot_id": target_id, "dst_topic": dst_topic}],
        "freq_limit": 0.0,
        "transport": transport,
        "qos": qos,
        "frame_policy": "namespace",
    }


def build_binary_target_agent(msg_class):
    """构造不依赖 roscore 的目标 ROS1Agent 测试对象。"""
    agent = object.__new__(ROS1Agent)
    agent._get_ros_msg_class = MagicMock(return_value=msg_class)
    agent._get_fleet_publisher = MagicMock(return_value=MagicMock())
    agent._publish_fleet_summary = MagicMock()
    return agent


def build_binary_envelope(md5sum, transfer_id):
    """构造通过 BaseAgent 配对后交给 ROS1 hook 的 envelope。"""
    return FleetBinaryEnvelopeData(
        transfer_id=transfer_id,
        payload_size=8,
        md5sum=md5sum,
        src_topic="/odom",
        dst_topic="/fleet/r1/odom",
        msg_type="nav_msgs/Odometry",
        frame_policy="preserve",
        ttl=1.0,
    )


def test_on_fleet_binary_message_deserializes_and_publishes_typed_topic():
    """合法 binary 应恢复原 ROS 类型并应用对象级 frame namespace。"""
    typed_pub = MagicMock()
    agent = object.__new__(ROS1Agent)
    agent._get_ros_msg_class = MagicMock(return_value=_DeserializableRosMsg)
    agent._get_fleet_publisher = MagicMock(return_value=typed_pub)
    agent._publish_fleet_summary = MagicMock()
    envelope = build_binary_envelope(md5sum="test-md5", transfer_id=21)
    envelope.frame_policy = "namespace"

    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")

    typed_pub.publish.assert_called_once()
    published = typed_pub.publish.call_args.args[0]
    assert published.payload == b"ros-body"
    assert published.header.frame_id == "r1/odom"
    assert published.child_frame_id == "r1/base_link"
    agent._publish_fleet_summary.assert_called_once_with(
        src_id="r1",
        dst_topic="/fleet/r1/odom",
        msg_type="nav_msgs/Odometry",
        transport="mqtt_binary",
        transfer_id=21,
        payload_size=8,
    )


def test_on_fleet_binary_message_rejects_md5_mismatch():
    """源端和本地 ROS 消息定义 MD5 不一致时拒绝发布。"""
    agent = build_binary_target_agent(_DeserializableRosMsg)
    envelope = build_binary_envelope(md5sum="other-md5", transfer_id=22)

    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")

    agent._get_fleet_publisher.assert_not_called()
    agent._publish_fleet_summary.assert_not_called()


def test_on_fleet_binary_message_rejects_missing_local_md5():
    """本地消息类缺少 MD5 时不能尝试反序列化。"""

    class MissingMd5Message(_DeserializableRosMsg):
        _md5sum = ""

    agent = build_binary_target_agent(MissingMd5Message)
    envelope = build_binary_envelope(md5sum="test-md5", transfer_id=23)

    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")

    agent._get_fleet_publisher.assert_not_called()


def test_on_fleet_binary_deserialize_error_does_not_block_next_message():
    """单条坏 body 只丢弃当前 transfer，下一条仍可发布。"""

    class FailingMessage(_DeserializableRosMsg):
        def deserialize(self, payload):
            raise ValueError("bad payload")

    agent = build_binary_target_agent(FailingMessage)
    envelope = build_binary_envelope(md5sum="test-md5", transfer_id=24)
    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"bad")
    agent._get_ros_msg_class = MagicMock(return_value=_DeserializableRosMsg)
    envelope.transfer_id = 25

    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"good")

    assert agent._get_fleet_publisher.return_value.publish.call_count == 1


def test_on_fleet_binary_message_rejects_unknown_type():
    """目标端无法加载 ROS 消息类时丢弃当前 transfer。"""
    agent = build_binary_target_agent(None)
    envelope = build_binary_envelope(md5sum="test-md5", transfer_id=26)

    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")

    agent._get_fleet_publisher.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("data_type", "custom"),
    ("encoding", "unknown"),
    ("payload_format", "unknown"),
    ("dst_topic", "relative/topic"),
    ("msg_type", ""),
])
def test_on_fleet_binary_message_rejects_invalid_route_markers(field, value):
    """目标 hook 再次验证关键协议标记和 ROS 目标路径。"""
    agent = build_binary_target_agent(_DeserializableRosMsg)
    envelope = build_binary_envelope(md5sum="test-md5", transfer_id=27)
    setattr(envelope, field, value)

    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")

    agent._get_fleet_publisher.assert_not_called()


def test_on_fleet_binary_reuses_publishers_and_emits_lightweight_summary(
    monkeypatch,
):
    """连续 binary 消息复用两个 publisher，摘要不得携带 ROS body。"""
    typed_pub = MagicMock()
    summary_pub = MagicMock()
    mock_rospy = MagicMock()
    mock_rospy.Publisher.side_effect = [typed_pub, summary_pub]
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    agent = object.__new__(ROS1Agent)
    agent._get_ros_msg_class = MagicMock(return_value=_DeserializableRosMsg)
    agent._fleet_publishers = {}
    agent._fleet_incoming_pub = None
    envelope = build_binary_envelope(md5sum="test-md5", transfer_id=31)

    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")
    envelope.transfer_id = 32
    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-next")

    assert mock_rospy.Publisher.call_count == 2
    assert typed_pub.publish.call_count == 2
    assert summary_pub.publish.call_count == 2
    summary = json.loads(summary_pub.publish.call_args.args[0])
    assert set(summary) == {
        "src_id",
        "dst_topic",
        "msg_type",
        "transport",
        "transfer_id",
        "payload_size",
        "timestamp",
    }
    assert summary["transport"] == "mqtt_binary"
    assert summary["transfer_id"] == 32
    assert "body" not in summary
    assert "payload" not in summary


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
    assert agent._fleet_subscribers[("/odom", "nav_msgs/Odometry")] is mock_sub


def test_apply_fleet_rules_groups_same_source_topic_into_one_subscriber(
    monkeypatch,
):
    """同一 source topic/type 的多个 route 只创建一个 ROS subscriber。"""
    mock_rospy = MagicMock()
    mock_rospy.Subscriber.return_value = MagicMock()
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    agent = object.__new__(ROS1Agent)
    agent._fleet_subscribers = {}
    agent._get_ros_msg_class = MagicMock(return_value=object)
    rules = [
        build_fleet_rule(
            "/odom",
            "nav_msgs/Odometry",
            "r2",
            "/fleet/r1/odom",
        ),
        build_fleet_rule(
            "/odom",
            "nav_msgs/Odometry",
            "r3",
            "/fleet/r1/odom",
            transport="mqtt_binary",
            qos=0,
        ),
    ]

    ROS1Agent._apply_fleet_rules(agent, rules)

    assert mock_rospy.Subscriber.call_count == 1
    assert len(agent._fleet_subscribers) == 1


def test_group_fleet_routes_rejects_conflicting_types_for_same_topic():
    """同一源 topic 配置不同消息类型时整组拒绝。"""
    rules = [
        build_fleet_rule(
            "/odom",
            "nav_msgs/Odometry",
            "r2",
            "/fleet/r1/odom",
        ),
        build_fleet_rule(
            "/odom",
            "geometry_msgs/PoseStamped",
            "r3",
            "/debug/odom",
        ),
    ]

    assert ROS1Agent._group_fleet_routes(rules) == {}


def test_group_fleet_routes_deduplicates_identical_routes():
    """重复配置不能造成同一消息重复发送。"""
    rule = build_fleet_rule(
        "/odom",
        "nav_msgs/Odometry",
        "r2",
        "/fleet/r1/odom",
        transport="mqtt_binary",
        qos=0,
    )

    groups = ROS1Agent._group_fleet_routes([rule, dict(rule)])

    assert len(groups[("/odom", "nav_msgs/Odometry")]) == 1


def test_fleet_callback_serializes_once_and_uses_unique_transfer_per_route():
    """同一 ROS 回调只 serialize 一次，但每条 binary route 使用独立 ID。"""
    agent = object.__new__(ROS1Agent)
    binary_send = MagicMock(return_value=(True, True))
    agent.send_fleet_binary_to_robot = binary_send
    agent.send_to_robot = MagicMock(return_value=True)
    agent._next_fleet_transfer_id = MagicMock(side_effect=[101, 102])
    routes = [
        _FleetRoute(
            "r2",
            "/fleet/r1/odom",
            0.0,
            "mqtt_binary",
            0,
            "namespace",
        ),
        _FleetRoute(
            "r2",
            "/debug/r1/odom",
            0.0,
            "mqtt_binary",
            0,
            "preserve",
        ),
    ]
    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        src_topic="/odom",
        msg_type="nav_msgs/Odometry",
        routes=routes,
    )
    msg = _SerializableRosMsg(b"serialized-odom")

    callback(msg)

    assert msg.serialize_count == 1
    assert binary_send.call_count == 2
    ids = [item.args[1].transfer_id for item in binary_send.call_args_list]
    assert len(set(ids)) == 2


def test_fleet_routes_use_independent_frequency_limits(monkeypatch):
    """同一 subscriber 中每条 route 独立判断是否到期。"""
    times = iter([100.0, 100.05, 100.11])
    monkeypatch.setattr("agent.ros1_agent.time.monotonic", lambda: next(times))
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        MagicMock(return_value={"header": {"frame_id": "odom"}}),
    )
    agent = object.__new__(ROS1Agent)
    agent.send_to_robot = MagicMock(return_value=True)
    routes = [
        _FleetRoute("r2", "/slow", 10.0, "mqtt_json", 1, "preserve"),
        _FleetRoute("r3", "/fast", 20.0, "mqtt_json", 1, "preserve"),
    ]
    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        "/odom",
        "nav_msgs/Odometry",
        routes,
    )

    callback(object())
    callback(object())
    callback(object())

    targets = [item.args[0] for item in agent.send_to_robot.call_args_list]
    assert targets.count("r2") == 2
    assert targets.count("r3") == 3


def test_fleet_frequency_limit_does_not_accumulate_callback_phase_drift(
    monkeypatch,
):
    """24 Hz 输入限制到 10 Hz 时，不应量化成每三帧一次的 8 Hz。"""
    times = iter(100.0 + index / 24.0 for index in range(240))
    monkeypatch.setattr("agent.ros1_agent.time.monotonic", lambda: next(times))
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        MagicMock(return_value={"header": {"frame_id": "odom"}}),
    )
    agent = object.__new__(ROS1Agent)
    agent.send_to_robot = MagicMock(return_value=True)
    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        "/odom",
        "nav_msgs/Odometry",
        [_FleetRoute("r2", "/odom", 10.0, "mqtt_json", 1, "preserve")],
    )

    for _index in range(240):
        callback(object())

    assert 99 <= agent.send_to_robot.call_count <= 101


def test_fleet_frequency_limit_skips_missed_periods_without_catch_up(
    monkeypatch,
):
    """长时间停顿后只发送当前帧，不按源频率追赶已错过的周期。"""
    times = iter([100.0, 110.0, 110.01, 110.02, 110.1])
    monkeypatch.setattr("agent.ros1_agent.time.monotonic", lambda: next(times))
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        MagicMock(return_value={"header": {"frame_id": "odom"}}),
    )
    agent = object.__new__(ROS1Agent)
    agent.send_to_robot = MagicMock(return_value=True)
    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        "/odom",
        "nav_msgs/Odometry",
        [_FleetRoute("r2", "/odom", 10.0, "mqtt_json", 1, "preserve")],
    )

    for _index in range(5):
        callback(object())

    assert agent.send_to_robot.call_count == 3


def test_fleet_binary_serialize_failure_falls_back_to_json_once(monkeypatch):
    """serialize 失败时只转一次字典，并为 binary route 发送完整 JSON。"""
    ros_msg_to_dict = MagicMock(return_value={"header": {"frame_id": "odom"}})
    monkeypatch.setattr("agent.ros1_agent.ros_msg_to_dict", ros_msg_to_dict)
    agent = object.__new__(ROS1Agent)
    json_send = MagicMock(return_value=True)
    binary_send = MagicMock(return_value=(True, True))
    agent.send_to_robot = json_send
    agent.send_fleet_binary_to_robot = binary_send
    routes = [
        _FleetRoute(
            "r2",
            "/fleet/r1/odom",
            0.0,
            "mqtt_binary",
            0,
            "namespace",
        )
    ]
    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        "/odom",
        "nav_msgs/Odometry",
        routes,
    )

    callback(_UnserializableRosMsg())

    ros_msg_to_dict.assert_called_once()
    json_send.assert_called_once()
    binary_send.assert_not_called()


def test_fleet_binary_missing_md5_falls_back_to_json(monkeypatch):
    """源消息 MD5 缺失时不得发送无法安全反序列化的 binary。"""

    class NoMd5Message(_SerializableRosMsg):
        _md5sum = ""

    ros_msg_to_dict = MagicMock(return_value={"header": {"frame_id": "odom"}})
    monkeypatch.setattr("agent.ros1_agent.ros_msg_to_dict", ros_msg_to_dict)
    agent = object.__new__(ROS1Agent)
    agent.send_to_robot = MagicMock(return_value=True)
    agent.send_fleet_binary_to_robot = MagicMock(return_value=(True, True))
    routes = [
        _FleetRoute(
            "r2",
            "/fleet/r1/odom",
            0.0,
            "mqtt_binary",
            0,
            "namespace",
        )
    ]
    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        "/odom",
        "nav_msgs/Odometry",
        routes,
    )

    callback(NoMd5Message(b"serialized-odom"))

    ros_msg_to_dict.assert_called_once()
    agent.send_to_robot.assert_called_once()
    agent.send_fleet_binary_to_robot.assert_not_called()


def test_fleet_binary_publish_failure_does_not_fallback_to_json():
    """Paho rc 失败只记录结果，不能产生重复 JSON 逻辑消息。"""
    agent = object.__new__(ROS1Agent)
    agent.send_to_robot = MagicMock(return_value=True)
    agent.send_fleet_binary_to_robot = MagicMock(return_value=(False, True))
    agent._next_fleet_transfer_id = MagicMock(return_value=31)
    route = _FleetRoute(
        "r2",
        "/fleet/r1/odom",
        0.0,
        "mqtt_binary",
        1,
        "namespace",
    )
    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        "/odom",
        "nav_msgs/Odometry",
        [route],
    )

    callback(_SerializableRosMsg(b"serialized-odom"))

    agent.send_fleet_binary_to_robot.assert_called_once()
    agent.send_to_robot.assert_not_called()


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
        {"freq_limit": 100.0, "transport": "mqtt_binary"},
    )
    captured_callback["callback"](_SerializableRosMsg(b"tf-raw"))

    agent.publish_sensor_binary_data.assert_called_once()
    assert agent.publish_sensor_binary_data.call_args[0][:3] == (
        "/tf",
        "tf2_msgs/TFMessage",
        b"tf-raw",
    )


def test_allowlisted_topic_uses_ros1_serialized_fast_path(monkeypatch):
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.is_ros_message_binary_supported",
        lambda topic, msg_type: topic == "/odom" and msg_type == "nav_msgs/Odometry",
    )
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: (_ for _ in ()).throw(
            AssertionError("serialized topic should not use JSON conversion")
        ),
    )

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
        "/odom",
        "nav_msgs/Odometry",
        {"freq_limit": 100.0, "transport": "mqtt_binary"},
    )
    captured_callback["callback"](_SerializableRosMsg(b"odom-raw"))

    agent.publish_sensor_binary_data.assert_called_once()
    assert agent.publish_sensor_binary_data.call_args[0][:3] == (
        "/odom",
        "nav_msgs/Odometry",
        b"odom-raw",
    )


def test_compressed_image_uses_ros1_serialized_fast_path(monkeypatch):
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: (_ for _ in ()).throw(
            AssertionError("compressed image should not use JSON conversion")
        ),
    )

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
        "/realsense/color/image_raw/compressed",
        "sensor_msgs/CompressedImage",
        {"freq_limit": 100.0, "transport": "mqtt_binary"},
    )
    captured_callback["callback"](_SerializableRosMsg(b"jpeg-bytes"))

    agent.publish_sensor_binary_data.assert_called_once()
    assert agent.publish_sensor_binary_data.call_args[0][:3] == (
        "/realsense/color/image_raw/compressed",
        "sensor_msgs/CompressedImage",
        b"jpeg-bytes",
    )


def test_joint_state_uses_ros1_serialized_fast_path(monkeypatch):
    """普通 ROS 话题配置为 mqtt_binary 时优先发送原始 ROS1 序列化字节。"""
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: (_ for _ in ()).throw(
            AssertionError("mqtt_binary ROS topic should not use JSON conversion")
        ),
    )

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
        "/joint_states",
        "sensor_msgs/JointState",
        {"freq_limit": 100.0, "transport": "mqtt_binary"},
    )
    captured_callback["callback"](_SerializableRosMsg(b"joint-state-raw"))

    agent.publish_sensor_binary_data.assert_called_once()
    assert agent.publish_sensor_binary_data.call_args[0][:3] == (
        "/joint_states",
        "sensor_msgs/JointState",
        b"joint-state-raw",
    )


def test_mqtt_binary_falls_back_to_json_when_ros1_serialize_fails(monkeypatch):
    """ROS1 原始序列化失败时继续走 JSON 路径，避免中断话题发布。"""
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: {"name": ["front_left"], "position": [1.0]},
    )

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.default_freq_limit = 100.0
    agent._ros_subscribers = {}
    agent._sensor_data = {}
    agent._sensor_lock = MagicMock()
    agent._get_ros_msg_class = MagicMock(return_value=object)
    agent.publish_sensor_binary_data = MagicMock()
    agent.publish_sensor_data = MagicMock()

    ROS1Agent._on_topic_subscribed(
        agent,
        "/joint_states",
        "sensor_msgs/JointState",
        {"freq_limit": 100.0, "transport": "mqtt_binary"},
    )
    captured_callback["callback"](_UnserializableRosMsg())

    agent.publish_sensor_binary_data.assert_not_called()
    agent.publish_sensor_data.assert_called_once_with(
        "/joint_states",
        "sensor_msgs/JointState",
        {"name": ["front_left"], "position": [1.0]},
    )


def test_allowlisted_topic_uses_json_when_transport_is_mqtt_json(monkeypatch):
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.is_ros_message_binary_supported",
        lambda topic, msg_type: topic == "/odom" and msg_type == "nav_msgs/Odometry",
    )
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: {"header": {"frame_id": "odom"}},
    )

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.default_freq_limit = 100.0
    agent._ros_subscribers = {}
    agent._sensor_data = {}
    agent._sensor_lock = MagicMock()
    agent._get_ros_msg_class = MagicMock(return_value=object)
    agent.publish_sensor_binary_data = MagicMock()
    agent.publish_sensor_data = MagicMock()

    ROS1Agent._on_topic_subscribed(
        agent,
        "/odom",
        "nav_msgs/Odometry",
        {"freq_limit": 100.0, "transport": "mqtt_json"},
    )
    captured_callback["callback"](_SerializableRosMsg(b"odom-raw"))

    agent.publish_sensor_binary_data.assert_not_called()
    agent.publish_sensor_data.assert_called_once_with(
        "/odom",
        "nav_msgs/Odometry",
        {"header": {"frame_id": "odom"}},
    )


def test_pointcloud2_uses_heavy_snapshot_path(monkeypatch):
    from agent.mock_pointcloud2_data import (
        FakePointCloud2Message,
        build_pointcloud2_dict,
    )

    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: (_ for _ in ()).throw(
            AssertionError("PointCloud2 heavy path should not use JSON conversion")
        ),
    )

    data = build_pointcloud2_dict(
        frame_id="velodyne",
        seq=9,
        stamp={"secs": 3, "nsecs": 4},
    )
    msg = FakePointCloud2Message.from_dict(data)
    raw_payload = bytes(msg.data)

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.default_freq_limit = 2.0
    agent._ros_subscribers = {}
    agent._sensor_data = {}
    agent._sensor_lock = MagicMock()
    agent._get_ros_msg_class = MagicMock(return_value=object)
    agent.publish_heavy_snapshot_data = MagicMock()

    ROS1Agent._on_topic_subscribed(
        agent,
        "/velodyne_points",
        "sensor_msgs/PointCloud2",
        {"freq_limit": 2.0, "transport": "http_stream"},
    )
    captured_callback["callback"](msg)

    agent.publish_heavy_snapshot_data.assert_called_once_with(
        "/velodyne_points",
        "sensor_msgs/PointCloud2",
        raw_payload,
        seq=9,
        stamp={"secs": 3, "nsecs": 4},
        frame_id="velodyne",
    )


def test_fleet_rule_callback_sends_fleet_data(monkeypatch):
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: {"header": {"frame_id": "odom"}},
    )

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.robot_id = "turtlebot_001"
    agent.send_to_robot = MagicMock(return_value=True)

    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        src_topic="/odom",
        msg_type="nav_msgs/Odometry",
        routes=[
            _FleetRoute(
                "turtlebot_002",
                "/fleet/turtlebot_001/odom",
                0.0,
                "mqtt_json",
                1,
                "namespace",
            )
        ],
    )

    callback(object())

    sent_data = agent.send_to_robot.call_args.args[1]
    assert agent.send_to_robot.call_args.args[0] == "turtlebot_002"
    assert agent.send_to_robot.call_args.kwargs == {"qos": 1}
    assert isinstance(sent_data, FleetData)
    assert sent_data.data_type == "ros_topic"
    assert sent_data.src_topic == "/odom"
    assert sent_data.dst_topic == "/fleet/turtlebot_001/odom"
    assert sent_data.msg_type == "nav_msgs/Odometry"
    assert sent_data.frame_policy == "namespace"
    assert sent_data.payload == {"header": {"frame_id": "odom"}}
    assert sent_data.ttl == 1.0


def test_fleet_rule_callback_respects_freq_limit(monkeypatch):
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: {"header": {"frame_id": "odom"}},
    )
    times = iter([100.0, 100.05, 100.11])
    monkeypatch.setattr("agent.ros1_agent.time.monotonic", lambda: next(times))

    agent = object.__new__(ROS1Agent)
    agent.send_to_robot = MagicMock(return_value=True)

    callback = ROS1Agent._make_fleet_forward_callback(
        agent,
        src_topic="/odom",
        msg_type="nav_msgs/Odometry",
        routes=[
            _FleetRoute(
                "turtlebot_002",
                "/fleet/turtlebot_001/odom",
                10.0,
                "mqtt_json",
                1,
                "preserve",
            )
        ],
    )

    callback(object())
    callback(object())
    callback(object())

    assert agent.send_to_robot.call_count == 2


def test_fleet_summary_json_ros_topic_publishes_typed_dst_topic(monkeypatch):
    mock_rospy = MagicMock()
    typed_pub = MagicMock()
    summary_pub = MagicMock()
    mock_rospy.Publisher.side_effect = [typed_pub, summary_pub]
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.dict_to_ros_msg",
        lambda payload, msg_type: {"msg_type": msg_type, "payload": payload},
    )

    agent = object.__new__(ROS1Agent)
    agent._fleet_publishers = {}
    agent._fleet_incoming_pub = None

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
    summary_pub.publish.assert_called_once()
    summary = json.loads(summary_pub.publish.call_args.args[0])
    assert set(summary) == {
        "src_id",
        "dst_topic",
        "msg_type",
        "transport",
        "transfer_id",
        "payload_size",
        "timestamp",
    }
    assert summary["transport"] == "mqtt_json"
    assert "payload" not in summary


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
    agent._fleet_incoming_pub = None

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
    summary_pub = MagicMock()
    mock_rospy.Publisher.side_effect = [typed_pub, summary_pub]
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr("agent.ros1_agent.dict_to_ros_msg", lambda payload, msg_type: object())

    agent = object.__new__(ROS1Agent)
    agent._fleet_publishers = {}
    agent._fleet_incoming_pub = None
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
    summary_topic_calls = [
        call for call in mock_rospy.Publisher.call_args_list
        if call[0][0] == "/fleet/incoming"
    ]
    assert len(summary_topic_calls) == 1
    assert summary_pub.publish.call_count == 2
