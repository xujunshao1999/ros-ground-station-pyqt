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
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

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


@pytest.fixture
def bridge():
    """Create an MqttRosBridge instance with a mocked config loader.

    The bridge is created with ``_running = True`` so heartbeat-related
    methods can operate without needing a full ``start()`` call.
    """
    with patch.object(MqttRosBridge, "_load_config", return_value=_TEST_CONFIG):
        br = MqttRosBridge()
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
# 9. TestMiscHelpers
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
