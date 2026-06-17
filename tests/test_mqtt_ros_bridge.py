from __future__ import annotations

"""
Tests for mqtt_ros_bridge — MQTT to ROS bridge core logic.

Covers: RobotState dataclass, topic map management, heartbeat monitoring,
status aggregation, MQTT message routing, connection handling, station
response handling, config loading, and miscellaneous helper methods.
"""

import json
import os
import sys
import types
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from protocol.binary_payloads import encode_sensor_binary

# ---------------------------------------------------------------------------
# Mock rospy and std_msgs.msg at sys.modules level before importing bridge
#
# Note: we only set up the rospy mock when it does not already exist in
# sys.modules so that other test files (e.g. test_dict_to_ros_msg.py) can
# share the same mock object.  The mock includes MockTime / MockDuration
# classes that match what dict_to_ros_msg expects.
# ---------------------------------------------------------------------------


class MockTime:
    """Mock rospy.Time -- identical to copy in test_dict_to_ros_msg.py."""
    def __init__(self, secs=0, nsecs=0):
        self.secs = secs
        self.nsecs = nsecs

    @classmethod
    def now(cls):
        return cls()

    def __eq__(self, other):
        if isinstance(other, MockTime):
            return self.secs == other.secs and self.nsecs == other.nsecs
        return NotImplemented

    def __repr__(self):
        return f"MockTime(secs={self.secs}, nsecs={self.nsecs})"


class MockDuration:
    """Mock rospy.Duration -- identical to copy in test_dict_to_ros_msg.py."""
    def __init__(self, secs=0, nsecs=0):
        self.secs = secs
        self.nsecs = nsecs

    def __eq__(self, other):
        if isinstance(other, MockDuration):
            return self.secs == other.secs and self.nsecs == other.nsecs
        return NotImplemented

    def __repr__(self):
        return f"MockDuration(secs={self.secs}, nsecs={self.nsecs})"

    @classmethod
    def from_sec(cls, seconds):
        secs = int(seconds)
        nsecs = int(round((seconds - secs) * 1e9))
        return cls(secs=secs, nsecs=nsecs)

    def to_sec(self):
        return self.secs + self.nsecs * 1e-9


if "rospy" not in sys.modules:
    _mock_rospy = MagicMock()
    _mock_rospy.init_node = MagicMock()
    _mock_rospy.spin = MagicMock()
    _mock_rospy.Publisher = MagicMock()
    _mock_rospy.Subscriber = MagicMock()
    _mock_rospy.Time = MockTime
    _mock_rospy.Duration = MockDuration
    sys.modules["rospy"] = _mock_rospy
    sys.modules["rospy.msg"] = _mock_rospy.msg


class MockString:
    """Mock std_msgs.msg.String"""
    def __init__(self, data: str = ""):
        self.data = data


if "std_msgs" not in sys.modules:
    _mock_std_msgs = MagicMock()
    _mock_std_msgs.msg = MagicMock()
    _mock_std_msgs.msg.String = MockString
    sys.modules["std_msgs"] = _mock_std_msgs
    sys.modules["std_msgs.msg"] = _mock_std_msgs.msg
else:
    # Ensure String is available on an existing std_msgs mock
    if not hasattr(sys.modules["std_msgs"].msg, "String"):
        sys.modules["std_msgs"].msg.String = MockString


class MockTwist:
    def __init__(self):
        self.linear = types.SimpleNamespace(x=0.0, y=0.0, z=0.0)
        self.angular = types.SimpleNamespace(x=0.0, y=0.0, z=0.0)


class MockTransformStamped:
    def __init__(self):
        self.header = types.SimpleNamespace(
            stamp=None,
            frame_id="",
        )
        self.child_frame_id = ""
        self.transform = types.SimpleNamespace(
            translation=types.SimpleNamespace(x=0.0, y=0.0, z=0.0),
            rotation=types.SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
        )


if "geometry_msgs" not in sys.modules:
    _mock_geometry_msgs = types.ModuleType("geometry_msgs")
    _mock_geometry_msgs_msg = types.ModuleType("geometry_msgs.msg")

    _mock_geometry_msgs_msg.Twist = MockTwist
    _mock_geometry_msgs_msg.TransformStamped = MockTransformStamped
    _mock_geometry_msgs.msg = _mock_geometry_msgs_msg
    sys.modules["geometry_msgs"] = _mock_geometry_msgs
    sys.modules["geometry_msgs.msg"] = _mock_geometry_msgs_msg
else:
    if not hasattr(sys.modules["geometry_msgs"].msg, "Twist"):
        sys.modules["geometry_msgs"].msg.Twist = MockTwist
    if not hasattr(sys.modules["geometry_msgs"].msg, "TransformStamped"):
        sys.modules["geometry_msgs"].msg.TransformStamped = MockTransformStamped

if "tf2_ros" not in sys.modules:
    _mock_tf2_ros = types.ModuleType("tf2_ros")
    _mock_tf2_ros.StaticTransformBroadcaster = MagicMock()
    sys.modules["tf2_ros"] = _mock_tf2_ros

# Now import the module under test
from protocol.messages import Message, MessageType, TopicResponseResult  # noqa: E402
from bridge.mqtt_ros_bridge import (  # noqa: E402
    MqttRosBridge,
    RobotState,
)

# ---------------------------------------------------------------------------
# Shared test config
# ---------------------------------------------------------------------------
_TEST_CONFIG = {
    "mqtt": {
        "broker_host": "localhost",
        "broker_port": 1883,
        "client_id": "test_bridge",
    },
    "ros": {
        "master_uri": "http://localhost:11311",
        "node_name": "test_bridge",
        "max_update_frequency": 30.0,
    },
    "heartbeat_timeout": 30.0,
    "transmit_config_path": "../config/transmit_config.yaml",
}

_SENSOR_DATA_PAYLOAD = json.dumps(
    {"x": 1.0, "y": 2.0, "z": 3.0}
).encode("utf-8")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockMqttMsg:
    """Simulate a paho MQTT message."""
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


def make_mock_rospy():
    mock_rospy = MagicMock()
    mock_rospy.Publisher = MagicMock()
    mock_rospy.Subscriber = MagicMock()
    mock_rospy.Time = MockTime
    mock_rospy.Duration = MockDuration
    mock_rospy.is_shutdown.return_value = False
    return mock_rospy


@pytest.fixture
def bridge(monkeypatch):
    """Create an MqttRosBridge instance with a mocked config loader.

    The bridge is created with ``_running = True`` so heartbeat-related
    methods can operate without needing a full ``start()`` call.
    """
    import bridge.mqtt_ros_bridge as bridge_module

    mock_rospy = make_mock_rospy()
    monkeypatch.setattr(bridge_module, "rospy", mock_rospy)
    monkeypatch.setattr(bridge_module, "TransformStamped", MockTransformStamped)

    with patch.object(MqttRosBridge, "_load_config", return_value=_TEST_CONFIG):
        br = MqttRosBridge()
    br._test_rospy = mock_rospy
    br._running = True
    return br


# ===================================================================
# 1. TestRobotState
# ===================================================================

class TestRobotState:
    """RobotState dataclass creation and field manipulation."""

    def test_create_robot_state(self):
        """Default field values are correct."""
        state = RobotState(robot_id="robot_001")
        assert state.robot_id == "robot_001"
        assert state.online is True
        assert state.last_seen == 0.0
        assert state.status == {}
        assert state.available_topics == []
        assert state.subscriptions == {}

    def test_robot_state_update_fields(self):
        """Fields can be updated after creation."""
        state = RobotState(robot_id="robot_001")
        state.online = False
        state.last_seen = 12345.67
        state.status = {"battery": 85.0}
        state.available_topics = [{"topic": "/odom", "msg_type": "nav_msgs/Odometry"}]
        state.subscriptions = {"/camera/image": {"msg_type": "sensor_msgs/Image"}}

        assert state.online is False
        assert state.last_seen == 12345.67
        assert state.status["battery"] == 85.0
        assert len(state.available_topics) == 1
        assert state.subscriptions["/camera/image"]["msg_type"] == "sensor_msgs/Image"

    def test_robot_state_multiple_instances(self):
        """Each robot has an independent state."""
        r1 = RobotState(robot_id="r1")
        r2 = RobotState(robot_id="r2")

        r1.online = False
        r1.status = {"battery": 50.0}

        assert r2.online is True
        assert r2.status == {}
        assert r1.robot_id == "r1"
        assert r2.robot_id == "r2"


# ===================================================================
# 2. TestTopicMapping
# ===================================================================

class TestTopicMapping:
    """_topic_map management (add / remove / overwrite)."""

    def test_topic_map_update(self, bridge: MqttRosBridge):
        """Adding a topic mapping stores it by robot_id and sensor_name."""
        bridge._topic_map["robot_001"] = {}
        bridge._topic_map["robot_001"]["camera"] = ("/camera/image", "sensor_msgs/Image")
        assert bridge._topic_map["robot_001"]["camera"] == (
            "/camera/image", "sensor_msgs/Image"
        )

    def test_topic_map_clear(self, bridge: MqttRosBridge):
        """Removing a topic mapping from the dict works."""
        bridge._topic_map["robot_001"] = {
            "camera": ("/camera/image", "sensor_msgs/Image"),
            "lidar": ("/scan", "sensor_msgs/LaserScan"),
        }
        bridge._topic_map["robot_001"].pop("camera", None)
        assert "camera" not in bridge._topic_map["robot_001"]
        assert "lidar" in bridge._topic_map["robot_001"]

    def test_topic_map_overwrite(self, bridge: MqttRosBridge):
        """Overwriting an existing mapping replaces it."""
        bridge._topic_map["robot_001"] = {}
        bridge._topic_map["robot_001"]["camera"] = (
            "/camera/image_raw", "sensor_msgs/Image"
        )
        bridge._topic_map["robot_001"]["camera"] = (
            "/camera/image_compressed", "sensor_msgs/CompressedImage"
        )
        assert bridge._topic_map["robot_001"]["camera"] == (
            "/camera/image_compressed", "sensor_msgs/CompressedImage"
        )


# ===================================================================
# 3. TestHeartbeat
# ===================================================================

class TestHeartbeat:
    """Heartbeat timeout detection and monitor lifecycle."""

    def test_heartbeat_marks_offline(self, bridge: MqttRosBridge):
        """Robot is marked offline when last_seen exceeds the timeout."""
        bridge._heartbeat_timeout = 0.5
        bridge._robots["robot_001"] = RobotState(
            robot_id="robot_001",
            online=True,
            last_seen=time.monotonic() - 60,
        )
        bridge._check_heartbeats()
        assert bridge._robots["robot_001"].online is False

    def test_heartbeat_stays_online(self, bridge: MqttRosBridge):
        """Robot stays online when last_seen is within the timeout."""
        bridge._heartbeat_timeout = 60.0
        bridge._robots["robot_001"] = RobotState(
            robot_id="robot_001",
            online=True,
            last_seen=time.monotonic(),
        )
        bridge._check_heartbeats()
        assert bridge._robots["robot_001"].online is True

    def test_heartbeat_only_checks_online_robots(self, bridge: MqttRosBridge):
        """Already-offline robots are skipped by _check_heartbeats."""
        bridge._heartbeat_timeout = 0.5
        bridge._robots["robot_001"] = RobotState(
            robot_id="robot_001",
            online=True,
            last_seen=time.monotonic() - 60,
        )
        bridge._robots["robot_002"] = RobotState(
            robot_id="robot_002",
            online=False,
            last_seen=0.0,
        )
        bridge._check_heartbeats()
        # robot_001 was online but timed out -> offline
        assert bridge._robots["robot_001"].online is False
        # robot_002 was already offline, unchanged
        assert bridge._robots["robot_002"].online is False


# ===================================================================
# 4. TestStatusAggregation
# ===================================================================

class TestStatusAggregation:
    """_build_robot_list_aggregation output."""

    def test_empty_robot_list_aggregation(self, bridge: MqttRosBridge):
        """No robots yields count=0 and an empty list."""
        result = bridge._build_robot_list_aggregation()
        assert result["count"] == 0
        assert result["robots"] == []

    def test_single_robot_aggregation(self, bridge: MqttRosBridge):
        """A single robot appears in the aggregation."""
        bridge._robots["robot_001"] = RobotState(
            robot_id="robot_001",
            online=True,
            last_seen=1000.0,
            status={"battery": 90.0},
            subscriptions={"/odom": {"msg_type": "nav_msgs/Odometry"}},
            available_topics=[{"topic": "/odom"}],
        )
        result = bridge._build_robot_list_aggregation()
        assert result["count"] == 1
        entry = result["robots"][0]
        assert entry["robot_id"] == "robot_001"
        assert entry["online"] is True
        assert entry["status"]["battery"] == 90.0
        assert "/odom" in entry["subscriptions"]

    def test_multiple_robot_aggregation(self, bridge: MqttRosBridge):
        """Multiple robots with mixed state are all included."""
        bridge._robots["robot_001"] = RobotState(
            robot_id="robot_001", online=True, last_seen=100.0,
            status={"battery": 90.0},
        )
        bridge._robots["robot_002"] = RobotState(
            robot_id="robot_002", online=False, last_seen=0.0,
            status={},
        )
        result = bridge._build_robot_list_aggregation()
        assert result["count"] == 2
        ids = {r["robot_id"] for r in result["robots"]}
        assert ids == {"robot_001", "robot_002"}


# ===================================================================
# 5. TestMqttRouting
# ===================================================================

class TestMqttRouting:
    """_on_mqtt_message dispatches to the correct handler."""

    def test_route_sensor_data(self, bridge: MqttRosBridge):
        """robot/+/sensor/# messages reach _handle_sensor_data."""
        msg = MockMqttMsg("robot/robot_001/sensor/camera", _SENSOR_DATA_PAYLOAD)
        with patch.object(bridge, "_handle_sensor_data") as spied:
            bridge._on_mqtt_message(None, None, msg)
            spied.assert_called_once_with("robot_001", "camera", _SENSOR_DATA_PAYLOAD)

    def test_route_sensor_binary(self, bridge: MqttRosBridge):
        """robot/+/sensor/+/bin messages reach _handle_sensor_binary."""
        payload = b"\x00\x01binary"
        msg = MockMqttMsg("robot/robot_001/sensor/scan/bin", payload)
        with patch.object(bridge, "_handle_sensor_binary") as spied:
            bridge._on_mqtt_message(None, None, msg)
            spied.assert_called_once_with("robot_001", "scan", payload)

    def test_route_status(self, bridge: MqttRosBridge):
        """robot/+/status messages reach _handle_status."""
        payload = json.dumps({"battery": 85.0}).encode("utf-8")
        msg = MockMqttMsg("robot/robot_001/status", payload)
        with patch.object(bridge, "_handle_status") as spied:
            bridge._on_mqtt_message(None, None, msg)
            spied.assert_called_once_with("robot_001", payload)

    def test_route_event(self, bridge: MqttRosBridge):
        """robot/+/event messages reach _handle_event."""
        payload = json.dumps({"level": "error", "code": "E001"}).encode("utf-8")
        msg = MockMqttMsg("robot/robot_001/event", payload)
        with patch.object(bridge, "_handle_event") as spied:
            bridge._on_mqtt_message(None, None, msg)
            spied.assert_called_once_with("robot_001", payload)

    def test_route_cmd_ack(self, bridge: MqttRosBridge):
        """robot/+/cmd/ack messages reach _handle_cmd_ack."""
        payload = json.dumps({"exec_id": "abc123", "result": "ok"}).encode("utf-8")
        msg = MockMqttMsg("robot/robot_001/cmd/ack", payload)
        with patch.object(bridge, "_handle_cmd_ack") as spied:
            bridge._on_mqtt_message(None, None, msg)
            spied.assert_called_once_with("robot_001", payload)

    def test_route_unrecognized_topic(self, bridge: MqttRosBridge):
        """Unrecognised topics are silently ignored (no exception)."""
        msg = MockMqttMsg("some/unknown/topic", b"data")
        # Should not raise and should not call any handler
        with patch.multiple(
            bridge,
            _handle_sensor_data=MagicMock(),
            _handle_status=MagicMock(),
            _handle_event=MagicMock(),
            _handle_cmd_ack=MagicMock(),
            _handle_station_response=MagicMock(),
        ):
            bridge._on_mqtt_message(None, None, msg)
            bridge._handle_sensor_data.assert_not_called()
            bridge._handle_status.assert_not_called()
            bridge._handle_event.assert_not_called()
            bridge._handle_cmd_ack.assert_not_called()
            bridge._handle_station_response.assert_not_called()


# ===================================================================
# 5b. TestBinarySensorData
# ===================================================================

class TestBinarySensorData:
    """Binary sensor envelopes and payloads are decoded before ROS publish."""

    def test_binary_laser_scan_roundtrip_publishes_ros_message(
        self, bridge: MqttRosBridge
    ):
        source = {
            "header": {
                "seq": 1,
                "stamp": {"secs": 2, "nsecs": 3},
                "frame_id": "base_scan",
            },
            "angle_min": 0.0,
            "angle_max": 1.0,
            "angle_increment": 0.5,
            "time_increment": 0.0,
            "scan_time": 0.1,
            "range_min": 0.12,
            "range_max": 3.5,
            "ranges": [1.0, 2.0],
            "intensities": [0.5, 0.25],
            "_msg_type": "sensor_msgs/LaserScan",
        }
        envelope, payload = encode_sensor_binary(
            "/scan",
            "sensor_msgs/LaserScan",
            source,
            seq=1,
        )
        publisher = MagicMock()
        ros_msg = types.SimpleNamespace(ranges=[1.0, 2.0])

        def fake_dict_to_ros_msg(data, msg_type):
            assert msg_type == "sensor_msgs/LaserScan"
            assert data["ranges"] == pytest.approx([1.0, 2.0])
            assert data["intensities"] == pytest.approx([0.5, 0.25])
            return ros_msg

        with patch("bridge.mqtt_ros_bridge.dict_to_ros_msg", side_effect=fake_dict_to_ros_msg), \
                patch.object(
                    bridge,
                    "_get_or_create_typed_publisher",
                    return_value=publisher,
                ) as get_pub, \
                patch.object(bridge, "_wait_for_publisher_connection"):
            bridge._handle_sensor_data(
                "robot_001",
                "scan",
                json.dumps(envelope).encode("utf-8"),
            )
            bridge._handle_sensor_binary("robot_001", "scan", payload)

        get_pub.assert_called_once_with("/robot_001/scan", type(ros_msg))
        publisher.publish.assert_called_once_with(ros_msg)


# ===================================================================
# 6. TestMqttConnect
# ===================================================================

class TestMqttConnect:
    """_on_mqtt_connect callback wildcard subscription logic."""

    def test_on_mqtt_connect_success(self, bridge: MqttRosBridge):
        """Reason code 0 triggers wildcard subscriptions."""
        mock_client = MagicMock()
        bridge._on_mqtt_connect(mock_client, None, None, 0, None)
        expected_calls = [
            call("robot/+/sensor/#", qos=0),
            call("robot/+/status", qos=1),
            call("robot/+/event", qos=1),
            call("robot/+/cmd/ack", qos=1),
            call("station/topic/response/+", qos=1),
        ]
        mock_client.subscribe.assert_has_calls(expected_calls, any_order=False)
        assert mock_client.subscribe.call_count >= 5

    def test_on_mqtt_connect_failure(self, bridge: MqttRosBridge):
        """Non-zero reason code does not subscribe."""
        mock_client = MagicMock()
        bridge._on_mqtt_connect(mock_client, None, None, 1, None)
        mock_client.subscribe.assert_not_called()


# ===================================================================
# 7. TestStationResponseHandling
# ===================================================================

class TestStationResponseHandling:
    """Station response parsing (discover_resp / topic_resp)."""

    def test_discover_response(self, bridge: MqttRosBridge):
        """Discover response updates robot state with available topics."""
        topics_payload = [
            {"topic": "/odom", "msg_type": "nav_msgs/Odometry"},
            {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
        ]
        msg = Message(
            type=MessageType.DISCOVER_RESPONSE,
            src="robot_001",
            data={"topics": topics_payload},
        )
        bridge._handle_station_response(
            "station/topic/response/robot_001",
            msg.to_json().encode("utf-8"),
        )
        assert "robot_001" in bridge._robots
        assert bridge._robots["robot_001"].online is True
        assert len(bridge._robots["robot_001"].available_topics) == 2
        assert bridge._robots["robot_001"].available_topics[0]["topic"] == "/odom"

    def test_topic_response_subscribe(self, bridge: MqttRosBridge):
        """Topic response updates _topic_map and RobotState subscriptions."""
        # Pre-populate robot state so the handler updates subscriptions
        bridge._robots["robot_001"] = RobotState(robot_id="robot_001")

        msg = Message(
            type=MessageType.TOPIC_RESPONSE,
            src="robot_001",
            data={
                "action": "subscribe",
                "result": TopicResponseResult.OK.value,
                "topic": "/camera/image",
                "msg_type": "sensor_msgs/Image",
                "freq_limit": 10.0,
            },
        )
        # Mock ROS publishing since we are not running a full ROS environment
        with patch.object(bridge, "_publish_as_json"):
            bridge._handle_station_response(
                "station/topic/response/robot_001",
                msg.to_json().encode("utf-8"),
            )
        # Topic map should contain the new mapping
        assert "robot_001" in bridge._topic_map
        assert bridge._topic_map["robot_001"]["camera_image"] == (
            "/camera/image",
            "sensor_msgs/Image",
        )
        # RobotState subscriptions should also be updated
        assert bridge._robots["robot_001"].subscriptions["/camera/image"] == {
            "msg_type": "sensor_msgs/Image",
            "freq_limit": 10.0,
        }


# ===================================================================
# 8. TestConfigLoading
# ===================================================================

class TestConfigLoading:
    """_load_config static method behaviour."""

    def test_load_config_default_on_missing(self):
        """Non-existent file returns default config."""
        config = MqttRosBridge._load_config("/nonexistent/path/config.yaml")
        assert config["mqtt"]["broker_host"] == "localhost"
        assert config["mqtt"]["broker_port"] == 1883
        assert config["ros"]["master_uri"] == "http://localhost:11311"
        assert config["heartbeat_timeout"] == 30.0

    def test_load_config_success(self, tmp_path: Path):
        """Valid YAML content is returned as a dict."""
        config_file = tmp_path / "bridge_config.yaml"
        config_file.write_text("dummy")  # content replaced by patched yaml.safe_load
        with patch("yaml.safe_load", return_value={
            "mqtt": {"broker_host": "192.168.1.10", "broker_port": 1883},
            "ros": {"master_uri": "http://192.168.1.10:11311"},
            "heartbeat_timeout": 15.0,
        }):
            config = MqttRosBridge._load_config(str(config_file))
        assert config["mqtt"]["broker_host"] == "192.168.1.10"
        assert config["heartbeat_timeout"] == 15.0
        assert config["ros"]["master_uri"] == "http://192.168.1.10:11311"

    def test_load_config_empty_yaml_returns_empty(self, tmp_path: Path):
        """Non-dict YAML (e.g. empty or list) returns {}."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        with patch("yaml.safe_load", return_value=[]):
            config = MqttRosBridge._load_config(str(config_file))
        assert config == {}


# ===================================================================
# 9. TestStartupRecovery
# ===================================================================

class TestStartupRecovery:
    """Saved transmit_config subscriptions are restored as protocol messages."""

    def test_restore_subscriptions_publishes_topic_request_messages(
        self, bridge: MqttRosBridge
    ):
        bridge._load_transmit_config = MagicMock(return_value={
            "subscriptions": {
                "robot_001": [
                    {
                        "topic": "/scan",
                        "msg_type": "sensor_msgs/LaserScan",
                        "freq_limit": 5.0,
                        "transport": "mqtt_json",
                        "qos": 0,
                        "compression": {},
                    }
                ]
            }
        })
        bridge._mqtt_publish = MagicMock()

        bridge._restore_subscriptions()

        bridge._mqtt_publish.assert_called_once()
        mqtt_topic, payload = bridge._mqtt_publish.call_args[0][:2]
        message = Message.from_json(payload.decode("utf-8"))

        assert mqtt_topic == "station/topic/request"
        assert message.type == MessageType.TOPIC_REQUEST
        assert message.dst == "robot_001"
        assert message.data["action"] == "subscribe"
        assert message.data["topic"] == "/scan"
        assert message.data["msg_type"] == "sensor_msgs/LaserScan"
        assert message.data["freq_limit"] == 5.0
        assert message.data["transport"] == "mqtt_json"
        assert message.data["qos"] == 0
        assert message.data["compression"] == {}

    def test_normalize_subscriptions_accepts_legacy_mapping_format(self):
        result = MqttRosBridge._normalize_transmit_subscriptions({
            "robot_001": {
                "/scan": {"msg_type": "sensor_msgs/LaserScan"}
            }
        })

        assert result == {
            "robot_001": [
                {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"}
            ]
        }


# ===================================================================
# 10. TestMiscHelpers
# ===================================================================

class TestMiscHelpers:
    """Miscellaneous static helper methods."""

    def test_resolve_msg_data(self):
        """_resolve_msg_data parses JSON or returns raw string."""
        # Valid JSON object
        msg = MockString('{"key": "value"}')
        result = MqttRosBridge._resolve_msg_data(msg)
        assert result == {"key": "value"}

        # Non-JSON plain string
        msg = MockString("plain text")
        result = MqttRosBridge._resolve_msg_data(msg)
        assert result == "plain text"

        # Numeric value (int) — str() converts then json.loads parses
        msg = MockString(42)
        result = MqttRosBridge._resolve_msg_data(msg)
        assert result == 42

    def test_prefix_tf_frames_namespaces_regular_message_frames(
        self, bridge: MqttRosBridge
    ):
        """Bridge frame prefixing also applies to non-TF ROS messages."""
        data = {
            "header": {"frame_id": "odom"},
            "child_frame_id": "base_footprint",
        }

        bridge._prefix_tf_frames(data, "turtlebot_001")

        assert data["header"]["frame_id"] == "turtlebot_001/odom"
        assert data["child_frame_id"] == "turtlebot_001/base_footprint"

    def test_get_or_create_typed_publisher_latches_tf_static(self, bridge: MqttRosBridge):
        bridge._get_or_create_typed_publisher("/tf_static", object)

        bridge._test_rospy.Publisher.assert_called_with(
            "/tf_static",
            object,
            queue_size=10,
            latch=True,
        )

    def test_build_fleet_static_transforms_from_config(self, bridge: MqttRosBridge):
        config = {
            "enabled": True,
            "global_frame": "global_map",
            "robots": {
                "turtlebot_001": {
                    "local_root_frame": "map",
                    "pose": {
                        "x": 1.0,
                        "y": 2.0,
                        "z": 0.0,
                        "roll": 0.0,
                        "pitch": 0.0,
                        "yaw": 1.57079632679,
                    },
                },
                "turtlebot_002": {
                    "local_root_frame": "map",
                    "pose": {"x": 3.0, "y": 0.0, "z": 0.0},
                },
            },
        }

        transforms = MqttRosBridge._build_fleet_static_transforms(config)

        assert [tf.header.frame_id for tf in transforms] == ["global_map", "global_map"]
        assert [tf.child_frame_id for tf in transforms] == [
            "turtlebot_001/map",
            "turtlebot_002/map",
        ]
        assert transforms[0].transform.translation.x == 1.0
        assert transforms[0].transform.translation.y == 2.0
        assert round(transforms[0].transform.rotation.z, 6) == 0.707107
        assert round(transforms[0].transform.rotation.w, 6) == 0.707107

    def test_build_fleet_static_transforms_disabled_returns_empty(self):
        assert MqttRosBridge._build_fleet_static_transforms({"enabled": False}) == []

    def test_refresh_fleet_static_frames_reuses_broadcaster(self, bridge: MqttRosBridge):
        bridge._config["fleet_frames"] = {
            "enabled": True,
            "global_frame": "global_map",
            "robots": {
                "turtlebot_001": {
                    "local_root_frame": "map",
                    "pose": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
                "turtlebot_002": {
                    "local_root_frame": "map",
                    "pose": {"x": 2.0, "y": 0.0, "z": 0.0},
                },
            },
        }
        broadcaster = MagicMock()
        bridge._fleet_static_tf_broadcaster = broadcaster

        bridge._refresh_fleet_static_frames(None)

        broadcaster.sendTransform.assert_called_once()
        transforms = broadcaster.sendTransform.call_args[0][0]
        assert [tf.header.frame_id for tf in transforms] == ["global_map", "global_map"]
        assert [tf.child_frame_id for tf in transforms] == [
            "turtlebot_001/map",
            "turtlebot_002/map",
        ]

    def test_refresh_fleet_static_frames_includes_cached_robot_static_transforms(
        self, bridge: MqttRosBridge
    ):
        bridge._config["fleet_frames"] = {
            "enabled": True,
            "global_frame": "global_map",
            "robots": {
                "turtlebot_001": {
                    "local_root_frame": "map",
                    "pose": {"x": 0.0, "y": 0.0, "z": 0.0},
                },
            },
        }
        broadcaster = MagicMock()
        bridge._fleet_static_tf_broadcaster = broadcaster
        robot_tf = MockTransformStamped()
        robot_tf.header.frame_id = "turtlebot_001/base_link"
        robot_tf.child_frame_id = "turtlebot_001/base_scan"

        bridge._cache_robot_static_transforms("turtlebot_001", [robot_tf])
        bridge._refresh_fleet_static_frames(None)

        transforms = broadcaster.sendTransform.call_args[0][0]
        assert [tf.child_frame_id for tf in transforms] == [
            "turtlebot_001/map",
            "turtlebot_001/base_scan",
        ]
