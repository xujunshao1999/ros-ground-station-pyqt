# ROS1 Serialized 数据面迁移实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将高频 ROS 数据从通用 JSON 路径逐步迁移到 ROS1 serialized 数据面，保留 JSON 作为控制面和轻量 meta 协议。

**架构：** MQTT topic 结构继续承担 robot_id 隔离；sensor envelope 继续使用 JSON，但 payload 改为 ROS1 原生 serialized bytes。Bridge 收到 payload 后反序列化、按 robot_id 做 frame namespace，再发布到地面站 ROS。低频控制、状态、discover、配置和 UI 摘要仍走 JSON。

**技术栈：** Python 3.8、ROS Noetic `rospy` message `serialize()` / `deserialize()`、MQTT envelope + `/bin` payload、pytest、PyQt5 前端 MQTT 客户端。

---

## 文件结构

- 修改：`protocol/binary_payloads.py`
  - 将 `tf_message_ros1_v1` 扩展为通用 ROS1 serialized encoding。
  - 暴露 `is_ros_message_binary_supported()`，集中定义允许走 ROS1 serialized 的消息类型。
- 修改：`agent/base_agent.py`
  - 保持 `publish_sensor_binary_data()` 作为 ROS1 serialized 发布入口，并让 envelope encoding 与 msg_type 解耦。
- 修改：`agent/ros1_agent.py`
  - 从只处理动态 `/tf`，改为按 transport、msg_type 和 allowlist 决定是否使用 ROS1 serialized。
  - 保留 `/tf_static` 的 latched 语义，先在独立任务中迁移。
- 修改：`bridge/mqtt_ros_bridge.py`
  - 将 `_publish_ros_binary_sensor()` 的 frame namespace 从 TF 专用扩展为通用 ROS message。
  - 对 `/tf_static` 的 static broadcaster、缓存与合并逻辑补齐 ROS1 serialized 路径。
- 修改：`agent/frame_utils.py`
  - 新增针对 ROS message 对象的 frame namespace helper，避免 dict 路径和 serialized 路径各写一套递归逻辑。
- 修改：`qt_frontend/mqtt_client.py`
  - 继续忽略高频 data payload；如需要 UI 可见性，只保留 envelope/meta 摘要，不解析 `/bin`。
- 测试：`tests/test_binary_payloads.py`
- 测试：`tests/test_ros1_agent.py`
- 测试：`tests/test_mqtt_ros_bridge.py`
- 测试：`tests/test_mqtt_client.py`
- 文档：`docs/work-log-2026-06-17.md`

## 范围决策

本计划分批迁移：

- 第 1 批：抽象通用 ROS1 serialized 数据面，不改变当前 `/tf` 行为。
- 第 2 批：迁移 `/tf_static`，统一 TF 动态与静态路径。
- 第 3 批：迁移 `/odom`、`/imu`，验证远程操控所需连续状态数据的延迟和频率。
- 第 4 批：评估并可选迁移 `/scan`。如果自定义 `laser_scan_v1` 在带宽或摘要 meta 上仍更优，则保留当前路径。

`/map` 暂不迁移。当前 `occupancy_grid_v1` 使用 `zlib` 压缩，带宽收益明显；地图 frame 和 global/local map 语义也比普通 sensor 更复杂。

## 多机器人与 `/tf` 约束

`/tf` 和 `/tf_static` 在地面站 ROS 中仍保持公共 topic，不为每台机器人创建 `/turtlebot_001/tf`、`/turtlebot_002/tf` 这类私有 topic。ROS TF 的正常模型是多个 publisher 同时向同一个 `/tf` 发布不同 frame 的 transform，RViz 和 tf listener 订阅一个 `/tf` 后合成完整 TF tree。

多机器人隔离不能依赖 topic 名隔离，而必须依赖 frame 全局唯一：

```text
turtlebot_001/odom -> turtlebot_001/base_link
turtlebot_002/odom -> turtlebot_002/base_link
```

禁止在地面站 ROS 中出现多个机器人共用以下 frame：

```text
odom
base_link
base_scan
map
```

因此 serialized 数据面必须遵守以下规则：

- MQTT topic 继续用 `robot/<robot_id>/sensor/<name>` 区分数据来源。
- 只有订阅配置 `transport: mqtt_binary` 且 `(topic, msg_type)` 命中 ROS1 serialized allowlist 时，Agent 才能发布 `ros1_serialized_v1`。
- 如果 allowlist 命中但订阅配置仍为 `transport: mqtt_json`，Agent 必须保留 JSON 路径，避免配置语义和实际传输方式不一致。
- 普通 sensor topic 发布到地面站 ROS 时继续使用 `/<robot_id>/<topic>`，例如 `/turtlebot_001/odom`。
- `/tf` 和 `/tf_static` 发布到公共 topic，但 Bridge 发布前必须反序列化并给 `frame_id`、`child_frame_id` 加 `robot_id` 前缀。
- 允许多个 Bridge 进程同时发布 `/tf`，前提是每个进程只发布自己负责机器人的 namespace 后 frame。
- `/tf_static` 可以由每个 Bridge 进程广播自己负责机器人的 static transforms；如果实测出现缓存或覆盖问题，再单独设计 TF static aggregator。

### 任务 1：协议层抽象 ROS1 serialized encoding

**文件：**
- 修改：`protocol/binary_payloads.py`
- 测试：`tests/test_binary_payloads.py`

- [x] **步骤 1：编写失败的测试**

在 `tests/test_binary_payloads.py` 增加：

```python
def test_ros1_serialized_envelope_is_not_tf_specific():
    envelope, payload = encode_ros_message_binary(
        "/odom",
        "nav_msgs/Odometry",
        b"serialized-odom",
        seq=12,
    )

    assert envelope["encoding"] == "ros1_serialized_v1"
    assert envelope["payload_format"] == "ros1_serialized"
    assert envelope["msg_type"] == "nav_msgs/Odometry"
    assert envelope["topic"] == "/odom"
    assert envelope["payload_size"] == len(payload)
    assert payload == b"serialized-odom"
    assert is_ros_message_binary_encoding(envelope) is True


def test_ros1_serialized_supported_types_are_controlled_by_allowlist():
    assert is_ros_message_binary_supported("/tf", "tf2_msgs/TFMessage") is True
    assert is_ros_message_binary_supported("/tf_static", "tf2_msgs/TFMessage") is True
    assert is_ros_message_binary_supported("/odom", "nav_msgs/Odometry") is True
    assert is_ros_message_binary_supported("/imu", "sensor_msgs/Imu") is True
    assert is_ros_message_binary_supported("/scan", "sensor_msgs/LaserScan") is False
    assert is_ros_message_binary_supported("/map", "nav_msgs/OccupancyGrid") is False
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_binary_payloads.py::test_ros1_serialized_envelope_is_not_tf_specific tests/test_binary_payloads.py::test_ros1_serialized_supported_types_are_controlled_by_allowlist -q
```

预期：失败，原因是 `ros1_serialized_v1` 和 `is_ros_message_binary_supported()` 尚未实现。

- [x] **步骤 3：实现协议常量和 allowlist**

在 `protocol/binary_payloads.py` 中：

```python
ENCODING_ROS1_SERIALIZED = "ros1_serialized_v1"
ENCODING_TF_MESSAGE = ENCODING_ROS1_SERIALIZED

_ROS1_SERIALIZED_TOPIC_TYPES = {
    ("/tf", "tf2_msgs/TFMessage"),
    ("/tf_static", "tf2_msgs/TFMessage"),
    ("/odom", "nav_msgs/Odometry"),
    ("/imu", "sensor_msgs/Imu"),
}
_ROS_MESSAGE_BINARY_ENCODINGS = frozenset({ENCODING_ROS1_SERIALIZED})
```

新增：

```python
def is_ros_message_binary_supported(topic: str, msg_type: str) -> bool:
    return (topic, msg_type) in _ROS1_SERIALIZED_TOPIC_TYPES
```

修改 `encode_ros_message_binary()` 中的 envelope：

```python
"encoding": ENCODING_ROS1_SERIALIZED,
```

- [x] **步骤 4：运行协议测试验证通过**

运行：

```bash
python3 -m pytest tests/test_binary_payloads.py -q
```

预期：全部通过。

- [x] **步骤 5：Commit**

```bash
git add protocol/binary_payloads.py tests/test_binary_payloads.py
git commit -m "refactor: 抽象 ROS1 serialized 数据面协议"
```

### 任务 2：Agent 按 allowlist 使用 ROS1 serialized

**文件：**
- 修改：`agent/ros1_agent.py`
- 测试：`tests/test_ros1_agent.py`

- [x] **步骤 1：编写失败的测试**

在 `tests/test_ros1_agent.py` 增加：

```python
def test_allowlisted_topic_uses_ros1_serialized_fast_path(monkeypatch):
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.is_ros_message_binary_supported",
        lambda topic, msg_type: topic == "/odom" and msg_type == "nav_msgs/Odometry",
    )
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: (_ for _ in ()).throw(
            AssertionError("serialized topic should not use JSON conversion")
        ),
    )

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.default_freq_limit = 100.0
    agent._ros_subscribers = {}
    agent._sensor_data = {}
    agent._sensor_lock = MagicMock()
    agent._get_ros_msg_class = MagicMock(return_value=object)
    agent.publish_sensor_binary_data = MagicMock()

    ROS1Agent._on_topic_subscribed(
        agent,
        "/odom",
        "nav_msgs/Odometry",
        {"freq_limit": 100.0},
    )
    captured_callback["callback"](_SerializableRosMsg(b"odom-raw"))

    agent.publish_sensor_binary_data.assert_called_once()
    assert agent.publish_sensor_binary_data.call_args[0][:3] == (
        "/odom",
        "nav_msgs/Odometry",
        b"odom-raw",
    )
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py::test_allowlisted_topic_uses_ros1_serialized_fast_path -q
```

预期：失败，原因是 ROS1Agent 仍只对 `/tf` 走 fast path。

- [x] **步骤 3：实现 allowlist fast path**

在 `agent/ros1_agent.py` import：

```python
from protocol.binary_payloads import is_ros_message_binary_supported
```

将 callback 中的 `/tf` 专用判断替换为：

```python
            if is_ros_message_binary_supported(t, mt):
                raw_payload = self._serialize_ros_message(msg)
                if raw_payload is not None:
                    self.publish_sensor_binary_data(
                        t,
                        mt,
                        raw_payload,
                        seq=self._message_seq(msg),
                        bypass_rate_limit=(t == "/tf_static"),
                        retain=(t == "/tf_static"),
                    )
                    return
```

将 `_tf_message_seq()` 改为更通用的 `_message_seq()`：

```python
    @staticmethod
    def _message_seq(msg) -> Optional[int]:
        header = getattr(msg, "header", None)
        if header is None:
            transforms = getattr(msg, "transforms", None)
            if transforms:
                header = getattr(transforms[0], "header", None)
        seq = getattr(header, "seq", None)
        try:
            return int(seq) if seq is not None else None
        except (TypeError, ValueError):
            return None
```

- [x] **步骤 4：运行 Agent 测试验证通过**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py -q
```

预期：全部通过。

- [x] **步骤 5：Commit**

```bash
git add agent/ros1_agent.py tests/test_ros1_agent.py
git commit -m "feat: 支持高频话题 ROS1 serialized 发布"
```

### 任务 2.1：Agent serialized fast path 必须受 transport 控制

**背景：** 任务 2 已将 serialized fast path 从 `/tf` 专用扩展到 allowlist，但实现必须同时检查订阅配置的 `transport`。`ros1_serialized_v1` 是 `mqtt_binary` 传输下的一种 payload encoding；allowlist 只表示“这个 `(topic, msg_type)` 可以走 ROS1 serialized”，不应覆盖用户在配置中选择的 `mqtt_json`。

**文件：**
- 修改：`agent/ros1_agent.py`
- 测试：`tests/test_ros1_agent.py`

- [x] **步骤 1：编写失败的 transport 门控测试**

在 `tests/test_ros1_agent.py` 增加：

```python
def test_allowlisted_topic_uses_json_when_transport_is_mqtt_json(monkeypatch):
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.is_ros_message_binary_supported",
        lambda topic, msg_type: topic == "/odom" and msg_type == "nav_msgs/Odometry",
    )
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: {"header": {"frame_id": "odom"}},
    )

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.default_freq_limit = 100.0
    agent._ros_subscribers = {}
    agent._sensor_data = {}
    agent._sensor_lock = MagicMock()
    agent._get_ros_msg_class = MagicMock(return_value=object)
    agent.publish_sensor_binary_data = MagicMock()
    agent.publish_sensor_data = MagicMock()

    ROS1Agent._on_topic_subscribed(
        agent,
        "/odom",
        "nav_msgs/Odometry",
        {"freq_limit": 100.0, "transport": "mqtt_json"},
    )
    captured_callback["callback"](_SerializableRosMsg(b"odom-raw"))

    agent.publish_sensor_binary_data.assert_not_called()
    agent.publish_sensor_data.assert_called_once_with(
        "/odom",
        "nav_msgs/Odometry",
        {"header": {"frame_id": "odom"}},
    )
```

同时保留 `test_allowlisted_topic_uses_ros1_serialized_fast_path`，并将其订阅 options 改为显式传入：

```python
{"freq_limit": 100.0, "transport": "mqtt_binary"}
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py::test_allowlisted_topic_uses_json_when_transport_is_mqtt_json tests/test_ros1_agent.py::test_allowlisted_topic_uses_ros1_serialized_fast_path -q
```

预期：`test_allowlisted_topic_uses_json_when_transport_is_mqtt_json` 失败，原因是当前 Agent 只按 allowlist 判断，仍会调用 `publish_sensor_binary_data()`。

- [x] **步骤 3：实现 transport + allowlist 双条件**

在 `agent/ros1_agent.py` 的 `_on_topic_subscribed()` 中，在 callback 定义前读取 transport：

```python
        transport = options.get("transport", "mqtt_json")
```

将 callback 默认参数补充为：

```python
        def callback(
            msg,
            t=topic,
            mt=msg_type,
            tr=transport,
            lpt=last_pub_time,
            mi=min_interval,
        ):
```

将 serialized fast path 判断改为：

```python
            if tr == "mqtt_binary" and is_ros_message_binary_supported(t, mt):
```

- [x] **步骤 4：运行 Agent 测试验证通过**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py -q
```

预期：全部通过。

- [x] **步骤 5：Commit**

```bash
git add agent/ros1_agent.py tests/test_ros1_agent.py docs/superpowers/plans/2026-06-17-ros1-serialized-data-plane.md
git commit -m "fix: 按 transport 控制 serialized 快路径"
```

### 任务 3：Bridge 对 ROS message 对象做通用 frame namespace

**文件：**
- 修改：`agent/frame_utils.py`
- 修改：`bridge/mqtt_ros_bridge.py`
- 测试：`tests/test_mqtt_ros_bridge.py`

- [x] **步骤 1：编写失败的测试**

在 `tests/test_mqtt_ros_bridge.py` 增加 mock message：

```python
class MockHeaderMessage:
    def __init__(self):
        self.raw_payload = b""
        self.header = types.SimpleNamespace(frame_id="odom")

    def deserialize(self, payload):
        self.raw_payload = payload
        return self
```

增加测试：

```python
def test_ros1_serialized_header_message_is_namespaced(self, bridge: MqttRosBridge):
    envelope, payload = encode_ros_message_binary(
        "/odom",
        "nav_msgs/Odometry",
        b"serialized-odom",
        seq=10,
    )
    publisher = MagicMock()

    with patch(
        "bridge.mqtt_ros_bridge._get_message_class",
        return_value=MockHeaderMessage,
    ), patch.object(
        bridge,
        "_get_or_create_typed_publisher",
        return_value=publisher,
    ) as get_pub, patch.object(
        bridge,
        "_wait_for_publisher_connection",
    ):
        bridge._handle_sensor_data(
            "robot_001",
            "odom",
            json.dumps(envelope).encode("utf-8"),
        )
        bridge._handle_sensor_binary("robot_001", "odom", payload)

    get_pub.assert_called_once_with("/robot_001/odom", MockHeaderMessage)
    published = publisher.publish.call_args[0][0]
    assert published.header.frame_id == "robot_001/odom"
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_mqtt_ros_bridge.py::TestBinarySensorData::test_ros1_serialized_header_message_is_namespaced -q
```

预期：失败，原因是 serialized 路径目前只处理 `tf2_msgs/TFMessage` frame。

- [x] **步骤 3：新增 ROS message frame namespace helper**

在 `agent/frame_utils.py` 新增：

```python
def namespace_ros_message_frames(msg: Any, robot_id: str) -> None:
    header = getattr(msg, "header", None)
    if header is not None:
        frame_id = getattr(header, "frame_id", None)
        if isinstance(frame_id, str):
            header.frame_id = namespace_frame_id(frame_id, robot_id)

    child_frame_id = getattr(msg, "child_frame_id", None)
    if isinstance(child_frame_id, str):
        msg.child_frame_id = namespace_frame_id(child_frame_id, robot_id)

    transforms = getattr(msg, "transforms", None)
    if isinstance(transforms, list):
        for transform in transforms:
            namespace_ros_message_frames(transform, robot_id)
```

在 `bridge/mqtt_ros_bridge.py` import 并使用：

```python
from agent.frame_utils import (
    namespace_frame_id,
    namespace_message_frames,
    namespace_ros_message_frames,
)
```

将 `_publish_ros_binary_sensor()` 中 TF 专用 namespace 替换为：

```python
            if self._namespace_tf_frames:
                namespace_ros_message_frames(ros_msg, robot_id)
```

保留 `_prefix_tf_message_frames()` 到本任务结束后删除，或直接改为调用 `namespace_ros_message_frames()`，避免重复逻辑。

- [x] **步骤 4：运行 Bridge 测试验证通过**

运行：

```bash
python3 -m pytest tests/test_mqtt_ros_bridge.py -q
```

预期：全部通过。

- [x] **步骤 5：Commit**

```bash
git add agent/frame_utils.py bridge/mqtt_ros_bridge.py tests/test_mqtt_ros_bridge.py
git commit -m "fix: 为 serialized 数据补齐 frame 命名空间"
```

### 任务 4：补齐 `/tf_static` serialized 的 latched/static 行为

**文件：**
- 修改：`bridge/mqtt_ros_bridge.py`
- 测试：`tests/test_mqtt_ros_bridge.py`
- 测试：`tests/test_ros1_agent.py`

- [x] **步骤 1：编写 Bridge 失败测试**

在 `tests/test_mqtt_ros_bridge.py` 的 `TestBinarySensorData` 类中增加：

```python
def test_binary_tf_static_uses_static_transform_broadcaster(self, bridge: MqttRosBridge):
    envelope, payload = encode_ros_message_binary(
        "/tf_static",
        "tf2_msgs/TFMessage",
        b"serialized-static-tf",
        seq=1,
    )
    ros_msg = MockTfMessage()
    ros_msg.transforms = [MockTransformStamped()]

    with patch(
        "bridge.mqtt_ros_bridge._get_message_class",
        return_value=lambda: ros_msg,
    ), patch.object(
        bridge,
        "_ensure_static_tf_broadcaster",
    ) as ensure_broadcaster, patch.object(
        bridge,
        "_cache_robot_static_transforms",
    ) as cache_static, patch.object(
        bridge,
        "_send_static_transforms",
    ) as send_static, patch.object(
        bridge,
        "_get_or_create_typed_publisher",
    ) as get_pub:
        bridge._handle_sensor_data(
            "robot_001",
            "tf_static",
            json.dumps(envelope).encode("utf-8"),
        )
        bridge._handle_sensor_binary("robot_001", "tf_static", payload)

    ensure_broadcaster.assert_called_once()
    cache_static.assert_called_once()
    send_static.assert_called_once()
    get_pub.assert_not_called()
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_mqtt_ros_bridge.py::TestBinarySensorData::test_binary_tf_static_uses_static_transform_broadcaster -q
```

预期：失败，原因是 serialized `/tf_static` 目前会走普通 publisher。

- [x] **步骤 3：实现 serialized `/tf_static` 静态广播路径**

在 `_publish_ros_binary_sensor()` 的 namespace 之后、普通 publisher 之前加入：

```python
            if full_topic == "/tf_static":
                self._ensure_static_tf_broadcaster()
                self._cache_robot_static_transforms(
                    robot_id,
                    list(getattr(ros_msg, "transforms", [])),
                )
                self._send_static_transforms(self._build_all_static_transforms())
                return
```

- [x] **步骤 4：运行 TF static 相关测试**

运行：

```bash
python3 -m pytest tests/test_mqtt_ros_bridge.py::TestBinarySensorData tests/test_ros1_agent.py::test_tf_static_callback_merges_multiple_latched_messages -q
```

预期：全部通过。

- [x] **步骤 5：Commit**

```bash
git add bridge/mqtt_ros_bridge.py tests/test_mqtt_ros_bridge.py tests/test_ros1_agent.py
git commit -m "fix: 支持 TF static serialized 广播"
```

### 任务 5：前端忽略 serialized 数据 payload，保留 envelope 摘要

**文件：**
- 修改：`qt_frontend/mqtt_client.py`
- 测试：`tests/test_mqtt_client.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_mqtt_client.py` 增加：

```python
def test_serialized_odom_envelope_is_summarized_but_bin_payload_is_ignored(client, mock_paho):
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
    bin_msg = _make_mqtt_msg(
        "robot/robot_001/sensor/odom/bin",
        b"\x00\x01serialized",
    )

    client.connect()
    client._on_message(mock_paho, None, envelope_msg)
    client._on_message(mock_paho, None, bin_msg)

    assert sensor_signal.call_count == 1
    assert sensor_signal.call_args[0][1]["msg_type"] == "nav_msgs/Odometry"
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_mqtt_client.py::TestOnMessageStatus::test_serialized_odom_envelope_is_summarized_but_bin_payload_is_ignored -q
```

预期：如果当前前端已能总结二进制 envelope，则测试可能直接通过；若失败，按步骤 3 修复。

- [ ] **步骤 3：保证 sensor `/bin` 全量忽略，`tf` envelope 全量忽略**

确认 `qt_frontend/mqtt_client.py` 满足：

```python
if robot_info and robot_info.get("type") == "sensor_binary":
    return
if robot_info and robot_info.get("type") == "sensor":
    sensor_name = robot_info.get("name", "")
    if self._should_ignore_sensor_payload(sensor_name):
        return
```

`_IGNORED_SENSOR_TOPICS` 只包含 `tf` 和 `tf_static`。`odom`、`imu` serialized envelope 可作为轻量摘要进入 UI，但 `/bin` 不进入 UI。

- [ ] **步骤 4：运行前端 MQTT 测试**

运行：

```bash
python3 -m pytest tests/test_mqtt_client.py -q
```

预期：全部通过。

- [ ] **步骤 5：Commit**

```bash
git add qt_frontend/mqtt_client.py tests/test_mqtt_client.py
git commit -m "fix: 保护前端 serialized 传感器数据路径"
```

### 任务 6：运行态配置与分批验证

**文件：**
- 修改：`qt_frontend/config/transmit_config.yaml`
- 修改：`agent/configs/turtlebot_001.yaml`
- 文档：`docs/work-log-2026-06-17.md`

- [ ] **步骤 1：先启用 `/tf_static`、`/odom`、`/imu` 的 serialized 路径**

确认配置中保留：

```yaml
- topic: /tf_static
  msg_type: tf2_msgs/TFMessage
  transport: mqtt_binary
  qos: 1
- topic: /odom
  msg_type: nav_msgs/Odometry
  transport: mqtt_binary
  qos: 0
- topic: /imu
  msg_type: sensor_msgs/Imu
  transport: mqtt_binary
  qos: 0
```

`/scan` 暂不在本步骤迁移，继续使用当前 `laser_scan_v1` 或现有配置。

- [ ] **步骤 2：启动链路**

运行：

```bash
docker compose up -d robot-turtlebot-001
./qt_frontend/scripts/start.sh
```

预期：机器人容器、broker、Bridge、Qt 前端正常启动。

- [ ] **步骤 3：验证 MQTT envelope**

运行：

```bash
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/odom -C 3
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/imu -C 3
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/tf_static -C 1
```

预期：envelope 中 `encoding=ros1_serialized_v1`、`payload_format=ros1_serialized`、`msg_type` 分别为 `nav_msgs/Odometry`、`sensor_msgs/Imu`、`tf2_msgs/TFMessage`。

- [ ] **步骤 4：验证地面站 ROS topic 频率**

运行：

```bash
timeout 12 rostopic hz /tf
timeout 12 rostopic hz /turtlebot_001/odom
timeout 12 rostopic hz /turtlebot_001/imu
timeout 12 rostopic hz /turtlebot_001/scan
```

预期：`/tf` 接近容器内频率，`/turtlebot_001/odom` 和 `/turtlebot_001/imu` 不低于配置限频，`/turtlebot_001/scan` 保持约 5Hz。

- [ ] **步骤 5：验证 frame namespace**

运行：

```bash
timeout 8 rostopic echo -n 1 /turtlebot_001/odom/header
timeout 8 rostopic echo -n 1 /turtlebot_001/imu/header
timeout 6 rosrun tf tf_echo turtlebot_001/odom turtlebot_001/base_link
```

预期：`header.frame_id` 已带 `turtlebot_001/` 前缀；`tf_echo` 可持续输出，不出现跨机器人 frame 冲突。

- [ ] **步骤 6：记录验证结果并 Commit**

在 `docs/work-log-2026-06-17.md` 增加“ROS1 serialized 数据面迁移验证”小节，写入实际命令和结果。

```bash
git add qt_frontend/config/transmit_config.yaml agent/configs/turtlebot_001.yaml docs/work-log-2026-06-17.md
git commit -m "config: 启用高频话题 serialized 数据面"
```

### 任务 7：评估 `/scan` 是否迁移到 ROS1 serialized

**文件：**
- 修改：`protocol/binary_payloads.py`
- 修改：`docs/work-log-2026-06-17.md`
- 测试：`tests/test_binary_payloads.py`
- 测试：`tests/test_mqtt_ros_bridge.py`

- [ ] **步骤 1：先记录基线**

保持 `/scan` 当前路径，运行：

```bash
timeout 12 rostopic hz /turtlebot_001/scan
timeout 12 rostopic bw /turtlebot_001/scan
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/scan -C 20
```

预期：记录当前 `laser_scan_v1` 的频率、带宽、envelope 可读 meta。

- [ ] **步骤 2：编写 `/scan` serialized allowlist 测试**

修改 `tests/test_binary_payloads.py`：

```python
def test_scan_can_be_enabled_for_ros1_serialized_when_selected():
    assert is_ros_message_binary_supported(
        "/scan",
        "sensor_msgs/LaserScan",
    ) is True
```

- [ ] **步骤 3：临时启用 `/scan` serialized 并验证**

在 `_ROS1_SERIALIZED_TOPIC_TYPES` 中加入：

```python
("/scan", "sensor_msgs/LaserScan"),
```

运行：

```bash
python3 -m pytest tests/test_binary_payloads.py tests/test_ros1_agent.py tests/test_mqtt_ros_bridge.py -q
```

预期：全部通过。

- [ ] **步骤 4：运行态 A/B 对比**

运行：

```bash
timeout 12 rostopic hz /turtlebot_001/scan
timeout 12 rostopic bw /turtlebot_001/scan
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/scan -C 20
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/scan/bin -C 20 > /tmp/scan_serialized_bin
wc -c /tmp/scan_serialized_bin
```

预期：记录 serialized `/scan` 的频率、带宽和 payload 大小。与步骤 1 比较 CPU、带宽、RViz 流畅度和前端摘要可读性。

- [ ] **步骤 5：决定并提交**

如果 serialized `/scan` 在频率和 CPU 上更稳定，且前端摘要只依赖 envelope，则保留迁移：

```bash
git add protocol/binary_payloads.py tests/test_binary_payloads.py docs/work-log-2026-06-17.md
git commit -m "perf: 评估并启用 LaserScan serialized 传输"
```

如果 `laser_scan_v1` 更省带宽或摘要价值更高，则回退步骤 3 的 allowlist 改动，只提交工作日志中的评估结论：

```bash
git add docs/work-log-2026-06-17.md
git commit -m "docs: 记录 LaserScan 传输方案评估"
```

### 任务 8：补充 Bridge 按 robot_id 分片能力

**文件：**
- 修改：`bridge/mqtt_ros_bridge.py`
- 测试：`tests/test_mqtt_ros_bridge.py`
- 文档：`docs/work-log-2026-06-17.md`

此任务只在单 Bridge 进程处理多机器人时 CPU 仍偏高后执行。目标是允许多个 Bridge 进程按 robot_id 分片处理 MQTT 数据，避免多个 Bridge 重复消费同一批 sensor 消息。

- [ ] **步骤 1：编写失败的订阅过滤测试**

在 `tests/test_mqtt_ros_bridge.py` 的 `TestMqttConnect` 类中增加：

```python
def test_bridge_subscribes_only_selected_robot_sensor_topics():
    bridge = MqttRosBridge(robot_ids=["turtlebot_001", "turtlebot_002"])
    mock_client = MagicMock()

    bridge._on_mqtt_connect(mock_client, None, None, 0, None)

    subscribed_topics = [call_args[0][0] for call_args in mock_client.subscribe.call_args_list]
    assert "robot/turtlebot_001/sensor/#" in subscribed_topics
    assert "robot/turtlebot_002/sensor/#" in subscribed_topics
    assert "robot/+/sensor/#" not in subscribed_topics
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_mqtt_ros_bridge.py::TestMqttConnect::test_bridge_subscribes_only_selected_robot_sensor_topics -q
```

预期：失败，原因是 Bridge 当前默认订阅 `robot/+/sensor/#`，没有 robot_id 分片参数。

- [ ] **步骤 3：实现 Bridge robot_id 过滤参数**

在 `MqttRosBridge.__init__()` 增加可选参数：

```python
def __init__(
    self,
    mqtt_host: str = "localhost",
    mqtt_port: int = 1883,
    robot_ids: Optional[List[str]] = None,
):
    self._robot_ids = list(robot_ids or [])
```

在 `_on_mqtt_connect()` 中替换 sensor 订阅逻辑：

```python
sensor_topics = (
    [f"robot/{robot_id}/sensor/#" for robot_id in self._robot_ids]
    if self._robot_ids
    else ["robot/+/sensor/#"]
)
for topic in sensor_topics:
    client.subscribe(topic, qos=0)
```

status、event、cmd ack、topic response 也按同样原则分片；如果该 Bridge 没有配置 `robot_ids`，保留现有 wildcard 行为。

- [ ] **步骤 4：实现 CLI 参数**

在 Bridge main 入口增加：

```python
parser.add_argument(
    "--robot-id",
    action="append",
    dest="robot_ids",
    default=[],
    help="Only bridge MQTT topics for the given robot id. Can be repeated.",
)
```

创建 Bridge 时传入：

```python
bridge = MqttRosBridge(
    mqtt_host=args.mqtt_host,
    mqtt_port=args.mqtt_port,
    robot_ids=args.robot_ids,
)
```

- [ ] **步骤 5：运行 Bridge 测试验证通过**

运行：

```bash
python3 -m pytest tests/test_mqtt_ros_bridge.py -q
```

预期：全部通过。

- [ ] **步骤 6：运行态验证两个 Bridge 分片**

启动两个 Bridge：

```bash
python3 -m bridge.mqtt_ros_bridge --robot-id turtlebot_001
python3 -m bridge.mqtt_ros_bridge --robot-id turtlebot_002
```

验证 `/tf` 仍是公共 topic，且 frame 不冲突：

```bash
timeout 12 rostopic hz /tf
timeout 6 rosrun tf tf_echo turtlebot_001/odom turtlebot_001/base_link
timeout 6 rosrun tf tf_echo turtlebot_002/odom turtlebot_002/base_link
timeout 8 rostopic echo -n 1 /turtlebot_001/odom/header
timeout 8 rostopic echo -n 1 /turtlebot_002/odom/header
```

预期：两个 Bridge 都向公共 `/tf` 发布各自机器人 namespace 后的 transforms；`/turtlebot_001/odom` 和 `/turtlebot_002/odom` 互不串 frame。

- [ ] **步骤 7：记录验证结果并 Commit**

在 `docs/work-log-2026-06-17.md` 记录 Bridge 分片验证结果。

```bash
git add bridge/mqtt_ros_bridge.py tests/test_mqtt_ros_bridge.py docs/work-log-2026-06-17.md
git commit -m "feat: 支持 Bridge 按机器人分片"
```

## 最终验证清单

完成所有已选择任务后运行：

```bash
python3 -m pytest tests/test_binary_payloads.py tests/test_ros1_agent.py tests/test_mqtt_ros_bridge.py tests/test_mqtt_client.py -q
git diff --check
```

运行态验证：

```bash
docker compose up -d robot-turtlebot-001
./qt_frontend/scripts/start.sh
timeout 12 rostopic hz /tf
timeout 12 rostopic hz /turtlebot_001/odom
timeout 12 rostopic hz /turtlebot_001/imu
timeout 12 rostopic hz /turtlebot_001/scan
timeout 8 rostopic echo -n 1 /turtlebot_001/odom/header
timeout 6 rosrun tf tf_echo turtlebot_001/odom turtlebot_001/base_link
timeout 6 rosrun tf tf_echo turtlebot_002/odom turtlebot_002/base_link
```

成功标准：

- 地面站 `/tf` 接近容器内约 80Hz。
- `/odom`、`/imu` 不因 JSON 转换出现明显掉频。
- `/scan` 保持约 5Hz，RViz 不出现明显成批刷新。
- 多机器人 frame 均带 robot_id 前缀，不出现 `base_link`、`odom`、`base_scan` 冲突。
- `/tf` 与 `/tf_static` 保持公共 topic，可由单个或多个 Bridge 发布；隔离边界是 frame namespace，不是 TF topic namespace。
- 如果启用 Bridge 分片，每个 Bridge 只消费自己负责的 `robot_id` MQTT topic，不重复消费 `robot/+/sensor/#`。
- 前端摘要面板不解析高频 `/bin` payload，Qt 主进程 CPU 不因 sensor payload 解析上升。
