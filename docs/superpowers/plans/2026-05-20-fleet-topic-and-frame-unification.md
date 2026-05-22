# 多机器人 Topic 转发与坐标统一实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将当前 MQTT 地面站扩展为通用多机器人 ROS topic 跨机器人转发与统一坐标显示系统，逐步具备替代旧 TCP 桥接的能力。

**架构：** 机器人端 Agent 根据 `fleet_rules` 执行本地 ROS topic 到 MQTT `robot/{src}/to/{dst}` 的出站转发，并在目标机器人端还原为指定 `dst_topic` 的类型化 ROS 消息。地面站 Bridge 负责多机器人可视化侧的 frame 命名空间化和 fleet 静态 TF 发布，Qt 前端负责配置、保存、下发和拉取规则。

**技术栈：** ROS Noetic、rospy、tf2_ros、MQTT、PyQt5、pytest、Docker Compose、Turtlebot3 Gazebo/gmapping。

---

## 背景与边界

当前目标不是深度集成某个多机探索算法，而是把系统扩展成通用的 ROS topic 跨机器人转发层和多机器人统一坐标显示层。多机探索算法继续在机器人本地运行；地面站不理解算法语义，只理解机器人、topic、msg_type、frame 和订阅/转发配置。

已有基础：

- `protocol/topics.py` 已定义 `robot/{src}/to/{dst}` 和 `robot/{src}/to/{dst}/meta`。
- `protocol/messages.py` 已定义 `FleetData`。
- `agent/base_agent.py` 已支持发送和接收 `fleet_data`。
- `agent/ros1_agent.py` 当前会把收到的 fleet 数据发布到 `/fleet/incoming`。
- `bridge/mqtt_ros_bridge.py` 已支持 robot_id 命名空间发布、动态 topic 订阅和 `namespace_tf_frames`。
- `qt_frontend/panels/fleet_comm_panel.py` 已有 FleetCommPanel 入口。

主要缺口：

- `fleet_rules` 还没有真正驱动 ROS topic 自动转发。
- 收到 `fleet_data` 后没有按 `dst_topic` 还原成类型化 ROS topic。
- `FleetData` 缺少 `src_topic`、`dst_topic`、`msg_type`、`frame_policy`、`stamp` 等字段。
- frame 命名空间化目前主要处理 `tf2_msgs/TFMessage`，还没有覆盖普通 ROS 消息的 `header.frame_id` 和 `child_frame_id`。
- 还缺 `global_map -> robot_i/map` 这类 fleet 静态 TF 管理。

## 目标数据流

```text
Robot A 本地 ROS topic
  /odom
    ↓
Robot A Agent 按 fleet_rules 订阅
    ↓
MQTT robot/A/to/B
    ↓
Robot B Agent 接收
    ↓
还原为 ROS 消息
    ↓
发布到 Robot B 本地指定话题
  /fleet/A/odom 或旧算法期望的固定话题
```

机器人间数据不经过 Qt 前端。Qt 前端关闭后，只要 Agent 和 MQTT Broker 仍在，转发规则应继续工作。

## 计划文件结构

- 修改：`docker-compose.yml`
  - 新增 `robot-turtlebot-002` 服务，用于双 Turtlebot 多机器人接入验证。
- 修改：`protocol/messages.py`
  - 扩展 `FleetData` 字段，保持向后兼容。
- 修改：`agent/base_agent.py`
  - 规范化 `fleet_rules`，接收配置后应用规则，发送扩展后的 `FleetData`。
- 修改：`agent/ros1_agent.py`
  - 增加 fleet 出站 ROS 订阅管理。
  - 增加入站 `fleet_data` 到类型化 ROS topic 的还原发布。
- 创建：`agent/frame_utils.py`
  - 处理 dict 形式 ROS 消息中的 `header.frame_id`、`child_frame_id` 和 TF transforms frame。
- 修改：`bridge/mqtt_ros_bridge.py`
  - 复用 frame 工具，让传感器数据进入地面站 roscore 前进行一致的 frame 命名空间化。
  - 增加 fleet 静态 TF 发布入口。
- 修改：`bridge/bridge_config.yaml`
  - 增加 `fleet_frames` 配置样例，并为多机器人测试开启或说明 `namespace_tf_frames`。
- 修改：`qt_frontend/config/transmit_config.yaml`
  - 增加 `turtlebot_002` 测试订阅和 `fleet_rules` 样例。
- 修改：`qt_frontend/panels/fleet_comm_panel.py`
  - 扩展 UI 字段：源 topic、消息类型、目标机器人、目标 topic、频率、frame 策略。
- 测试：`tests/test_protocol_messages.py`
  - 覆盖扩展 `FleetData` 序列化兼容性。
- 测试：`tests/test_agent_fleet_rules.py`
  - 覆盖规则规范化、配置同步保留行为、出站目标展开。
- 测试：`tests/test_frame_utils.py`
  - 覆盖常见 ROS 消息 dict 的 frame 命名空间化。
- 测试：`tests/test_bridge_frame_namespace.py`
  - 覆盖 Bridge 对普通消息和 TFMessage 的 frame 处理。

## 任务 1：新增双 Turtlebot 测试服务

**文件：**

- 修改：`docker-compose.yml`

- [x] **步骤 1：新增 `robot-turtlebot-002` 服务**

在 `robot-turtlebot-001` 后新增：

```yaml
  robot-turtlebot-002:
    build:
      context: .
      dockerfile: docker/Dockerfile.ros
    container_name: turtlebot-002
    environment:
      - ROBOT_ID=turtlebot_002
      - BROKER_HOST=host-gateway
      - TURTLEBOT3_MODEL=burger
      - DISPLAY=${DISPLAY}
    extra_hosts:
      - "host-gateway:host-gateway"
    restart: unless-stopped
    volumes:
      - ./protocol:/app/protocol:ro
      - ./agent:/app/agent:rw
      - ./docker/supervisord-turtlebot3.conf:/etc/supervisor/conf.d/ros-agent.conf:ro
      - /tmp/.X11-unix:/tmp/.X11-unix:rw
    devices:
      - /dev/dri:/dev/dri
    stdin_open: true
    tty: true
```

- [ ] **步骤 2：启动两个 Turtlebot 容器**

运行：

```bash
docker compose up -d robot-turtlebot-001 robot-turtlebot-002
```

预期：两个容器均处于 running 状态。

- [ ] **步骤 3：启动地面站链路**

运行：

```bash
./qt_frontend/scripts/start.sh
```

预期：Bridge、Qt 前端、roscore、Mosquitto 能启动；若 Gazebo 图形环境不可用，记录该风险，不影响后续 mock/topic 级测试。

- [ ] **步骤 4：验证两个机器人被发现**

运行：

```bash
rostopic list | grep turtlebot
```

预期至少能看到：

```text
/turtlebot_001/odom
/turtlebot_001/scan
/turtlebot_002/odom
/turtlebot_002/scan
```

## 任务 2：扩展 FleetData 协议

**文件：**

- 修改：`protocol/messages.py`
- 测试：`tests/test_protocol_messages.py`

- [x] **步骤 1：编写失败测试**

在 `tests/test_protocol_messages.py` 中增加：

```python
def test_fleet_data_ros_topic_fields(factory):
    fd = FleetData(
        data_type="ros_topic",
        src_topic="/odom",
        dst_topic="/fleet/turtlebot_001/odom",
        msg_type="nav_msgs/Odometry",
        frame_policy="namespace",
        payload={"header": {"frame_id": "odom"}},
        stamp=123.0,
        ttl=1.0,
    )

    msg = factory.fleet_data(fd, dst="turtlebot_002")

    assert msg.type == MessageType.FLEET_DATA
    assert msg.dst == "turtlebot_002"
    assert msg.data["src_topic"] == "/odom"
    assert msg.data["dst_topic"] == "/fleet/turtlebot_001/odom"
    assert msg.data["msg_type"] == "nav_msgs/Odometry"
    assert msg.data["frame_policy"] == "namespace"
    assert msg.data["stamp"] == 123.0
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_protocol_messages.py::TestMessageFactory::test_fleet_data_ros_topic_fields -v
```

预期：FAIL，提示 `FleetData.__init__()` 不接受新增字段。

- [x] **步骤 3：扩展 `FleetData`**

在 `protocol/messages.py` 中将 `FleetData` 扩展为：

```python
@dataclass
class FleetData:
    """机器人间数据"""
    data_type: str = "custom"
    payload: Dict[str, Any] = field(default_factory=dict)
    ttl: float = 30.0
    src_topic: str = ""
    dst_topic: str = ""
    msg_type: str = ""
    frame_policy: str = "preserve"
    stamp: float = 0.0
```

保持字段默认值，确保旧消息仍可解析。

- [x] **步骤 4：运行协议测试**

运行：

```bash
python3 -m pytest tests/test_protocol_messages.py -v
```

预期：PASS。

## 任务 3：新增 frame 命名空间工具

**文件：**

- 创建：`agent/frame_utils.py`
- 测试：`tests/test_frame_utils.py`

- [x] **步骤 1：编写失败测试**

创建 `tests/test_frame_utils.py`：

```python
from __future__ import annotations

from agent.frame_utils import namespace_message_frames


def test_namespace_header_frame_id():
    data = {"header": {"frame_id": "base_scan"}}

    namespace_message_frames(data, "turtlebot_001")

    assert data["header"]["frame_id"] == "turtlebot_001/base_scan"


def test_namespace_child_frame_id():
    data = {"child_frame_id": "base_link"}

    namespace_message_frames(data, "turtlebot_001")

    assert data["child_frame_id"] == "turtlebot_001/base_link"


def test_namespace_tf_message_frames():
    data = {
        "transforms": [
            {
                "header": {"frame_id": "odom"},
                "child_frame_id": "base_footprint",
            }
        ]
    }

    namespace_message_frames(data, "turtlebot_001")

    transform = data["transforms"][0]
    assert transform["header"]["frame_id"] == "turtlebot_001/odom"
    assert transform["child_frame_id"] == "turtlebot_001/base_footprint"


def test_namespace_is_idempotent():
    data = {"header": {"frame_id": "turtlebot_001/odom"}}

    namespace_message_frames(data, "turtlebot_001")

    assert data["header"]["frame_id"] == "turtlebot_001/odom"
```

- [x] **步骤 2：运行测试验证失败**

运行：

```bash
python3 -m pytest tests/test_frame_utils.py -v
```

预期：FAIL，提示 `agent.frame_utils` 不存在。

- [x] **步骤 3：实现工具函数**

创建 `agent/frame_utils.py`：

```python
from __future__ import annotations

from typing import Any, Dict


def namespace_frame_id(frame_id: str, robot_id: str) -> str:
    if not frame_id or not robot_id:
        return frame_id
    prefix = f"{robot_id}/"
    if frame_id.startswith(prefix):
        return frame_id
    if frame_id.startswith("/"):
        frame_id = frame_id[1:]
    return prefix + frame_id


def namespace_message_frames(data: Dict[str, Any], robot_id: str) -> None:
    if not isinstance(data, dict):
        return

    header = data.get("header")
    if isinstance(header, dict):
        frame_id = header.get("frame_id")
        if isinstance(frame_id, str):
            header["frame_id"] = namespace_frame_id(frame_id, robot_id)

    child_frame_id = data.get("child_frame_id")
    if isinstance(child_frame_id, str):
        data["child_frame_id"] = namespace_frame_id(child_frame_id, robot_id)

    transforms = data.get("transforms")
    if isinstance(transforms, list):
        for transform in transforms:
            if isinstance(transform, dict):
                namespace_message_frames(transform, robot_id)
```

- [x] **步骤 4：运行 frame 工具测试**

运行：

```bash
python3 -m pytest tests/test_frame_utils.py -v
```

预期：PASS。

## 任务 4：Bridge 复用通用 frame 命名空间化

**文件：**

- 修改：`bridge/mqtt_ros_bridge.py`
- 测试：`tests/test_bridge_frame_namespace.py`

- [x] **步骤 1：编写 Bridge frame 测试**

创建或扩展 `tests/test_bridge_frame_namespace.py`：

```python
from __future__ import annotations

from agent.frame_utils import namespace_message_frames


def test_namespace_occupancy_grid_frame():
    data = {"header": {"frame_id": "map"}, "info": {}}

    namespace_message_frames(data, "turtlebot_001")

    assert data["header"]["frame_id"] == "turtlebot_001/map"


def test_namespace_odometry_frames():
    data = {
        "header": {"frame_id": "odom"},
        "child_frame_id": "base_footprint",
        "pose": {},
        "twist": {},
    }

    namespace_message_frames(data, "turtlebot_001")

    assert data["header"]["frame_id"] == "turtlebot_001/odom"
    assert data["child_frame_id"] == "turtlebot_001/base_footprint"
```

- [x] **步骤 2：替换 Bridge 内部 `_prefix_tf_frames` 逻辑**

在 `bridge/mqtt_ros_bridge.py` 引入：

```python
from agent.frame_utils import namespace_message_frames
```

将传感器数据转换前的逻辑改为：

```python
if self._namespace_tf_frames:
    namespace_message_frames(data_dict, robot_id)
```

保留 `_prefix_tf_frames` 作为兼容包装也可以，但新逻辑必须覆盖所有带 frame 的消息，而不仅是 `tf2_msgs/TFMessage`。

- [x] **步骤 3：运行 Bridge 相关测试**

运行：

```bash
python3 -m pytest tests/test_bridge_frame_namespace.py tests/test_frame_utils.py -v
```

预期：PASS。

## 任务 5：实现 Agent 出站 fleet_rules 转发

**文件：**

- 修改：`agent/base_agent.py`
- 修改：`agent/ros1_agent.py`
- 测试：`tests/test_agent_fleet_rules.py`

- [x] **步骤 1：编写规则规范化测试**

创建 `tests/test_agent_fleet_rules.py`，先覆盖纯逻辑函数：

```python
from __future__ import annotations

from agent.base_agent import BaseAgent


def test_normalize_fleet_rule_targets():
    raw = [
        {
            "enabled": True,
            "src_topic": "/odom",
            "msg_type": "nav_msgs/Odometry",
            "targets": [
                {
                    "robot_id": "turtlebot_002",
                    "dst_topic": "/fleet/turtlebot_001/odom",
                }
            ],
            "freq_limit": 10.0,
            "transport": "mqtt_json",
            "frame_policy": "namespace",
        }
    ]

    rules = BaseAgent._normalize_fleet_rules(raw)

    assert rules[0]["enabled"] is True
    assert rules[0]["src_topic"] == "/odom"
    assert rules[0]["targets"][0]["robot_id"] == "turtlebot_002"
    assert rules[0]["targets"][0]["dst_topic"] == "/fleet/turtlebot_001/odom"
```

- [x] **步骤 2：实现 `_normalize_fleet_rules`**

在 `agent/base_agent.py` 增加静态方法，输出字段固定为：

```python
{
    "enabled": bool,
    "src_topic": str,
    "msg_type": str,
    "targets": [{"robot_id": str, "dst_topic": str}],
    "freq_limit": float,
    "transport": str,
    "frame_policy": str,
}
```

过滤缺少 `src_topic`、`msg_type` 或有效 target 的规则。

- [x] **步骤 3：配置同步时应用 fleet rules**

在 `_handle_config_sync()` 中，把：

```python
new_fleet_rules = data.get("fleet_rules", self.config.fleet_rules)
```

改为：

```python
new_fleet_rules = self._normalize_fleet_rules(
    data.get("fleet_rules", self.config.fleet_rules)
)
```

并在规则变化后调用子类钩子：

```python
self._apply_fleet_rules(self.config.fleet_rules)
```

在 `BaseAgent` 中提供空实现：

```python
def _apply_fleet_rules(self, fleet_rules: List[Dict[str, Any]]) -> None:
    return
```

- [x] **步骤 4：ROS1Agent 根据规则订阅出站 topic**

在 `agent/ros1_agent.py` 增加 `_fleet_subscribers` 字典。`_apply_fleet_rules()` 应：

1. 注销旧 fleet 订阅。
2. 对每条 enabled 规则订阅 `src_topic`。
3. 回调中将 ROS 消息转 dict，按 target 调用 `send_to_robot()`。

回调构造：

```python
FleetData(
    data_type="ros_topic",
    src_topic=src_topic,
    dst_topic=target["dst_topic"],
    msg_type=msg_type,
    frame_policy=frame_policy,
    payload=payload_dict,
    stamp=time.time(),
    ttl=1.0,
)
```

- [x] **步骤 5：运行 Agent fleet 测试**

运行：

```bash
python3 -m pytest tests/test_agent_fleet_rules.py -v
```

预期：PASS。

## 任务 6：实现入站 fleet_data 类型化 ROS 发布

**文件：**

- 修改：`agent/ros1_agent.py`
- 测试：`tests/test_agent_fleet_rules.py`

- [x] **步骤 1：定义入站行为**

当 `data.data_type == "ros_topic"` 时：

- `dst_topic` 必须以 `/` 开头。
- `msg_type` 必须非空。
- `payload` 必须是 dict。
- 如果 `frame_policy == "namespace"`，对 `payload` 做 frame 命名空间化，使用 `src_id` 作为命名空间。
- 使用现有 ROS 消息转换工具将 dict 转为 ROS msg。
- 发布到 `dst_topic`。

- [x] **步骤 2：实现发布者缓存**

在 `ROS1Agent` 增加：

```python
self._fleet_publishers = {}
```

key 使用 `(dst_topic, msg_type)`，避免重复创建 publisher。

- [x] **步骤 3：保留 `/fleet/incoming` 调试发布**

现有 `/fleet/incoming` 的 JSON String 发布保留，但类型化发布应先执行。类型化发布失败时，记录 error，并仍发布调试消息。

- [x] **步骤 4：手动验证**

启动两个 Turtlebot 后，下发一条规则：

```yaml
fleet_rules:
  - enabled: true
    src_topic: /odom
    msg_type: nav_msgs/Odometry
    targets:
      - robot_id: turtlebot_002
        dst_topic: /fleet/turtlebot_001/odom
    freq_limit: 10.0
    transport: mqtt_json
    frame_policy: namespace
```

在 `turtlebot_002` 容器内运行：

```bash
rostopic info /fleet/turtlebot_001/odom
rostopic echo -n 1 /fleet/turtlebot_001/odom/header
```

预期：topic 类型为 `nav_msgs/Odometry`，`header.frame_id` 为 `turtlebot_001/odom`。

## 任务 7：增加 fleet 静态 TF 配置和发布

**文件：**

- 修改：`bridge/bridge_config.yaml`
- 修改：`bridge/mqtt_ros_bridge.py`
- 测试：`tests/test_mqtt_ros_bridge.py`

- [x] **步骤 1：添加配置样例**

在 `bridge/bridge_config.yaml` 增加：

```yaml
fleet_frames:
  enabled: false
  global_frame: "global_map"
  robots:
    turtlebot_001:
      local_root_frame: "map"
      pose:
        x: 0.0
        y: 0.0
        z: 0.0
        roll: 0.0
        pitch: 0.0
        yaw: 0.0
    turtlebot_002:
      local_root_frame: "map"
      pose:
        x: 2.0
        y: 0.0
        z: 0.0
        roll: 0.0
        pitch: 0.0
        yaw: 0.0
```

- [x] **步骤 2：实现静态 TF 发布**

在 Bridge 初始化时，如果 `fleet_frames.enabled` 为 true，发布：

```text
global_map -> turtlebot_001/map
global_map -> turtlebot_002/map
```

发布方式优先使用 `tf2_ros.StaticTransformBroadcaster`。`child_frame_id` 使用：

```python
f"{robot_id}/{local_root_frame}"
```

- [x] **步骤 3：验证 RViz fixed frame**

开启配置后，启动地面站链路，在 RViz 中将 fixed frame 设置为：

```text
global_map
```

预期：TF 树能连到两个机器人局部 map。

## 任务 8：扩展 FleetCommPanel

**文件：**

- 修改：`qt_frontend/panels/fleet_comm_panel.py`
- 修改：`qt_frontend/main_window.py`
- 测试：`tests/test_panels.py`

- [x] **步骤 1：扩展规则字段校验**

将校验从 `(src, dst, topic)` 扩展到：

```python
validate_fleet_rule(
    src_robot,
    src_topic,
    msg_type,
    dst_robot,
    dst_topic,
    freq_limit,
)
```

规则：

- 源机器人和目标机器人非空。
- 源机器人不能等于目标机器人。
- `src_topic` 和 `dst_topic` 必须以 `/` 开头。
- `msg_type` 非空。
- `freq_limit >= 0.0`。

- [x] **步骤 2：更新面板列**

表格列改为：

```text
启用
源机器人
源话题
消息类型
目标机器人
目标话题
频率
Frame 策略
操作
```

- [x] **步骤 3：生成配置结构**

保存时输出：

```yaml
fleet_rules:
  - enabled: true
    src_topic: /odom
    msg_type: nav_msgs/Odometry
    targets:
      - robot_id: turtlebot_002
        dst_topic: /fleet/turtlebot_001/odom
    freq_limit: 10.0
    transport: mqtt_json
    frame_policy: namespace
```

- [x] **步骤 4：运行面板测试**

运行：

```bash
python3 -m pytest tests/test_panels.py -v
```

预期：PASS。

## 任务 9：端到端双 Turtlebot 验证

**文件：**

- 修改：`qt_frontend/config/transmit_config.yaml`
- 修改：`bridge/bridge_config.yaml`

- [ ] **步骤 1：配置两个 Turtlebot 的基础订阅**

确保 `qt_frontend/config/transmit_config.yaml` 中有：

```yaml
subscriptions:
  turtlebot_001:
    - topic: /odom
      msg_type: nav_msgs/Odometry
      freq_limit: 30.0
      transport: mqtt_json
      qos: 1
      compression: {}
  turtlebot_002:
    - topic: /odom
      msg_type: nav_msgs/Odometry
      freq_limit: 30.0
      transport: mqtt_json
      qos: 1
      compression: {}
```

- [ ] **步骤 2：开启 frame namespace 和 fleet frames**

在 `bridge/bridge_config.yaml` 中设置：

```yaml
ros:
  namespace_tf_frames: true

fleet_frames:
  enabled: true
```

- [ ] **步骤 3：启动环境**

运行：

```bash
docker compose up -d robot-turtlebot-001 robot-turtlebot-002
./qt_frontend/scripts/start.sh
```

- [ ] **步骤 4：验证地面站 ROS topic**

运行：

```bash
rostopic list | grep turtlebot
```

预期能看到两个机器人各自的 `odom`、`scan`、`map` 等话题。

- [ ] **步骤 5：验证 TF**

运行：

```bash
rosrun tf view_frames
```

预期 TF 树中存在：

```text
global_map -> turtlebot_001/map
global_map -> turtlebot_002/map
turtlebot_001/map -> turtlebot_001/odom
turtlebot_002/map -> turtlebot_002/odom
```

- [ ] **步骤 6：验证 fleet topic 转发**

在 `turtlebot_002` 容器内运行：

```bash
rostopic echo -n 1 /fleet/turtlebot_001/odom/header
```

预期能收到来自 `turtlebot_001` 的 odom，且 frame_id 已命名空间化。

## 任务 10：最终验证和记录

**文件：**

- 创建：`docs/work-log-YYYY-MM-DD.md`

- [ ] **步骤 1：运行单元测试**

运行：

```bash
python3 -m pytest tests/ -v
```

预期：PASS。

- [ ] **步骤 2：运行 lint**

运行：

```bash
ruff check .
```

预期：PASS，或记录已有 lint 问题和本次变更是否引入新问题。

- [ ] **步骤 3：写工作日志**

按照仓库要求创建当天工作日志，包含：

- 今日概览
- 多机器人 Docker 测试环境
- fleet_rules 转发闭环
- 坐标 frame 命名空间化
- fleet 静态 TF
- 测试与验证
- 当前状态和未验证风险

## 验收标准

最终应满足：

- 可以启动 `robot-turtlebot-001` 和 `robot-turtlebot-002`。
- 地面站能发现两台机器人。
- 地面站 roscore 中机器人 topic 按 `/{robot_id}/{topic}` 隔离。
- `/tf` 中多个机器人 frame 不冲突。
- `global_map` 能连接到每台机器人的局部 map frame。
- `turtlebot_001` 的 `/odom` 能通过 MQTT fleet data 到达 `turtlebot_002`，并在 `turtlebot_002` 本地发布为配置指定的 `dst_topic`。
- 入站发布为类型化 ROS 消息，不是 `std_msgs/String`。
- Qt 前端能够保存、下发、拉取 fleet 规则。

## 风险与约束

- 两个 Turtlebot 容器各自运行独立 Gazebo/roscore，不是在同一个 Gazebo 世界中产生物理交互；这不影响通信和坐标系统验证。
- 如果真实旧多机探索算法依赖特殊 topic 名称或私有消息类型，需要后续拿到算法后补充对应 `msg_type` 转换测试。
- MQTT JSON 适合轻量/中等数据。高频点云、大地图或图像应使用限频、二进制或 HTTP stream。
- 第一版只做 frame 命名空间化和静态 TF 对齐，不做运行时地图融合或自动全局坐标估计。

## 执行建议

优先顺序：

1. 双 Turtlebot 接入验证。
2. frame 命名空间化和 `global_map` 静态 TF。
3. `FleetData` 和 `fleet_rules` 协议闭环。
4. Agent 出站和入站类型化 ROS topic 转发。
5. Qt 面板补全。
6. 用真实多机探索算法做无侵入替换测试。
