# 重型数据 HTTP Snapshot 通道实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 为 `sensor_msgs/PointCloud2` 建立第一版重型数据通道：MQTT 只发送 meta 信令，实际 ROS1 serialized payload 由 Bridge 通过 HTTP snapshot 从 Agent 拉取，再反序列化并发布到地面站本地 ROS，供 RViz 直接订阅。

**架构：** Robot Agent 订阅重型 ROS topic 后，将最新一帧 ROS1 serialized bytes 缓存在本地 HTTP endpoint，同时通过 `robot/<id>/sensor/<name>/meta` 发布包含 `stream_url`、`msg_type`、`seq`、`stamp`、`frame_id` 和大小的 JSON meta。Bridge 收到 meta 后主动 HTTP GET 拉取 payload，按 `msg_type` 反序列化为 ROS message，补齐 frame namespace，然后发布到 `/<robot_id>/<topic>`。PyQt/RViz 不直接访问 HTTP，RViz 仍只消费地面站本地 ROS topic。

**技术栈：** Python 3.8、ROS Noetic `serialize()` / `deserialize()`、HTTPServer、MQTT meta topic、pytest、RViz PointCloud2 Display。

---

## 范围与原则

第一版只支持 `sensor_msgs/PointCloud2`，目标是跑通重型数据链路闭环，不做高帧率视频流。`sensor_msgs/Image`、`sensor_msgs/CompressedImage`、HTTP 长连接、WebSocket、点云压缩和体素降采样留到后续计划。

本计划选择 HTTP snapshot，而不是 MQTT 大包，原因是：

- MQTT broker 不承载 PointCloud2 大 payload，降低队列和内存压力。
- Bridge 主动拉取最新帧，天然具备简单 backpressure。
- 每个重型 topic 第一版只缓存最新一帧，避免历史帧堆积。
- RViz 不感知 HTTP，仍通过本地 ROS topic 显示点云。
- `curl` 或 `python urllib` 可以直接验证 stream endpoint，调试成本低。

需要特别处理的约束：

- Agent 暴露的 `stream_url` 必须是 Bridge 可访问的地址。Docker 场景不能直接使用容器内部不可达 IP。
- 重型数据 topic 不应进入前端普通 sensor 摘要解析路径。
- Bridge 拉取失败不能阻塞 MQTT 回调线程过久，需要有短超时和错误日志。
- frame namespace 仍由 Bridge 发布前统一处理，避免多机器人共享 `base_link`、`velodyne` 等 frame。

## 文件结构

- 创建：`agent/mock_pointcloud2_data.py`
  - 提供可复用的 mock PointCloud2 数据生成工具，包含确定性的 XYZ 点数组、PointCloud2 dict、可选真实 ROS message 构造和 ROS1 serialized bytes。
- 测试：`tests/test_mock_pointcloud2_data.py`
  - 覆盖 mock 点云数据的点数、字段、frame_id、纯 Python fallback，以及有 ROS 环境时的真实序列化路径。
- 修改：`protocol/messages.py`
  - 扩展 `SensorMetaData` 字段，承载 `seq`、`stamp`、`frame_id`、`encoding`、`payload_format` 和 `payload_size`。
- 修改：`protocol/topic_registry.py`
  - 将 `sensor_msgs/PointCloud2` 从 `MEDIUM` 调整为 `HEAVY`，默认 transport 为 `http_stream`。
- 修改：`agent/base_agent.py`
  - 增加重型 ROS serialized frame 的缓存、HTTP stream URL 构造和 meta 发布 helper。
  - 增加 `stream_host` / `stream_base_url` 配置读取，避免 Docker 内部 IP 不可达。
- 修改：`agent/ros1_agent.py`
  - 对 `transport: http_stream` 或 registry 判定为 HEAVY 的 `PointCloud2`，直接 `serialize()` 后走 HTTP snapshot meta 路径。
- 修改：`bridge/mqtt_ros_bridge.py`
  - 将 `_handle_sensor_meta()` 从“转发 JSON String”升级为“解析 meta、HTTP GET 拉取、反序列化、namespace、发布 ROS topic”。
- 修改：`qt_frontend/mqtt_client.py`
  - 忽略 `sensor_meta` 普通 UI 解析，或只保留轻量状态摘要，不解析重型 payload。
- 修改：`qt_frontend/config/transmit_config.yaml`
  - 增加一个示例 PointCloud2 订阅项，默认禁用或仅作为注释示例。
- 修改：`agent/configs/turtlebot_001.yaml`
  - 增加 `stream_public_host` 或 `stream_base_url` 配置字段示例。
- 测试：`tests/test_protocol_messages.py`
  - 覆盖扩展后的 `SensorMetaData` 序列化字段。
- 测试：`tests/test_protocol_registry.py`
  - 覆盖 `sensor_msgs/PointCloud2` 为 `HEAVY`，默认 transport 为 `http_stream`。
- 测试：`tests/test_agent_topic_config.py`
  - 使用 `agent/mock_pointcloud2_data.py` 生成的 mock payload，覆盖 Agent 发布 heavy meta 和 HTTP stream 缓存。
- 测试：`tests/test_ros1_agent.py`
  - 使用 `agent/mock_pointcloud2_data.py` 的 serializable mock message，覆盖 ROS1 Agent 对 PointCloud2 走 serialize + heavy meta，不走 JSON dict 转换。
- 测试：`tests/test_mqtt_ros_bridge.py`
  - 使用 `agent/mock_pointcloud2_data.py` 的 fake/真实 PointCloud2 message，覆盖 Bridge 收到 heavy meta 后拉取 bytes、反序列化并发布本地 ROS topic。
- 文档：`docs/work-log-YYYY-MM-DD.md`
  - 执行当天记录设计、实现、验证和剩余风险。

## Meta 协议

第一版使用现有 topic：

```text
robot/<robot_id>/sensor/<sensor_name>/meta
```

`sensor_name` 继续沿用 `ros_topic.lstrip("/").replace("/", "_")`，例如：

```text
/velodyne_points -> robot/turtlebot_001/sensor/velodyne_points/meta
/camera/depth/points -> robot/turtlebot_001/sensor/camera_depth_points/meta
```

meta payload 使用普通 `Message`，`type=sensor_meta`，`data` 示例：

```json
{
  "topic": "/velodyne_points",
  "msg_type": "sensor_msgs/PointCloud2",
  "transport": "http_stream",
  "stream_url": "http://192.168.1.101:8080/stream/velodyne_points",
  "encoding": "ros1_serialized_v1",
  "payload_format": "ros1_serialized",
  "payload_size": 1048576,
  "seq": 128,
  "stamp": {"secs": 1782370000, "nsecs": 120000000},
  "frame_id": "velodyne"
}
```

HTTP endpoint 返回 body 为 ROS1 serialized bytes，不再包额外 JSON；meta 已经提供解码所需的 `msg_type` 和校验信息。

## 任务 1：新增 mock PointCloud2 数据工具

**文件：**
- 创建：`agent/mock_pointcloud2_data.py`
- 测试：`tests/test_mock_pointcloud2_data.py`

- [x] **步骤 1：编写失败的测试**

创建 `tests/test_mock_pointcloud2_data.py`：

```python
from __future__ import annotations

import struct

from agent.mock_pointcloud2_data import (
    FakePointCloud2Message,
    build_pointcloud2_dict,
    generate_xyz_points,
    serialize_fake_pointcloud2,
)


def test_generate_xyz_points_is_deterministic():
    points = generate_xyz_points()

    assert len(points) > 100
    assert points[0] == (-2.5, -2.5, 0.0)
    assert all(len(point) == 3 for point in points)


def test_build_pointcloud2_dict_contains_standard_fields():
    data = build_pointcloud2_dict(frame_id="velodyne", seq=7)

    assert data["_msg_type"] == "sensor_msgs/PointCloud2"
    assert data["header"]["seq"] == 7
    assert data["header"]["frame_id"] == "velodyne"
    assert data["height"] == 1
    assert data["width"] == len(generate_xyz_points())
    assert data["point_step"] == 12
    assert data["row_step"] == data["width"] * data["point_step"]
    assert [field["name"] for field in data["fields"]] == ["x", "y", "z"]
    assert len(data["data"]) == data["row_step"]


def test_fake_pointcloud2_message_serializes_payload():
    data = build_pointcloud2_dict(frame_id="velodyne", seq=3)
    msg = FakePointCloud2Message.from_dict(data)
    payload = serialize_fake_pointcloud2(msg)

    assert msg.header.frame_id == "velodyne"
    assert msg.header.seq == 3
    assert payload == bytes(data["data"])
    first_x, first_y, first_z = struct.unpack("<fff", payload[:12])
    assert first_x == -2.5
    assert first_y == -2.5
    assert first_z == 0.0
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_mock_pointcloud2_data.py -q
```

预期：失败，原因是 `agent/mock_pointcloud2_data.py` 尚未创建。

- [x] **步骤 3：实现 mock 数据工具**

创建 `agent/mock_pointcloud2_data.py`：

```python
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


PointXYZ = Tuple[float, float, float]


@dataclass
class FakeStamp:
    secs: int = 0
    nsecs: int = 0


@dataclass
class FakeHeader:
    seq: int = 0
    stamp: FakeStamp = field(default_factory=FakeStamp)
    frame_id: str = "velodyne"


class FakePointCloud2Message:
    """Small ROS-like PointCloud2 fake used by non-ROS unit tests."""

    def __init__(self) -> None:
        self.header = FakeHeader()
        self.height = 1
        self.width = 0
        self.fields: List[Dict[str, int]] = []
        self.is_bigendian = False
        self.point_step = 12
        self.row_step = 0
        self.data = b""
        self.is_dense = True

    @classmethod
    def from_dict(cls, data: dict) -> "FakePointCloud2Message":
        msg = cls()
        header = data.get("header", {})
        stamp = header.get("stamp", {})
        msg.header = FakeHeader(
            seq=int(header.get("seq", 0)),
            stamp=FakeStamp(
                secs=int(stamp.get("secs", 0)),
                nsecs=int(stamp.get("nsecs", 0)),
            ),
            frame_id=str(header.get("frame_id", "velodyne")),
        )
        msg.height = int(data.get("height", 1))
        msg.width = int(data.get("width", 0))
        msg.fields = list(data.get("fields", []))
        msg.is_bigendian = bool(data.get("is_bigendian", False))
        msg.point_step = int(data.get("point_step", 12))
        msg.row_step = int(data.get("row_step", msg.width * msg.point_step))
        msg.data = bytes(data.get("data", b""))
        msg.is_dense = bool(data.get("is_dense", True))
        return msg

    def serialize(self, buff) -> None:
        buff.write(self.data)

    def deserialize(self, payload: bytes) -> None:
        self.data = payload


def generate_xyz_points() -> List[PointXYZ]:
    points: List[PointXYZ] = []
    for xi in range(20):
        x = -2.5 + xi * (5.0 / 19.0)
        for yi in range(20):
            y = -2.5 + yi * (5.0 / 19.0)
            points.append((round(x, 4), round(y, 4), 0.0))

    for zi in range(20):
        z = zi * (1.5 / 19.0)
        points.append((1.0, 0.5, round(z, 4)))

    return points


def pack_xyz_points(points: List[PointXYZ]) -> bytes:
    payload = bytearray()
    for x, y, z in points:
        payload.extend(struct.pack("<fff", x, y, z))
    return bytes(payload)


def build_pointcloud2_dict(
    frame_id: str = "velodyne",
    seq: int = 0,
    stamp: dict = None,
) -> dict:
    points = generate_xyz_points()
    data = pack_xyz_points(points)
    stamp_data = stamp or {"secs": 0, "nsecs": 0}
    return {
        "_msg_type": "sensor_msgs/PointCloud2",
        "header": {
            "seq": int(seq),
            "stamp": stamp_data,
            "frame_id": frame_id,
        },
        "height": 1,
        "width": len(points),
        "fields": [
            {"name": "x", "offset": 0, "datatype": 7, "count": 1},
            {"name": "y", "offset": 4, "datatype": 7, "count": 1},
            {"name": "z", "offset": 8, "datatype": 7, "count": 1},
        ],
        "is_bigendian": False,
        "point_step": 12,
        "row_step": len(data),
        "data": data,
        "is_dense": True,
    }


def serialize_fake_pointcloud2(msg: FakePointCloud2Message) -> bytes:
    return bytes(msg.data)
```

- [x] **步骤 4：运行 mock 数据测试验证通过**

运行：

```bash
python3 -m pytest tests/test_mock_pointcloud2_data.py -q
```

预期：全部通过。

- [x] **步骤 5：Commit**

```bash
git add agent/mock_pointcloud2_data.py tests/test_mock_pointcloud2_data.py
git commit -m "test: 增加 mock PointCloud2 数据工具"
```

## 任务 2：扩展 SensorMetaData 协议字段

**文件：**
- 修改：`protocol/messages.py`
- 测试：`tests/test_protocol_messages.py`

- [x] **步骤 1：编写失败的测试**

在 `tests/test_protocol_messages.py` 增加：

```python
def test_sensor_meta_message_includes_heavy_snapshot_fields(self, factory):
    meta = SensorMetaData(
        topic="/velodyne_points",
        msg_type="sensor_msgs/PointCloud2",
        transport="http_stream",
        stream_url="http://192.168.1.10:8080/stream/velodyne_points",
        size_bytes=2048000,
        seq=12,
        stamp={"secs": 1782370000, "nsecs": 120000000},
        frame_id="velodyne",
        encoding="ros1_serialized_v1",
        payload_format="ros1_serialized",
        payload_size=2048000,
    )

    msg = factory.sensor_meta(meta)

    assert msg.type == MessageType.SENSOR_META
    assert msg.data["stream_url"].startswith("http://")
    assert msg.data["seq"] == 12
    assert msg.data["stamp"]["secs"] == 1782370000
    assert msg.data["frame_id"] == "velodyne"
    assert msg.data["encoding"] == "ros1_serialized_v1"
    assert msg.data["payload_format"] == "ros1_serialized"
    assert msg.data["payload_size"] == 2048000
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_protocol_messages.py::TestMessageFactory::test_sensor_meta_message_includes_heavy_snapshot_fields -q
```

预期：失败，原因是 `SensorMetaData` 尚未定义这些字段。

- [x] **步骤 3：扩展 SensorMetaData**

在 `protocol/messages.py` 中将 `SensorMetaData` 改为：

```python
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
```

- [x] **步骤 4：运行协议消息测试验证通过**

运行：

```bash
python3 -m pytest tests/test_protocol_messages.py -q
```

预期：全部通过。

- [x] **步骤 5：Commit**

```bash
git add protocol/messages.py tests/test_protocol_messages.py
git commit -m "feat: 扩展重型数据 meta 字段"
```

## 任务 3：将 PointCloud2 注册为 HEAVY

**文件：**
- 修改：`protocol/topic_registry.py`
- 测试：`tests/test_protocol_registry.py`

- [ ] **步骤 1：编写失败的测试**

更新或新增以下测试：

```python
def test_pointcloud2_is_heavy_http_stream():
    info = default_registry.get("sensor_msgs/PointCloud2")

    assert info.tier == TopicTier.HEAVY
    assert default_registry.get_transport_type("sensor_msgs/PointCloud2") == "http_stream"
    assert info.default_freq_limit == 2
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_protocol_registry.py::test_pointcloud2_is_heavy_http_stream -q
```

预期：失败，原因是当前 `sensor_msgs/PointCloud2` 注册为 `MEDIUM`。

- [ ] **步骤 3：修改 registry**

在 `protocol/topic_registry.py` 中将 PointCloud2 条目改为：

```python
"sensor_msgs/PointCloud2": TopicInfo(
    "sensor_msgs/PointCloud2", TopicTier.HEAVY, "3D点云",
    default_freq_limit=2,
),
```

保留 `sensor_msgs/PointCloud` 为 `MEDIUM`，除非后续单独验证旧点云类型。

- [ ] **步骤 4：运行 registry 测试验证通过**

运行：

```bash
python3 -m pytest tests/test_protocol_registry.py -q
```

预期：全部通过。如有旧测试断言 PointCloud2 为 `MEDIUM`，同步改为 `HEAVY/http_stream`。

- [ ] **步骤 5：Commit**

```bash
git add protocol/topic_registry.py tests/test_protocol_registry.py
git commit -m "config: 将 PointCloud2 归入重型数据通道"
```

## 任务 4：Agent 支持 heavy snapshot 缓存与 meta 发布

**文件：**
- 修改：`agent/base_agent.py`
- 测试：`tests/test_agent_topic_config.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_agent_topic_config.py` 中增加：

```python
def test_publish_heavy_snapshot_data_stores_stream_and_publishes_meta():
    from agent.mock_pointcloud2_data import FakePointCloud2Message, build_pointcloud2_dict

    agent = RecordingAgent(AgentConfig(robot_id="robot_001", http_stream_port=18080))
    agent.config.stream_public_host = "10.0.0.2"
    agent._subscribed_topics["/velodyne_points"] = {
        "msg_type": "sensor_msgs/PointCloud2",
        "freq_limit": 2.0,
        "transport": "http_stream",
        "qos": 0,
        "options": {},
    }
    agent._stream_data = {}

    data = build_pointcloud2_dict(
        frame_id="velodyne",
        seq=7,
        stamp={"secs": 1, "nsecs": 2},
    )
    msg = FakePointCloud2Message.from_dict(data)
    raw_payload = bytes(msg.data)

    agent.publish_heavy_snapshot_data(
        "/velodyne_points",
        "sensor_msgs/PointCloud2",
        raw_payload,
        seq=msg.header.seq,
        stamp={"secs": msg.header.stamp.secs, "nsecs": msg.header.stamp.nsecs},
        frame_id=msg.header.frame_id,
    )

    assert agent._stream_data["/velodyne_points"] == raw_payload
    topic, meta_payload, qos, retain = agent.published[-1]
    assert topic == "robot/robot_001/sensor/velodyne_points/meta"
    assert qos == 0
    assert retain is False
    assert meta_payload["type"] == "sensor_meta"
    assert meta_payload["data"]["topic"] == "/velodyne_points"
    assert meta_payload["data"]["msg_type"] == "sensor_msgs/PointCloud2"
    assert meta_payload["data"]["transport"] == "http_stream"
    assert meta_payload["data"]["stream_url"] == "http://10.0.0.2:18080/stream/velodyne_points"
    assert meta_payload["data"]["encoding"] == "ros1_serialized_v1"
    assert meta_payload["data"]["payload_format"] == "ros1_serialized"
    assert meta_payload["data"]["payload_size"] == len(raw_payload)
    assert meta_payload["data"]["seq"] == 7
    assert meta_payload["data"]["stamp"] == {"secs": 1, "nsecs": 2}
    assert meta_payload["data"]["frame_id"] == "velodyne"
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_agent_topic_config.py::test_publish_heavy_snapshot_data_stores_stream_and_publishes_meta -q
```

预期：失败，原因是 `publish_heavy_snapshot_data()` 尚未实现，`AgentConfig` 也没有 `stream_public_host` 字段。

- [ ] **步骤 3：扩展 AgentConfig**

在 `agent/base_agent.py` 的 `AgentConfig` 中新增：

```python
stream_public_host: str = ""  # Bridge 可访问的 HTTP stream host
stream_base_url: str = ""     # 显式覆盖完整 stream base URL，例如 http://host:8080
```

在 `AgentConfig.from_yaml()` 中：

```python
"stream_public_host", "stream_base_url",
```

并设置：

```python
stream_public_host=raw.get("stream_public_host", ""),
stream_base_url=raw.get("stream_base_url", ""),
```

- [ ] **步骤 4：实现 stream URL 构造**

在 `agent/base_agent.py` 中新增：

```python
    def _get_stream_base_url(self) -> str:
        if self.config.stream_base_url:
            return self.config.stream_base_url.rstrip("/")
        host = self.config.stream_public_host or self._get_local_ip()
        return f"http://{host}:{self.config.http_stream_port}"

    def _get_stream_url(self, ros_topic: str) -> str:
        name = ros_topic.lstrip("/")
        return f"{self._get_stream_base_url()}/stream/{name}"
```

- [ ] **步骤 5：实现 heavy snapshot 发布 helper**

在 `agent/base_agent.py` 中新增：

```python
    def publish_heavy_snapshot_data(
        self,
        ros_topic: str,
        msg_type: str,
        payload: bytes,
        seq: Optional[int] = None,
        stamp: Optional[dict] = None,
        frame_id: str = "",
        retain: bool = False,
    ) -> None:
        if ros_topic not in self._subscribed_topics:
            return
        if not self._rate_limiter.can_send(ros_topic):
            return

        sub_info = self._subscribed_topics[ros_topic]
        qos = int(sub_info.get("qos", 0))
        self._store_stream_data(ros_topic, payload)
        self._start_stream_server()

        meta_msg = self._factory.sensor_meta(SensorMetaData(
            topic=ros_topic,
            msg_type=msg_type,
            transport="http_stream",
            stream_url=self._get_stream_url(ros_topic),
            size_bytes=len(payload),
            seq=seq if seq is not None else int(time.time() * 1000),
            stamp=stamp or {},
            frame_id=frame_id,
            encoding="ros1_serialized_v1",
            payload_format="ros1_serialized",
            payload_size=len(payload),
        ))
        meta_topic = robot_sensor_meta(self.config.robot_id, ros_topic)
        self._mqtt_publish(
            meta_topic,
            meta_msg.to_json().encode("utf-8"),
            qos=qos,
            retain=retain,
        )
        self._rate_limiter.mark_sent(ros_topic)
```

- [ ] **步骤 6：运行 Agent 配置测试验证通过**

运行：

```bash
python3 -m pytest tests/test_agent_topic_config.py -q
```

预期：全部通过。

- [ ] **步骤 7：Commit**

```bash
git add agent/base_agent.py tests/test_agent_topic_config.py
git commit -m "feat: 支持重型数据 HTTP snapshot meta"
```

## 任务 5：ROS1 Agent 对 PointCloud2 走 heavy snapshot

**文件：**
- 修改：`agent/ros1_agent.py`
- 测试：`tests/test_ros1_agent.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_ros1_agent.py` 中增加：

```python
def test_pointcloud2_uses_heavy_snapshot_path(monkeypatch):
    from agent.mock_pointcloud2_data import FakePointCloud2Message, build_pointcloud2_dict

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
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py::test_pointcloud2_uses_heavy_snapshot_path -q
```

预期：失败，原因是 `ROS1Agent` 还没有 `http_stream` 分支。

- [ ] **步骤 3：实现 header stamp helper**

在 `agent/ros1_agent.py` 中新增：

```python
    @staticmethod
    def _message_stamp(msg) -> dict:
        header = getattr(msg, "header", None)
        stamp = getattr(header, "stamp", None)
        if stamp is None:
            return {}
        return {
            "secs": int(getattr(stamp, "secs", 0)),
            "nsecs": int(getattr(stamp, "nsecs", 0)),
        }

    @staticmethod
    def _message_frame_id(msg) -> str:
        header = getattr(msg, "header", None)
        return str(getattr(header, "frame_id", "") or "")
```

- [ ] **步骤 4：实现 http_stream 分支**

在 `_on_topic_subscribed()` callback 中，放在 ROS1 serialized fast path 之前：

```python
            if tr == "http_stream" and mt == "sensor_msgs/PointCloud2":
                raw_payload = self._serialize_ros_message(msg)
                if raw_payload is not None:
                    self.publish_heavy_snapshot_data(
                        t,
                        mt,
                        raw_payload,
                        seq=self._message_seq(msg),
                        stamp=self._message_stamp(msg),
                        frame_id=self._message_frame_id(msg),
                    )
                    return
```

- [ ] **步骤 5：运行 ROS1 Agent 测试验证通过**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py -q
```

预期：全部通过。

- [ ] **步骤 6：Commit**

```bash
git add agent/ros1_agent.py tests/test_ros1_agent.py
git commit -m "feat: 支持 PointCloud2 HTTP snapshot 发布"
```

## 任务 6：Bridge 拉取 heavy snapshot 并发布 ROS topic

**文件：**
- 修改：`bridge/mqtt_ros_bridge.py`
- 测试：`tests/test_mqtt_ros_bridge.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_mqtt_ros_bridge.py` 增加：

```python
def test_sensor_meta_http_stream_fetches_and_publishes_pointcloud(monkeypatch):
    from agent.mock_pointcloud2_data import FakePointCloud2Message, build_pointcloud2_dict

    bridge = MqttRosBridge.__new__(MqttRosBridge)
    bridge._lock = threading.Lock()
    bridge._publishers_lock = threading.Lock()
    bridge._robots = {}
    bridge._topic_map = {"robot_001": {"velodyne_points": ("/velodyne_points", "sensor_msgs/PointCloud2")}}
    bridge._ros_publishers = {}
    bridge._namespace_tf_frames = True

    data = build_pointcloud2_dict(frame_id="velodyne", seq=5)
    raw_payload = bytes(data["data"])
    published = []

    fake_pub = MagicMock()
    fake_pub.publish.side_effect = lambda msg: published.append(msg)

    monkeypatch.setattr(
        "bridge.mqtt_ros_bridge._get_message_class",
        lambda msg_type: FakePointCloud2Message if msg_type == "sensor_msgs/PointCloud2" else None,
    )
    monkeypatch.setattr(
        bridge,
        "_get_or_create_typed_publisher",
        lambda topic, msg_class: fake_pub,
    )
    monkeypatch.setattr(bridge, "_wait_for_publisher_connection", lambda topic, pub: None)
    monkeypatch.setattr(
        bridge,
        "_fetch_heavy_payload",
        lambda url, expected_size=None: raw_payload,
    )

    payload = json.dumps({
        "type": "sensor_meta",
        "data": {
            "topic": "/velodyne_points",
            "msg_type": "sensor_msgs/PointCloud2",
            "transport": "http_stream",
            "stream_url": "http://robot:8080/stream/velodyne_points",
            "encoding": "ros1_serialized_v1",
            "payload_format": "ros1_serialized",
            "payload_size": len(raw_payload),
        },
    }).encode("utf-8")

    bridge._handle_sensor_meta("robot_001", "velodyne_points", payload)

    assert published
    assert published[0].data == raw_payload
    assert published[0].header.frame_id == "robot_001/velodyne"
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_mqtt_ros_bridge.py::test_sensor_meta_http_stream_fetches_and_publishes_pointcloud -q
```

预期：失败，原因是 `_handle_sensor_meta()` 目前只把 meta 转发为 JSON String，不会拉取 HTTP payload。

- [ ] **步骤 3：实现 HTTP 拉取 helper**

在 `bridge/mqtt_ros_bridge.py` 中新增：

```python
    @staticmethod
    def _fetch_heavy_payload(stream_url: str, expected_size: Optional[int] = None) -> bytes:
        from urllib.request import urlopen

        with urlopen(stream_url, timeout=2.0) as response:
            payload = response.read()
        if expected_size is not None and expected_size > 0 and len(payload) != expected_size:
            raise ValueError(
                "HTTP stream payload size mismatch: expected %d, got %d"
                % (expected_size, len(payload))
            )
        return payload
```

- [ ] **步骤 4：实现 heavy meta 处理**

将 `_handle_sensor_meta()` 改为：

```python
    def _handle_sensor_meta(
        self, robot_id: str, sensor_name: str, payload: bytes
    ) -> None:
        try:
            message = Message.from_json(payload.decode("utf-8"))
            meta = message.data if isinstance(message.data, dict) else {}
        except Exception as e:
            logger.error("[Bridge] Failed to decode sensor meta from %s/%s: %s", robot_id, sensor_name, e)
            return

        if meta.get("transport") != "http_stream":
            self._publish_as_json(f"/{robot_id}/{sensor_name}/meta", payload.decode("utf-8", errors="replace"))
            return

        msg_type = str(meta.get("msg_type", ""))
        stream_url = str(meta.get("stream_url", ""))
        if not msg_type or not stream_url:
            logger.warning("[Bridge] Incomplete heavy meta for %s/%s", robot_id, sensor_name)
            return

        try:
            raw_payload = self._fetch_heavy_payload(
                stream_url,
                expected_size=int(meta.get("payload_size") or meta.get("size_bytes") or 0),
            )
            ros_msg = self._deserialize_ros_binary_message(
                {"msg_type": msg_type},
                raw_payload,
            )
            self._publish_ros_binary_sensor(
                robot_id,
                sensor_name,
                {
                    "topic": meta.get("topic", "/" + sensor_name),
                    "msg_type": msg_type,
                },
                ros_msg,
                payload_size=len(raw_payload),
                total_start=time.monotonic(),
                decode_ms=0.0,
            )
        except Exception as e:
            logger.error("[Bridge] Failed to fetch/publish heavy sensor %s/%s: %s", robot_id, sensor_name, e)
```

注意：如果实现时希望保留 `_handle_sensor_meta()` 的旧 JSON 转发能力，可以将旧逻辑提取为 `_publish_sensor_meta_as_json()`。

- [ ] **步骤 5：运行 Bridge 测试验证通过**

运行：

```bash
python3 -m pytest tests/test_mqtt_ros_bridge.py -q
```

预期：全部通过。

- [ ] **步骤 6：Commit**

```bash
git add bridge/mqtt_ros_bridge.py tests/test_mqtt_ros_bridge.py
git commit -m "feat: 支持 Bridge 拉取重型 HTTP snapshot"
```

## 任务 7：配置示例与前端保护

**文件：**
- 修改：`agent/configs/turtlebot_001.yaml`
- 修改：`qt_frontend/config/transmit_config.yaml`
- 修改：`qt_frontend/mqtt_client.py`
- 测试：`tests/test_mqtt_client.py`

- [ ] **步骤 1：编写前端保护测试**

在 `tests/test_mqtt_client.py` 增加：

```python
def test_sensor_meta_does_not_emit_sensor_data(client, mock_paho):
    received = []
    client.signals.sensor_data_received.connect(
        lambda robot_id, sensor_name, data: received.append((robot_id, sensor_name, data))
    )

    payload = json.dumps({
        "type": "sensor_meta",
        "data": {
            "topic": "/velodyne_points",
            "msg_type": "sensor_msgs/PointCloud2",
            "transport": "http_stream",
            "stream_url": "http://robot:8080/stream/velodyne_points",
        },
    }).encode("utf-8")

    msg = MagicMock()
    msg.topic = "robot/robot_001/sensor/velodyne_points/meta"
    msg.payload = payload

    client._on_message(None, None, msg)

    assert received == []
```

- [ ] **步骤 2：运行测试验证失败或确认现状**

运行：

```bash
python3 -m pytest tests/test_mqtt_client.py::test_sensor_meta_does_not_emit_sensor_data -q
```

预期：如果当前前端已经不把 `sensor_meta` 当普通 sensor 数据，则通过；如果失败，说明需要补充保护。

- [ ] **步骤 3：补充前端忽略 sensor_meta**

如果步骤 2 失败，在 `qt_frontend/mqtt_client.py` 的 `_on_message()` 中，在普通 sensor 分支前增加：

```python
            if robot_info and robot_info.get("type") == "sensor_meta":
                logger.debug("[MqttClient] Ignoring heavy sensor meta on %s", msg.topic)
                return
```

- [ ] **步骤 4：配置示例**

在 `agent/configs/turtlebot_001.yaml` 中新增或保留注释示例：

```yaml
# Bridge 可访问的 HTTP stream host；Docker 场景下不要使用容器内部 IP。
# stream_public_host: "192.168.1.101"
# stream_base_url: "http://192.168.1.101:8080"

# - topic: /velodyne_points
#   msg_type: sensor_msgs/PointCloud2
#   freq_limit: 2.0
#   transport: http_stream
#   qos: 0
#   compression: {}
```

在 `qt_frontend/config/transmit_config.yaml` 中新增注释示例，不默认启用：

```yaml
# - topic: /velodyne_points
#   msg_type: sensor_msgs/PointCloud2
#   freq_limit: 2.0
#   transport: http_stream
#   qos: 0
#   compression: {}
```

- [ ] **步骤 5：运行前端 MQTT 测试**

运行：

```bash
python3 -m pytest tests/test_mqtt_client.py -q
```

预期：全部通过。

- [ ] **步骤 6：Commit**

```bash
git add agent/configs/turtlebot_001.yaml qt_frontend/config/transmit_config.yaml qt_frontend/mqtt_client.py tests/test_mqtt_client.py
git commit -m "config: 增加重型数据 HTTP stream 示例"
```

## 任务 8：运行态验证

**文件：**
- 不修改代码；执行验证命令并记录结果。

- [ ] **步骤 1：启动链路**

运行：

```bash
docker compose up -d robot-turtlebot-001
./qt_frontend/scripts/start.sh
```

预期：容器、`roscore`、Mosquitto、Bridge、Qt 前端正常启动。

- [ ] **步骤 2：确认 PointCloud2 话题存在**

运行：

```bash
rostopic list | grep -E "points|cloud|velodyne"
```

预期：如果当前仿真环境没有点云话题，记录为“运行态 PointCloud2 需要实机或额外仿真传感器验证”，不要伪造通过结果。

- [ ] **步骤 3：订阅 PointCloud2**

如果存在 `/velodyne_points` 或其它 PointCloud2 话题，在配置中启用：

```yaml
- topic: /velodyne_points
  msg_type: sensor_msgs/PointCloud2
  freq_limit: 2.0
  transport: http_stream
  qos: 0
  compression: {}
```

重启链路后运行：

```bash
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/velodyne_points/meta -C 1
```

预期：收到 `type=sensor_meta`，`transport=http_stream`，`stream_url` 非空，`encoding=ros1_serialized_v1`。

- [ ] **步骤 4：验证 HTTP endpoint**

从 meta 中取出 `stream_url` 后运行：

```bash
curl -I "<stream_url>"
curl -o /tmp/pointcloud2.raw "<stream_url>"
wc -c /tmp/pointcloud2.raw
```

预期：HTTP 200，`wc -c` 与 meta 中 `payload_size` 一致。

- [ ] **步骤 5：验证 Bridge 本地 ROS 发布**

运行：

```bash
timeout 12 rostopic hz /turtlebot_001/velodyne_points
timeout 8 rostopic echo -n 1 /turtlebot_001/velodyne_points/header
```

预期：

- 本地 ROS topic 有数据。
- `header.frame_id` 已带 `turtlebot_001/` 前缀。

- [ ] **步骤 6：验证 RViz**

在 RViz 中添加 `PointCloud2` Display，订阅：

```text
/turtlebot_001/velodyne_points
```

预期：如果有真实点云数据，RViz 能显示点云；如果没有点云话题，则记录为环境缺口。

- [ ] **步骤 7：关闭链路**

运行：

```bash
./qt_frontend/scripts/stop.sh
```

预期：Bridge、Qt 前端和地面站本地进程清理完成。

## 任务 9：工作日志与计划状态

**文件：**
- 创建或修改：`docs/work-log-YYYY-MM-DD.md`
- 修改：`docs/superpowers/plans/2026-06-25-heavy-data-http-stream.md`

- [ ] **步骤 1：新增当天工作日志**

工作日志应包含：

- 为什么不使用 MQTT 大包承载 PointCloud2。
- HTTP snapshot 的数据流。
- Agent meta、HTTP endpoint、Bridge 拉取、ROS 发布的实现范围。
- 单元测试命令和结果。
- 运行态是否有真实 PointCloud2 环境；如没有，明确未验证风险。

- [ ] **步骤 2：勾选本计划已完成任务**

按实际完成情况将本计划中的 `- [ ]` 改为 `- [x]`。

- [ ] **步骤 3：Commit**

```bash
git add docs/work-log-YYYY-MM-DD.md docs/superpowers/plans/2026-06-25-heavy-data-http-stream.md
git commit -m "docs: 记录重型数据 HTTP 通道进展"
```

## 最终验证命令

单元测试：

```bash
python3 -m pytest tests/test_mock_pointcloud2_data.py tests/test_protocol_messages.py tests/test_protocol_registry.py tests/test_agent_topic_config.py tests/test_ros1_agent.py tests/test_mqtt_ros_bridge.py tests/test_mqtt_client.py -q
```

预期：全部通过。

运行态验证：

```bash
docker compose up -d robot-turtlebot-001
./qt_frontend/scripts/start.sh
rostopic list | grep -E "points|cloud|velodyne"
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/velodyne_points/meta -C 1
curl -I "<stream_url>"
curl -o /tmp/pointcloud2.raw "<stream_url>"
wc -c /tmp/pointcloud2.raw
timeout 12 rostopic hz /turtlebot_001/velodyne_points
timeout 8 rostopic echo -n 1 /turtlebot_001/velodyne_points/header
./qt_frontend/scripts/stop.sh
```

预期：在存在 PointCloud2 数据源的环境中，MQTT meta、HTTP payload、Bridge ROS 发布和 RViz 显示链路都能闭环。如果当前 Turtlebot3 仿真没有 PointCloud2 话题，运行态验证只能完成“无数据源确认”，不能宣称点云显示通过。

## 不在第一版处理

- 不支持高帧率图像流。
- 不做 HTTP 长连接、WebSocket、GStreamer 或 WebRTC。
- 不做点云体素降采样或压缩。
- 不做历史帧查询，只保留最新一帧。
- 不改变机器人 ROS 网络与地面站 ROS master 隔离边界。
- 不让 PyQt/RViz 直接访问 HTTP；HTTP 只在 Agent 与 Bridge 之间使用。
