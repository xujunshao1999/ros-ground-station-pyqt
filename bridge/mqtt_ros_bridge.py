from __future__ import annotations

"""
MQTT-ROS Bridge — bidirectional translation between MQTT and ROS

The bridge runs as a ROS node on the ground station Linux machine,
translating between MQTT (robot communication) and ROS (Foxglove
visualization and control).

Architecture overview:

  MQTT → ROS (6 channels):
    1. robot/+/sensor/#   → dict_to_ros_msg() → /{robot_id}/{ros_topic}
    2. robot/+/status     → RobotState cache  → /station/robot_list (aggregated JSON)
    3. robot/+/event      → forward           → /{robot_id}/event
    4. robot/+/cmd/ack    → forward           → /{robot_id}/cmd_ack
    5. station/topic/response/+ → update _topic_map → /{robot_id}/topic_response
    6. (discover responses)  → internal RobotState.available_topics only

  ROS → MQTT (6 channels):
    1. /station/topic_request              → station/topic/request
    2. /station/config_sync                → station/config/sync + write local YAML
    3. /station/discover                   → station/discover
    4. /cmd/command                        → robot/{id}/cmd
    5. /station/config_query               → /station/config_response (no MQTT)
    6. /station/available_topics_query     → /{robot_id}/available_topics (no MQTT)
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt
import rospy
import yaml
from std_msgs.msg import String

from protocol.messages import Message, MessageType, TopicResponseResult
from protocol.topics import (
    robot_cmd,
    station_discover,
    station_topic_request,
    parse_robot_topic,
)
from bridge.dict_to_ros_msg import dict_to_ros_msg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------


@dataclass
class RobotState:
    """Runtime state for a single tracked robot."""

    robot_id: str
    online: bool = True
    last_seen: float = 0.0  # time.monotonic() timestamp
    status: dict = field(default_factory=dict)
    available_topics: list = field(default_factory=list)
    subscriptions: dict = field(default_factory=dict)
    # subscriptions: {ros_topic: {msg_type: str, freq_limit: float, ...}}


# ---------------------------------------------------------------------------
# Main bridge class
# ---------------------------------------------------------------------------


class MqttRosBridge:
    """Main MQTT-ROS bidirectional bridge.

    Usage:
        bridge = MqttRosBridge()
        bridge.start()   # blocks via rospy.spin()
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._lock = threading.Lock()
        self._publishers_lock = threading.Lock()
        self._robots: Dict[str, RobotState] = {}
        # _topic_map: {robot_id: {sensor_name: (ros_topic, msg_type)}}
        self._topic_map: Dict[str, Dict[str, Tuple[str, str]]] = {}
        self._mqtt_client: Optional[mqtt.Client] = None
        self._running = False

        # ROS publishers created lazily
        self._ros_publishers: Dict[str, rospy.Publisher] = {}
        self._ros_subscribers: List[rospy.Subscriber] = []
        self._publisher_ready_topics: set[str] = set()

        # Resolve config paths
        self._bridge_dir = Path(__file__).resolve().parent

        if config_path is None:
            config_path = str(self._bridge_dir / "bridge_config.yaml")
        self._config = self._load_config(config_path)

        # Resolve transmit config path (relative to foxglove/config/)
        tx_rel = self._config.get("transmit_config_path", "../config/transmit_config.yaml")
        tx_candidate = self._bridge_dir.parent / tx_rel
        self._transmit_config_path = str(tx_candidate)

        self._heartbeat_timeout = float(self._config.get("heartbeat_timeout", 30.0))
        self._namespace_tf_frames = bool(
            self._config.get("ros", {}).get("namespace_tf_frames", False)
        )

    # ================================================================
    # Public API
    # ================================================================

    def start(self) -> None:
        """Start the bridge. Blocks via rospy.spin()."""
        logger.info("[Bridge] Starting MQTT-ROS Bridge...")
        self._running = True

        # 1. Initialize ROS node FIRST (MQTT messages will need rospy)
        self._init_ros()

        # 2. Connect MQTT and subscribe to wildcard topics
        self._init_mqtt()

        # 3. Send discover to find online robots
        self._send_discover()

        # 4-5. Load transmit config and restore previous subscriptions
        self._restore_subscriptions()

        # 6. Start heartbeat monitoring
        self._start_heartbeat_monitor()

        logger.info("[Bridge] Bridge is running. Entering ROS spin...")
        try:
            rospy.spin()
        except KeyboardInterrupt:
            logger.info("[Bridge] Interrupted by user")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the bridge cleanly."""
        logger.info("[Bridge] Stopping...")
        self._running = False

        if self._mqtt_client is not None:
            self._mqtt_client.loop_stop()
            self._mqtt_client.disconnect()

        # Unregister ROS subscribers
        for sub in self._ros_subscribers:
            sub.unregister()
        self._ros_subscribers.clear()
        self._ros_publishers.clear()

        logger.info("[Bridge] Stopped")

    # ================================================================
    # Configuration loading
    # ================================================================

    @staticmethod
    def _load_config(config_path: str) -> dict:
        """Load YAML configuration file, returning defaults on failure."""
        p = Path(config_path)
        if not p.exists():
            logger.warning("Config file not found: %s, using defaults", config_path)
            return {
                "mqtt": {
                    "broker_host": "localhost",
                    "broker_port": 1883,
                    "client_id": "mqtt_ros_bridge",
                },
                "ros": {
                    "master_uri": "http://localhost:11311",
                    "node_name": "mqtt_ros_bridge",
                    "max_update_frequency": 30.0,
                },
                "heartbeat_timeout": 30.0,
                "transmit_config_path": "../config/transmit_config.yaml",
            }
        try:
            with open(p, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                return loaded if isinstance(loaded, dict) else {}
        except Exception as e:
            logger.error("Failed to load config %s: %s", config_path, e)
            return {}

    # ================================================================
    # MQTT initialization
    # ================================================================

    def _init_mqtt(self) -> None:
        """Initialize MQTT client and connect to broker."""
        mqtt_config = self._config.get("mqtt", {})
        broker_host = mqtt_config.get("broker_host", "localhost")
        broker_port = mqtt_config.get("broker_port", 1883)
        client_id = mqtt_config.get("client_id", "mqtt_ros_bridge")

        self._mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )
        self._mqtt_client.on_connect = self._on_mqtt_connect
        self._mqtt_client.on_message = self._on_mqtt_message
        self._mqtt_client.on_disconnect = self._on_mqtt_disconnect
        self._mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

        try:
            self._mqtt_client.connect(broker_host, broker_port)
            self._mqtt_client.loop_start()
            logger.info(
                "[Bridge] MQTT connected to %s:%s", broker_host, broker_port
            )
        except Exception as e:
            logger.error("[Bridge] MQTT connection failed: %s", e)

    # ================================================================
    # ROS initialization
    # ================================================================

    def _init_ros(self) -> None:
        """Initialize ROS node and set up ROS subscribers (ROS ---> MQTT)."""
        ros_config = self._config.get("ros", {})
        master_uri = ros_config.get("master_uri", "http://localhost:11311")
        node_name = ros_config.get("node_name", "mqtt_ros_bridge")

        os.environ["ROS_MASTER_URI"] = master_uri

        rospy.init_node(node_name, anonymous=False, disable_signals=True)

        # Subscribers: each ROS topic forwards to MQTT
        self._ros_subscribers = [
            rospy.Subscriber(
                "/station/topic_request", String, self._on_topic_request
            ),
            rospy.Subscriber(
                "/station/config_sync", String, self._on_config_sync
            ),
            rospy.Subscriber(
                "/station/discover", String, self._on_discover_request
            ),
            rospy.Subscriber(
                "/cmd/command", String, self._on_cmd_command
            ),
            rospy.Subscriber(
                "/station/config_query", String, self._on_config_query
            ),
            rospy.Subscriber(
                "/station/available_topics_query",
                String,
                self._on_available_topics_query,
            ),
        ]

        logger.info(
            "[Bridge] ROS node '%s' initialized, master URI: %s",
            node_name,
            master_uri,
        )

    # ================================================================
    # ROS Publisher helpers
    # ================================================================

    def _get_or_create_string_publisher(
        self, topic: str
    ) -> rospy.Publisher:
        """Get or create a ROS ``std_msgs/String`` publisher."""
        key = f"string::{topic}"
        with self._publishers_lock:
            if key not in self._ros_publishers:
                self._ros_publishers[key] = rospy.Publisher(
                    topic, String, queue_size=10
                )
            return self._ros_publishers[key]

    def _get_or_create_typed_publisher(
        self, topic: str, msg_class: type
    ) -> rospy.Publisher:
        """Get or create a typed ROS publisher."""
        key = f"{msg_class.__name__}::{topic}"
        with self._publishers_lock:
            if key not in self._ros_publishers:
                self._ros_publishers[key] = rospy.Publisher(
                    topic, msg_class, queue_size=10
                )
            return self._ros_publishers[key]

    def _wait_for_publisher_connection(
        self, topic: str, pub: rospy.Publisher, timeout: float = 0.5
    ) -> None:
        """Give new ROS publishers a short window to connect to subscribers."""
        if topic in self._publisher_ready_topics:
            return

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not rospy.is_shutdown():
            if pub.get_num_connections() > 0:
                break
            time.sleep(0.02)

        self._publisher_ready_topics.add(topic)

    # ================================================================
    # MQTT callbacks
    # ================================================================

    def _on_mqtt_connect(
        self, client, userdata, flags, reason_code, properties
    ) -> None:
        """Subscribe to MQTT wildcard topics on (re-)connect."""
        rc_val = (
            reason_code
            if isinstance(reason_code, int)
            else getattr(reason_code, "value", 1)
        )
        if rc_val == 0:
            logger.info("[Bridge] MQTT connected to broker")

            client.subscribe("robot/+/sensor/#", qos=0)
            client.subscribe("robot/+/status", qos=1)
            client.subscribe("robot/+/event", qos=1)
            client.subscribe("robot/+/cmd/ack", qos=1)
            client.subscribe("station/topic/response/+", qos=1)

            # Recover state after reconnect
            self._send_discover()
            self._restore_subscriptions()
        else:
            logger.error("[Bridge] MQTT connection failed: %s", rc_val)

    def _on_mqtt_disconnect(
        self, client, userdata, flags, reason_code, properties
    ) -> None:
        """Log unexpected disconnects."""
        rc_val = (
            reason_code
            if isinstance(reason_code, int)
            else getattr(reason_code, "value", 0)
        )
        if rc_val != 0:
            logger.warning(
                "[Bridge] MQTT disconnected (rc=%s). Reconnecting...", rc_val
            )

    def _on_mqtt_message(self, client, userdata, msg) -> None:
        """Route incoming MQTT messages to the correct handler."""
        topic = msg.topic
        try:
            # Station-level responses arrive without robot/{id} prefix
            if topic.startswith("station/topic/response/"):
                self._handle_station_response(topic, msg.payload)
                return

            # Robot-level topics via parse_robot_topic
            parsed = parse_robot_topic(topic)
            if parsed is None:
                logger.debug("[Bridge] Unrecognised MQTT topic: %s", topic)
                return

            msg_type = parsed.get("type", "")
            robot_id = parsed.get("robot_id", "")

            if msg_type == "sensor":
                sensor_name = parsed.get("name", "")
                self._handle_sensor_data(robot_id, sensor_name, msg.payload)
            elif msg_type == "sensor_meta":
                sensor_name = parsed.get("name", "")
                self._handle_sensor_meta(robot_id, sensor_name, msg.payload)
            elif msg_type == "status":
                self._handle_status(robot_id, msg.payload)
            elif msg_type == "event":
                self._handle_event(robot_id, msg.payload)
            elif msg_type == "cmd_ack":
                self._handle_cmd_ack(robot_id, msg.payload)
            else:
                logger.debug(
                    "[Bridge] Unhandled MQTT message type: %s", msg_type
                )
        except Exception as e:
            logger.error(
                "[Bridge] Error handling MQTT message on %s: %s", topic, e
            )

    # ================================================================
    # MQTT ---> ROS: station/topic/response/+ (incl. discover responses)
    # ================================================================

    def _handle_station_response(
        self, topic: str, payload: bytes
    ) -> None:
        """Dispatch station/topic/response/+ to the correct sub-handler.

        This topic receives both ``topic_response`` and ``discover_resp``
        messages; the ``Message.type`` field distinguishes them.
        """
        parts = topic.split("/")
        robot_id = parts[-1] if len(parts) >= 3 else ""

        try:
            text = payload.decode("utf-8")
            message = Message.from_json(text)
        except Exception as e:
            logger.error(
                "[Bridge] Failed to decode station response: %s", e
            )
            return

        if message.type == MessageType.DISCOVER_RESPONSE:
            self._handle_discover_response(robot_id, message)
        elif message.type == MessageType.TOPIC_RESPONSE:
            self._handle_topic_response(robot_id, message)
        else:
            logger.debug(
                "[Bridge] Unknown station response type: %s", message.type
            )

    def _handle_discover_response(
        self, robot_id: str, message: Message
    ) -> None:
        """Update robot state with available topics from a discover response."""
        data = message.data if isinstance(message.data, dict) else {}
        topics = data.get("topics", [])

        with self._lock:
            if robot_id not in self._robots:
                self._robots[robot_id] = RobotState(robot_id=robot_id)
            self._robots[robot_id].available_topics = topics
            self._robots[robot_id].last_seen = time.monotonic()
            self._robots[robot_id].online = True

        logger.info(
            "[Bridge] Discover response from %s: %d topics available",
            robot_id,
            len(topics),
        )

    def _handle_topic_response(
        self, robot_id: str, message: Message
    ) -> None:
        """Process topic_response: update _topic_map and forward to ROS."""
        data = message.data if isinstance(message.data, dict) else {}
        action = data.get("action", "")
        result = data.get("result", "")
        ros_topic_str = data.get("topic", "")
        msg_type = data.get("msg_type", "")

        # Always forward the raw response to ROS
        self._publish_as_json(
            f"/{robot_id}/topic_response",
            message.to_json(),
        )

        if action == "subscribe" and result == TopicResponseResult.OK.value:
            sensor_name = ros_topic_str.lstrip("/").replace("/", "_")
            with self._lock:
                if robot_id not in self._topic_map:
                    self._topic_map[robot_id] = {}
                self._topic_map[robot_id][sensor_name] = (
                    ros_topic_str,
                    msg_type,
                )

                # Update subscriptions in RobotState
                if robot_id in self._robots:
                    freq = data.get("freq_limit", 0.0)
                    self._robots[robot_id].subscriptions[ros_topic_str] = {
                        "msg_type": msg_type,
                        "freq_limit": freq,
                    }

            logger.info(
                "[Bridge] Topic map updated: %s/%s -> %s (%s)",
                robot_id,
                sensor_name,
                ros_topic_str,
                msg_type,
            )
        elif (
            action == "unsubscribe"
            and result == TopicResponseResult.OK.value
        ):
            sensor_name = ros_topic_str.lstrip("/").replace("/", "_")
            with self._lock:
                if robot_id in self._topic_map:
                    self._topic_map[robot_id].pop(sensor_name, None)
                if robot_id in self._robots:
                    self._robots[robot_id].subscriptions.pop(
                        ros_topic_str, None
                    )

    # ================================================================
    # MQTT ---> ROS: sensor data
    # ================================================================

    # Special sensor names that publish to canonical ROS topics
    # (RViz and standard tools subscribe to these, not /{robot_id}/...)
    _CANONICAL_TOPICS = frozenset({"tf", "tf_static", "joint_states"})

    def _handle_sensor_data(
        self, robot_id: str, sensor_name: str, payload: bytes
    ) -> None:
        """Decode sensor data and publish to ROS.

        Payload is expected to be a JSON dict of ROS message fields
        (LIGHT transport tier).  The topic map provides the target ROS
        topic and message type; when no mapping exists, the ``_msg_type``
        field injected by the agent is used for auto-detection.

        TF, TF_STATIC, and JOINT_STATES are routed to canonical ROS
        topics (``/tf``, ``/tf_static``, ``/joint_states``) so that
        RViz and other standard tools can consume them.
        """
        total_start = time.monotonic()
        payload_size = len(payload)
        is_large_payload = payload_size >= 256 * 1024

        # 1. Decode the JSON payload (moved first for auto-detection)
        try:
            decode_start = time.monotonic()
            text = payload.decode("utf-8")
            data_dict = json.loads(text)
            decode_ms = (time.monotonic() - decode_start) * 1000.0
        except Exception as e:
            logger.error(
                "[Bridge] Failed to decode sensor data from %s/%s: %s",
                robot_id, sensor_name, e,
            )
            return

        if not isinstance(data_dict, dict):
            logger.warning(
                "[Bridge] Sensor data is not a dict for %s/%s",
                robot_id, sensor_name,
            )
            return

        # 2. Resolve ROS topic and message type
        is_canonical = sensor_name in self._CANONICAL_TOPICS

        with self._lock:
            robot_map = self._topic_map.get(robot_id, {})
            mapping = robot_map.get(sensor_name)

        if mapping is not None:
            ros_topic_str, msg_type = mapping
        else:
            # Auto-detect from the _msg_type field injected by the agent
            msg_type = data_dict.get("_msg_type", "")
            if not msg_type:
                logger.debug(
                    "[Bridge] No topic mapping or _msg_type for %s/%s, "
                    "publishing as JSON String",
                    robot_id, sensor_name,
                )
                self._publish_as_json(
                    f"/{robot_id}/{sensor_name}", text
                )
                return

            # Canonical topics go to the standard ROS topic name
            if is_canonical:
                ros_topic_str = f"/{sensor_name}"
            else:
                ros_topic_str = f"/{sensor_name}"

        # 3. Strip internal field before conversion
        data_dict.pop("_msg_type", None)

        # 4. Convert to ROS message and publish
        try:
            convert_start = time.monotonic()
            # Prefix frame_ids for multi-robot when enabled
            if (
                self._namespace_tf_frames
                and msg_type == "tf2_msgs/TFMessage"
            ):
                self._prefix_tf_frames(data_dict, robot_id)

            ros_msg = dict_to_ros_msg(data_dict, msg_type)
            convert_ms = (time.monotonic() - convert_start) * 1000.0

            if is_canonical:
                full_topic = ros_topic_str  # /tf, /tf_static, /joint_states
            else:
                full_topic = f"/{robot_id}{ros_topic_str}"

            pub = self._get_or_create_typed_publisher(
                full_topic, type(ros_msg)
            )
            if is_large_payload:
                logger.debug(
                    "[Bridge] Large sensor payload: mqtt=%s/%s size=%.1fKB "
                    "msg_type=%s ros_topic=%s decode=%.1fms convert=%.1fms "
                    "connections=%d",
                    robot_id,
                    sensor_name,
                    payload_size / 1024.0,
                    msg_type,
                    full_topic,
                    decode_ms,
                    convert_ms,
                    pub.get_num_connections(),
                )
            self._wait_for_publisher_connection(full_topic, pub)

            publish_start = time.monotonic()
            pub.publish(ros_msg)
            publish_ms = (time.monotonic() - publish_start) * 1000.0

            if is_large_payload:
                total_ms = (time.monotonic() - total_start) * 1000.0
                logger.debug(
                    "[Bridge] Published large sensor payload: ros_topic=%s "
                    "publish=%.1fms total=%.1fms connections=%d",
                    full_topic,
                    publish_ms,
                    total_ms,
                    pub.get_num_connections(),
                )
            logger.debug(
                "[Bridge] Published sensor data to ROS: %s (%s)",
                full_topic, msg_type,
            )
        except Exception as e:
            logger.error(
                "[Bridge] Failed to publish sensor data: %s", e
            )

    def _handle_sensor_meta(
        self, robot_id: str, sensor_name: str, payload: bytes
    ) -> None:
        """Forward sensor meta information as JSON String."""
        try:
            text = payload.decode("utf-8")
        except Exception:
            text = str(payload)
        self._publish_as_json(f"/{robot_id}/{sensor_name}/meta", text)

    # ================================================================
    # MQTT ---> ROS: status, event, cmd_ack
    # ================================================================

    def _handle_status(self, robot_id: str, payload: bytes) -> None:
        """Update cached robot state and publish aggregated robot list."""
        try:
            text = payload.decode("utf-8")
            message = Message.from_json(text)
            status_data = (
                message.data if isinstance(message.data, dict) else {}
            )

            now = time.monotonic()
            with self._lock:
                if robot_id not in self._robots:
                    self._robots[robot_id] = RobotState(
                        robot_id=robot_id
                    )
                self._robots[robot_id].last_seen = now
                self._robots[robot_id].online = True
                self._robots[robot_id].status = status_data

            # Publish aggregated robot list to /station/robot_list
            aggregation = self._build_robot_list_aggregation()
            pub = self._get_or_create_string_publisher(
                "/station/robot_list"
            )
            pub.publish(json.dumps(aggregation))
            logger.debug("[Bridge] Updated status for %s", robot_id)
        except Exception as e:
            logger.error(
                "[Bridge] Failed to handle status for %s: %s",
                robot_id,
                e,
            )

    def _handle_event(self, robot_id: str, payload: bytes) -> None:
        """Forward robot event to ROS as JSON String."""
        self._publish_raw_as_json(f"/{robot_id}/event", payload)

    def _handle_cmd_ack(self, robot_id: str, payload: bytes) -> None:
        """Forward command ack to ROS as JSON String."""
        self._publish_raw_as_json(f"/{robot_id}/cmd_ack", payload)

    # ================================================================
    # ROS ---> MQTT subscribers
    # ================================================================

    def _on_topic_request(self, msg: String) -> None:
        """Forward /station/topic_request to MQTT ``station/topic/request``."""
        try:
            data = self._resolve_msg_data(msg)
            self._mqtt_publish(
                station_topic_request(),
                json.dumps(data).encode("utf-8"),
                qos=1,
            )
            logger.debug("[Bridge] Forwarded topic request to MQTT")
        except Exception as e:
            logger.error(
                "[Bridge] Failed to forward topic request: %s", e
            )

    def _on_config_sync(self, msg: String) -> None:
        """Handle /station/config_sync: forward to MQTT + save local YAML."""
        try:
            data = self._resolve_msg_data(msg)
            # Forward to MQTT
            self._mqtt_publish(
                "station/config/sync",
                json.dumps(data).encode("utf-8"),
                qos=1,
            )
            # Persist locally
            self._save_transmit_config(data)
            logger.debug(
                "[Bridge] Forwarded config sync to MQTT and saved locally"
            )
        except Exception as e:
            logger.error(
                "[Bridge] Failed to handle config sync: %s", e
            )

    def _on_discover_request(self, msg: String) -> None:
        """Forward /station/discover to MQTT ``station/discover``."""
        try:
            data = self._resolve_msg_data(msg)
            self._mqtt_publish(
                station_discover(),
                json.dumps(data).encode("utf-8"),
                qos=1,
            )
            logger.info("[Bridge] Forwarded discover request to MQTT")
        except Exception as e:
            logger.error(
                "[Bridge] Failed to forward discover: %s", e
            )

    def _on_cmd_command(self, msg: String) -> None:
        """Handle /cmd/command: extract robot_id and forward to MQTT.

        Expected JSON payload format:
            {"robot_id": "robot_001", "action": "velocity", "params": {...}}
        """
        try:
            data = self._resolve_msg_data(msg)
            robot_id = data.get("robot_id", "")
            if not robot_id:
                logger.warning(
                    "[Bridge] cmd/command missing robot_id, cannot forward"
                )
                return

            # Strip robot_id before forwarding the command payload
            cmd_data = {
                k: v for k, v in data.items() if k != "robot_id"
            }
            self._mqtt_publish(
                robot_cmd(robot_id),
                json.dumps(cmd_data).encode("utf-8"),
                qos=1,
            )
            logger.debug(
                "[Bridge] Forwarded command to %s", robot_id
            )
        except Exception as e:
            logger.error(
                "[Bridge] Failed to forward command: %s", e
            )

    def _on_config_query(self, msg: String) -> None:
        """Reply to /station/config_query with saved config (no MQTT)."""
        try:
            config = self._load_transmit_config()
            pub = self._get_or_create_string_publisher(
                "/station/config_response"
            )
            pub.publish(json.dumps(config))
            logger.debug("[Bridge] Replied to config query")
        except Exception as e:
            logger.error(
                "[Bridge] Failed to handle config query: %s", e
            )

    def _on_available_topics_query(self, msg: String) -> None:
        """Reply with cached available topics (no MQTT)."""
        try:
            data = self._resolve_msg_data(msg)
            target_robot = data.get("robot_id", "")

            if target_robot:
                robot_ids = [target_robot]
            else:
                with self._lock:
                    robot_ids = list(self._robots.keys())

            for rid in robot_ids:
                with self._lock:
                    if rid in self._robots:
                        topics = self._robots[rid].available_topics
                    else:
                        topics = []

                response = {"robot_id": rid, "topics": topics}
                pub = self._get_or_create_string_publisher(
                    f"/{rid}/available_topics"
                )
                pub.publish(json.dumps(response))
                logger.debug(
                    "[Bridge] Replied available topics for %s (%d topics)",
                    rid,
                    len(topics),
                )
        except Exception as e:
            logger.error(
                "[Bridge] Failed to handle available topics query: %s",
                e,
            )

    # ================================================================
    # Heartbeat monitor
    # ================================================================

    def _start_heartbeat_monitor(self) -> None:
        """Start daemon thread that checks robot heartbeats periodically."""
        thread = threading.Thread(
            target=self._heartbeat_monitor_loop,
            daemon=True,
            name="bridge_heartbeat",
        )
        thread.start()
        logger.info("[Bridge] Heartbeat monitor started")

    def _heartbeat_monitor_loop(self) -> None:
        """Check robot timestamps every ~5 s; mark offline after timeout."""
        check_interval = min(5.0, self._heartbeat_timeout / 6.0)
        while self._running:
            time.sleep(check_interval)
            try:
                self._check_heartbeats()
            except Exception as e:
                logger.error(
                    "[Bridge] Heartbeat check error: %s", e
                )

    def _check_heartbeats(self) -> None:
        """Iterate robots and mark offline those past the timeout."""
        now = time.monotonic()
        changed = False

        with self._lock:
            for robot_id, state in self._robots.items():
                if not state.online:
                    continue
                elapsed = now - state.last_seen
                if elapsed > self._heartbeat_timeout:
                    state.online = False
                    changed = True
                    logger.warning(
                        "[Bridge] Robot %s marked offline "
                        "(no status for %.1f s)",
                        robot_id,
                        elapsed,
                    )

        if changed:
            aggregation = self._build_robot_list_aggregation()
            pub = self._get_or_create_string_publisher(
                "/station/robot_list"
            )
            pub.publish(json.dumps(aggregation))

    # ================================================================
    # Startup recovery
    # ================================================================

    def _send_discover(self) -> None:
        """Broadcast MQTT discover request to find online robots."""
        self._mqtt_publish(
            station_discover(),
            json.dumps({}).encode("utf-8"),
            qos=1,
        )
        logger.info("[Bridge] Sent discover request")

    def _restore_subscriptions(self) -> None:
        """Load saved subscriptions from transmit_config.yaml and re-request."""
        config = self._load_transmit_config()
        subscriptions = config.get("subscriptions", {})
        if not subscriptions:
            logger.info("[Bridge] No saved subscriptions to restore")
            return

        restored = 0
        for robot_id, subs in subscriptions.items():
            for ros_topic_str, sub_info in subs.items():
                request = {
                    "action": "subscribe",
                    "topic": ros_topic_str,
                    "msg_type": sub_info.get("msg_type", ""),
                    "freq_limit": sub_info.get("freq_limit", 10.0),
                    "transport": sub_info.get("transport", "auto"),
                    "compression": sub_info.get("compression", {}),
                }
                message = Message(
                    src="mqtt_ros_bridge",
                    dst=robot_id,
                    type=MessageType.TOPIC_REQUEST,
                    data=request,
                )
                self._mqtt_publish(
                    station_topic_request(),
                    message.to_json().encode("utf-8"),
                    qos=1,
                )
                restored += 1
                logger.info(
                    "[Bridge] Restored subscription: %s%s",
                    robot_id,
                    ros_topic_str,
                )

        if restored:
            logger.info(
                "[Bridge] Restored %d subscription(s)", restored
            )

    # ================================================================
    # Config persistence
    # ================================================================

    def _load_transmit_config(self) -> dict:
        """Read transmit_config.yaml, returning defaults on failure."""
        p = Path(self._transmit_config_path)
        if not p.exists():
            return {"subscriptions": {}}
        try:
            with open(p, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                return loaded if isinstance(loaded, dict) else {
                    "subscriptions": {}
                }
        except Exception as e:
            logger.error(
                "[Bridge] Failed to load transmit config: %s", e
            )
            return {"subscriptions": {}}

    def _save_transmit_config(self, data: dict) -> None:
        """Write a dict to transmit_config.yaml."""
        try:
            p = Path(self._transmit_config_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                yaml.safe_dump(data, f, default_flow_style=False)
            logger.debug(
                "[Bridge] Saved transmit config to %s",
                self._transmit_config_path,
            )
        except Exception as e:
            logger.error(
                "[Bridge] Failed to save transmit config: %s", e
            )

    # ================================================================
    # Helpers
    # ================================================================

    def _build_robot_list_aggregation(self) -> Dict[str, Any]:
        """Build an aggregated robot list dict for /station/robot_list."""
        with self._lock:
            robots_list: List[Dict[str, Any]] = []
            for robot_id, state in self._robots.items():
                robots_list.append(
                    {
                        "robot_id": robot_id,
                        "online": state.online,
                        "last_seen": state.last_seen,
                        "status": state.status,
                        "subscriptions": list(
                            state.subscriptions.keys()
                        ),
                        "available_topics": state.available_topics,
                    }
                )
            return {
                "robots": robots_list,
                "count": len(robots_list),
            }

    def _mqtt_publish(
        self,
        topic: str,
        payload: bytes,
        qos: int = 1,
    ) -> None:
        """Publish a message to MQTT (thread-safe)."""
        if self._mqtt_client is not None and self._running:
            self._mqtt_client.publish(topic, payload, qos=qos)

    def _publish_as_json(
        self, ros_topic: str, json_str: str
    ) -> None:
        """Publish a pre-serialized JSON string to a ROS String topic."""
        pub = self._get_or_create_string_publisher(ros_topic)
        pub.publish(json_str)

    def _publish_raw_as_json(
        self, ros_topic: str, payload: bytes
    ) -> None:
        """Decode bytes and publish to a ROS String topic."""
        try:
            text = payload.decode("utf-8")
        except Exception:
            text = str(payload)
        self._publish_as_json(ros_topic, text)

    def _prefix_tf_frames(
        self, data_dict: dict, robot_id: str
    ) -> None:
        """Prefix frame_id and child_frame_id with robot namespace.

        Modifies *data_dict* in place so that each transform's
        ``header.frame_id`` and ``child_frame_id`` become e.g.
        ``turtlebot_001/odom`` instead of ``odom``.

        Idempotent: skips frames that already carry the prefix.
        """
        transforms = data_dict.get("transforms")
        if not transforms:
            return

        prefix = f"{robot_id}/"
        for tf in transforms:
            if not isinstance(tf, dict):
                continue
            header = tf.get("header")
            if isinstance(header, dict):
                fid = header.get("frame_id")
                if isinstance(fid, str) and fid and not fid.startswith(prefix):
                    header["frame_id"] = prefix + fid
            cid = tf.get("child_frame_id")
            if isinstance(cid, str) and cid and not cid.startswith(prefix):
                tf["child_frame_id"] = prefix + cid

    @staticmethod
    def _resolve_msg_data(msg: String) -> Any:
        """Return the string content of a std_msgs/String as a Python object.

        If the content is valid JSON it is decoded, otherwise the raw
        string is returned.
        """
        raw = msg.data if isinstance(msg.data, str) else str(msg.data)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    bridge = MqttRosBridge()
    bridge.start()
