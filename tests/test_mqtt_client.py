from __future__ import annotations

"""MqttClient 单元测试 — Mock paho.mqtt.client"""

import json
from unittest.mock import MagicMock, patch

import pytest

from protocol.messages import Message
from qt_frontend.mqtt_client import MqttClient, MqttSignals


class _FakeCallbackAPIVersion:
    VERSION2 = 2


@pytest.fixture
def mock_paho():
    with patch("paho.mqtt.client.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client_cls.CallbackAPIVersion = _FakeCallbackAPIVersion
        yield mock_client


@pytest.fixture
def client(mock_paho):
    c = MqttClient(broker_host="localhost", broker_port=1883, client_id="test_client")
    return c


# ------------------------------------------------------------------
# Test __init__
# ------------------------------------------------------------------
class TestMqttClientInit:
    def test_default_params(self):
        c = MqttClient()
        assert c._broker_host == "localhost"
        assert c._broker_port == 1883
        assert c._client_id == "qt_frontend"
        assert isinstance(c.signals, MqttSignals)
        assert c.is_connected is False

    def test_custom_params(self):
        c = MqttClient(broker_host="192.168.1.1", broker_port=9000, client_id="qt_test")
        assert c._broker_host == "192.168.1.1"
        assert c._broker_port == 9000
        assert c._client_id == "qt_test"


# ------------------------------------------------------------------
# Test connect / disconnect
# ------------------------------------------------------------------
class TestMqttConnect:
    def test_connect_creates_paho_client(self, client, mock_paho):
        client.connect()
        mock_paho.assert_called_once()

    def test_connect_sets_callbacks(self, client, mock_paho):
        client.connect()
        # on_connect, on_disconnect, on_message should be set
        mock_paho.on_connect = client._on_connect
        mock_paho.on_disconnect = client._on_disconnect
        mock_paho.on_message = client._on_message

    def test_connect_success_emits_connected(self, client, mock_paho):
        connected_signal = MagicMock()
        client.signals.connected.connect(connected_signal)

        client.connect()
        client._on_connect(mock_paho, None, None, 0, None)

        connected_signal.assert_called_once()

    def test_connect_failure_emits_error(self, client, mock_paho):
        error_signal = MagicMock()
        client.signals.connection_error.connect(error_signal)

        client.connect()
        client._on_connect(mock_paho, None, None, 5, None)

        error_signal.assert_called_once_with("5")

    def test_connect_success_subscribes_wildcards(self, client, mock_paho):
        client.connect()
        client._on_connect(mock_paho, None, None, 0, None)
        assert mock_paho.subscribe.call_count >= 5

    def test_disconnect_stops_loop(self, client, mock_paho):
        client.connect()
        client.disconnect()
        mock_paho.loop_stop.assert_called_once()


# ------------------------------------------------------------------
# Test publish / subscribe
# ------------------------------------------------------------------
class TestMqttPublish:
    def test_publish(self, client, mock_paho):
        client.connect()
        client.publish("test/topic", b"hello", qos=1)
        mock_paho.publish.assert_called_with("test/topic", b"hello", qos=1)

    def test_subscribe(self, client, mock_paho):
        client.connect()
        client.subscribe("robot/+/status", qos=1)
        mock_paho.subscribe.assert_called_with("robot/+/status", qos=1)


# ------------------------------------------------------------------
# Test on_message dispatch
# ------------------------------------------------------------------
class TestOnMessageStatus:
    def test_status_received(self, client, mock_paho):
        status_signal = MagicMock()
        client.signals.status_received.connect(status_signal)

        msg = Message(src="robot_001", type="status", data={"battery": 85.0, "mode": "auto"})
        mqtt_msg = _make_mqtt_msg("robot/robot_001/status", msg.to_json())

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        status_signal.assert_called_once()
        args = status_signal.call_args[0]
        assert args[0] == "robot_001"
        assert args[1]["battery"] == 85.0

    def test_event_received(self, client, mock_paho):
        event_signal = MagicMock()
        client.signals.event_received.connect(event_signal)

        msg = Message(src="robot_001", type="event", data={"level": "error", "code": "E1", "message": "err"})
        mqtt_msg = _make_mqtt_msg("robot/robot_001/event", msg.to_json())

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        event_signal.assert_called_once()
        assert event_signal.call_args[0][0] == "robot_001"
        assert event_signal.call_args[0][1]["code"] == "E1"

    def test_cmd_ack_received(self, client, mock_paho):
        ack_signal = MagicMock()
        client.signals.cmd_ack_received.connect(ack_signal)

        msg = Message(src="robot_001", type="cmd_ack", data={"exec_id": "abc", "result": "ok"})
        mqtt_msg = _make_mqtt_msg("robot/robot_001/cmd/ack", msg.to_json())

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        ack_signal.assert_called_once()

    def test_sensor_received(self, client, mock_paho):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        msg = Message(src="robot_001", type="sensor_data", data={"ranges": [1.0, 2.0, 3.0]})
        mqtt_msg = _make_mqtt_msg("robot/robot_001/sensor/scan", msg.to_json())

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        sensor_signal.assert_called_once()
        assert sensor_signal.call_args[0][0] == "robot_001"
        assert sensor_signal.call_args[0][1] == "scan"

    def test_sensor_received_keeps_nested_topic_path(self, client, mock_paho):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        msg = Message(
            src="robot_001",
            type="sensor_data",
            data={"_msg_type": "sensor_msgs/Imu"},
        )
        mqtt_msg = _make_mqtt_msg("robot/robot_001/sensor/imu/data", msg.to_json())

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        sensor_signal.assert_called_once()
        assert sensor_signal.call_args[0][0] == "robot_001"
        assert sensor_signal.call_args[0][1] == "imu/data"

    def test_sensor_received_accepts_raw_json_payload(self, client, mock_paho):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        mqtt_msg = _make_mqtt_msg(
            "robot/robot_001/sensor/imu/data",
            json.dumps(
                {
                    "_msg_type": "sensor_msgs/Imu",
                    "angular_velocity": {"x": 0.1},
                }
            ),
        )

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        sensor_signal.assert_called_once()
        assert sensor_signal.call_args[0][0] == "robot_001"
        assert sensor_signal.call_args[0][1] == "imu/data"
        assert sensor_signal.call_args[0][2]["_msg_type"] == "sensor_msgs/Imu"

    def test_topic_response_received(self, client, mock_paho):
        resp_signal = MagicMock()
        client.signals.topic_response_received.connect(resp_signal)

        msg = Message(src="robot_001", type="topic_resp", data={"action": "subscribe", "topic": "/odom"})
        mqtt_msg = _make_mqtt_msg("station/topic/response/robot_001", msg.to_json())

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        resp_signal.assert_called_once()
        assert resp_signal.call_args[0][0] == "robot_001"
        assert resp_signal.call_args[0][1]["topic"] == "/odom"

    def test_discover_response_received_on_station_topic_response(self, client, mock_paho):
        discover_signal = MagicMock()
        topic_signal = MagicMock()
        client.signals.discover_response_received.connect(discover_signal)
        client.signals.topic_response_received.connect(topic_signal)

        msg = Message(
            src="robot_001",
            type="discover_resp",
            data={
                "robot_id": "robot_001",
                "topics": [
                    {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"}
                ],
            },
        )
        mqtt_msg = _make_mqtt_msg("station/topic/response/robot_001", msg.to_json())

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        discover_signal.assert_called_once()
        topic_signal.assert_not_called()
        assert discover_signal.call_args[0][0] == "robot_001"
        assert discover_signal.call_args[0][1]["topics"][0]["topic"] == "/scan"

    def test_config_response_received(self, client, mock_paho):
        cfg_signal = MagicMock()
        client.signals.config_response_received.connect(cfg_signal)

        msg = Message(src="robot_001", type="config_response", data={"robot_id": "robot_001", "subscriptions": []})
        mqtt_msg = _make_mqtt_msg("station/robot_001/config/response", msg.to_json())

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        cfg_signal.assert_called_once()


# ------------------------------------------------------------------
# Test send methods
# ------------------------------------------------------------------
class TestSendMethods:
    def test_send_cmd(self, client, mock_paho):
        client.connect()
        client.send_cmd("robot_001", {"action": "velocity", "params": {"linear": 1.0}})
        mock_paho.publish.assert_called_once()
        args = mock_paho.publish.call_args[0]
        assert "robot/robot_001/cmd" in str(args[0])

    def test_send_emergency_stop(self, client, mock_paho):
        client.connect()
        client.send_emergency_stop(["robot_001", "robot_002"])
        assert mock_paho.publish.call_count == 4  # velocity + mode * 2 robots

    def test_send_discover(self, client, mock_paho):
        client.connect()
        client.send_discover()
        mock_paho.publish.assert_called_once()
        assert "station/discover" in str(mock_paho.publish.call_args[0][0])

    def test_send_config_sync(self, client, mock_paho):
        client.connect()
        client.send_config_sync("robot_001", {"subscriptions": []})
        mock_paho.publish.assert_called_once()
        assert "config/sync" in str(mock_paho.publish.call_args[0][0])

    def test_send_config_query(self, client, mock_paho):
        client.connect()
        client.send_config_query("robot_001")
        mock_paho.publish.assert_called_once()
        assert "config/query" in str(mock_paho.publish.call_args[0][0])


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _make_mqtt_msg(topic: str, payload: str):
    m = MagicMock()
    m.topic = topic
    m.payload = payload.encode("utf-8")
    return m
