# MQTT 传输策略 auto 化实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将高频 ROS 话题的传输方式从“必须手动指定 `mqtt_binary` 才启用高效路径”调整为“默认 `auto` 策略自动选择高效路径，同时保留 `mqtt_json` 作为显式回退”。

**架构：** `transport` 字段继续保留，但语义从“每个话题必须手动区分传输类型”调整为“可覆盖的传输策略”。当 `transport` 为 `auto` 或缺省时，Agent 根据话题、消息类型和 binary/serialized allowlist 自动选择 ROS1 serialized、现有 binary 编码或 JSON 路径；当显式写 `mqtt_json` 时，仍强制走 JSON，方便调试和兼容回退。

**技术栈：** Python 3.8、ROS Noetic、MQTT JSON envelope、ROS1 `serialize()` / `deserialize()`、pytest、YAML 配置。

---

## 背景与当前观察

当前运行态验证中，`/tf` 配置为 `mqtt_json` 时，地面站 ROS `/tf` 仍能达到约 80 Hz。这说明在当前单机器人、当前负载和前端高频数据保护已经生效的条件下，JSON 路径的频率表现足够。

但这不能直接推出 `transport` 字段没有意义，因为 `rostopic hz` 只反映 ROS 侧到达频率，不反映 MQTT payload 体积、Agent CPU、Bridge JSON 解析和 dict 转 ROS message 的开销、端到端延迟、多机器人余量和 RViz/Qt 同时高负载时的稳定性。

历史上 `/tf` 卡顿改善并不只来自 payload 格式变化，还叠加了以下变化：

- 前端忽略 `tf`、`tf_static` 高频 sensor envelope，不再把它们送入普通 UI 摘要路径。
- 传感器摘要面板改为批处理刷新，避免每帧驱动 Qt UI 更新。
- `/scan`、`/map`、`/odom`、`/imu` 等部分话题已经走 binary 或更轻路径，整体链路负载下降。
- `b187889 perf: 优化 TF 传输性能` 曾让 `/tf` 强制走 ROS1 serialized；后来 `496783a fix: 按 transport 控制 serialized 快路径` 为了配置语义一致，改为只有 `transport: mqtt_binary` 时才启用 serialized。

因此，本计划不删除 `transport` 字段，而是引入更合理的默认策略：

```text
transport: auto 或未配置：
  - 命中 ROS1 serialized allowlist 的话题走 ros1_serialized_v1。
  - /scan、/map 继续走现有 binary 编码策略。
  - 其它话题走 JSON。

transport: mqtt_binary：
  - 支持 binary 或 ROS1 serialized 的话题强制走对应 binary 路径。
  - 不支持 binary 的话题保留 JSON fallback，并记录 warning。

transport: mqtt_json：
  - 显式走 JSON，不启用 binary 或 ROS1 serialized。
```

## 文件结构

- 修改：`protocol/binary_payloads.py`
  - 新增传输策略判断 helper，集中定义 `auto`、`mqtt_binary`、`mqtt_json` 对 ROS1 serialized 和现有 binary 编码的选择语义。
- 修改：`agent/ros1_agent.py`
  - 将 ROS1 serialized fast path 从 `transport == "mqtt_binary"` 扩展为 `auto/mqtt_binary` 策略下启用。
  - 保留 `transport == "mqtt_json"` 的显式 JSON 回退。
- 修改：`agent/base_agent.py`
  - 将 `/scan`、`/map` 等现有 `encode_sensor_binary()` 路径改为支持 `auto/mqtt_binary` 策略。
  - 保留不支持 binary 的消息类型走 JSON 的兼容行为。
- 修改：`qt_frontend/config/transmit_config.yaml`
  - 将 allowlist 内高频话题的配置改为 `transport: auto`，表达“由系统按能力选择”。
- 修改：`agent/configs/turtlebot_001.yaml`
  - 同步 turtlebot_001 的持久订阅配置，避免机器人端本地配置覆盖地面站下发配置。
- 可选修改：`agent/configs/turtlebot_002.yaml`
  - 如果后续需要双机器人统一验证，再将 turtlebot_002 的同类高频话题同步为 `transport: auto`。
- 修改：`docs/superpowers/plans/2026-06-17-ros1-serialized-data-plane.md`
  - 修正文档中“必须 `mqtt_binary` 才启用 serialized”的描述，改为 `auto/mqtt_binary` 启用，`mqtt_json` 显式回退。
- 修改：`docs/work-log-YYYY-MM-DD.md`
  - 执行当天新增工作日志，记录 transport 策略调整、验证结果和剩余风险。
- 测试：`tests/test_binary_payloads.py`
  - 覆盖传输策略 helper 的判定行为。
- 测试：`tests/test_ros1_agent.py`
  - 覆盖 ROS1 serialized fast path 在 `auto`、缺省、`mqtt_binary`、`mqtt_json` 下的行为。
- 测试：`tests/test_agent_topic_config.py`
  - 覆盖现有 binary sensor 路径在 `auto` 下仍能使用 `/scan`、`/map` binary 编码。

## 任务 1：协议层定义 transport 策略 helper

**文件：**
- 修改：`protocol/binary_payloads.py`
- 测试：`tests/test_binary_payloads.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_binary_payloads.py` 增加：

```python
def test_ros1_serialized_transport_policy_defaults_to_auto():
    assert should_use_ros_message_binary(
        "/tf",
        "tf2_msgs/TFMessage",
        transport=None,
    ) is True
    assert should_use_ros_message_binary(
        "/odom",
        "nav_msgs/Odometry",
        transport="auto",
    ) is True
    assert should_use_ros_message_binary(
        "/imu",
        "sensor_msgs/Imu",
        transport="mqtt_binary",
    ) is True
    assert should_use_ros_message_binary(
        "/odom",
        "nav_msgs/Odometry",
        transport="mqtt_json",
    ) is False
    assert should_use_ros_message_binary(
        "/joint_states",
        "sensor_msgs/JointState",
        transport="auto",
    ) is False


def test_structured_binary_transport_policy_defaults_to_auto():
    assert should_use_structured_sensor_binary(
        "sensor_msgs/LaserScan",
        transport=None,
    ) is True
    assert should_use_structured_sensor_binary(
        "nav_msgs/OccupancyGrid",
        transport="auto",
    ) is True
    assert should_use_structured_sensor_binary(
        "sensor_msgs/LaserScan",
        transport="mqtt_binary",
    ) is True
    assert should_use_structured_sensor_binary(
        "sensor_msgs/LaserScan",
        transport="mqtt_json",
    ) is False
    assert should_use_structured_sensor_binary(
        "sensor_msgs/JointState",
        transport="auto",
    ) is False
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_binary_payloads.py::test_ros1_serialized_transport_policy_defaults_to_auto tests/test_binary_payloads.py::test_structured_binary_transport_policy_defaults_to_auto -q
```

预期：失败，原因是 `should_use_ros_message_binary()` 和 `should_use_structured_sensor_binary()` 尚未实现。

- [ ] **步骤 3：实现传输策略 helper**

在 `protocol/binary_payloads.py` 中新增：

```python
TRANSPORT_AUTO = "auto"
TRANSPORT_MQTT_BINARY = "mqtt_binary"
TRANSPORT_MQTT_JSON = "mqtt_json"


def _normalize_transport(transport: Any) -> str:
    if transport is None:
        return TRANSPORT_AUTO
    value = str(transport).strip()
    return value or TRANSPORT_AUTO


def should_use_ros_message_binary(
    topic: str,
    msg_type: str,
    transport: Any = None,
) -> bool:
    mode = _normalize_transport(transport)
    if mode == TRANSPORT_MQTT_JSON:
        return False
    if mode in {TRANSPORT_AUTO, TRANSPORT_MQTT_BINARY}:
        return is_ros_message_binary_supported(topic, msg_type)
    return False


def should_use_structured_sensor_binary(
    msg_type: str,
    transport: Any = None,
) -> bool:
    mode = _normalize_transport(transport)
    if mode == TRANSPORT_MQTT_JSON:
        return False
    if mode in {TRANSPORT_AUTO, TRANSPORT_MQTT_BINARY}:
        return is_binary_supported(msg_type)
    return False
```

- [ ] **步骤 4：运行协议测试验证通过**

运行：

```bash
python3 -m pytest tests/test_binary_payloads.py -q
```

预期：全部通过。

- [ ] **步骤 5：Commit**

```bash
git add protocol/binary_payloads.py tests/test_binary_payloads.py
git commit -m "refactor: 抽象 MQTT 传输策略判断"
```

## 任务 2：Agent ROS1 serialized fast path 支持 auto

**文件：**
- 修改：`agent/ros1_agent.py`
- 测试：`tests/test_ros1_agent.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_ros1_agent.py` 中新增：

```python
def test_allowlisted_topic_uses_ros1_serialized_when_transport_is_auto(monkeypatch):
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
            AssertionError("auto allowlisted topic should use serialized path")
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
        "/tf",
        "tf2_msgs/TFMessage",
        {"freq_limit": 100.0, "transport": "auto"},
    )
    captured_callback["callback"](_SerializableRosMsg(b"tf-raw"))

    agent.publish_sensor_binary_data.assert_called_once()
    assert agent.publish_sensor_binary_data.call_args[0][:3] == (
        "/tf",
        "tf2_msgs/TFMessage",
        b"tf-raw",
    )


def test_allowlisted_topic_uses_ros1_serialized_when_transport_missing(monkeypatch):
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
            AssertionError("missing transport should default to auto")
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

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py::test_allowlisted_topic_uses_ros1_serialized_when_transport_is_auto tests/test_ros1_agent.py::test_allowlisted_topic_uses_ros1_serialized_when_transport_missing -q
```

预期：失败，原因是当前 `ROS1Agent` 默认 `transport` 为 `mqtt_json`，且 serialized fast path 只接受 `mqtt_binary`。

- [ ] **步骤 3：修改 Agent 判断逻辑**

在 `agent/ros1_agent.py` 中将 import 从：

```python
from protocol.binary_payloads import is_ros_message_binary_supported
```

改为：

```python
from protocol.binary_payloads import should_use_ros_message_binary
```

将 `_on_topic_subscribed()` 中：

```python
transport = options.get("transport", "mqtt_json")
```

改为：

```python
transport = options.get("transport", "auto")
```

将 callback 中：

```python
if tr == "mqtt_binary" and is_ros_message_binary_supported(t, mt):
```

改为：

```python
if should_use_ros_message_binary(t, mt, tr):
```

- [ ] **步骤 4：运行 Agent 测试验证通过**

运行：

```bash
python3 -m pytest tests/test_ros1_agent.py -q
```

预期：全部通过，且 `test_allowlisted_topic_uses_json_when_transport_is_mqtt_json` 仍通过，证明显式 JSON 回退未被破坏。

- [ ] **步骤 5：Commit**

```bash
git add agent/ros1_agent.py tests/test_ros1_agent.py
git commit -m "feat: 支持 ROS1 serialized auto 传输策略"
```

## 任务 3：结构化 binary sensor 路径支持 auto

**文件：**
- 修改：`agent/base_agent.py`
- 测试：`tests/test_agent_topic_config.py`

- [ ] **步骤 1：编写失败的测试**

在 `tests/test_agent_topic_config.py` 中增加：

```python
def test_publish_sensor_data_uses_binary_transport_for_scan_when_auto():
    agent = RecordingAgent(AgentConfig(robot_id="robot_001"))
    agent._subscribed_topics["/scan"] = {
        "msg_type": "sensor_msgs/LaserScan",
        "freq_limit": 0.0,
        "transport": "auto",
        "qos": 2,
        "options": {},
    }

    agent.publish_sensor_data(
        "/scan",
        "sensor_msgs/LaserScan",
        {
            "header": {
                "seq": 1,
                "stamp": {"secs": 2, "nsecs": 3},
                "frame_id": "base_scan",
            },
            "angle_min": 0.0,
            "angle_max": 1.0,
            "angle_increment": 1.0,
            "time_increment": 0.0,
            "scan_time": 0.1,
            "range_min": 0.1,
            "range_max": 3.5,
            "ranges": [1.0, 2.0],
            "intensities": [],
        },
    )

    topics = [item[0] for item in agent.published]
    assert "robot/robot_001/sensor/scan" in topics
    assert "robot/robot_001/sensor/scan/bin" in topics
```

- [ ] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_agent_topic_config.py::test_publish_sensor_data_uses_binary_transport_for_scan_when_auto -q
```

预期：失败，原因是当前 `BaseAgent.publish_sensor_data()` 只在 `transport == "mqtt_binary"` 时使用 `encode_sensor_binary()`。

- [ ] **步骤 3：修改 BaseAgent 判断逻辑**

在 `agent/base_agent.py` 中将 import 从：

```python
from protocol.binary_payloads import (
    encode_ros_message_binary,
    encode_sensor_binary,
    is_binary_supported,
)
```

改为：

```python
from protocol.binary_payloads import (
    encode_ros_message_binary,
    encode_sensor_binary,
    should_use_structured_sensor_binary,
)
```

将 `publish_sensor_data()` 中：

```python
transport = sub_info.get("transport", "mqtt_json")
if transport == "mqtt_binary" and is_binary_supported(msg_type):
```

改为：

```python
transport = sub_info.get("transport", "auto")
if should_use_structured_sensor_binary(msg_type, transport):
```

- [ ] **步骤 4：运行 topic config 测试验证通过**

运行：

```bash
python3 -m pytest tests/test_agent_topic_config.py -q
```

预期：全部通过。

- [ ] **步骤 5：Commit**

```bash
git add agent/base_agent.py tests/test_agent_topic_config.py
git commit -m "feat: 支持结构化传感器 auto binary 策略"
```

## 任务 4：配置文件改为 auto 策略

**文件：**
- 修改：`qt_frontend/config/transmit_config.yaml`
- 修改：`agent/configs/turtlebot_001.yaml`
- 可选修改：`agent/configs/turtlebot_002.yaml`

- [ ] **步骤 1：修改 turtlebot_001 地面站订阅配置**

在 `qt_frontend/config/transmit_config.yaml` 中，将 `turtlebot_001` 下列话题改为：

```yaml
- topic: /odom
  msg_type: nav_msgs/Odometry
  transport: auto
  qos: 0
- topic: /imu
  msg_type: sensor_msgs/Imu
  transport: auto
  qos: 0
- topic: /tf
  msg_type: tf2_msgs/TFMessage
  transport: auto
  qos: 0
- topic: /tf_static
  msg_type: tf2_msgs/TFMessage
  transport: auto
  qos: 1
- topic: /scan
  msg_type: sensor_msgs/LaserScan
  transport: auto
  qos: 0
- topic: /map
  msg_type: nav_msgs/OccupancyGrid
  transport: auto
  qos: 1
```

保留 `/joint_states` 为：

```yaml
transport: mqtt_json
```

- [ ] **步骤 2：修改 turtlebot_001 Agent 持久配置**

在 `agent/configs/turtlebot_001.yaml` 中做同样调整，确保 Agent 重启后不会用本地持久配置覆盖地面站配置。

- [ ] **步骤 3：可选同步 turtlebot_002**

如果需要双机器人同时验证，则在 `agent/configs/turtlebot_002.yaml` 中将 `/odom`、`/imu`、`/tf`、`/tf_static`、`/scan`、`/map` 同步为 `transport: auto`，并保留 `/joint_states` 为 `mqtt_json`。

- [ ] **步骤 4：运行 YAML 解析检查**

运行：

```bash
python3 - <<'PY'
from __future__ import annotations

from pathlib import Path

import yaml

for path in [
    Path("qt_frontend/config/transmit_config.yaml"),
    Path("agent/configs/turtlebot_001.yaml"),
    Path("agent/configs/turtlebot_002.yaml"),
]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    print(path, "ok")
PY
```

预期：输出 3 个 `ok`。

- [ ] **步骤 5：Commit**

```bash
git add qt_frontend/config/transmit_config.yaml agent/configs/turtlebot_001.yaml agent/configs/turtlebot_002.yaml
git commit -m "config: 使用 auto 传输策略"
```

## 任务 5：文档更新

**文件：**
- 修改：`docs/superpowers/plans/2026-06-17-ros1-serialized-data-plane.md`
- 创建或修改：`docs/work-log-YYYY-MM-DD.md`

- [ ] **步骤 1：更新 serialized 数据面计划说明**

将 `docs/superpowers/plans/2026-06-17-ros1-serialized-data-plane.md` 中类似表述：

```text
只有订阅配置 transport: mqtt_binary 且 (topic, msg_type) 命中 ROS1 serialized allowlist 时，Agent 才能发布 ros1_serialized_v1。
```

改为：

```text
当订阅配置为 transport: auto、缺省 transport，或显式 transport: mqtt_binary，且 (topic, msg_type) 命中 ROS1 serialized allowlist 时，Agent 发布 ros1_serialized_v1。显式 transport: mqtt_json 用作调试和兼容回退，必须保留 JSON 路径。
```

- [ ] **步骤 2：新增当天工作日志**

在 `docs/work-log-YYYY-MM-DD.md` 中增加一节，说明：

```text
今日将 transport 字段从“手动选择具体传输类型”调整为“传输策略覆盖项”。auto 策略下，系统会根据话题和消息类型自动选择 ROS1 serialized、结构化 binary 或 JSON 路径；mqtt_json 保留为显式回退。
```

并记录运行过的测试命令和结果。

- [ ] **步骤 3：Commit**

```bash
git add docs/superpowers/plans/2026-06-17-ros1-serialized-data-plane.md docs/work-log-YYYY-MM-DD.md
git commit -m "docs: 记录 auto 传输策略调整"
```

## 任务 6：运行态验证

**文件：**
- 不修改代码；只执行验证命令。

- [ ] **步骤 1：启动 turtlebot_001 和地面站链路**

运行：

```bash
docker compose up -d robot-turtlebot-001
./qt_frontend/scripts/start.sh
```

预期：容器、`roscore`、Mosquitto、Bridge 和 Qt 前端正常启动。

- [ ] **步骤 2：验证 `/tf` 走 ROS1 serialized**

运行：

```bash
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/tf -C 1
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/tf/bin -C 1
```

预期：

- `robot/turtlebot_001/sensor/tf` 输出 JSON envelope，包含 `encoding=ros1_serialized_v1`、`payload_format=ros1_serialized`、`msg_type=tf2_msgs/TFMessage`。
- `robot/turtlebot_001/sensor/tf/bin` 能收到二进制 payload。

- [ ] **步骤 3：验证 ROS 侧 TF 频率和 frame namespace**

运行：

```bash
timeout 12 rostopic hz /tf
timeout 6 rosrun tf tf_echo turtlebot_001/odom turtlebot_001/base_link
```

预期：

- `/tf` 接近容器内原始频率，单机器人场景约 80 Hz。
- `tf_echo` 持续输出 transform。
- 地面站 TF tree 中不出现未命名空间化的 `odom`、`base_link`、`base_scan` 作为多机器人共享 frame。

- [ ] **步骤 4：验证 `/odom`、`/imu`、`/scan`、`/map` 自动策略**

运行：

```bash
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/odom -C 1
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/imu -C 1
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/scan -C 1
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/map -C 1
```

预期：

- `/odom`、`/imu` envelope 为 `encoding=ros1_serialized_v1`。
- `/scan` envelope 为 `encoding=laser_scan_v1`。
- `/map` envelope 为 `encoding=occupancy_grid_v1`。

- [ ] **步骤 5：关闭链路**

运行：

```bash
./qt_frontend/scripts/stop.sh
```

预期：Bridge、Qt 前端和本地地面站相关进程被清理。

- [ ] **步骤 6：记录验证结果**

将 MQTT envelope、`/tf/bin` 是否存在、`rostopic hz /tf` 输出和 `tf_echo` 结果写入当天工作日志。

## 最终验证命令

执行全部自动化测试：

```bash
python3 -m pytest tests/test_binary_payloads.py tests/test_ros1_agent.py tests/test_agent_topic_config.py tests/test_mqtt_ros_bridge.py tests/test_mqtt_client.py -q
```

预期：全部通过。

执行运行态验证：

```bash
docker compose up -d robot-turtlebot-001
./qt_frontend/scripts/start.sh
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/tf -C 1
timeout 12 mosquitto_sub -h localhost -t robot/turtlebot_001/sensor/tf/bin -C 1
timeout 12 rostopic hz /tf
timeout 6 rosrun tf tf_echo turtlebot_001/odom turtlebot_001/base_link
./qt_frontend/scripts/stop.sh
```

预期：`/tf` 通过 `ros1_serialized_v1` envelope 加 `/tf/bin` payload 传输，ROS 侧 `/tf` 频率保持约 80 Hz，frame namespace 验证通过。

## 不在本计划中处理

- 不删除 `transport` 字段。
- 不把所有话题无条件改成 binary。
- 不改变 MQTT topic 命名结构。
- 不改变 `/tf`、`/tf_static` 在地面站 ROS 中使用公共 topic 的模型。
- 不迁移 `/map` 到 ROS1 serialized，仍保留 `occupancy_grid_v1` 加 zlib 压缩。
