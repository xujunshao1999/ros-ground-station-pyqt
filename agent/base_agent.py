from __future__ import annotations

"""
Agent 抽象基类

所有 Agent（Mock/ROS1/ROS2）的统一接口。
Agent 的核心职责：
1. 连接 MQTT Broker
2. 上报机器人状态
3. 接收地面站指令
4. 按需转发话题数据（轻量/中等/重量分层）
5. 响应发现请求和话题订阅请求
"""

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import paho.mqtt.client as mqtt

from protocol.messages import (
    Message,
    MessageType,
    MessageFactory,
    StatusData,
    Position,
    Velocity,
    CmdData,
    CmdAckData,
    EventData,
    DiscoverData,
    DiscoverResponseData,
    TopicRequestData,
    TopicResponseData,
    SensorMetaData,
    FleetData,
    ConfigSyncData,
    ConfigResponseData,
    TopicAction,
    RobotMode,
    CmdAction,
)
from protocol.topics import (
    robot_status,
    robot_sensor,
    robot_sensor_meta,
    robot_sensor_binary,
    robot_cmd,
    robot_cmd_ack,
    robot_event,
    robot_to_robot,
    robot_to_robot_meta,
    all_robot_to_robot,
    all_robot_to_robot_meta,
    station_discover,
    station_topic_request,
    station_topic_response,
    station_config_sync,
    station_config_query,
    station_config_response,
)
from protocol.binary_payloads import encode_sensor_binary, is_binary_supported
from agent.rate_limiter import RateLimiter
from agent.topic_handler import TopicHandler
from protocol.topic_registry import TopicTier

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent 状态"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class AgentConfig:
    """Agent 配置"""

    robot_id: str = "robot_001"
    broker_host: str = "localhost"
    broker_port: int = 1883
    status_interval: float = 2.0  # 状态上报间隔（秒）
    default_freq_limit: float = 10.0  # 默认话题频率上限（Hz）
    http_stream_port: int = 8080  # 重量话题 HTTP 流端口
    auto_reconnect: bool = True  # 自动重连
    reconnect_delay: float = 5.0  # 重连延迟（秒）
    subscriptions: list = field(default_factory=list)  # 持久订阅列表
    fleet_rules: list = field(default_factory=list)  # 编队通信规则
    config_path: str = ""  # 当前配置文件路径，用于写回

    def __post_init__(self):
        """校验配置字段"""
        if not self.robot_id:
            raise ValueError("robot_id 不能为空")
        if not self.broker_host:
            raise ValueError("broker_host 不能为空")
        if not (1 <= self.broker_port <= 65535):
            raise ValueError(f"broker_port 必须在 1-65535 之间，当前: {self.broker_port}")
        if self.status_interval <= 0:
            raise ValueError(f"status_interval 必须大于 0，当前: {self.status_interval}")
        if self.default_freq_limit < 0:
            raise ValueError(f"default_freq_limit 必须 >= 0，当前: {self.default_freq_limit}")
        if not (1 <= self.http_stream_port <= 65535):
            raise ValueError(f"http_stream_port 必须在 1-65535 之间，当前: {self.http_stream_port}")
        if self.reconnect_delay <= 0:
            raise ValueError(f"reconnect_delay 必须大于 0，当前: {self.reconnect_delay}")

    @classmethod
    def from_yaml(cls, path: str) -> AgentConfig:
        """从 YAML 文件加载并校验配置"""
        import logging
        from pathlib import Path

        import yaml

        logger = logging.getLogger(__name__)

        p = Path(path)
        if not p.exists():
            logger.warning(f"配置文件不存在: {path}，使用默认值")
            return cls(config_path=str(p))

        with open(p, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # 检测未知字段（防止拼写错误）
        known_keys = {
            "robot_id", "broker_host", "broker_port",
            "status_interval", "default_freq_limit", "http_stream_port",
            "auto_reconnect", "reconnect_delay",
            "subscriptions", "fleet_rules",
            "username", "password", "ros_master_uri", "ros_namespace",
        }
        unknown = set(raw.keys()) - known_keys
        if unknown:
            logger.warning(f"配置文件中存在未识别的字段: {unknown}")

        return cls(
            robot_id=raw.get("robot_id", "robot_001"),
            broker_host=raw.get("broker_host", "localhost"),
            broker_port=raw.get("broker_port", 1883),
            status_interval=raw.get("status_interval", 2.0),
            default_freq_limit=raw.get("default_freq_limit", 10.0),
            http_stream_port=raw.get("http_stream_port", 8080),
            auto_reconnect=raw.get("auto_reconnect", True),
            reconnect_delay=raw.get("reconnect_delay", 5.0),
            subscriptions=raw.get("subscriptions", []),
            fleet_rules=raw.get("fleet_rules", []),
            config_path=str(p),
        )


class BaseAgent(ABC):
    """Agent 抽象基类

    子类需要实现：
    - _get_status_data() -> StatusData: 获取当前机器人状态
    - _execute_command(cmd: CmdData) -> bool: 执行控制指令
    - _get_available_topics() -> list[dict]: 获取可用话题列表
    - _on_topic_subscribed(topic, msg_type, options): 话题被订阅时的回调
    - _on_topic_unsubscribed(topic): 话题被取消订阅时的回调

    使用方法：
        agent = MockAgent(config)
        agent.start()  # 阻塞运行
    """

    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or AgentConfig()
        self.state = AgentState.DISCONNECTED

        # MQTT 客户端
        self._mqtt_client: Optional[mqtt.Client] = None
        self._factory = MessageFactory(src=self.config.robot_id)

        # 限频器和话题处理器
        self._rate_limiter = RateLimiter(default_freq_limit=self.config.default_freq_limit)
        self._topic_handler = TopicHandler()

        # 话题订阅管理：{ros_topic: {"msg_type": str, "freq_limit": float, ...}}
        self._subscribed_topics: Dict[str, dict] = {}

        # 指令追踪
        self._exec_counter = 0

        # 运行标志
        self._running = False
        self._last_status_time = 0.0

        # 状态上报线程（基类默认实现）
        self._status_thread: Optional[threading.Thread] = None

        # HTTP 流服务端（重量话题用）
        self._stream_server: Optional[HTTPServer] = None
        self._stream_thread: Optional[threading.Thread] = None
        self._stream_data: Dict[str, bytes] = {}
        self._stream_lock = threading.Lock()

    # ============================================================
    # 公共接口
    # ============================================================

    def start(self) -> None:
        """启动 Agent（阻塞运行）"""
        logger.info(f"[Agent] Starting {self.config.robot_id}...")
        self._running = True
        self.state = AgentState.CONNECTING

        # 初始化 MQTT 客户端
        self._init_mqtt()

        # 连接 Broker
        try:
            self._mqtt_client.connect(
                self.config.broker_host, self.config.broker_port
            )
            logger.info(
                f"[Agent] Connecting to {self.config.broker_host}:{self.config.broker_port}"
            )
        except Exception as e:
            logger.error(f"[Agent] Connection failed: {e}")
            if self.config.auto_reconnect:
                self._reconnect_loop()
            return

        # 启动网络循环（阻塞）
        self.state = AgentState.CONNECTED
        try:
            self._mqtt_client.loop_forever()
        except KeyboardInterrupt:
            logger.info("[Agent] Interrupted by user")
        finally:
            self.stop()

    def stop(self) -> None:
        """停止 Agent"""
        logger.info("[Agent] Stopping...")
        self._running = False
        self.state = AgentState.STOPPING

        # 等待状态上报线程结束
        if self._status_thread and self._status_thread.is_alive():
            self._status_thread.join(timeout=2.0)
            self._status_thread = None

        if self._mqtt_client:
            self._mqtt_client.disconnect()
            self._mqtt_client.loop_stop()

        self.state = AgentState.STOPPED
        logger.info("[Agent] Stopped.")

    def publish_event(self, event_data: EventData) -> None:
        """发布事件/告警

        由子类调用，通过 MQTT 发送事件消息到地面站。

        Args:
            event_data: 事件数据
        """
        try:
            msg = self._factory.event(event_data)
            from protocol.topics import robot_event
            self._mqtt_publish(
                robot_event(self.config.robot_id), msg.to_json().encode("utf-8")
            )
        except Exception as e:
            logger.error(f"[Agent] Failed to publish event: {e}")

    def publish_sensor_data(
        self,
        ros_topic: str,
        msg_type: str,
        data: dict,
        bypass_rate_limit: bool = False,
        retain: bool = False,
    ) -> None:
        """发布传感器数据

        由子类调用，将话题数据通过分层策略发送。

        Args:
            ros_topic: ROS 话题名，如 "/camera/image_raw/compressed"
            msg_type: 消息类型，如 "sensor_msgs/CompressedImage"
            data: 话题数据字典
            bypass_rate_limit: 是否跳过发送限频
            retain: 是否使用 MQTT retained 消息
        """
        # 检查是否被地面站订阅
        if ros_topic not in self._subscribed_topics:
            return

        # 检查限频
        if not bypass_rate_limit and not self._rate_limiter.can_send(ros_topic):
            return

        # 添加消息类型信息
        data["_msg_type"] = msg_type

        # 处理数据
        try:
            sub_info = self._subscribed_topics[ros_topic]
            options = sub_info.get("options", {})
            qos = int(sub_info.get("qos", 1))
            transport = sub_info.get("transport", "mqtt_json")
            if transport == "mqtt_binary" and is_binary_supported(msg_type):
                header = data.get("header", {})
                seq = int(header.get("seq", int(time.time() * 1000)))
                envelope, binary_payload = encode_sensor_binary(
                    ros_topic,
                    msg_type,
                    data,
                    seq=seq,
                )
                sensor_topic = self._get_sensor_mqtt_topic(ros_topic, TopicTier.MEDIUM)
                binary_topic = self._get_sensor_binary_mqtt_topic(ros_topic)
                self._mqtt_publish(
                    sensor_topic,
                    json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
                    qos=qos,
                    retain=retain,
                )
                self._mqtt_publish(
                    binary_topic,
                    binary_payload,
                    qos=qos,
                    retain=retain,
                )
                if not bypass_rate_limit:
                    self._rate_limiter.mark_sent(ros_topic)
                return
            processed = self._topic_handler.process(
                ros_topic, data, **options
            )
        except Exception as e:
            logger.error(f"[Agent] Failed to process topic {ros_topic}: {e}")
            return

        # 发送
        mqtt_topic = self._get_sensor_mqtt_topic(ros_topic, processed.tier)

        if processed.mqtt_payload:
            self._mqtt_publish(
                mqtt_topic,
                processed.mqtt_payload,
                qos=qos,
                retain=retain,
            )

        # 重量话题额外处理
        if processed.tier == TopicTier.HEAVY and processed.stream_data:
            # 存储流数据，供 HTTP 流服务端读取
            self._store_stream_data(ros_topic, processed.stream_data)
            # 发送元信息
            if processed.meta:
                meta_topic = robot_sensor_meta(self.config.robot_id, ros_topic)
                meta_msg = self._factory.sensor_meta(SensorMetaData(
                    topic=ros_topic,
                    msg_type=msg_type,
                    transport="http_stream",
                    stream_url=f"http://{self._get_local_ip()}:{self.config.http_stream_port}/stream{ros_topic}",
                    size_bytes=processed.meta.get("size_bytes", 0),
                ))
                self._mqtt_publish(meta_topic, meta_msg.to_json().encode("utf-8"), qos=qos)

        if not bypass_rate_limit:
            self._rate_limiter.mark_sent(ros_topic)

    # ============================================================
    # 机器人间通信
    # ============================================================

    def send_to_robot(self, target_id: str, fleet_data: FleetData) -> None:
        """向指定机器人发送轻量数据（MQTT JSON）

        Args:
            target_id: 目标机器人 ID
            fleet_data: 机器人间数据（位置/导航目标/自定义）
        """
        msg = self._factory.fleet_data(fleet_data, dst=target_id)
        topic = robot_to_robot(self.config.robot_id, target_id)
        self._mqtt_publish(topic, msg.to_json().encode("utf-8"))
        logger.info(f"[Agent] Sent fleet data to {target_id}: type={fleet_data.data_type}")

    def share_heavy_data(self, target_id: str, topic: str, data: bytes,
                         msg_type: str = "sensor_msgs/PointCloud2") -> None:
        """向指定机器人共享重量数据（点云等）

        复用 HTTP 流服务端存储数据，通过 MQTT 发送带 stream_url 的信令。

        Args:
            target_id: 目标机器人 ID
            topic: 数据话题名，如 "/fleet/points"
            data: 二进制数据（如 float32 点云）
            msg_type: ROS 消息类型
        """
        self._store_stream_data(topic, data)

        stream_url = (
            f"http://{self._get_local_ip()}:"
            f"{self.config.http_stream_port}/stream{topic}"
        )
        meta = FleetData(
            data_type="pointcloud",
            payload={
                "topic": topic,
                "msg_type": msg_type,
                "stream_url": stream_url,
                "size_bytes": len(data),
            },
            ttl=30.0,
        )
        # 通过 meta topic 发送信令
        meta_msg = self._factory.fleet_data(meta, dst=target_id)
        meta_topic = robot_to_robot_meta(self.config.robot_id, target_id)
        self._mqtt_publish(meta_topic, meta_msg.to_json().encode("utf-8"))
        logger.info(f"[Agent] Shared heavy data to {target_id}: topic={topic} ({len(data)} bytes)")

    # ============================================================
    # 抽象方法（子类实现）
    # ============================================================

    @abstractmethod
    def _get_status_data(self) -> StatusData:
        """获取当前机器人状态

        Returns:
            StatusData 实例
        """
        ...

    @abstractmethod
    def _execute_command(self, cmd: CmdData) -> tuple[bool, str]:
        """执行控制指令

        Args:
            cmd: 指令数据

        Returns:
            (成功与否, 消息)
        """
        ...

    @abstractmethod
    def _get_available_topics(self) -> List[dict]:
        """获取机器人可用的话题列表

        Returns:
            [{"topic": str, "msg_type": str, "description": str}, ...]
        """
        ...

    def _on_topic_subscribed(self, topic: str, msg_type: str, options: dict) -> None:
        """话题被地面站订阅时的回调

        子类可重写此方法以启动话题数据采集。

        Args:
            topic: ROS 话题名
            msg_type: 消息类型
            options: 订阅选项（频率、压缩等）
        """
        pass

    def _on_topic_unsubscribed(self, topic: str) -> None:
        """话题被取消订阅时的回调

        子类可重写此方法以停止话题数据采集。

        Args:
            topic: ROS 话题名
        """
        pass

    @abstractmethod
    def _on_fleet_message(self, src_id: str, data: FleetData) -> None:
        """收到其他机器人数据的回调

        Args:
            src_id: 源机器人 ID
            data: 机器人间数据
        """
        ...

    # ============================================================
    # MQTT 回调
    # ============================================================

    def _init_mqtt(self) -> None:
        """初始化 MQTT 客户端"""
        client_id = f"agent_{self.config.robot_id}"
        self._mqtt_client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=client_id,
        )

        # 设置 Last Will：异常断开时 Broker 立即通知地面站
        will_topic = robot_event(self.config.robot_id)
        will_payload = json.dumps({
            "type": "event",
            "src": self.config.robot_id,
            "data": {
                "level": "error",
                "code": "AGENT_DISCONNECTED",
                "message": f"Agent {self.config.robot_id} disconnected unexpectedly",
            },
        })
        self._mqtt_client.will_set(will_topic, will_payload, qos=1, retain=False)

        # 设置回调
        self._mqtt_client.on_connect = self._on_connect
        self._mqtt_client.on_disconnect = self._on_disconnect
        self._mqtt_client.on_message = self._on_message

        logger.info(f"[Agent] MQTT client initialized: {client_id}")

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        """MQTT 连接成功回调（paho-mqtt v2 签名）"""
        if reason_code == 0 or (hasattr(reason_code, 'value') and reason_code.value == 0):
            self.state = AgentState.CONNECTED
            logger.info("[Agent] Connected to broker")

            # 订阅控制话题
            client.subscribe(robot_cmd(self.config.robot_id), qos=1)
            client.subscribe(station_discover(), qos=1)
            client.subscribe(station_topic_request(), qos=1)
            client.subscribe(station_config_sync(self.config.robot_id), qos=1)
            client.subscribe(station_config_query(self.config.robot_id), qos=1)

            # 订阅其他机器人发来的 fleet 数据
            client.subscribe(all_robot_to_robot(self.config.robot_id), qos=1)
            client.subscribe(all_robot_to_robot_meta(self.config.robot_id), qos=1)

            # 恢复持久化订阅
            self._load_subscriptions_from_config()

            # 启动状态上报循环
            self._start_status_loop()
        else:
            rc_val = reason_code if isinstance(reason_code, int) else getattr(reason_code, 'value', -1)
            logger.error(f"[Agent] Connection failed with code: {rc_val}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        """MQTT 断开连接回调（paho-mqtt v2 签名）"""
        self.state = AgentState.DISCONNECTED
        rc_val = reason_code if isinstance(reason_code, int) else getattr(reason_code, 'value', 1)
        if rc_val != 0:
            logger.warning(f"[Agent] Unexpected disconnect (rc={rc_val})")
            if self.config.auto_reconnect:
                self._reconnect_loop()

    def _on_message(self, client, userdata, msg) -> None:
        """MQTT 消息回调"""
        try:
            payload = msg.payload.decode("utf-8")
            message = Message.from_json(payload)
            self._handle_message(message)
        except Exception as e:
            logger.error(f"[Agent] Failed to handle message on {msg.topic}: {e}")

    def _handle_message(self, message: Message) -> None:
        """处理收到的消息"""
        msg_type = message.type

        if msg_type == MessageType.DISCOVER:
            self._handle_discover(message)
        elif msg_type == MessageType.CMD:
            self._handle_command(message)
        elif msg_type == MessageType.TOPIC_REQUEST:
            self._handle_topic_request(message)
        elif msg_type == MessageType.FLEET_DATA:
            self._handle_fleet_message(message)
        elif msg_type == MessageType.CONFIG_SYNC:
            self._handle_config_sync(message)
        elif msg_type == MessageType.CONFIG_QUERY:
            self._handle_config_query(message)
        else:
            logger.warning(f"[Agent] Unknown message type: {msg_type}")

    # ============================================================
    # 消息处理
    # ============================================================

    def _handle_discover(self, message: Message) -> None:
        """处理发现请求"""
        logger.info("[Agent] Received discover request")

        # 获取可用话题
        topics = self._get_available_topics()

        # 发送发现响应
        response = self._factory.discover_response(DiscoverResponseData(
            request_id=message.data.get("request_id", ""),
            robot_id=self.config.robot_id,
            ros_version=self._get_ros_version(),
            ip=self._get_local_ip(),
            topics=topics,  # 直接传递完整列表 [{"topic": ..., "msg_type": ..., "description": ...}]
        ))
        self._mqtt_publish(station_topic_response(self.config.robot_id), response.to_json().encode("utf-8"))

    def _handle_command(self, message: Message) -> None:
        """处理控制指令"""
        cmd_data = message.data
        if isinstance(cmd_data, dict):
            cmd = CmdData(
                action=cmd_data.get("action", ""),
                params=cmd_data.get("params", {}),
                exec_id=cmd_data.get("exec_id", ""),
            )
        else:
            cmd = cmd_data
        logger.info(f"[Agent] Received command: {cmd.action}")

        # 执行指令
        success, result_msg = self._execute_command(cmd)

        # 发送确认
        self._exec_counter += 1
        ack = self._factory.cmd_ack(CmdAckData(
            exec_id=cmd.exec_id or str(self._exec_counter),
            result="ok" if success else "error",
            message=result_msg,
        ))
        self._mqtt_publish(
            robot_cmd_ack(self.config.robot_id), ack.to_json().encode("utf-8")
        )

    def _handle_topic_request(self, message: Message) -> None:
        """处理话题订阅/取消订阅请求"""
        data = message.data
        action = data.get("action")
        topic = data.get("topic")
        msg_type = data.get("msg_type")
        freq_limit = data.get("freq_limit", self.config.default_freq_limit)
        qos = int(data.get("qos", 1))
        # 兼容 options 和 compression 两种字段名
        options = data.get("options") or data.get("compression", {})

        logger.info(f"[Agent] Topic request: {action} {topic}")

        if action == TopicAction.SUBSCRIBE.value:
            # 订阅话题
            transport = data.get("transport", "auto")
            sub_info = {
                "msg_type": msg_type,
                "freq_limit": freq_limit,
                "qos": qos,
                "options": options,
            }
            self._subscribed_topics[topic] = sub_info
            self._upsert_subscription_config(
                topic, msg_type, freq_limit, transport, qos, options
            )
            self._save_config()
            self._rate_limiter.set_limit(topic, freq_limit)
            self._on_topic_subscribed(topic, msg_type, options)

            # 发送确认
            response = self._factory.topic_response(TopicResponseData(
                request_id=data.get("request_id", ""),
                action="subscribe",
                topic=topic,
                msg_type=msg_type,
                freq_limit=freq_limit,
                result="ok",
                transport=transport,
            ))
            self._mqtt_publish(
                station_topic_response(self.config.robot_id),
                response.to_json().encode("utf-8"),
            )

        elif action == TopicAction.UNSUBSCRIBE.value:
            # 取消订阅
            self._subscribed_topics.pop(topic, None)
            self._rate_limiter.remove_limit(topic)
            self._on_topic_unsubscribed(topic)
            self._remove_subscription_config(topic)
            self._save_config()

            response = self._factory.topic_response(TopicResponseData(
                request_id=data.get("request_id", ""),
                action="unsubscribe",
                topic=topic,
                result="ok",
            ))
            self._mqtt_publish(
                station_topic_response(self.config.robot_id),
                response.to_json().encode("utf-8"),
            )

    def _handle_fleet_message(self, message: Message) -> None:
        """处理其他机器人发来的数据

        Args:
            message: fleet_data 类型的消息
        """
        src_id = message.src
        fleet_data = message.data  # dict
        data_type = fleet_data.get("data_type", "custom")

        logger.info(f"[Agent] Fleet data from {src_id}: type={data_type}")

        # 重量数据 meta 信令
        if data_type == "pointcloud":
            payload = fleet_data.get("payload", {})
            stream_url = payload.get("stream_url", "")
            if stream_url:
                logger.info(f"[Agent] Received heavy data meta from {src_id}: "
                            f"url={stream_url}, size={payload.get('size_bytes', 0)}")
                self._on_fleet_message(src_id, FleetData(
                    data_type=data_type,
                    payload=payload,
                    ttl=fleet_data.get("ttl", 30.0),
                    src_topic=fleet_data.get("src_topic", ""),
                    dst_topic=fleet_data.get("dst_topic", ""),
                    msg_type=fleet_data.get("msg_type", ""),
                    frame_policy=fleet_data.get("frame_policy", "preserve"),
                    stamp=float(fleet_data.get("stamp", 0.0)),
                ))
            return

        # 轻量数据：直接回调子类
        self._on_fleet_message(src_id, FleetData(
            data_type=data_type,
            payload=fleet_data.get("payload", {}),
            ttl=fleet_data.get("ttl", 30.0),
            src_topic=fleet_data.get("src_topic", ""),
            dst_topic=fleet_data.get("dst_topic", ""),
            msg_type=fleet_data.get("msg_type", ""),
            frame_policy=fleet_data.get("frame_policy", "preserve"),
            stamp=float(fleet_data.get("stamp", 0.0)),
        ))

    # ============================================================
    # 配置同步
    # ============================================================

    def _handle_config_sync(self, message: Message) -> None:
        """处理地面站下发的配置同步"""
        logger.info(f"[Agent] Received config sync from station")
        data = message.data

        has_subscriptions = "subscriptions" in data
        new_subscriptions = self._normalize_subscriptions(
            data.get("subscriptions", self.config.subscriptions)
        )
        has_fleet_rules = "fleet_rules" in data
        new_fleet_rules = self._normalize_fleet_rules(
            data.get("fleet_rules", self.config.fleet_rules)
        )

        if has_subscriptions:
            self._apply_subscription_config(new_subscriptions)
            self.config.subscriptions = new_subscriptions
        if has_fleet_rules:
            self.config.fleet_rules = new_fleet_rules
            self._apply_fleet_rules(self.config.fleet_rules)
        self._save_config()

        # 回复确认
        response = self._factory.config_response(ConfigResponseData(
            robot_id=self.config.robot_id,
            subscriptions=self.config.subscriptions,
            fleet_rules=self.config.fleet_rules,
        ))
        self._mqtt_publish(
            station_config_response(self.config.robot_id),
            response.to_json().encode("utf-8"),
        )

    def _handle_config_query(self, message: Message) -> None:
        """处理地面站发来的配置查询"""
        logger.info(f"[Agent] Received config query from station")

        response = self._factory.config_response(ConfigResponseData(
            robot_id=self.config.robot_id,
            subscriptions=self.config.subscriptions,
            fleet_rules=self.config.fleet_rules,
        ))
        self._mqtt_publish(
            station_config_response(self.config.robot_id),
            response.to_json().encode("utf-8"),
        )

    def _load_subscriptions_from_config(self) -> None:
        """启动时恢复持久化订阅"""
        self.config.subscriptions = self._normalize_subscriptions(self.config.subscriptions)
        self.config.fleet_rules = self._normalize_fleet_rules(self.config.fleet_rules)
        for sub in self.config.subscriptions:
            topic = sub.get("topic", "")
            msg_type = sub.get("msg_type", "")
            freq_limit = sub.get("freq_limit", self.config.default_freq_limit)
            options = sub.get("compression", {})

            if topic:
                self._subscribed_topics[topic] = self._subscription_runtime_info(sub)
                self._rate_limiter.set_limit(topic, freq_limit)
                self._on_topic_subscribed(topic, msg_type, options)
                logger.info(f"[Agent] Restored subscription: {topic}")
        self._apply_fleet_rules(self.config.fleet_rules)

    def _normalize_subscriptions(self, subscriptions: List[dict]) -> List[dict]:
        """清洗订阅配置，保留协议字段并按 topic 去重。"""
        normalized: List[dict] = []
        seen = set()
        for sub in subscriptions:
            topic = sub.get("topic", "")
            if not topic or topic in seen:
                continue
            seen.add(topic)
            normalized.append({
                "topic": topic,
                "msg_type": sub.get("msg_type", ""),
                "freq_limit": sub.get("freq_limit", self.config.default_freq_limit),
                "transport": sub.get("transport", "auto"),
                "qos": int(sub.get("qos", 1)),
                "compression": dict(sub.get("compression") or sub.get("options") or {}),
            })
        return normalized

    @staticmethod
    def _normalize_fleet_rules(fleet_rules: List[dict]) -> List[dict]:
        """清洗编队转发规则，保留可执行的 ROS topic 转发配置。"""
        normalized: List[dict] = []
        if not isinstance(fleet_rules, list):
            return normalized

        for rule in fleet_rules:
            if not isinstance(rule, dict):
                continue
            src_topic = rule.get("src_topic", "")
            msg_type = rule.get("msg_type", "")
            if not src_topic or not msg_type:
                continue

            targets = []
            for target in rule.get("targets", []):
                if not isinstance(target, dict):
                    continue
                robot_id = target.get("robot_id", "")
                dst_topic = target.get("dst_topic", "")
                if robot_id and dst_topic:
                    targets.append({
                        "robot_id": robot_id,
                        "dst_topic": dst_topic,
                    })
            if not targets:
                continue

            normalized.append({
                "enabled": bool(rule.get("enabled", True)),
                "src_topic": src_topic,
                "msg_type": msg_type,
                "targets": targets,
                "freq_limit": float(rule.get("freq_limit", 0.0)),
                "transport": rule.get("transport", "mqtt_json"),
                "frame_policy": rule.get("frame_policy", "preserve"),
            })
        return normalized

    def _apply_fleet_rules(self, fleet_rules: List[dict]) -> None:
        """Apply fleet forwarding rules. Subclasses can create ROS subscribers."""
        return

    def _subscription_runtime_info(self, sub: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "msg_type": sub.get("msg_type", ""),
            "freq_limit": sub.get("freq_limit", self.config.default_freq_limit),
            "transport": sub.get("transport", "mqtt_json"),
            "qos": int(sub.get("qos", 1)),
            "options": dict(sub.get("compression") or {}),
        }

    def _runtime_subscription_changed(self, topic: str, sub: Dict[str, Any]) -> bool:
        current = self._subscribed_topics.get(topic)
        if current is None:
            return True
        desired = self._subscription_runtime_info(sub)
        return (
            current.get("msg_type") != desired["msg_type"]
            or current.get("freq_limit") != desired["freq_limit"]
            or current.get("transport", "mqtt_json") != desired["transport"]
            or int(current.get("qos", 1)) != desired["qos"]
            or current.get("options", {}) != desired["options"]
        )

    def _apply_subscription_config(self, subscriptions: List[dict]) -> None:
        desired_by_topic = {sub["topic"]: sub for sub in subscriptions}

        for topic in list(self._subscribed_topics.keys()):
            if topic not in desired_by_topic:
                self._subscribed_topics.pop(topic, None)
                self._rate_limiter.remove_limit(topic)
                self._on_topic_unsubscribed(topic)
                logger.info(f"[Agent] Config sync: unsubscribed from {topic}")

        for sub in subscriptions:
            topic = sub["topic"]
            msg_type = sub.get("msg_type", "")
            freq_limit = sub.get("freq_limit", self.config.default_freq_limit)
            options = sub.get("compression", {})

            if self._runtime_subscription_changed(topic, sub):
                if topic in self._subscribed_topics:
                    self._on_topic_unsubscribed(topic)
                self._subscribed_topics[topic] = self._subscription_runtime_info(sub)
                self._rate_limiter.set_limit(topic, freq_limit)
                self._on_topic_subscribed(topic, msg_type, options)
                logger.info(f"[Agent] Config sync: subscribed to {topic}")

    def _upsert_subscription_config(
        self,
        topic: str,
        msg_type: str,
        freq_limit: float,
        transport: str,
        qos: int,
        compression: Dict[str, Any],
    ) -> None:
        next_sub = {
            "topic": topic,
            "msg_type": msg_type,
            "freq_limit": freq_limit,
            "transport": transport,
            "qos": int(qos),
            "compression": dict(compression),
        }
        remaining = [
            sub for sub in self.config.subscriptions
            if sub.get("topic") != topic
        ]
        self.config.subscriptions = self._normalize_subscriptions(remaining + [next_sub])

    def _remove_subscription_config(self, topic: str) -> None:
        self.config.subscriptions = self._normalize_subscriptions([
            sub for sub in self.config.subscriptions
            if sub.get("topic") != topic
        ])

    def _save_config(self) -> None:
        """持久化动态配置，保留原 YAML 中的其他字段。"""
        config_path = (
            Path(self.config.config_path)
            if self.config.config_path
            else Path(__file__).resolve().parent / "config.yaml"
        )
        try:
            if config_path.exists():
                original = config_path.read_text(encoding="utf-8")
            else:
                original = ""
            updated = self._replace_top_level_yaml_section(
                original, "subscriptions", self.config.subscriptions
            )
            updated = self._replace_top_level_yaml_section(
                updated, "fleet_rules", self.config.fleet_rules
            )
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(updated)
            self._match_config_owner_to_parent(config_path)
            logger.info(f"[Agent] Config saved to {config_path}")
        except Exception as e:
            logger.error(f"[Agent] Failed to save config: {e}")

    @staticmethod
    def _match_config_owner_to_parent(config_path: Path) -> None:
        """Keep Docker bind-mounted config files editable on the host."""
        try:
            parent_stat = config_path.parent.stat()
            if os.geteuid() != 0:
                return
            if parent_stat.st_uid == 0 and parent_stat.st_gid == 0:
                return
            os.chown(str(config_path), parent_stat.st_uid, parent_stat.st_gid)
        except Exception as e:
            logger.debug(
                "[Agent] Could not adjust config file owner for %s: %s",
                config_path,
                e,
            )

    @staticmethod
    def _dump_top_level_yaml_section(key: str, value: Any) -> List[str]:
        import yaml

        dumped = yaml.safe_dump(
            {key: value},
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )
        return dumped.splitlines(keepends=True)

    @staticmethod
    def _is_top_level_yaml_key(line: str) -> bool:
        if not line or line[0].isspace() or line.startswith("#"):
            return False
        stripped = line.strip()
        if ":" not in stripped:
            return False
        key = stripped.split(":", 1)[0]
        return bool(key) and all(ch.isalnum() or ch in "_-" for ch in key)

    @classmethod
    def _replace_top_level_yaml_section(
        cls, original: str, key: str, value: Any
    ) -> str:
        lines = original.splitlines(keepends=True)
        new_section = cls._dump_top_level_yaml_section(key, value)

        start = None
        for idx, line in enumerate(lines):
            if line.startswith(f"{key}:"):
                start = idx
                break

        if start is None:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            if lines and lines[-1].strip():
                lines.append("\n")
            return "".join(lines + new_section)

        next_key = len(lines)
        for idx in range(start + 1, len(lines)):
            if cls._is_top_level_yaml_key(lines[idx]):
                next_key = idx
                break

        end = next_key
        while end > start + 1:
            previous = lines[end - 1]
            if previous.strip() == "" or previous.lstrip().startswith("#"):
                end -= 1
            else:
                break

        return "".join(lines[:start] + new_section + lines[end:])

    # ============================================================
    # 状态上报
    # ============================================================

    def _start_status_loop(self) -> None:
        """启动状态上报循环

        默认实现：启动独立线程定时上报。子类可重写以使用其他方式
        （如 ROS timer、asyncio 任务等）。
        """
        if self._status_thread is not None and self._status_thread.is_alive():
            return  # 已经在运行

        self._status_thread = threading.Thread(
            target=self._default_status_loop,
            daemon=True,
            name="status_reporter",
        )
        self._status_thread.start()
        logger.info("[Agent] Status report loop started")

    def _default_status_loop(self) -> None:
        """默认状态上报循环（独立线程）"""
        while self._running:
            if self.state in (AgentState.CONNECTED, AgentState.RUNNING):
                self._check_and_publish_status()
            time.sleep(self.config.status_interval)

    def _check_and_publish_status(self) -> None:
        """检查并发布状态（由定时器或主循环调用）"""
        now = time.monotonic()
        if now - self._last_status_time < self.config.status_interval:
            return

        self._last_status_time = now

        try:
            status = self._get_status_data()
            msg = self._factory.status(status)
            self._mqtt_publish(
                robot_status(self.config.robot_id), msg.to_json().encode("utf-8")
            )
        except Exception as e:
            logger.error(f"[Agent] Failed to publish status: {e}")

    # ============================================================
    # 工具方法
    # ============================================================

    def _mqtt_publish(
        self,
        topic: str,
        payload: bytes,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """发布 MQTT 消息"""
        if self._mqtt_client and self.state in (
            AgentState.CONNECTED,
            AgentState.RUNNING,
        ):
            self._mqtt_client.publish(topic, payload, qos=qos, retain=retain)
            logger.debug(f"[Agent] Published to {topic} ({len(payload)} bytes)")

    def _reconnect_loop(self) -> None:
        """自动重连循环"""
        while self._running and self.config.auto_reconnect:
            logger.info(
                f"[Agent] Reconnecting in {self.config.reconnect_delay}s..."
            )
            time.sleep(self.config.reconnect_delay)
            try:
                self._mqtt_client.reconnect()
                logger.info("[Agent] Reconnected!")
                return
            except Exception as e:
                logger.error(f"[Agent] Reconnect failed: {e}")

    def _get_ros_version(self) -> str:
        """获取 ROS 版本（子类可重写）"""
        return "mock"

    def _get_local_ip(self) -> str:
        """获取本地 IP 地址"""
        import socket

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def _get_sensor_mqtt_topic(self, ros_topic: str, tier) -> str:
        """获取传感器数据的 MQTT topic"""
        # 简化话题名（移除开头的 /）
        name = ros_topic.lstrip("/").replace("/", "_")
        return robot_sensor(self.config.robot_id, name)

    def _get_sensor_binary_mqtt_topic(self, ros_topic: str) -> str:
        """获取传感器二进制数据的 MQTT topic"""
        name = ros_topic.lstrip("/").replace("/", "_")
        return robot_sensor_binary(self.config.robot_id, name)

    def _store_stream_data(self, topic: str, data: bytes) -> None:
        """存储流数据（供 HTTP 流服务端读取）"""
        with self._stream_lock:
            self._stream_data[topic] = data

    # ============================================================
    # HTTP 流服务端（重量话题）
    # ============================================================

    def _start_stream_server(self) -> None:
        """启动 HTTP 流服务端"""
        if self._stream_server is not None:
            return

        handler = self._create_stream_handler()

        try:
            self._stream_server = HTTPServer(
                ("0.0.0.0", self.config.http_stream_port), handler
            )
            self._stream_thread = threading.Thread(
                target=self._stream_server.serve_forever,
                daemon=True,
                name="http_stream_server",
            )
            self._stream_thread.start()
            logger.info(
                f"[Agent] HTTP stream server started on port {self.config.http_stream_port}"
            )
        except Exception as e:
            logger.error(f"[Agent] Failed to start stream server: {e}")

    def _stop_stream_server(self) -> None:
        """停止 HTTP 流服务端"""
        if self._stream_server:
            self._stream_server.shutdown()
            self._stream_server = None
        if self._stream_thread:
            self._stream_thread.join(timeout=2.0)
            self._stream_thread = None

    def _create_stream_handler(self):
        """创建 HTTP 流请求处理器"""
        agent = self

        class StreamHandler(BaseHTTPRequestHandler):
            """HTTP 流请求处理器"""

            def do_GET(self):
                if self.path.startswith("/stream/"):
                    topic = "/" + self.path[len("/stream/"):]
                    with agent._stream_lock:
                        data = agent._stream_data.get(topic)
                    if data:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/octet-stream")
                        self.send_header("Content-Length", str(len(data)))
                        self.send_header("Cache-Control", "no-cache")
                        self.end_headers()
                        self.wfile.write(data)
                    else:
                        self.send_error(404, f"No data for topic: {topic}")
                else:
                    self.send_error(404, "Not found. Use /stream/<topic>")

            def log_message(self, format, *args):
                logger.debug(f"[StreamServer] {format % args}")

        return StreamHandler
