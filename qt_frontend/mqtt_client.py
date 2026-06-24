from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt
from PyQt5.QtCore import QObject, pyqtSignal

from protocol.messages import Message, MessageFactory
from protocol.topics import (
    all_robot_cmd_ack,
    all_robot_event,
    all_robot_status,
    parse_robot_topic,
    parse_station_topic,
    robot_cmd,
    station_config_query,
    station_config_sync,
    station_discover,
    station_topic_request,
)

logger = logging.getLogger(__name__)


class MqttSignals(QObject):
    """MQTT 事件 Signal 集合 — 主线程创建，paho 回调 emit"""

    connected = pyqtSignal()
    disconnected = pyqtSignal()
    connection_error = pyqtSignal(str)
    message_received = pyqtSignal(str, object)  # (mqtt_topic, Message)

    status_received = pyqtSignal(str, dict)  # (robot_id, status_data)
    event_received = pyqtSignal(str, dict)  # (robot_id, event_data)
    cmd_ack_received = pyqtSignal(str, dict)  # (robot_id, ack_data)
    sensor_data_received = pyqtSignal(str, str, object)  # (robot_id, sensor_name, payload)
    topic_response_received = pyqtSignal(str, dict)  # (robot_id, response_data)
    config_response_received = pyqtSignal(str, dict)  # (robot_id, config_data)
    discover_response_received = pyqtSignal(str, dict)  # (robot_id, response_data)


class MqttClient:
    """线程安全 MQTT 客户端 — paho 回调 emit Qt Signal，不直接操作 UI"""

    _LARGE_SENSOR_PAYLOAD_BYTES = 128 * 1024
    _LARGE_SENSOR_MSG_TYPES = {
        "map": "nav_msgs/OccupancyGrid",
    }
    _IGNORED_SENSOR_TOPICS = frozenset({"tf", "tf_static"})

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        client_id: str = "qt_frontend",
    ) -> None:
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._client_id = client_id
        self._client: Optional[mqtt.Client] = None
        self._factory: Optional[MessageFactory] = None
        self.signals = MqttSignals()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def connect(self) -> None:
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=self._client_id,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

        try:
            self._client.connect(self._broker_host, self._broker_port)
            self._client.loop_start()
            logger.info(
                f"[MqttClient] Connecting to {self._broker_host}:{self._broker_port}"
            )
        except Exception as e:
            logger.error(f"[MqttClient] Connection failed: {e}")
            self.signals.connection_error.emit(str(e))

    def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            logger.info("[MqttClient] Disconnected")

    def subscribe(self, topic: str, qos: int = 1) -> None:
        if self._client:
            self._client.subscribe(topic, qos=qos)

    def publish(self, topic: str, payload: bytes, qos: int = 1) -> None:
        if self._client:
            self._client.publish(topic, payload, qos=qos)

    def send_discover(self) -> None:
        msg = Message(
            src=self._client_id,
            dst="broadcast",
            type="discover",
            data={"request_id": ""},
        )
        self.publish(station_discover(), msg.to_json().encode("utf-8"), qos=1)

    def send_cmd(self, robot_id: str, cmd_data: Dict[str, Any]) -> None:
        msg = Message(
            src=self._client_id,
            dst=robot_id,
            type="cmd",
            data=cmd_data,
        )
        self.publish(robot_cmd(robot_id), msg.to_json().encode("utf-8"), qos=1)

    def send_topic_request(self, robot_id: str, req_data: Dict[str, Any]) -> None:
        msg = Message(
            src=self._client_id,
            dst=robot_id,
            type="topic_request",
            data=req_data,
        )
        self.publish(
            station_topic_request(), msg.to_json().encode("utf-8"), qos=1
        )

    def send_emergency_stop(self, robot_ids: list) -> None:
        for robot_id in robot_ids:
            self.send_cmd(
                robot_id,
                {
                    "action": "velocity",
                    "params": {"linear": 0.0, "angular": 0.0},
                },
            )
            self.send_cmd(
                robot_id,
                {"action": "mode", "params": {"mode": "stop"}},
            )

    def send_config_sync(self, robot_id: str, config_data: Dict[str, Any]) -> None:
        msg = Message(
            src=self._client_id,
            dst=robot_id,
            type="config_sync",
            data=config_data,
        )
        self.publish(
            station_config_sync(robot_id), msg.to_json().encode("utf-8"), qos=1
        )

    def send_config_query(self, robot_id: str) -> None:
        msg = Message(
            src=self._client_id,
            dst=robot_id,
            type="config_query",
            data={"robot_id": robot_id},
        )
        self.publish(
            station_config_query(robot_id), msg.to_json().encode("utf-8"), qos=1
        )

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected()

    # ------------------------------------------------------------------
    # paho 回调（在 paho 网络线程执行，只 emit Signal）
    # ------------------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        rc_val = reason_code if isinstance(reason_code, int) else getattr(reason_code, "value", -1)
        if rc_val == 0:
            logger.info("[MqttClient] Connected to broker")
            client.subscribe(all_robot_status(), qos=1)
            client.subscribe(all_robot_event(), qos=1)
            client.subscribe(all_robot_cmd_ack(), qos=1)
            client.subscribe("robot/+/sensor/#", qos=0)
            client.subscribe("station/topic/response/+", qos=1)
            client.subscribe("station/+/config/response", qos=1)
            self.signals.connected.emit()
        else:
            logger.error(f"[MqttClient] Connection failed: rc={rc_val}")
            self.signals.connection_error.emit(str(rc_val))

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        rc_val = reason_code if isinstance(reason_code, int) else getattr(reason_code, "value", 0)
        if rc_val != 0:
            logger.warning(f"[MqttClient] Unexpected disconnect (rc={rc_val})")
        self.signals.disconnected.emit()

    def _on_message(self, client, userdata, msg) -> None:
        try:
            robot_info = parse_robot_topic(msg.topic)
            if robot_info and robot_info.get("type") == "sensor_binary":
                logger.debug(
                    "[MqttClient] Ignoring binary sensor payload on %s (%d bytes)",
                    msg.topic,
                    len(msg.payload),
                )
                return
            if robot_info and robot_info.get("type") == "sensor":
                sensor_name = robot_info.get("name", "")
                if self._should_ignore_sensor_payload(sensor_name):
                    logger.debug(
                        "[MqttClient] Ignoring high-frequency sensor payload on %s",
                        msg.topic,
                    )
                    return
                if self._should_summarize_sensor_payload(sensor_name, msg.payload):
                    message = Message(
                        src=robot_info.get("robot_id", ""),
                        dst=self._client_id,
                        type="sensor_data",
                        data=self._large_sensor_payload_summary(
                            sensor_name,
                            msg.payload,
                        ),
                    )
                    self.signals.message_received.emit(msg.topic, message)
                    self._dispatch(msg.topic, message)
                    return

                payload_str = msg.payload.decode("utf-8")
                payload = json.loads(payload_str)
                message = (
                    Message.from_dict(payload)
                    if isinstance(payload, dict) and "type" in payload and "data" in payload
                    else Message(
                        src=robot_info.get("robot_id", ""),
                        dst=self._client_id,
                        type="sensor_data",
                        data=payload if isinstance(payload, dict) else {"raw": payload},
                    )
                )
                self.signals.message_received.emit(msg.topic, message)
                self._dispatch(msg.topic, message)
                return

            payload_str = msg.payload.decode("utf-8")
            message = Message.from_json(payload_str)
            self.signals.message_received.emit(msg.topic, message)

            self._dispatch(msg.topic, message)
        except Exception as e:
            logger.error(f"[MqttClient] Failed to handle message on {msg.topic}: {e}")

    def _should_ignore_sensor_payload(self, sensor_name: str) -> bool:
        normalized = sensor_name.strip().lstrip("/")
        return normalized in self._IGNORED_SENSOR_TOPICS

    def _should_summarize_sensor_payload(self, sensor_name: str, payload: bytes) -> bool:
        normalized = sensor_name.strip().lstrip("/")
        return (
            normalized in self._LARGE_SENSOR_MSG_TYPES
            and len(payload) >= self._LARGE_SENSOR_PAYLOAD_BYTES
        )

    def _large_sensor_payload_summary(
        self,
        sensor_name: str,
        payload: bytes,
    ) -> Dict[str, Any]:
        normalized = sensor_name.strip().lstrip("/")
        return {
            "_msg_type": self._LARGE_SENSOR_MSG_TYPES.get(normalized, "custom/LargePayload"),
            "_payload_skipped": True,
            "_payload_bytes": len(payload),
        }

    def _dispatch(self, mqtt_topic: str, message: Message) -> None:
        robot_info = parse_robot_topic(mqtt_topic)
        if robot_info:
            robot_type = robot_info["type"]
            robot_id = robot_info["robot_id"]

            if robot_type == "status":
                self.signals.status_received.emit(robot_id, message.data)
            elif robot_type == "event":
                self.signals.event_received.emit(robot_id, message.data)
            elif robot_type == "cmd_ack":
                self.signals.cmd_ack_received.emit(robot_id, message.data)
            elif robot_type == "sensor":
                sensor_name = robot_info.get("name", "")
                self.signals.sensor_data_received.emit(robot_id, sensor_name, message.data)
            return

        station_info = parse_station_topic(mqtt_topic)
        if station_info:
            stype = station_info["type"]

            if stype == "topic_response":
                robot_id = station_info.get("robot_id", "")
                if message.type == "discover_resp":
                    self.signals.discover_response_received.emit(robot_id, message.data)
                else:
                    self.signals.topic_response_received.emit(robot_id, message.data)
            elif stype == "config_response":
                robot_id = station_info.get("robot_id", "")
                self.signals.config_response_received.emit(robot_id, message.data)
            elif stype == "discover":
                pass
            return

        logger.debug(f"[MqttClient] Unrecognized topic: {mqtt_topic}")
