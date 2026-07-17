# 机器人 Agent 间编队 ROS1 Serialized 传输实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 让机器人 Agent 之间的编队 ROS topic 转发按 `fleet_rules.transport` 选择 `mqtt_json` 或 `mqtt_binary`，其中 binary 路径直接传输 ROS1 serialized bytes，源端序列化或 MD5 获取失败时自动回退 JSON。

**架构：** 源 `ROS1Agent` 按源 topic 合并规则，只订阅和转换一次，然后通过 `robot/{src}/to/{dst}` JSON envelope 与 `/bin` body 向目标 Agent 发送。`BaseAgent` 负责 MQTT 原始分流、协议校验、TTL 和有界配对缓存，目标 `ROS1Agent` 负责 MD5 校验、ROS 反序列化、frame 策略及目标 ROS topic 发布。地面站 Bridge、普通 sensor 数据面和 RViz 不参与此链路。

**技术栈：** Python 3.8、ROS Noetic `rospy` message `serialize()` / `deserialize()`、paho-mqtt 2.x、MQTT JSON envelope + binary body、PyQt5、pytest、ruff。

---

## 术语与执行约定

- **Agent 间编队链路**：源机器人 ROS topic 经源 Agent、共享 MQTT Broker 和目标 Agent，最终发布到目标机器人本地 ROS master。它不是 Agent 到地面站 Bridge 的 sensor 链路。
- **route**：一条规则展开到单个 target 后的实际发送单元，包含 `src_topic`、`msg_type`、`robot_id`、`dst_topic`、`freq_limit`、`transport`、`qos` 和 `frame_policy`。
- **binary envelope**：`type=fleet_data` 的统一 JSON `Message`，`data.binary=true`，携带 route、`transfer_id`、`payload_size`、ROS MD5、TTL 和 encoding，不携带 ROS 字段 payload。
- **binary body**：13 字节 `FRB1` 关联头加 ROS1 serialized bytes，经 `robot/{src}/to/{dst}/bin` 发送。
- **`transfer_id`**：32 位随机 session nonce 与 32 位递增计数组成的 64 位整数。每个到期 route 独立生成；同一次 ROS 回调只复用 serialized bytes，不复用 transfer ID。
- **ROS MD5**：源端 `type(msg)._md5sum` 与目标端 message class `_md5sum` 必须都是非空字符串且完全一致。源端缺失时回退 JSON；目标端缺失或不一致时丢弃 binary transfer。
- **TTL**：现有 ROS topic 编队消息固定 `ttl=1.0`。binary envelope 入缓存前检查一次，配对完成并释放锁后再检查一次；JSON fleet 消息在回调子类前检查一次。TTL 使用 `Message.ts`，运行环境需要时钟同步。
- **serialized 失败回退**：仅 ROS serialize、ROS MD5 获取或随后的 JSON 转换阶段决定。MQTT `publish().rc` 失败不得触发 JSON 回退，因为 QoS 1 消息仍可能在 Paho 内部队列中重连后送达。
- **缓存边界**：envelope/body 单侧 2 秒、各 256 条、单 body 8 MiB、body 总量 64 MiB。缓存锁内只清理、写入、配对、弹出和更新计数，ROS hook 必须锁外调用。
- **QoS 默认策略**：旧规则缺失字段及 Qt 新建规则默认 `mqtt_json + qos: 1`；高频连续状态由用户显式选择 `mqtt_binary + qos: 0`。
- **运行态配置保护**：执行前检查 `git status --short`。只修改本计划列出的文件；`agent/configs/husky_001.yaml`、`qt_frontend/config/transmit_config.yaml` 等已有用户改动不得覆盖或回滚，配置示例只对目标 fleet 段做最小合并。

## 文件职责

- 修改 `protocol/messages.py`
  - 定义 `FleetBinaryEnvelopeData`、严格 `from_dict()` 校验及 `MessageFactory.fleet_binary_envelope()`。
- 修改 `protocol/topics.py`
  - 定义 Agent 间 `/bin` topic、订阅通配符和精确段数解析。
- 修改 `protocol/binary_payloads.py`
  - 定义 `FRB1` 关联头 encode/decode helper，不引入 ROS 依赖。
- 修改 `agent/base_agent.py`
  - 规范化 fleet transport/QoS/重复 target，生成 transfer ID，返回 MQTT rc 结果，发布 binary，原始 MQTT 分流，执行 TTL 与有界配对。
- 修改 `agent/ros1_agent.py`
  - 合并源规则、独立 route 限频、一次 serialize/dict、JSON 回退、目标 ROS deserialize/MD5/frame/publisher。
- 修改 `agent/mock_agent.py`
  - 提供无 ROS binary hook，保证 MockAgent 仍可实例化和测试。
- 修改 `qt_frontend/panels/fleet_comm_panel.py`
  - 增加 transport/QoS 表格列、表单控件、保存、下发和回填。
- 修改 `agent/configs/default.yaml`、`agent/configs/turtlebot_001.yaml`、`agent/configs/turtlebot_002.yaml`、`qt_frontend/config/transmit_config.yaml`
  - 更新禁用状态的 fleet 示例；保持现有运行态开关不变。
- 修改 `tests/test_protocol_messages.py`、`tests/test_protocol_topics.py`、`tests/test_binary_payloads.py`
  - 覆盖纯协议模型、topic 和关联头。
- 修改 `tests/test_agent_topic_config.py`
  - 覆盖 BaseAgent 配置、发布、原始分流、TTL、缓存和资源边界。
- 修改 `tests/test_ros1_agent.py`
  - 覆盖源 route 聚合、一次转换、回退、目标 deserialize、MD5 和 frame。
- 修改 `tests/test_panels.py`
  - 覆盖 fleet transport/QoS 的 Qt 逻辑和控件。
- 创建或修改 `docs/work-log-2026-07-17.md`
  - 仅记录实际执行的测试、ROS/Docker/MQTT 现象和未验证风险。

### 任务 1：定义 Agent 间 Binary Envelope 与 MQTT Topic

**文件：**
- 修改：`protocol/messages.py`
- 修改：`protocol/topics.py`
- 测试：`tests/test_protocol_messages.py`
- 测试：`tests/test_protocol_topics.py`

- [x] **步骤 1：编写 envelope 和 topic 失败测试**

在 `tests/test_protocol_messages.py` 导入 `FleetBinaryEnvelopeData`，新增：

```python
def test_fleet_binary_envelope_round_trip(factory):
    envelope = FleetBinaryEnvelopeData(
        transfer_id=0x1234567800000001,
        payload_size=736,
        md5sum="cd5e73d190d741a2f92e81eda573aca7",
        src_topic="/odom",
        dst_topic="/fleet/turtlebot_001/odom",
        msg_type="nav_msgs/Odometry",
        frame_policy="namespace",
        stamp=123.5,
        ttl=1.0,
    )

    message = factory.fleet_binary_envelope(envelope, dst="turtlebot_002")
    parsed = Message.from_json(message.to_json())
    restored = FleetBinaryEnvelopeData.from_dict(parsed.data)

    assert parsed.type == MessageType.FLEET_DATA
    assert parsed.dst == "turtlebot_002"
    assert restored.binary is True
    assert restored.transport == "mqtt_binary"
    assert restored.encoding == "ros1_serialized_v1"
    assert restored.transfer_id == 0x1234567800000001
    assert restored.md5sum == envelope.md5sum
```

新增参数化非法输入测试：

```python
@pytest.mark.parametrize("field,value", [
    ("transfer_id", True),
    ("transfer_id", -1),
    ("transfer_id", 1 << 64),
    ("payload_size", -1),
    ("md5sum", ""),
    ("md5sum", None),
    ("encoding", "unknown"),
    ("ttl", float("nan")),
])
def test_fleet_binary_envelope_rejects_invalid_fields(field, value):
    data = {
        "data_type": "ros_topic",
        "binary": True,
        "transport": "mqtt_binary",
        "encoding": "ros1_serialized_v1",
        "payload_format": "ros1_serialized",
        "transfer_id": 1,
        "payload_size": 4,
        "md5sum": "md5",
        "src_topic": "/odom",
        "dst_topic": "/fleet/r1/odom",
        "msg_type": "nav_msgs/Odometry",
        "frame_policy": "namespace",
        "stamp": 1.0,
        "ttl": 1.0,
    }
    data[field] = value

    with pytest.raises(ValueError):
        FleetBinaryEnvelopeData.from_dict(data)
```

在 `tests/test_protocol_topics.py` 导入新 helper，新增：

```python
def test_robot_to_robot_binary_topics():
    assert robot_to_robot_binary("r1", "r2") == "robot/r1/to/r2/bin"
    assert all_robot_to_robot_binary("r2") == "robot/+/to/r2/bin"


def test_parse_robot_to_robot_binary_requires_exact_segments():
    parsed = parse_robot_topic("robot/r1/to/r2/bin")
    assert parsed == {"robot_id": "r1", "type": "to_robot_binary", "dst_id": "r2"}
    assert parse_robot_topic("robot/r1/to/r2/bin/extra") is None
    assert parse_robot_topic("robot/r1/to/r2/meta/extra") is None
```

- [x] **步骤 2：运行测试验证目标符号缺失**

运行：

```bash
python3 -m pytest \
  tests/test_protocol_messages.py::test_fleet_binary_envelope_round_trip \
  tests/test_protocol_messages.py::test_fleet_binary_envelope_rejects_invalid_fields \
  tests/test_protocol_topics.py::test_robot_to_robot_binary_topics \
  tests/test_protocol_topics.py::test_parse_robot_to_robot_binary_requires_exact_segments -q
```

预期：收集阶段因 `FleetBinaryEnvelopeData`、`robot_to_robot_binary` 或 `all_robot_to_robot_binary` 尚未定义而失败；不应因 pytest fixture 或 ROS import 失败。

- [x] **步骤 3：实现结构化 envelope**

在 `protocol/messages.py` 增加 `math` import 和 dataclass：

```python
@dataclass
class FleetBinaryEnvelopeData:
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
        transfer_id = data.get("transfer_id")
        payload_size = data.get("payload_size")
        md5sum = data.get("md5sum")
        try:
            ttl = float(data.get("ttl", 1.0))
            stamp = float(data.get("stamp", 0.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("fleet envelope times must be numeric") from exc
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
        envelope = cls(
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
        return envelope
```

将该 dataclass 加入 `MessageFactory._make()` 的 dataclass 类型列表，并新增：

```python
def fleet_binary_envelope(
    self,
    envelope: FleetBinaryEnvelopeData,
    dst: str,
) -> Message:
    return self._make(MessageType.FLEET_DATA, envelope, dst=dst)
```

- [x] **步骤 4：实现精确 binary topic**

在 `protocol/topics.py` 增加：

```python
def robot_to_robot_binary(src_id: str, dst_id: str) -> str:
    return f"{ROBOT_PREFIX}/{src_id}/{_TO}/{dst_id}/{_BIN}"


def all_robot_to_robot_binary(dst_id: str) -> str:
    return f"{ROBOT_PREFIX}/+/{_TO}/{dst_id}/{_BIN}"
```

将 `_TO` 解析改为只接受 4 段主 topic 或 5 段且末段为 `bin`/`meta` 的 topic，其他段数返回 `None`。将 `to_robot_binary` 加入 parser 类型测试集合。

- [x] **步骤 5：运行协议模型和 topic 测试**

运行：

```bash
python3 -m pytest tests/test_protocol_messages.py tests/test_protocol_topics.py -q
```

预期：全部通过，现有 JSON fleet 和 `/meta` topic 测试不回归。

- [x] **步骤 6：提交协议模型与 topic**

```bash
git add protocol/messages.py protocol/topics.py tests/test_protocol_messages.py tests/test_protocol_topics.py
git commit -m "feat: 定义编队二进制消息协议"
```

### 任务 2：实现 Fleet Binary 关联头

**文件：**
- 修改：`protocol/binary_payloads.py`
- 测试：`tests/test_binary_payloads.py`

- [ ] **步骤 1：编写关联头失败测试**

在 `tests/test_binary_payloads.py` 导入新 helper，新增：

```python
def test_fleet_binary_payload_round_trip():
    framed = encode_fleet_binary_payload(0x1234567800000001, b"ros-body")
    transfer_id, body = decode_fleet_binary_payload(framed)

    assert framed[:4] == b"FRB1"
    assert len(framed) == 13 + len(body)
    assert transfer_id == 0x1234567800000001
    assert body == b"ros-body"


def test_fleet_binary_payload_accepts_empty_ros_body():
    transfer_id, body = decode_fleet_binary_payload(
        encode_fleet_binary_payload(1, b"")
    )
    assert transfer_id == 1
    assert body == b""


@pytest.mark.parametrize("payload", [
    b"",
    b"FRB1",
    b"BAD!\x01" + b"\x00" * 8,
    b"FRB1\x02" + b"\x00" * 8,
])
def test_fleet_binary_payload_rejects_invalid_headers(payload):
    with pytest.raises(ValueError):
        decode_fleet_binary_payload(payload)
```

- [ ] **步骤 2：运行测试验证 helper 缺失**

运行：

```bash
python3 -m pytest \
  tests/test_binary_payloads.py::test_fleet_binary_payload_round_trip \
  tests/test_binary_payloads.py::test_fleet_binary_payload_accepts_empty_ros_body \
  tests/test_binary_payloads.py::test_fleet_binary_payload_rejects_invalid_headers -q
```

预期：收集阶段因 `encode_fleet_binary_payload` 和 `decode_fleet_binary_payload` 尚未定义而失败。

- [ ] **步骤 3：实现固定 13 字节关联头**

在 `protocol/binary_payloads.py` 增加：

```python
_FLEET_BINARY_MAGIC = b"FRB1"
_FLEET_BINARY_VERSION = 1
_FLEET_BINARY_HEADER = struct.Struct(">4sBQ")


def encode_fleet_binary_payload(transfer_id: int, body: bytes) -> bytes:
    if isinstance(transfer_id, bool) or not isinstance(transfer_id, int):
        raise ValueError("transfer_id must be an integer")
    if not 0 <= transfer_id < (1 << 64):
        raise ValueError("transfer_id out of uint64 range")
    if not isinstance(body, bytes):
        raise TypeError("fleet binary body must be bytes")
    return _FLEET_BINARY_HEADER.pack(
        _FLEET_BINARY_MAGIC,
        _FLEET_BINARY_VERSION,
        transfer_id,
    ) + body


def decode_fleet_binary_payload(payload: bytes) -> Tuple[int, bytes]:
    if len(payload) < _FLEET_BINARY_HEADER.size:
        raise ValueError("fleet binary payload is truncated")
    magic, version, transfer_id = _FLEET_BINARY_HEADER.unpack_from(payload)
    if magic != _FLEET_BINARY_MAGIC:
        raise ValueError("invalid fleet binary magic")
    if version != _FLEET_BINARY_VERSION:
        raise ValueError("unsupported fleet binary version")
    return transfer_id, payload[_FLEET_BINARY_HEADER.size:]
```

- [ ] **步骤 4：运行 binary payload 全量测试**

运行：`python3 -m pytest tests/test_binary_payloads.py -q`

预期：全部通过；现有 sensor binary 与 ROS1 serialized helper 不回归。

- [ ] **步骤 5：提交关联头 helper**

```bash
git add protocol/binary_payloads.py tests/test_binary_payloads.py
git commit -m "feat: 增加编队二进制关联头"
```

### 任务 3：实现 BaseAgent 配置规范化与 Binary 发布

**文件：**
- 修改：`agent/base_agent.py`
- 修改：`tests/test_agent_topic_config.py`

- [ ] **步骤 1：更新 RecordingAgent 发布夹具并编写失败测试**

先将 `RecordingAgent._mqtt_publish()` 返回类型改为 `bool`，末尾 `return True`，避免后续测试因旧 fixture 返回 `None` 把成功发布误判为失败。

新增配置和 transfer ID 测试：

```python
def test_normalize_fleet_rules_preserves_qos_and_deduplicates_targets():
    rules = MockAgent._normalize_fleet_rules([{
        "enabled": True,
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "targets": [
            {"robot_id": "r2", "dst_topic": "/fleet/r1/odom"},
            {"robot_id": "r2", "dst_topic": "/fleet/r1/odom"},
        ],
        "freq_limit": 10.0,
        "transport": "mqtt_binary",
        "qos": 0,
        "frame_policy": "namespace",
    }])

    assert rules[0]["transport"] == "mqtt_binary"
    assert rules[0]["qos"] == 0
    assert rules[0]["targets"] == [
        {"robot_id": "r2", "dst_topic": "/fleet/r1/odom"}
    ]


def test_fleet_transfer_ids_are_unique_and_roll_session_nonce(monkeypatch):
    nonces = iter([0x11111111, 0x22222222])
    monkeypatch.setattr("agent.base_agent.secrets.randbits", lambda bits: next(nonces))
    agent = RecordingAgent(AgentConfig(robot_id="r1"))
    first = agent._next_fleet_transfer_id()
    agent._fleet_transfer_counter = 0xFFFFFFFF
    wrapped = agent._next_fleet_transfer_id()

    assert first == 0x1111111100000001
    assert wrapped == 0x2222222200000001
```

新增发布测试：

```python
def test_send_fleet_binary_publishes_envelope_and_body_with_route_qos():
    agent = RecordingAgent(AgentConfig(robot_id="r1"))
    envelope = FleetBinaryEnvelopeData(
        transfer_id=7,
        payload_size=4,
        md5sum="md5",
        src_topic="/odom",
        dst_topic="/fleet/r1/odom",
        msg_type="nav_msgs/Odometry",
        ttl=1.0,
    )
    body = encode_fleet_binary_payload(7, b"body")

    result = agent.send_fleet_binary_to_robot("r2", envelope, body, qos=0)

    assert result == (True, True)
    assert agent.published[0][0] == "robot/r1/to/r2"
    assert agent.published[0][2] == 0
    assert agent.published[1] == ("robot/r1/to/r2/bin", body, 0, False)
```

- [ ] **步骤 2：运行测试验证缺失行为**

运行：

```bash
python3 -m pytest \
  tests/test_agent_topic_config.py::test_normalize_fleet_rules_preserves_qos_and_deduplicates_targets \
  tests/test_agent_topic_config.py::test_fleet_transfer_ids_are_unique_and_roll_session_nonce \
  tests/test_agent_topic_config.py::test_send_fleet_binary_publishes_envelope_and_body_with_route_qos -q
```

预期：因 fleet 规则尚未保留 QoS、transfer ID 和 binary 发送方法尚未实现而失败。

- [ ] **步骤 3：实现规范化和 transfer ID**

在 `agent/base_agent.py` 增加 `secrets` import，并将 typing import 扩展为包含 `Tuple`。

在 `BaseAgent.__init__()` 初始化：

```python
self._fleet_transfer_lock = threading.Lock()
self._fleet_session_nonce = secrets.randbits(32)
self._fleet_transfer_counter = 0
```

新增：

```python
def _next_fleet_transfer_id(self) -> int:
    with self._fleet_transfer_lock:
        if self._fleet_transfer_counter >= 0xFFFFFFFF:
            self._fleet_session_nonce = secrets.randbits(32)
            self._fleet_transfer_counter = 0
        self._fleet_transfer_counter += 1
        return (
            (self._fleet_session_nonce << 32)
            | self._fleet_transfer_counter
        )
```

修改 `_normalize_fleet_rules()`：transport 只保留 `mqtt_json`/`mqtt_binary`，非法值回落 JSON；QoS 只保留 0/1，非法值回落 1；使用 `seen_targets` 对 `(robot_id, dst_topic)` 去重。

- [ ] **步骤 4：实现 MQTT 返回值和 binary 发送**

在 `_init_mqtt()` 创建 client 后、连接前调用：

```python
self._mqtt_client.max_queued_messages_set(1000)
self._mqtt_client.max_inflight_messages_set(20)
```

将 `_mqtt_publish()` 改为：

```python
def _mqtt_publish(
    self,
    topic: str,
    payload: bytes,
    qos: int = 1,
    retain: bool = False,
) -> bool:
    if not self._mqtt_client or self.state not in (
        AgentState.CONNECTED,
        AgentState.RUNNING,
    ):
        return False
    info = self._mqtt_client.publish(topic, payload, qos=qos, retain=retain)
    return info.rc == mqtt.MQTT_ERR_SUCCESS
```

给 `send_to_robot()` 增加兼容默认参数 `qos: int = 1` 并返回 bool。新增：

```python
def send_fleet_binary_to_robot(
    self,
    target_id: str,
    envelope: FleetBinaryEnvelopeData,
    framed_body: bytes,
    qos: int,
) -> Tuple[bool, bool]:
    message = self._factory.fleet_binary_envelope(envelope, dst=target_id)
    envelope_ok = self._mqtt_publish(
        robot_to_robot(self.config.robot_id, target_id),
        message.to_json().encode("utf-8"),
        qos=qos,
    )
    body_ok = self._mqtt_publish(
        robot_to_robot_binary(self.config.robot_id, target_id),
        framed_body,
        qos=qos,
    )
    return envelope_ok, body_ok
```

- [ ] **步骤 5：增加 Paho client 配置和 rc 测试**

新增：

```python
def test_init_mqtt_sets_bounded_client_queues(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr("agent.base_agent.mqtt.Client", MagicMock(return_value=client))
    agent = RecordingAgent(AgentConfig(robot_id="r1"))

    agent._init_mqtt()

    client.max_queued_messages_set.assert_called_once_with(1000)
    client.max_inflight_messages_set.assert_called_once_with(20)


@pytest.mark.parametrize("rc,expected", [
    (mqtt.MQTT_ERR_SUCCESS, True),
    (mqtt.MQTT_ERR_NO_CONN, False),
    (mqtt.MQTT_ERR_QUEUE_SIZE, False),
])
def test_mqtt_publish_returns_paho_rc_status(rc, expected):
    agent = RecordingAgent(AgentConfig(robot_id="r1"))
    agent._mqtt_client = MagicMock()
    agent._mqtt_client.publish.return_value.rc = rc
    agent.state = AgentState.CONNECTED

    assert BaseAgent._mqtt_publish(
        agent, "robot/r1/test", b"payload"
    ) is expected
```

测试只验证 Paho rc，不断言最终 Broker 投递结果。补充 `pytest`、`MagicMock`、`paho.mqtt.client as mqtt`、`BaseAgent` 和 `AgentState` import。

- [ ] **步骤 6：运行 BaseAgent 发布与既有配置测试**

运行：

```bash
python3 -m pytest tests/test_agent_topic_config.py -q
```

预期：全部通过；现有 sensor JSON/binary/HTTP QoS 测试保持通过。

- [ ] **步骤 7：提交 BaseAgent 发送基础**

```bash
git add agent/base_agent.py tests/test_agent_topic_config.py
git commit -m "feat: 支持编队二进制发布"
```

### 任务 4：实现 BaseAgent 原始分流、TTL 与有界配对

**文件：**
- 修改：`agent/base_agent.py`
- 修改：`agent/mock_agent.py`
- 修改：`tests/test_agent_topic_config.py`

- [ ] **步骤 1：扩展 RecordingAgent binary hook 并编写乱序测试**

给 `RecordingAgent` 增加 `fleet_binary_messages`，并覆盖：

```python
def _on_fleet_binary_message(self, src_id, envelope, body) -> None:
    self.fleet_binary_messages.append((src_id, envelope, body))
```

新增 MQTT message fixture：

```python
class FakeMqttMessage:
    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload
```

新增 body 先到测试：

```python
def test_fleet_binary_pairs_when_body_arrives_before_envelope():
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    body = encode_fleet_binary_payload(7, b"body")
    envelope_message = MessageFactory("r1").fleet_binary_envelope(
        FleetBinaryEnvelopeData(
            transfer_id=7,
            payload_size=4,
            md5sum="md5",
            src_topic="/odom",
            dst_topic="/fleet/r1/odom",
            msg_type="nav_msgs/Odometry",
            ttl=1.0,
        ),
        dst="r2",
    )

    agent._on_message(None, None, FakeMqttMessage("robot/r1/to/r2/bin", body))
    agent._on_message(None, None, FakeMqttMessage(
        "robot/r1/to/r2",
        envelope_message.to_json().encode("utf-8"),
    ))

    assert agent.fleet_binary_messages[0][0] == "r1"
    assert agent.fleet_binary_messages[0][2] == b"body"
```

同时增加：

```python
def test_fleet_binary_pairs_when_envelope_arrives_before_body():
    agent, message = build_recording_agent_and_envelope(
        robot_id="r2", src_id="r1", transfer_id=12, body_size=4
    )
    agent._on_message(None, None, FakeMqttMessage(
        "robot/r1/to/r2", message.to_json().encode("utf-8")
    ))
    agent._on_message(None, None, FakeMqttMessage(
        "robot/r1/to/r2/bin", encode_fleet_binary_payload(12, b"body")
    ))
    assert agent.fleet_binary_messages[0][2] == b"body"


def test_fleet_binary_topic_bypasses_utf8_decode():
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    payload = encode_fleet_binary_payload(13, b"\xff\xfe")
    agent._on_message(None, None, FakeMqttMessage("robot/r1/to/r2/bin", payload))
    assert agent._fleet_body_cache[("r1", 13)][0] == b"\xff\xfe"


def test_fleet_main_topic_rejects_source_mismatch():
    agent, message = build_recording_agent_and_envelope(
        robot_id="r2", src_id="forged", transfer_id=14, body_size=4
    )
    agent._on_message(None, None, FakeMqttMessage(
        "robot/r1/to/r2", message.to_json().encode("utf-8")
    ))
    assert agent._fleet_envelope_cache == {}
```

在同一测试模块定义：

```python
def build_recording_agent_and_envelope(
    robot_id: str,
    src_id: str,
    transfer_id: int,
    body_size: int,
):
    agent = RecordingAgent(AgentConfig(robot_id=robot_id))
    message = MessageFactory(src_id).fleet_binary_envelope(
        FleetBinaryEnvelopeData(
            transfer_id=transfer_id,
            payload_size=body_size,
            md5sum="md5",
            src_topic="/odom",
            dst_topic="/fleet/%s/odom" % src_id,
            msg_type="nav_msgs/Odometry",
            ttl=0.0,
        ),
        dst=robot_id,
    )
    return agent, message
```

现有 `test_handle_fleet_message_preserves_ros_topic_fields` 继续作为 JSON fleet 回归测试，不删除其字段断言。

- [ ] **步骤 2：编写 TTL、锁外 hook 和资源边界测试**

通过 monkeypatch `time.time()` 和 `time.monotonic()` 覆盖：

```python
def test_fleet_binary_rechecks_ttl_after_pairing(monkeypatch):
    clock = {"wall": 100.5, "mono": 10.0}
    monkeypatch.setattr("agent.base_agent.time.time", lambda: clock["wall"])
    monkeypatch.setattr("agent.base_agent.time.monotonic", lambda: clock["mono"])
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    message = MessageFactory("r1").fleet_binary_envelope(
        FleetBinaryEnvelopeData(
            transfer_id=7,
            payload_size=4,
            md5sum="md5",
            src_topic="/odom",
            dst_topic="/fleet/r1/odom",
            msg_type="nav_msgs/Odometry",
            ttl=1.0,
        ),
        dst="r2",
    )
    message.ts = 100.0

    agent._handle_fleet_binary_envelope("r1", message)
    clock.update(wall=101.1, mono=10.6)
    agent._handle_fleet_binary_body(
        "r1", encode_fleet_binary_payload(7, b"body")
    )

    assert agent.fleet_binary_messages == []
    assert agent._fleet_envelope_cache == {}
    assert agent._fleet_body_cache == {}


def test_fleet_binary_hook_runs_without_cache_lock(monkeypatch):
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    lock_states = []

    def record_lock_state(src_id, envelope, body):
        acquired = agent._fleet_cache_lock.acquire(blocking=False)
        lock_states.append(acquired)
        if acquired:
            agent._fleet_cache_lock.release()

    agent._on_fleet_binary_message = record_lock_state
    message = MessageFactory("r1").fleet_binary_envelope(
        FleetBinaryEnvelopeData(
            transfer_id=8,
            payload_size=4,
            md5sum="md5",
            src_topic="/odom",
            dst_topic="/fleet/r1/odom",
            msg_type="nav_msgs/Odometry",
            ttl=0.0,
        ),
        dst="r2",
    )
    agent._handle_fleet_binary_envelope("r1", message)
    agent._handle_fleet_binary_body(
        "r1", encode_fleet_binary_payload(8, b"body")
    )

    assert lock_states == [True]


def test_fleet_binary_rejects_body_over_limit(monkeypatch):
    monkeypatch.setattr("agent.base_agent.FLEET_BODY_MAX_BYTES", 8)
    agent = RecordingAgent(AgentConfig(robot_id="r2"))

    agent._handle_fleet_binary_body(
        "r1", encode_fleet_binary_payload(9, b"123456789")
    )

    assert agent._fleet_body_cache == {}
    assert agent._fleet_body_cache_bytes == 0


def test_fleet_binary_evicts_oldest_body_to_keep_budget(monkeypatch):
    monkeypatch.setattr("agent.base_agent.FLEET_BODY_MAX_BYTES", 8)
    monkeypatch.setattr("agent.base_agent.FLEET_BODY_CACHE_MAX_BYTES", 8)
    agent = RecordingAgent(AgentConfig(robot_id="r2"))

    agent._handle_fleet_binary_body(
        "r1", encode_fleet_binary_payload(10, b"123456")
    )
    agent._handle_fleet_binary_body(
        "r1", encode_fleet_binary_payload(11, b"abcdef")
    )

    assert ("r1", 10) not in agent._fleet_body_cache
    assert agent._fleet_body_cache[("r1", 11)][0] == b"abcdef"
    assert agent._fleet_body_cache_bytes == 6
```

这些测试的 fixture 必须直接初始化测试所需 cache 常量或正常调用 `RecordingAgent.__init__()`，不能依赖 roscore。

- [ ] **步骤 3：运行测试验证 raw 分流和 cache 尚未实现**

运行：

```bash
python3 -m pytest tests/test_agent_topic_config.py -k "fleet_binary or fleet_message_ttl" -q
```

预期：因 `/bin` 仍被 UTF-8 解码、cache/hook/TTL helper 尚未实现而失败；现有 JSON fleet 测试仍能单独通过。

- [ ] **步骤 4：实现 cache 状态与订阅**

在 `BaseAgent.__init__()` 初始化：

```python
self._fleet_envelope_cache: Dict[
    Tuple[str, int],
    Tuple[Message, FleetBinaryEnvelopeData, float],
] = {}
self._fleet_body_cache: Dict[
    Tuple[str, int],
    Tuple[bytes, float],
] = {}
self._fleet_cache_lock = threading.Lock()
self._fleet_body_cache_bytes = 0
```

envelope tuple 固定为 `(message, envelope, inserted_monotonic)`；body tuple 固定为 `(ros_body, inserted_monotonic)`。后续任务和测试不得交换顺序。

定义模块常量：

```python
FLEET_CACHE_TTL_SECONDS = 2.0
FLEET_CACHE_MAX_ENTRIES = 256
FLEET_BODY_MAX_BYTES = 8 * 1024 * 1024
FLEET_BODY_CACHE_MAX_BYTES = 64 * 1024 * 1024
FLEET_MESSAGE_TTL_SECONDS = 1.0
FLEET_CLOCK_FUTURE_TOLERANCE_SECONDS = 5.0
```

在 `_on_connect()` 订阅 `all_robot_to_robot_binary(self.config.robot_id)`。

- [ ] **步骤 5：实现原始 MQTT 分流和主 topic 校验**

在 `agent/base_agent.py` 导入 `decode_fleet_binary_payload`、`FleetBinaryEnvelopeData`、`parse_robot_topic` 和 binary topic helper。重构 `_on_message()`：先 `parse_robot_topic(msg.topic)`；`to_robot_binary` 直接调用 `_handle_fleet_binary_body(src_id, msg.payload)`；其他消息才 UTF-8 decode。对 `to_robot` 主 topic 校验精确目标、`Message.type`、`Message.src`、`Message.dst`，再根据 `data.binary` 进入 envelope cache 或现有 JSON handler。

增加：

```python
def _on_fleet_binary_message(
    self,
    src_id: str,
    envelope: FleetBinaryEnvelopeData,
    body: bytes,
) -> None:
    return
```

`MockAgent` 覆盖该 hook，只记录 `src_id`、`msg_type`、`dst_topic` 和 body 长度，不尝试导入 ROS。

- [ ] **步骤 6：实现有限数值 TTL 和有界 cache**

实现 `_is_fleet_message_fresh(message_ts, ttl, now=None)`，拒绝 bool/非有限值、过期值和超过未来 5 秒的时间。实现 `_cache_fleet_envelope()`、`_cache_fleet_body()`、`_cleanup_fleet_cache_locked()` 与 `_take_fleet_pair_locked()`：

- 所有 cache 变更在 `_fleet_cache_lock` 内；
- body 入缓存前校验 8 MiB；
- 超过条数或 64 MiB 时按 monotonic 写入时间移除最早项；
- 配对时锁内弹出双方并扣减 body 字节数；
- 释放锁后校验尺寸、再次检查 TTL，最后调用 hook；
- `_check_and_publish_status()` 开头调用公开的 cache cleanup wrapper。

两个入口签名固定为：

```python
def _handle_fleet_binary_envelope(
    self,
    src_id: str,
    message: Message,
) -> None:
    envelope = FleetBinaryEnvelopeData.from_dict(message.data)
    if not self._is_fleet_message_fresh(message.ts, envelope.ttl):
        return
    pair = self._cache_fleet_envelope(src_id, message, envelope)
    self._dispatch_fleet_binary_pair(pair)


def _handle_fleet_binary_body(self, src_id: str, payload: bytes) -> None:
    transfer_id, body = decode_fleet_binary_payload(payload)
    pair = self._cache_fleet_body(src_id, transfer_id, body)
    self._dispatch_fleet_binary_pair(pair)
```

`_cache_fleet_envelope()` 和 `_cache_fleet_body()` 返回 `Optional[Tuple[Message, FleetBinaryEnvelopeData, bytes]]`。`_dispatch_fleet_binary_pair(None)` 直接返回；有值时在锁外校验 body 长度并二次 TTL，再调用 `_on_fleet_binary_message()`。

- [ ] **步骤 7：运行 BaseAgent 聚焦与回归测试**

运行：

```bash
python3 -m pytest tests/test_agent_topic_config.py -q
python3 -m pytest tests/test_protocol_topics.py tests/test_protocol_messages.py tests/test_binary_payloads.py -q
```

预期：全部通过；JSON fleet、config sync、普通 sensor 发布无回归。

- [ ] **步骤 8：提交 BaseAgent 接收数据面**

```bash
git add agent/base_agent.py agent/mock_agent.py tests/test_agent_topic_config.py
git commit -m "feat: 支持编队二进制接收配对"
```

### 任务 5：实现 ROS1Agent 源 Route 聚合与 JSON 回退

**文件：**
- 修改：`agent/ros1_agent.py`
- 测试：`tests/test_ros1_agent.py`

- [ ] **步骤 1：定义测试消息 MD5 并编写 route 聚合测试**

给测试消息增加 class 属性：

```python
class _SerializableRosMsg:
    _md5sum = "test-md5"

    def __init__(self, payload: bytes):
        self.payload = payload
        self.serialize_count = 0

    def serialize(self, buff):
        self.serialize_count += 1
        buff.write(self.payload)
```

新增测试，传入同一 `/odom` 的 JSON route、两个 binary route 和一个完全重复 route，断言：

```python
def test_apply_fleet_rules_groups_same_source_topic_into_one_subscriber(monkeypatch):
    mock_rospy = MagicMock()
    mock_rospy.Subscriber.return_value = MagicMock()
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    agent = object.__new__(ROS1Agent)
    agent._fleet_subscribers = {}
    agent._get_ros_msg_class = MagicMock(return_value=object)
    rules = [
        {
            "enabled": True,
            "src_topic": "/odom",
            "msg_type": "nav_msgs/Odometry",
            "targets": [{"robot_id": "r2", "dst_topic": "/fleet/r1/odom"}],
            "freq_limit": 10.0,
            "transport": "mqtt_json",
            "qos": 1,
            "frame_policy": "namespace",
        },
        {
            "enabled": True,
            "src_topic": "/odom",
            "msg_type": "nav_msgs/Odometry",
            "targets": [{"robot_id": "r3", "dst_topic": "/fleet/r1/odom"}],
            "freq_limit": 20.0,
            "transport": "mqtt_binary",
            "qos": 0,
            "frame_policy": "namespace",
        },
    ]

    ROS1Agent._apply_fleet_rules(agent, rules)
    assert mock_rospy.Subscriber.call_count == 1
    assert len(agent._fleet_subscribers) == 1


def test_fleet_callback_serializes_once_and_uses_unique_transfer_per_route(monkeypatch):
    agent = object.__new__(ROS1Agent)
    binary_send = MagicMock(return_value=(True, True))
    agent.send_fleet_binary_to_robot = binary_send
    agent.send_to_robot = MagicMock(return_value=True)
    agent._next_fleet_transfer_id = MagicMock(side_effect=[101, 102])
    routes = [
        _FleetRoute("r2", "/fleet/r1/odom", 0.0, "mqtt_binary", 0, "namespace"),
        _FleetRoute("r2", "/debug/r1/odom", 0.0, "mqtt_binary", 0, "preserve"),
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
    ids = [call.args[1].transfer_id for call in binary_send.call_args_list]
    assert len(set(ids)) == 2
```

增加分组纯逻辑测试：

```python
def test_group_fleet_routes_rejects_conflicting_types_for_same_topic():
    rules = [
        build_fleet_rule("/odom", "nav_msgs/Odometry", "r2", "/fleet/r1/odom"),
        build_fleet_rule("/odom", "geometry_msgs/PoseStamped", "r3", "/debug/odom"),
    ]
    assert ROS1Agent._group_fleet_routes(rules) == {}


def test_group_fleet_routes_deduplicates_identical_routes():
    rule = build_fleet_rule(
        "/odom", "nav_msgs/Odometry", "r2", "/fleet/r1/odom",
        transport="mqtt_binary", qos=0,
    )
    groups = ROS1Agent._group_fleet_routes([rule, dict(rule)])
    assert len(groups[("/odom", "nav_msgs/Odometry")]) == 1
```

在测试模块定义：

```python
def build_fleet_rule(
    src_topic,
    msg_type,
    target_id,
    dst_topic,
    transport="mqtt_json",
    qos=1,
):
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
```

- [ ] **步骤 2：编写 serialize/MD5 失败回退测试**

```python
def test_fleet_binary_serialize_failure_falls_back_to_json_once(monkeypatch):
    ros_msg_to_dict = MagicMock(return_value={"header": {"frame_id": "odom"}})
    monkeypatch.setattr("agent.ros1_agent.ros_msg_to_dict", ros_msg_to_dict)
    agent = object.__new__(ROS1Agent)
    json_send = MagicMock(return_value=True)
    binary_send = MagicMock(return_value=(True, True))
    agent.send_to_robot = json_send
    agent.send_fleet_binary_to_robot = binary_send
    routes = [
        _FleetRoute("r2", "/fleet/r1/odom", 0.0, "mqtt_binary", 0, "namespace")
    ]
    callback = ROS1Agent._make_fleet_forward_callback(
        agent, "/odom", "nav_msgs/Odometry", routes
    )

    callback(_UnserializableRosMsg())

    ros_msg_to_dict.assert_called_once()
    json_send.assert_called_once()
    binary_send.assert_not_called()


def test_fleet_binary_missing_md5_falls_back_to_json(monkeypatch):
    class NoMd5Message(_SerializableRosMsg):
        _md5sum = ""

    ros_msg_to_dict = MagicMock(return_value={"header": {"frame_id": "odom"}})
    monkeypatch.setattr("agent.ros1_agent.ros_msg_to_dict", ros_msg_to_dict)
    agent = object.__new__(ROS1Agent)
    agent.send_to_robot = MagicMock(return_value=True)
    agent.send_fleet_binary_to_robot = MagicMock(return_value=(True, True))
    routes = [
        _FleetRoute("r2", "/fleet/r1/odom", 0.0, "mqtt_binary", 0, "namespace")
    ]
    callback = ROS1Agent._make_fleet_forward_callback(
        agent, "/odom", "nav_msgs/Odometry", routes
    )

    callback(NoMd5Message(b"serialized-odom"))

    ros_msg_to_dict.assert_called_once()
    agent.send_to_robot.assert_called_once()
    agent.send_fleet_binary_to_robot.assert_not_called()
```

增加 publish rc 边界测试：

```python
def test_fleet_binary_publish_failure_does_not_fallback_to_json():
    agent = object.__new__(ROS1Agent)
    agent.send_to_robot = MagicMock(return_value=True)
    agent.send_fleet_binary_to_robot = MagicMock(return_value=(False, True))
    agent._next_fleet_transfer_id = MagicMock(return_value=31)
    route = _FleetRoute(
        "r2", "/fleet/r1/odom", 0.0, "mqtt_binary", 1, "namespace"
    )
    callback = ROS1Agent._make_fleet_forward_callback(
        agent, "/odom", "nav_msgs/Odometry", [route]
    )

    callback(_SerializableRosMsg(b"serialized-odom"))

    agent.send_fleet_binary_to_robot.assert_called_once()
    agent.send_to_robot.assert_not_called()
```

- [ ] **步骤 3：运行测试验证旧的一规则一 subscriber 实现失败**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py -k "fleet and (groups or serializes_once or falls_back or missing_md5)" -q
```

预期：因当前 `_apply_fleet_rules()` 为每条规则创建 subscriber、回调始终先转 dict 且不读 transport 而失败。

- [ ] **步骤 4：实现 `_FleetRoute` 和规则展开**

在 `agent/ros1_agent.py` 导入 `dataclass`，并将 typing import 扩展为包含 `Tuple`。定义私有 dataclass，全部类型兼容 Python 3.8：

```python
@dataclass
class _FleetRoute:
    target_id: str
    dst_topic: str
    freq_limit: float
    transport: str
    qos: int
    frame_policy: str
    last_sent: float = 0.0
```

实现 `_group_fleet_routes()`：按 `(src_topic, msg_type)` 分组，展开 targets，按 route 全字段去重；同一 topic 出现不同 msg type 时删除该 topic 的所有组并记录错误。

将 `_fleet_subscribers` 改为 `Dict[Tuple[str, str], object]`，每组只创建一个 subscriber。

- [ ] **步骤 5：实现一次转换和独立 route 限频**

导入 `FleetBinaryEnvelopeData`、`encode_fleet_binary_payload` 和 BaseAgent 中的固定 TTL 常量。

重写 `_make_fleet_forward_callback(src_topic, msg_type, routes)`：

1. 使用 `time.monotonic()` 计算每个 route 是否到期；
2. 将到期 route 的 `last_sent` 更新为当前值；
3. binary route 存在时调用 `_serialize_ros_message(msg)` 一次并读取 `type(msg)._md5sum`；
4. JSON route 存在或 binary 转换失败时调用 `ros_msg_to_dict(msg)` 最多一次；
5. JSON route 调用 `send_to_robot(route.target_id, fleet_data, qos=route.qos)`；
6. binary route 各自调用 `_next_fleet_transfer_id()`、`encode_fleet_binary_payload()` 和 `send_fleet_binary_to_robot()`；
7. 所有 route 固定 `ttl=FLEET_MESSAGE_TTL_SECONDS`；
8. serialize/MD5/JSON 失败告警按 `(src_topic, msg_type)` 每 10 秒限频。

修改 `_serialize_ros_message()`：捕获异常只返回 `None`，不在 helper 内逐条 warning。

同步改写现有 `test_fleet_rule_callback_sends_fleet_data` 和 `test_fleet_rule_callback_respects_freq_limit`：使用 `_FleetRoute` 列表调用新 callback；限频测试 monkeypatch `agent.ros1_agent.time.monotonic`，不能继续 patch `time.time`。JSON route 的原有 `FleetData` 字段断言全部保留，并新增 `qos=1` 调用断言。

- [ ] **步骤 6：运行 ROS1 源端和既有 sensor 测试**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py -q
python3 -m pytest tests/test_agent_topic_config.py -q
```

预期：全部通过；普通 Agent 到地面站 sensor serialized 路径测试保持通过。

- [ ] **步骤 7：提交 ROS1 源端 route**

```bash
git add agent/ros1_agent.py tests/test_ros1_agent.py
git commit -m "feat: 按传输方式转发编队数据"
```

### 任务 6：实现 ROS1Agent Binary 目标发布

**文件：**
- 修改：`agent/ros1_agent.py`
- 修改：`agent/mock_agent.py`
- 测试：`tests/test_ros1_agent.py`
- 测试：`tests/test_agent_topic_config.py`

- [ ] **步骤 1：编写目标反序列化和 MD5 测试**

新增 fake ROS class：

```python
class _DeserializableRosMsg:
    _md5sum = "test-md5"

    def __init__(self):
        self.payload = b""
        self.header = type("Header", (), {"frame_id": "odom"})()
        self.child_frame_id = "base_link"

    def deserialize(self, payload):
        self.payload = payload
```

测试：

```python
def test_on_fleet_binary_message_deserializes_and_publishes_typed_topic(monkeypatch):
    typed_pub = MagicMock()
    agent = object.__new__(ROS1Agent)
    agent._get_ros_msg_class = MagicMock(return_value=_DeserializableRosMsg)
    agent._get_fleet_publisher = MagicMock(return_value=typed_pub)
    agent._publish_fleet_summary = MagicMock()
    envelope = FleetBinaryEnvelopeData(
        transfer_id=21,
        payload_size=8,
        md5sum="test-md5",
        src_topic="/odom",
        dst_topic="/fleet/r1/odom",
        msg_type="nav_msgs/Odometry",
        frame_policy="namespace",
        ttl=1.0,
    )

    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")

    typed_pub.publish.assert_called_once()
    published = typed_pub.publish.call_args.args[0]
    assert published.payload == b"ros-body"
    assert published.header.frame_id == "r1/odom"
    assert published.child_frame_id == "r1/base_link"


def test_on_fleet_binary_message_rejects_md5_mismatch(monkeypatch):
    typed_pub = MagicMock()
    agent = object.__new__(ROS1Agent)
    agent._get_ros_msg_class = MagicMock(return_value=_DeserializableRosMsg)
    agent._get_fleet_publisher = MagicMock(return_value=typed_pub)
    agent._publish_fleet_summary = MagicMock()
    envelope = FleetBinaryEnvelopeData(
        transfer_id=22,
        payload_size=8,
        md5sum="other-md5",
        src_topic="/odom",
        dst_topic="/fleet/r1/odom",
        msg_type="nav_msgs/Odometry",
        frame_policy="preserve",
        ttl=1.0,
    )

    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")

    typed_pub.publish.assert_not_called()
    agent._publish_fleet_summary.assert_not_called()
```

增加以下明确错误隔离测试：

```python
def test_on_fleet_binary_message_rejects_missing_local_md5():
    class MissingMd5Message(_DeserializableRosMsg):
        _md5sum = ""

    agent = build_binary_target_agent(MissingMd5Message)
    envelope = build_binary_envelope(md5sum="test-md5", transfer_id=23)
    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")
    agent._get_fleet_publisher.assert_not_called()


def test_on_fleet_binary_deserialize_error_does_not_block_next_message():
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
```

辅助函数和未知类型测试写为：

```python
def build_binary_target_agent(msg_class):
    agent = object.__new__(ROS1Agent)
    agent._get_ros_msg_class = MagicMock(return_value=msg_class)
    agent._get_fleet_publisher = MagicMock(return_value=MagicMock())
    agent._publish_fleet_summary = MagicMock()
    return agent


def build_binary_envelope(md5sum, transfer_id):
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


def test_on_fleet_binary_message_rejects_unknown_type():
    agent = build_binary_target_agent(None)
    envelope = build_binary_envelope(md5sum="test-md5", transfer_id=26)
    ROS1Agent._on_fleet_binary_message(agent, "r1", envelope, b"ros-body")
    agent._get_fleet_publisher.assert_not_called()
```

- [ ] **步骤 2：编写 publisher 和轻量摘要复用测试**

连续处理两条相同 `(dst_topic, msg_type)` binary 消息，断言类型化 publisher 和 `/fleet/incoming` publisher 各只创建一次，摘要 JSON 不包含 body 或完整 payload，只包含 `src_id`、`dst_topic`、`msg_type`、`transport`、`transfer_id`、`payload_size`、`timestamp`。

同时更新现有 JSON fleet 测试，断言 JSON 和 binary 共用 `_publish_fleet_summary()`，而不是每条消息创建 debug publisher。

- [ ] **步骤 3：运行测试验证 binary hook 尚未实现**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py -k "on_fleet_binary or fleet_summary" -q
```

预期：因 `ROS1Agent._on_fleet_binary_message()` 仍使用 BaseAgent 默认 no-op、`_fleet_incoming_pub` 尚未缓存而失败。

- [ ] **步骤 4：实现目标 binary hook**

在 `ROS1Agent.__init__()` 初始化 `_fleet_incoming_pub = None`。导入 `namespace_ros_message_frames` 和 `FleetBinaryEnvelopeData`。实现：

```python
def _on_fleet_binary_message(
    self,
    src_id: str,
    envelope: FleetBinaryEnvelopeData,
    body: bytes,
) -> None:
    msg_class = self._get_ros_msg_class(envelope.msg_type)
    if msg_class is None:
        return
    local_md5 = getattr(msg_class, "_md5sum", "")
    if not local_md5 or local_md5 != envelope.md5sum:
        return
    ros_msg = msg_class()
    ros_msg.deserialize(body)
    if envelope.frame_policy == "namespace":
        namespace_ros_message_frames(ros_msg, src_id)
    publisher = self._get_fleet_publisher(
        envelope.dst_topic,
        envelope.msg_type,
        type(ros_msg),
    )
    publisher.publish(ros_msg)
    self._publish_fleet_summary(
        src_id=src_id,
        dst_topic=envelope.dst_topic,
        msg_type=envelope.msg_type,
        transport="mqtt_binary",
        transfer_id=envelope.transfer_id,
        payload_size=envelope.payload_size,
    )
```

验证 `dst_topic.startswith("/")`、encoding 和 payload format。捕获单条异常并限频记录，不能清空 publisher 或影响下一条消息。

- [ ] **步骤 5：抽取 publisher/摘要复用并更新 MockAgent**

抽取 `_get_fleet_publisher()` 和以下摘要入口，让现有 JSON `_publish_fleet_ros_topic()` 复用：

```python
def _publish_fleet_summary(
    self,
    src_id: str,
    dst_topic: str,
    msg_type: str,
    transport: str,
    transfer_id: int = 0,
    payload_size: int = 0,
) -> None:
    if self._fleet_incoming_pub is None:
        self._fleet_incoming_pub = rospy.Publisher(
            "/fleet/incoming", String, queue_size=10
        )
    summary = {
        "src_id": src_id,
        "dst_topic": dst_topic,
        "msg_type": msg_type,
        "transport": transport,
        "transfer_id": transfer_id,
        "payload_size": payload_size,
        "timestamp": time.time(),
    }
    self._fleet_incoming_pub.publish(json.dumps(summary))
```

`/fleet/incoming` 摘要不包含 JSON 路径的完整 `payload`。

`MockAgent._on_fleet_binary_message()` 仅记录或日志输出 envelope 摘要和 `len(body)`；对应 BaseAgent 测试断言不导入 rospy。

- [ ] **步骤 6：运行 ROS1、Mock 与全量无 ROS 测试**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py tests/test_agent_topic_config.py -q
python3 -m pytest tests/ -q
```

预期：全部通过；ROS1 测试使用 monkeypatch/fake message，无需 roscore。

- [ ] **步骤 7：提交目标 Agent 发布**

```bash
git add agent/ros1_agent.py agent/mock_agent.py tests/test_ros1_agent.py tests/test_agent_topic_config.py
git commit -m "feat: 发布编队二进制ROS消息"
```

### 任务 7：完善 Qt 编队 Transport 与 QoS 配置

**文件：**
- 修改：`qt_frontend/panels/fleet_comm_panel.py`
- 测试：`tests/test_panels.py`

- [ ] **步骤 1：编写纯逻辑保存和兼容测试**

在 `TestFleetCommPanel` 增加：

```python
def test_fleet_rule_protocol_dict_preserves_transport_and_qos(self):
    rule = {
        "enabled": True,
        "src_robot": "r1",
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "dst_robot": "r2",
        "dst_topic": "/fleet/r1/odom",
        "freq_limit": 10.0,
        "transport": "mqtt_binary",
        "qos": 0,
        "frame_policy": "namespace",
    }
    protocol_rule = FleetCommPanel.rule_to_protocol_dict(rule)
    assert protocol_rule["transport"] == "mqtt_binary"
    assert protocol_rule["qos"] == 0


def test_old_fleet_rule_defaults_to_json_qos_one(self):
    legacy_rule = {
        "enabled": True,
        "src_robot": "r1",
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "dst_robot": "r2",
        "dst_topic": "/fleet/r1/odom",
        "freq_limit": 10.0,
        "frame_policy": "namespace",
    }
    rules = FleetCommPanel.normalize_transmit_rules([legacy_rule])
    assert rules[0]["transport"] == "mqtt_json"
    assert rules[0]["qos"] == 1


def test_fleet_config_sync_and_response_preserve_qos_zero(self):
    rule = {
        "enabled": True,
        "src_robot": "r1",
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "dst_robot": "r2",
        "dst_topic": "/fleet/r1/odom",
        "freq_limit": 10.0,
        "transport": "mqtt_binary",
        "qos": 0,
        "frame_policy": "namespace",
    }
    payload = FleetCommPanel.build_config_sync_payload([rule])
    restored = FleetCommPanel.rules_from_config_response("r1", payload)

    assert payload["fleet_rules"][0]["qos"] == 0
    assert restored[0]["transport"] == "mqtt_binary"
    assert restored[0]["qos"] == 0
```

- [ ] **步骤 2：编写 Qt 表单和表格失败测试**

新增完整控件测试：

```python
def test_fleet_form_defaults_and_preserves_binary_qos_zero(
    self, qt_app, tmp_path
):
    panel = FleetCommPanel()
    panel._transmit_config_path = tmp_path / "transmit_config.yaml"
    panel.on_robot_list_changed(["r1", "r2"])
    panel._btn_add.click()

    assert panel._combo_transport.currentData() == "mqtt_json"
    assert panel._combo_qos.currentData() == 1

    panel._combo_src.setCurrentText("r1")
    panel._combo_dst.setCurrentText("r2")
    panel._combo_src_topic.setCurrentText("/odom")
    panel._edit_dst_topic.setText("/fleet/r1/odom")
    panel._combo_msg_type.setCurrentText("nav_msgs/Odometry")
    panel._spin_freq.setValue(10.0)
    panel._combo_frame_policy.setCurrentText("namespace")
    panel._combo_transport.setCurrentIndex(
        panel._combo_transport.findData("mqtt_binary")
    )
    panel._combo_qos.setCurrentIndex(panel._combo_qos.findData(0))
    panel._btn_confirm.click()

    assert panel._rules[0]["transport"] == "mqtt_binary"
    assert panel._rules[0]["qos"] == 0
    assert panel._table.item(0, 7).text() == "mqtt_binary"
    assert panel._table.item(0, 8).text() == "0"

    panel._table.selectRow(0)
    assert panel._combo_transport.currentData() == "mqtt_binary"
    assert panel._combo_qos.currentData() == 0
```

部署 signal 的现有测试增加 `emitted[0][1]["fleet_rules"][0]["qos"] == 0` 断言。

- [ ] **步骤 3：运行测试验证 fleet 面板尚无控件**

运行：

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_panels.py -k "FleetCommPanel and (transport or qos)" -q
```

预期：因 `_combo_transport`、`_combo_qos` 和新表格列尚不存在，或 protocol dict 丢失 QoS 而失败。

- [ ] **步骤 4：实现 transport/QoS 控件和数据闭环**

在 fleet 表单新增：

```python
self._combo_transport = QComboBox()
self._combo_transport.addItem("MQTT JSON", "mqtt_json")
self._combo_transport.addItem("MQTT Binary", "mqtt_binary")
self._combo_qos = QComboBox()
for label, value in TopicConfigPanel.qos_options()[:2]:
    self._combo_qos.addItem(label, value)
```

表格固定为 11 列，表头顺序为“启用、源机器人、源话题、消息类型、目标机器人、目标话题、频率、传输方式、QoS、Frame 策略、操作”，并为新增列设置稳定最小宽度。`_show_add_form()` 默认 JSON/QoS1；编辑时按 item data 回显；`_rule_from_form()`、`normalize_transmit_rules()`、`rule_to_protocol_dict()`、`rules_from_config_response()` 全部显式保留 `transport` 和 `qos`，使用 `is None` 判断，不能用 `or 1` 吞掉 QoS 0。

- [ ] **步骤 5：运行 Qt 聚焦和全量面板测试**

运行：

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_panels.py -k FleetCommPanel -q
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_panels.py -q
```

预期：全部通过，表格文本不截断，现有 topic 配置面板测试无回归。

- [ ] **步骤 6：提交 Qt 配置闭环**

```bash
git add qt_frontend/panels/fleet_comm_panel.py tests/test_panels.py
git commit -m "feat: 配置编队传输方式和QoS"
```

### 任务 8：更新 Fleet 示例配置且不覆盖用户改动

**文件：**
- 修改：`agent/configs/default.yaml`
- 修改：`agent/configs/turtlebot_001.yaml`
- 修改：`agent/configs/turtlebot_002.yaml`
- 修改：`qt_frontend/config/transmit_config.yaml`
- 测试：`tests/test_agent_topic_config.py`
- 测试：`tests/test_panels.py`

- [ ] **步骤 1：检查并记录配置文件已有差异**

运行：

```bash
git status --short
git diff -- agent/configs/default.yaml agent/configs/turtlebot_001.yaml agent/configs/turtlebot_002.yaml qt_frontend/config/transmit_config.yaml
```

预期：允许存在用户改动。后续只修改 `fleet_rules` 示例和紧邻注释；不得格式化、覆盖或还原 subscriptions、Husky 配置及其他运行态值。

- [ ] **步骤 2：编写 YAML 示例断言**

在 `tests/test_agent_topic_config.py` 增加 `Path` import 和完整 YAML 加载测试：

```python
def test_turtlebot_fleet_examples_use_expected_binary_qos():
    root = Path(__file__).resolve().parents[1]
    turtlebot_001 = yaml.safe_load(
        (root / "agent/configs/turtlebot_001.yaml").read_text(encoding="utf-8")
    )
    turtlebot_002 = yaml.safe_load(
        (root / "agent/configs/turtlebot_002.yaml").read_text(encoding="utf-8")
    )

    odom_rule = turtlebot_001["fleet_rules"][0]
    goal_rule = turtlebot_002["fleet_rules"][0]
    assert odom_rule["enabled"] is False
    assert odom_rule["transport"] == "mqtt_binary"
    assert odom_rule["qos"] == 0
    assert goal_rule["enabled"] is False
    assert goal_rule["transport"] == "mqtt_binary"
    assert goal_rule["qos"] == 1
```

在 `tests/test_panels.py` 增加：

```python
def test_transmit_config_fleet_examples_use_expected_binary_qos(self):
    path = Path(__file__).resolve().parents[1] / "qt_frontend/config/transmit_config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    rules = config["fleet_rules"]

    assert [(rule["transport"], rule["qos"], rule["enabled"]) for rule in rules] == [
        ("mqtt_binary", 0, False),
        ("mqtt_binary", 1, False),
    ]
```

- [ ] **步骤 3：运行测试验证示例仍为 JSON**

运行：

```bash
python3 -m pytest tests/test_agent_topic_config.py -k fleet_example -q
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_panels.py -k fleet_example -q
```

预期：因当前示例仍为 `mqtt_json` 且缺少 fleet QoS 而失败，不应因 YAML 解析或用户已有 subscriptions 改动失败。

- [ ] **步骤 4：最小更新 fleet 示例**

- `turtlebot_001:/odom` 示例改为 `mqtt_binary + qos: 0`；
- `turtlebot_002:/move_base_simple/goal` 示例改为 `mqtt_binary + qos: 1`；
- `default.yaml` 注释同时展示两类 QoS 语义；
- `transmit_config.yaml` 仅更新对应两条 fleet rule；
- 所有示例继续 `enabled: false`，避免启动容器即产生跨机器人流量。

- [ ] **步骤 5：运行配置与面板测试**

运行：

```bash
python3 -m pytest tests/test_agent_topic_config.py -q
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_panels.py -q
```

预期：全部通过。

- [ ] **步骤 6：复查没有覆盖用户配置**

运行：

```bash
git diff -- agent/configs/default.yaml agent/configs/turtlebot_001.yaml agent/configs/turtlebot_002.yaml qt_frontend/config/transmit_config.yaml
```

预期：diff 只包含目标 fleet 段及注释。若执行前已有同文件改动，逐行确认它们仍保留。

- [ ] **步骤 7：提交示例配置**

先根据步骤 1 的记录区分干净文件与执行前已修改文件。干净文件可直接暂存；执行前已修改的文件只有在 `git diff --cached` 能确认不包含用户既有改动时才可暂存。无法可靠拆分时保留在工作区，并在最终回复列为“包含计划内 fleet 示例但未提交的用户配置文件”，不得把整文件加入提交。

```bash
git add agent/configs/default.yaml agent/configs/turtlebot_001.yaml agent/configs/turtlebot_002.yaml tests/test_agent_topic_config.py tests/test_panels.py
git diff --cached --check
git diff --cached --name-only
git commit -m "config: 更新编队二进制示例"
```

如果 `qt_frontend/config/transmit_config.yaml` 在步骤 1 时为干净状态，将它加入上述 `git add`；如果执行前已包含用户改动，则不执行对该文件的整文件暂存。

### 任务 9：全量验证、双机器人验收与工作日志

**文件：**
- 创建或修改：`docs/work-log-2026-07-17.md`
- 验证：`protocol/`、`agent/`、`qt_frontend/`、`tests/`

- [ ] **步骤 1：运行聚焦测试**

```bash
python3 -m pytest tests/test_protocol_messages.py tests/test_protocol_topics.py tests/test_binary_payloads.py -v
python3 -m pytest tests/test_agent_topic_config.py tests/test_ros1_agent.py -v
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_panels.py -v
```

预期：全部通过，0 failed。

- [ ] **步骤 2：运行完整 pytest 和 ruff**

```bash
python3 -m pytest tests/ -v
ruff check protocol agent qt_frontend tests
```

预期：全部通过，ruff 无错误。若完整套件存在任务前即可复现的环境失败，保存原始命令和错误，不能把它描述为本功能通过。

- [ ] **步骤 3：验证无 ROS 的 Mock Agent 启动边界**

启动本地 Broker 后运行：

```bash
timeout 8 python3 -m agent.main --agent-type mock --robot-id fleet_mock_001 --log-level INFO
```

预期：Agent 能连接、订阅 `robot/+/to/fleet_mock_001/bin`，超时退出前无 abstract method、UTF-8 binary handler 或配置解析异常。若本机 Broker 未启动，记录未验证，不把连接失败归因于实现。

- [ ] **步骤 4：准备可恢复的双 Turtlebot 运行态配置**

仅在 Docker、ROS Noetic、显示环境和 Broker 可用时执行：

```bash
cp agent/configs/turtlebot_001.yaml /tmp/turtlebot_001.yaml.before-fleet-test
cp agent/configs/turtlebot_002.yaml /tmp/turtlebot_002.yaml.before-fleet-test
docker compose up -d robot-turtlebot-001 robot-turtlebot-002
docker compose ps robot-turtlebot-001 robot-turtlebot-002
```

预期：两个容器 running。通过 Qt 编队面板向 `turtlebot_001` 下发唯一启用规则：`/odom`、`nav_msgs/Odometry`、目标 `turtlebot_002`、`/fleet/turtlebot_001/odom`、10 Hz、`mqtt_binary`、QoS0、namespace。下发前后保留 `/tmp` 备份，测试结束必须恢复。

- [ ] **步骤 5：测量 Agent 间 MQTT 与目标机器人 ROS**

分别执行：

```bash
docker compose exec -T robot-turtlebot-001 bash -lc \
  'source /opt/ros/noetic/setup.bash && timeout 15 rostopic hz /odom'

timeout 15 mosquitto_sub -h localhost \
  -t 'robot/turtlebot_001/to/turtlebot_002' -C 20 -q 0 \
  > /tmp/fleet_envelopes.jsonl

timeout 15 mosquitto_sub -h localhost \
  -t 'robot/turtlebot_001/to/turtlebot_002/bin' -C 20 -q 0 \
  > /tmp/fleet_binary_payloads.bin

docker compose exec -T robot-turtlebot-002 bash -lc \
  'source /opt/ros/noetic/setup.bash && timeout 65 rostopic hz /fleet/turtlebot_001/odom'

docker compose exec -T robot-turtlebot-002 bash -lc \
  'source /opt/ros/noetic/setup.bash && timeout 8 rostopic echo -n 1 /fleet/turtlebot_001/odom/header'
```

预期：

- 源 `/odom` 不低于 10 Hz；
- envelope 包含 `binary=true`、`ros1_serialized_v1`、非空 MD5、不同 transfer ID；
- `/bin` 文件非空且每个 MQTT payload 以 `FRB1` 开始；
- 目标 topic 60 秒平均频率至少 9 Hz；
- 目标 header frame 带 `turtlebot_001/` 前缀。

- [ ] **步骤 6：恢复配置并记录运行环境限制**

```bash
cp /tmp/turtlebot_001.yaml.before-fleet-test agent/configs/turtlebot_001.yaml
cp /tmp/turtlebot_002.yaml.before-fleet-test agent/configs/turtlebot_002.yaml
docker compose restart robot-turtlebot-001 robot-turtlebot-002
git diff -- agent/configs/turtlebot_001.yaml agent/configs/turtlebot_002.yaml
```

预期：运行态测试产生的启用状态和 Agent 持久化写回已恢复；diff 只保留任务 8 计划内示例变化及执行前用户已有变化。

如果 Docker/ROS/MQTT 任一条件不满足，不执行会覆盖配置的步骤 4-6；在工作日志明确写出未验证的频率、延迟、Broker 字节数、系统时钟和真实 ROS MD5 风险。

- [ ] **步骤 7：按实际结果编写工作日志**

在 `docs/work-log-2026-07-17.md` 使用 `# 工作日志 — 2026年7月17日`，按“今日概览、Agent 间编队二进制链路、性能与可靠性处理、测试与验证、当前状态”组织。首次解释 envelope、binary body、transfer ID、ROS1 serialized、TTL 和自动回退；列出实际执行命令和结果，不写未执行命令为已通过。

- [ ] **步骤 8：最终 diff 和提交检查**

```bash
git status --short
git diff --check
git diff --stat
```

确认不包含 `.agents/`、`.codex/`、用户无关配置或运行态临时改动后提交：

```bash
git add docs/work-log-2026-07-17.md
git commit -m "docs: 记录编队二进制链路验证"
```

## 新对话干跑审查

1. **任务顺序与仓库可运行性**
   - 任务 1 只新增结构化 envelope/topic，现有调用者不受影响；
   - 任务 2 只新增纯协议 helper，无 ROS 依赖；
   - 任务 3 新 binary 发送入口尚无生产调用，但 JSON `send_to_robot()` 保持默认 QoS1 兼容；
   - 任务 4 在 BaseAgent 增加默认 no-op binary hook，同时立即让 MockAgent 覆盖，ROS1Agent 在任务 6 覆盖前仍可实例化；
   - 任务 5 才启用源端 binary 生产流量，依赖任务 1-4 已存在的 factory、topic、framing 和发送入口；
   - 任务 6 启用目标 ROS 发布，依赖任务 4 的锁外配对 hook；
   - 任务 7、8 只在数据面可用后暴露配置和示例；
   - 每个任务结束均有无 roscore pytest 命令，仓库保持可验证。

2. **符号和签名依赖**
   - `FleetBinaryEnvelopeData`、`MessageFactory.fleet_binary_envelope()`、`robot_to_robot_binary()` 在任务 1 定义；
   - `encode_fleet_binary_payload()` / `decode_fleet_binary_payload()` 在任务 2 定义；
   - `_next_fleet_transfer_id()`、`send_fleet_binary_to_robot()`、布尔 `_mqtt_publish()` 在任务 3 定义；
   - `_on_fleet_binary_message()` 和 cache helper 在任务 4 定义；
   - `_FleetRoute` 与新 callback 签名在任务 5 定义；
   - Qt 控件只依赖已存在的 `TopicConfigPanel.qos_options()`。

3. **预期失败来源**
   - 任务 1、2 失败于目标协议符号尚未定义；
   - 任务 3 失败于 QoS/transfer/binary send 行为缺失；
   - 任务 4 失败于现有 `_on_message()` 先 UTF-8 decode 且无 cache；
   - 任务 5 失败于现有一规则一 subscriber、只走 dict JSON；
   - 任务 6 失败于 ROS1Agent 尚未覆盖 binary hook；
   - 任务 7 失败于 FleetCommPanel 无 transport/QoS 控件；
   - 任务 8 失败于示例仍为 JSON 且缺 fleet QoS；
   - 上述失败均不依赖 roscore、Docker 或任务后序 fixture。

4. **本地 API 与兼容策略确认**
   - ROS1 generated message 使用 `serialize(buff)` 写入 `io.BytesIO`，目标对象使用 `deserialize(bytes)`；
   - ROS MD5 来自 generated class `_md5sum`；
   - paho-mqtt 2.x `Client.max_queued_messages_set()`、`max_inflight_messages_set()` 在 connect 前调用，`publish()` 返回 `MQTTMessageInfo.rc`；
   - MQTT 不保证不同 topic 之间的配对顺序，因此 binary body 自带 transfer ID；
   - `protocol/` 只使用标准库，不导入 rospy、PyQt 或 paho；
   - Python 代码继续兼容 3.8，使用 `Optional`、`List`、`Dict`、`Tuple`，新增代码首 import 保持 `from __future__ import annotations`。

5. **入口覆盖与剩余风险**
   - 主入口 `python3 -m agent.main --agent-type ros1` 和 Docker supervisor 都复用 `BaseAgent`/`ROS1Agent`，无需单独实现；
   - MockAgent 覆盖无 ROS 开发入口；
   - Qt 下发和 Agent YAML 启动恢复都经过同一 `_normalize_fleet_rules()`；
   - 地面站 Bridge、普通 sensor、RViz、HTTP pointcloud 不修改；
   - 真实频率、共享 MQTT client 高负载、系统时钟和自定义 ROS message MD5 只能在运行环境可用时验证，未验证时必须写入工作日志和最终回复。
