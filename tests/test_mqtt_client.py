from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from protocol.messages import Message
from qt_frontend.mqtt_client import MqttClient, MqttSignals

# MqttClient 单元测试 — Mock paho.mqtt.client


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
        assert client._client is mock_paho

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

    def test_connect_success_subscribes_message_schema_responses(
        self,
        client,
        mock_paho,
    ):
        client.connect()
        client._on_connect(mock_paho, None, None, 0, None)

        mock_paho.subscribe.assert_any_call(
            "station/+/message_schema/response",
            qos=1,
        )

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

    def test_traffic_totals_count_received_and_sent_payload_bytes(
        self,
        client,
        mock_paho,
    ):
        client.connect()
        client.publish("test/topic", b"hello", qos=1)
        message = Message(
            src="robot_001",
            type="status",
            data={"battery": 85.0},
        )
        mqtt_msg = _make_mqtt_msg(
            "robot/robot_001/status",
            message.to_json(),
        )

        client._on_message(mock_paho, None, mqtt_msg)

        assert client.traffic_totals() == (len(mqtt_msg.payload), 5)

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

        msg = Message(
            src="robot_001",
            type="event",
            data={"level": "error", "code": "E1", "message": "err"},
        )
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

    def test_sensor_meta_emits_traffic_metadata_without_sensor_data(self, client, mock_paho):
        sensor_received = []
        meta_received = []
        messages = []
        client.signals.sensor_data_received.connect(
            lambda robot_id, sensor_name, data: sensor_received.append(
                (robot_id, sensor_name, data)
            )
        )
        client.signals.sensor_meta_received.connect(
            lambda robot_id, sensor_name, data: meta_received.append(
                (robot_id, sensor_name, data)
            )
        )
        client.signals.message_received.connect(
            lambda topic, message: messages.append((topic, message))
        )

        payload = json.dumps({
            "type": "sensor_meta",
            "data": {
                "topic": "/velodyne_points",
                "msg_type": "sensor_msgs/PointCloud2",
                "transport": "http_stream",
                "stream_url": "http://robot:8080/stream/velodyne_points",
                "payload_size": 512374,
            },
        }).encode("utf-8")

        msg = MagicMock()
        msg.topic = "robot/robot_001/sensor/velodyne_points/meta"
        msg.payload = payload

        client._on_message(None, None, msg)

        assert sensor_received == []
        assert meta_received == [
            (
                "robot_001",
                "velodyne_points",
                {
                    "topic": "/velodyne_points",
                    "msg_type": "sensor_msgs/PointCloud2",
                    "transport": "http_stream",
                    "stream_url": "http://robot:8080/stream/velodyne_points",
                    "payload_size": 512374,
                },
            )
        ]
        assert messages[0][0] == "robot/robot_001/sensor/velodyne_points/meta"
        assert messages[0][1].type == "sensor_meta"

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

    def test_large_occupancy_grid_payload_is_summarized_without_json_decode(
        self, client, mock_paho
    ):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        mqtt_msg = MagicMock()
        mqtt_msg.topic = "robot/robot_001/sensor/map"
        mqtt_msg.payload = b'{"_msg_type":"nav_msgs/OccupancyGrid","data":[' + (
            b"0," * 200000
        ) + b"0]}"

        client.connect()
        with patch("qt_frontend.mqtt_client.json.loads") as mock_loads:
            client._on_message(mock_paho, None, mqtt_msg)

        mock_loads.assert_not_called()
        sensor_signal.assert_called_once()
        assert sensor_signal.call_args[0][0] == "robot_001"
        assert sensor_signal.call_args[0][1] == "map"
        assert sensor_signal.call_args[0][2] == {
            "_msg_type": "nav_msgs/OccupancyGrid",
            "_payload_skipped": True,
            "_payload_bytes": len(mqtt_msg.payload),
        }

    def test_binary_sensor_payload_is_not_json_decoded(self, client, mock_paho):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        mqtt_msg = MagicMock()
        mqtt_msg.topic = "robot/robot_001/sensor/scan/bin"
        mqtt_msg.payload = b"\x00\x01binary-payload"

        client.connect()
        with patch("qt_frontend.mqtt_client.json.loads") as mock_loads, \
                patch("qt_frontend.mqtt_client.Message.from_json") as mock_from_json:
            client._on_message(mock_paho, None, mqtt_msg)

        mock_loads.assert_not_called()
        mock_from_json.assert_not_called()
        sensor_signal.assert_not_called()

    def test_tf_sensor_payload_is_ignored_without_json_decode(self, client, mock_paho):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        mqtt_msg = _make_mqtt_msg(
            "robot/robot_001/sensor/tf",
            json.dumps(
                {
                    "binary": True,
                    "msg_type": "tf2_msgs/TFMessage",
                    "encoding": "tf_message_ros1_v1",
                }
            ),
        )

        client.connect()
        with patch("qt_frontend.mqtt_client.json.loads") as mock_loads, \
                patch("qt_frontend.mqtt_client.Message.from_json") as mock_from_json:
            client._on_message(mock_paho, None, mqtt_msg)

        mock_loads.assert_not_called()
        mock_from_json.assert_not_called()
        sensor_signal.assert_called_once()
        assert sensor_signal.call_args[0][0] == "robot_001"
        assert sensor_signal.call_args[0][1] == "tf"
        assert sensor_signal.call_args[0][2] == {
            "_msg_type": "tf2_msgs/TFMessage",
            "_payload_skipped": True,
            "_payload_bytes": len(mqtt_msg.payload),
            "_traffic_only": True,
        }

    def test_tf_static_sensor_payload_is_ignored_without_json_decode(
        self, client, mock_paho
    ):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        mqtt_msg = _make_mqtt_msg(
            "robot/robot_001/sensor/tf_static",
            json.dumps(
                {
                    "binary": True,
                    "msg_type": "tf2_msgs/TFMessage",
                    "encoding": "ros1_serialized_v1",
                }
            ),
        )

        client.connect()
        with patch("qt_frontend.mqtt_client.json.loads") as mock_loads, \
                patch("qt_frontend.mqtt_client.Message.from_json") as mock_from_json:
            client._on_message(mock_paho, None, mqtt_msg)

        mock_loads.assert_not_called()
        mock_from_json.assert_not_called()
        sensor_signal.assert_called_once()
        assert sensor_signal.call_args[0][0] == "robot_001"
        assert sensor_signal.call_args[0][1] == "tf_static"
        assert sensor_signal.call_args[0][2]["_payload_bytes"] == len(mqtt_msg.payload)
        assert sensor_signal.call_args[0][2]["_traffic_only"] is True

    def test_retained_sensor_payload_is_ignored_for_live_traffic(
        self, client, mock_paho
    ):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        mqtt_msg = _make_mqtt_msg(
            "robot/turtlebot_001/sensor/tf_static",
            json.dumps(
                {
                    "binary": True,
                    "msg_type": "tf2_msgs/TFMessage",
                    "encoding": "ros1_serialized_v1",
                }
            ),
        )
        mqtt_msg.retain = True

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        sensor_signal.assert_not_called()

    def test_serialized_odom_envelope_is_summarized_but_bin_payload_is_ignored(
        self, client, mock_paho
    ):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        envelope_msg = _make_mqtt_msg(
            "robot/robot_001/sensor/odom",
            json.dumps(
                {
                    "binary": True,
                    "topic": "/odom",
                    "msg_type": "nav_msgs/Odometry",
                    "encoding": "ros1_serialized_v1",
                    "payload_format": "ros1_serialized",
                    "payload_size": 128,
                }
            ),
        )
        bin_msg = MagicMock()
        bin_msg.topic = "robot/robot_001/sensor/odom/bin"
        bin_msg.payload = b"\x00\x01serialized"

        client.connect()
        client._on_message(mock_paho, None, envelope_msg)
        client._on_message(mock_paho, None, bin_msg)

        assert sensor_signal.call_count == 1
        assert sensor_signal.call_args[0][2]["msg_type"] == "nav_msgs/Odometry"

    def test_serialized_nested_envelope_uses_ros_topic_as_sensor_name(
        self, client, mock_paho
    ):
        sensor_signal = MagicMock()
        client.signals.sensor_data_received.connect(sensor_signal)

        envelope_msg = _make_mqtt_msg(
            "robot/robot_001/sensor/hdl_graph_slam_odom",
            json.dumps(
                {
                    "binary": True,
                    "topic": "/hdl_graph_slam/odom",
                    "msg_type": "nav_msgs/Odometry",
                    "encoding": "ros1_serialized_v1",
                    "payload_format": "ros1_serialized",
                    "payload_size": 128,
                    "transport": "mqtt_binary",
                }
            ),
        )

        client.connect()
        client._on_message(mock_paho, None, envelope_msg)

        sensor_signal.assert_called_once()
        assert sensor_signal.call_args[0][0] == "robot_001"
        assert sensor_signal.call_args[0][1] == "hdl_graph_slam/odom"

    def test_topic_response_received(self, client, mock_paho):
        resp_signal = MagicMock()
        client.signals.topic_response_received.connect(resp_signal)

        msg = Message(
            src="robot_001",
            type="topic_resp",
            data={"action": "subscribe", "topic": "/odom"},
        )
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

        msg = Message(
            src="robot_001",
            type="config_response",
            data={"robot_id": "robot_001", "subscriptions": []},
        )
        mqtt_msg = _make_mqtt_msg("station/robot_001/config/response", msg.to_json())

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        cfg_signal.assert_called_once()

    def test_message_schema_response_received(self, client, mock_paho):
        schema_signal = MagicMock()
        client.signals.schema_response_received.connect(schema_signal)
        data = {
            "request_id": "req-1",
            "msg_type": "geometry_msgs/Twist",
            "result": "ok",
            "schema": {
                "type": "geometry_msgs/Twist",
                "kind": "message",
                "fields": [],
            },
            "error": "",
        }
        msg = Message(
            src="robot_001",
            type="message_schema_response",
            data=data,
        )
        mqtt_msg = _make_mqtt_msg(
            "station/robot_001/message_schema/response",
            msg.to_json(),
        )

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        schema_signal.assert_called_once_with("robot_001", data)

    def test_message_schema_response_topic_rejects_wrong_message_type(
        self,
        client,
        mock_paho,
    ):
        schema_signal = MagicMock()
        client.signals.schema_response_received.connect(schema_signal)
        msg = Message(
            src="robot_001",
            type="config_response",
            data={"request_id": "req-1"},
        )
        mqtt_msg = _make_mqtt_msg(
            "station/robot_001/message_schema/response",
            msg.to_json(),
        )

        client.connect()
        client._on_message(mock_paho, None, mqtt_msg)

        schema_signal.assert_not_called()


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

    def test_send_cmd_preserves_caller_exec_id(self, client, mock_paho):
        client.connect()

        client.send_cmd(
            "robot_001",
            {
                "action": "custom",
                "params": {"topic": "/control", "data": {"enabled": True}},
                "exec_id": "exec-1",
            },
        )

        payload = mock_paho.publish.call_args.args[1]
        message = Message.from_json(payload.decode("utf-8"))
        assert message.data["exec_id"] == "exec-1"

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

    def test_send_message_schema_query_uses_target_topic(self, client, mock_paho):
        client.connect()

        client.send_message_schema_query(
            "r1",
            "req-1",
            "geometry_msgs/Twist",
        )

        topic, payload = mock_paho.publish.call_args.args[:2]
        message = Message.from_json(payload.decode("utf-8"))
        assert topic == "station/r1/message_schema/query"
        assert message.type == "message_schema_query"
        assert message.dst == "r1"
        assert message.data == {
            "request_id": "req-1",
            "msg_type": "geometry_msgs/Twist",
        }


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------
def _make_mqtt_msg(topic: str, payload: str):
    m = MagicMock()
    m.topic = topic
    m.payload = payload.encode("utf-8")
    return m
