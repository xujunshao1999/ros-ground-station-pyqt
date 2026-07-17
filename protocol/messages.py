from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# 消息协议定义 - 地面站与机器人之间的通信消息格式。
# 所有跨网络消息必须符合此模块定义的格式，确保 Agent 与地面站解耦。

# ---------------------------------------------------------------------------
# 协议版本
# ---------------------------------------------------------------------------
PROTOCOL_VERSION = "1.0"


# ---------------------------------------------------------------------------
# 枚举类型
# ---------------------------------------------------------------------------
class MessageType(str, Enum):
    """消息类型"""
    STATUS = "status"                # 机器人状态上报
    CMD = "cmd"                      # 控制指令
    CMD_ACK = "cmd_ack"              # 指令确认
    EVENT = "event"                  # 告警/异常事件
    DISCOVER = "discover"            # 发现请求
    DISCOVER_RESPONSE = "discover_resp"  # 发现响应
    TOPIC_REQUEST = "topic_request"  # Topic 订阅/取消请求
    TOPIC_RESPONSE = "topic_resp"    # Topic 请求响应
    SENSOR_DATA = "sensor_data"      # 传感器数据
    SENSOR_META = "sensor_meta"      # 重量话题元信息
    FLEET_DATA = "fleet_data"        # 机器人间数据
    CONFIG_SYNC = "config_sync"      # 配置同步
    CONFIG_QUERY = "config_query"    # 配置查询
    CONFIG_RESPONSE = "config_response"  # 配置响应


class TopicAction(str, Enum):
    """Topic 订阅动作"""
    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"


class TransportType(str, Enum):
    """传输方式"""
    MQTT_JSON = "mqtt_json"          # 轻量话题: MQTT + JSON
    MQTT_BINARY = "mqtt_binary"      # 中等话题: MQTT + 二进制
    HTTP_STREAM = "http_stream"      # 重量话题: HTTP 流
    AUTO = "auto"                    # 自动选择


class RobotMode(str, Enum):
    """机器人运行模式"""
    AUTO = "auto"
    MANUAL = "manual"
    STOP = "stop"
    ERROR = "error"


class CmdAction(str, Enum):
    """控制指令动作"""
    VELOCITY = "velocity"            # 速度控制
    MODE = "mode"                    # 模式切换
    NAV_GOAL = "nav_goal"            # 导航目标
    CUSTOM = "custom"                # 自定义指令


class EventLevel(str, Enum):
    """事件等级"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class TopicResponseResult(str, Enum):
    """Topic 请求结果"""
    OK = "ok"
    FAILED = "failed"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"


# ---------------------------------------------------------------------------
# 数据类 - 消息各部分的 data 结构
# ---------------------------------------------------------------------------
@dataclass
class Position:
    """2D 位置"""
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0


@dataclass
class Velocity:
    """速度"""
    linear: float = 0.0
    angular: float = 0.0


@dataclass
class StatusData:
    """状态上报数据"""
    battery: float = 0.0
    position: Position = field(default_factory=Position)
    velocity: Velocity = field(default_factory=Velocity)
    mode: str = RobotMode.STOP
    ros_version: str = ""
    uptime: int = 0
    ip: str = ""


@dataclass
class CmdParams:
    """控制指令参数（通用 key-value）"""
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CmdData:
    """控制指令数据"""
    action: str = CmdAction.VELOCITY
    params: Dict[str, Any] = field(default_factory=dict)
    exec_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class CmdAckData:
    """指令确认数据"""
    exec_id: str = ""
    result: str = "ok"
    message: str = ""


@dataclass
class EventData:
    """告警/异常事件数据"""
    level: str = EventLevel.INFO
    code: str = ""
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DiscoverData:
    """发现请求数据"""
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class DiscoverResponseData:
    """发现响应数据"""
    request_id: str = ""
    robot_id: str = ""
    ros_version: str = ""
    topics: List[Dict[str, str]] = field(default_factory=list)
    ip: str = ""
    uptime: int = 0


@dataclass
class CompressionOptions:
    """压缩/降采样选项"""
    quality: Optional[int] = None       # JPEG 质量 (1-100)
    resize: Optional[List[int]] = None  # 图像缩放 [width, height]
    voxel_size: Optional[float] = None  # 点云体素降采样大小


@dataclass
class TopicRequestData:
    """Topic 订阅/取消请求数据"""
    action: str = TopicAction.SUBSCRIBE
    topic: str = ""                  # ROS topic 名称
    msg_type: str = ""               # ROS 消息类型
    freq_limit: Optional[float] = None  # 频率限制 (Hz)
    transport: str = TransportType.AUTO
    compression: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TopicResponseData:
    """Topic 请求响应数据"""
    request_id: str = ""
    action: str = ""                   # "subscribe" | "unsubscribe"
    topic: str = ""                    # ROS 话题名
    msg_type: str = ""                 # ROS 消息类型
    freq_limit: float = 0.0           # 转发频率上限 (Hz)
    result: str = TopicResponseResult.OK
    message: str = ""
    transport: str = TransportType.MQTT_JSON
    stream_url: str = ""             # HTTP 流地址（重量话题）


@dataclass
class SensorMetaData:
    """重量话题元信息"""
    topic: str = ""
    msg_type: str = ""
    transport: str = TransportType.HTTP_STREAM
    stream_url: str = ""
    size_bytes: int = 0
    freq_hz: float = 0.0
    seq: int = 0
    stamp: Dict[str, int] = field(default_factory=dict)
    frame_id: str = ""
    encoding: str = ""
    payload_format: str = ""
    payload_size: int = 0


@dataclass
class FleetData:
    """机器人间数据"""
    data_type: str = "custom"        # "position" | "nav_goal" | "custom" | "pointcloud"
    payload: Dict[str, Any] = field(default_factory=dict)
    ttl: float = 30.0                # 有效时间（秒）
    src_topic: str = ""              # 源 ROS topic
    dst_topic: str = ""              # 目标机器人本地发布 topic
    msg_type: str = ""               # ROS 消息类型
    frame_policy: str = "preserve"   # "preserve" | "namespace"
    stamp: float = 0.0               # 数据时间戳


@dataclass
class FleetBinaryEnvelopeData:
    """Agent 间 ROS1 二进制主体的路由与校验信息。"""
    data_type: str = "ros_topic"
    binary: bool = True
    transport: str = TransportType.MQTT_BINARY
    encoding: str = "ros1_serialized_v1"
    payload_format: str = "ros1_serialized"
    transfer_id: int = 0
    payload_size: int = 0
    md5sum: str = ""
    src_topic: str = ""
    dst_topic: str = ""
    msg_type: str = ""
    frame_policy: str = "preserve"
    stamp: float = 0.0
    ttl: float = 1.0

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FleetBinaryEnvelopeData":
        """严格解析 envelope，避免无效标识进入后续配对缓存。"""
        transfer_id = data.get("transfer_id")
        payload_size = data.get("payload_size")
        md5sum = data.get("md5sum")
        try:
            ttl = float(data.get("ttl", 1.0))
            stamp = float(data.get("stamp", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("fleet envelope times must be numeric") from exc

        # bool 是 int 的子类，必须显式拒绝以保持协议类型严格。
        if isinstance(transfer_id, bool) or not isinstance(transfer_id, int):
            raise ValueError("transfer_id must be an integer")
        if not 0 <= transfer_id < (1 << 64):
            raise ValueError("transfer_id out of uint64 range")
        if isinstance(payload_size, bool) or not isinstance(payload_size, int):
            raise ValueError("payload_size must be an integer")
        if payload_size < 0:
            raise ValueError("payload_size must be non-negative")
        if not math.isfinite(ttl) or not math.isfinite(stamp):
            raise ValueError("fleet envelope times must be finite")
        if not isinstance(md5sum, str) or not md5sum:
            raise ValueError("md5sum is required")

        # 固定标记用于区分完整 JSON FleetData 与二进制 envelope。
        expected_markers = {
            "data_type": "ros_topic",
            "transport": "mqtt_binary",
            "encoding": "ros1_serialized_v1",
            "payload_format": "ros1_serialized",
        }
        for field_name, expected in expected_markers.items():
            if data.get(field_name) != expected:
                raise ValueError("invalid fleet binary %s" % field_name)
        if data.get("binary") is not True:
            raise ValueError("binary fleet envelope marker is required")

        return cls(
            transfer_id=transfer_id,
            payload_size=payload_size,
            md5sum=md5sum,
            src_topic=str(data.get("src_topic", "")),
            dst_topic=str(data.get("dst_topic", "")),
            msg_type=str(data.get("msg_type", "")),
            frame_policy=str(data.get("frame_policy", "preserve")),
            stamp=stamp,
            ttl=ttl,
        )


@dataclass
class ConfigSyncData:
    """配置同步数据 - 地面站下发到 Agent"""
    subscriptions: List[Dict[str, Any]] = field(default_factory=list)
    fleet_rules: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ConfigResponseData:
    """配置响应数据 - Agent 返回当前配置"""
    robot_id: str = ""
    subscriptions: List[Dict[str, Any]] = field(default_factory=list)
    fleet_rules: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 核心消息封装
# ---------------------------------------------------------------------------
@dataclass
class Message:
    """
    通用消息格式 - 所有跨网络通信的顶层包装

    JSON 示例:
    {
        "ver": "1.0",
        "ts": 1712582400.0,
        "src": "robot_001",
        "dst": "station",
        "type": "status",
        "seq": 42,
        "data": { ... }
    }
    """
    ver: str = PROTOCOL_VERSION
    ts: float = field(default_factory=time.time)
    src: str = ""
    dst: str = ""
    type: str = ""
    seq: int = 0
    data: Dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(asdict(self), ensure_ascii=False)

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return asdict(self)

    @classmethod
    def from_json(cls, raw: str) -> Message:
        """从 JSON 字符串反序列化"""
        d = json.loads(raw)
        return cls(
            ver=d.get("ver", PROTOCOL_VERSION),
            ts=d.get("ts", 0.0),
            src=d.get("src", ""),
            dst=d.get("dst", ""),
            type=d.get("type", ""),
            seq=d.get("seq", 0),
            data=d.get("data", {}),
        )

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Message:
        """从字典构建"""
        return cls(
            ver=d.get("ver", PROTOCOL_VERSION),
            ts=d.get("ts", 0.0),
            src=d.get("src", ""),
            dst=d.get("dst", ""),
            type=d.get("type", ""),
            seq=d.get("seq", 0),
            data=d.get("data", {}),
        )


# ---------------------------------------------------------------------------
# 消息工厂 - 快速创建各类消息
# ---------------------------------------------------------------------------
class MessageFactory:
    """消息工厂 - 快速创建各类标准消息"""

    def __init__(self, src: str, seq_start: int = 0):
        self.src = src
        self._seq = seq_start

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _make(self, msg_type: str, data: Any, dst: str = "station") -> Message:
        """构建通用消息"""
        if isinstance(data, (StatusData, CmdData, CmdAckData, EventData,
                             DiscoverData, DiscoverResponseData,
                             TopicRequestData, TopicResponseData,
                             SensorMetaData, FleetData, FleetBinaryEnvelopeData,
                             ConfigSyncData, ConfigResponseData)):
            data = asdict(data)
        return Message(
            ts=time.time(),
            src=self.src,
            dst=dst,
            type=msg_type,
            seq=self._next_seq(),
            data=data if isinstance(data, dict) else {},
        )

    def status(self, status_data: StatusData) -> Message:
        """创建状态上报消息"""
        return self._make(MessageType.STATUS, status_data)

    def cmd(self, cmd_data: CmdData, dst: str = "") -> Message:
        """创建控制指令消息"""
        return self._make(MessageType.CMD, cmd_data, dst=dst)

    def cmd_ack(self, ack_data: CmdAckData) -> Message:
        """创建指令确认消息"""
        return self._make(MessageType.CMD_ACK, ack_data)

    def event(self, event_data: EventData) -> Message:
        """创建事件消息"""
        return self._make(MessageType.EVENT, event_data)

    def discover(self) -> Message:
        """创建发现请求消息"""
        return self._make(MessageType.DISCOVER, DiscoverData(), dst="broadcast")

    def discover_response(self, resp_data: DiscoverResponseData) -> Message:
        """创建发现响应消息"""
        return self._make(MessageType.DISCOVER_RESPONSE, resp_data)

    def topic_request(self, req_data: TopicRequestData, dst: str = "") -> Message:
        """创建 Topic 订阅请求消息"""
        return self._make(MessageType.TOPIC_REQUEST, req_data, dst=dst)

    def topic_response(self, resp_data: TopicResponseData) -> Message:
        """创建 Topic 请求响应消息"""
        return self._make(MessageType.TOPIC_RESPONSE, resp_data)

    def sensor_meta(self, meta_data: SensorMetaData) -> Message:
        """创建重量话题元信息消息"""
        return self._make(MessageType.SENSOR_META, meta_data)

    def fleet_data(self, fleet_data: FleetData, dst: str = "") -> Message:
        """创建机器人间通信消息"""
        return self._make(MessageType.FLEET_DATA, fleet_data, dst=dst)

    def fleet_binary_envelope(
        self,
        envelope: FleetBinaryEnvelopeData,
        dst: str,
    ) -> Message:
        """创建 Agent 间 ROS1 二进制传输 envelope。"""
        return self._make(MessageType.FLEET_DATA, envelope, dst=dst)

    def config_sync(self, config_data: ConfigSyncData, dst: str = "") -> Message:
        """创建配置同步消息"""
        return self._make(MessageType.CONFIG_SYNC, config_data, dst=dst)

    def config_query(self, robot_id: str = "") -> Message:
        """创建配置查询消息"""
        return self._make(MessageType.CONFIG_QUERY, {"robot_id": robot_id}, dst="broadcast")

    def config_response(self, resp_data: ConfigResponseData) -> Message:
        """创建配置响应消息"""
        return self._make(MessageType.CONFIG_RESPONSE, resp_data)
