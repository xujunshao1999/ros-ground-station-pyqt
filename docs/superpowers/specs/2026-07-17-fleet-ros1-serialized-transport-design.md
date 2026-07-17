# 编队 ROS1 Serialized 传输设计

## 一、背景与目标

当前机器人编队转发由源机器人 `ROS1Agent` 订阅本地 ROS topic，将消息转换为 Python 字典并封装成 `FleetData`，再通过 MQTT JSON 发送到目标机器人。目标 Agent 解析 JSON、重建 ROS 消息并发布到配置的 `dst_topic`。这条链路通用且便于调试，但高频消息需要经历 `ROS 对象 -> dict -> JSON -> dict -> ROS 对象`，CPU、消息体积和 Broker 压力都会随频率及数组长度增长，实际接收频率可能低于源频率或配置的 `freq_limit`。

本次改造目标是让 `fleet_rules.transport` 真正控制编队数据面：

- `mqtt_json` 保持现有行为和兼容性；
- `mqtt_binary` 直接传输 ROS1 原生 serialized bytes；
- 源端二进制序列化失败时，当前消息自动回退到 MQTT JSON；
- 目标端仍按 `dst_topic` 发布原消息类型，并继续支持 `frame_policy`；
- 高频实时状态可使用 QoS 0 避免积压，关键低频消息可使用 QoS 1 保证至少送达一次。

本设计不改变机器人 ROS master 相互隔离的架构。机器人之间仍只通过共享 MQTT Broker 通信，不直接连接对方的 ROS master，也不经过地面站 Bridge 转发。

## 二、非目标

- 不在本次改造中迁移 HTTP pointcloud snapshot 链路；`share_heavy_data()` 保持现状。
- 不增加通用压缩。ROS1 serialized payload 默认不压缩，避免额外 CPU 和延迟。
- 不实现端到端 ACK、重传或严格一次投递；可靠性继续由 MQTT QoS 控制。
- 不让目标端在反序列化失败后回退 JSON，因为 binary 消息中不存在可供恢复的 JSON payload。
- 不改变普通机器人到地面站的 sensor 数据面和 Bridge 行为。

## 三、术语与执行约定

- **Agent**：运行在每台机器人 ROS 网络内的进程。它订阅本机 ROS topic，并通过 MQTT 与地面站或其他机器人交换数据。
- **编队规则（`fleet_rules`）**：定义源机器人、源 ROS topic、目标机器人、目标 ROS topic、消息类型、限频、传输方式、QoS 和 frame 处理策略的配置。
- **ROS1 serialized**：调用 ROS1 消息对象的 `serialize()` 得到的原生字节序列。目标端必须安装相同消息类型，并使用兼容的 ROS 消息定义才能 `deserialize()`。
- **envelope**：通过 MQTT JSON 发送的轻量描述信息，包含路由、消息类型、编码、序号和 payload 大小，不包含 ROS 字段数据。
- **binary payload**：最小关联头加 ROS1 serialized bytes，通过独立的 `/bin` MQTT topic 发送。
- **`seq`**：源 Agent 为每条 binary 编队消息生成的进程内递增序号。接收端使用 `(src_id, seq)` 配对 envelope 和 binary payload。
- **自动回退**：仅指源端调用 `serialize()` 失败时，把当前 ROS 消息改走现有 MQTT JSON 路径。配置本身仍保持 `mqtt_binary`，后续消息继续尝试二进制路径。
- **`frame_policy: preserve`**：目标端保留 ROS 消息里的 `frame_id` 和 `child_frame_id`。
- **`frame_policy: namespace`**：目标端反序列化后，使用源机器人 ID 为消息中的 frame 添加命名空间，例如 `odom` 变为 `turtlebot_001/odom`。
- **QoS 0**：最多投递一次，可能丢包但不重传，适合 `/odom` 等“最新值比历史完整性重要”的高频状态。
- **QoS 1**：至少投递一次，可能重复且可能因重传产生积压，适合导航目标等不能轻易丢失的低频消息。

## 四、总体架构

### 4.1 MQTT Topic

保留现有 JSON/envelope topic，并新增 binary topic：

```text
robot/{src_id}/to/{dst_id}      JSON FleetData 或 binary envelope
robot/{src_id}/to/{dst_id}/bin  带关联头的 ROS1 serialized payload
robot/{src_id}/to/{dst_id}/meta 现有 HTTP 重量数据 meta，行为不变
```

每个 Agent 连接 Broker 后订阅：

```text
robot/+/to/{self_robot_id}
robot/+/to/{self_robot_id}/bin
robot/+/to/{self_robot_id}/meta
```

主 topic 中 `type=fleet_data` 且 `data.binary=true` 时表示 binary envelope；`data.binary` 缺失或为 `false` 时按现有完整 `FleetData` JSON 处理。

### 4.2 Binary Envelope

binary envelope 继续使用项目统一的 `Message` 顶层结构。`data` 至少包含：

```json
{
  "data_type": "ros_topic",
  "binary": true,
  "transport": "mqtt_binary",
  "encoding": "ros1_serialized_v1",
  "payload_format": "ros1_serialized",
  "seq": 42,
  "payload_size": 736,
  "src_topic": "/odom",
  "dst_topic": "/fleet/turtlebot_001/odom",
  "msg_type": "nav_msgs/Odometry",
  "frame_policy": "namespace",
  "stamp": 1784250000.125,
  "ttl": 1.0
}
```

`payload_size` 只表示 ROS1 serialized 主体长度，不包含关联头。`Message.src` 和 `Message.dst` 仍分别是源、目标机器人 ID。

### 4.3 Binary 关联头

两个 MQTT topic 之间不能依赖到达顺序。binary payload 在 ROS bytes 前增加固定 13 字节关联头：

```text
magic:   4 bytes  ASCII "FRB1"
version: 1 byte   unsigned integer，首版固定为 1
seq:     8 bytes  big-endian unsigned integer
body:    N bytes  ROS1 serialized payload
```

协议 helper 负责关联头编码和解析，业务代码不得手工切片。解析时必须验证 magic、version、最小长度和 envelope 中的 `payload_size`。关联头只解决配对和版本识别，不重复携带 topic、类型或目标信息。

## 五、配置模型

编队规则采用以下结构：

```yaml
- enabled: true
  src_topic: /odom
  msg_type: nav_msgs/Odometry
  targets:
    - robot_id: turtlebot_002
      dst_topic: /fleet/turtlebot_001/odom
  freq_limit: 10.0
  transport: mqtt_binary
  qos: 0
  frame_policy: namespace
```

兼容规则如下：

- `transport` 缺失时默认 `mqtt_json`，已有配置行为不变；
- 只接受 `mqtt_json` 和 `mqtt_binary`，其他值在规则规范化时回落为 `mqtt_json` 并记录告警；
- `qos` 缺失时默认 `1`，已有规则保持当前可靠性语义；
- `qos` 只接受 `0` 或 `1`，非法值规范化为 `1`；
- 同一规则的所有 target 使用相同 `transport`、`qos`、`freq_limit` 和 `frame_policy`；
- `freq_limit <= 0` 表示不由 Agent 主动限频，不代表能超过 ROS 源频率或链路处理能力。

Qt 编队面板新增传输方式下拉框和 QoS 选择控件。载入、编辑、保存、配置下发和配置响应回填必须完整保留这两个字段。已有保存配置不得因打开面板而被改写为新的默认值。

新建规则的表单默认选择 `mqtt_binary + qos: 0`，面向高频状态转发提供低延迟默认值；用户将 QoS 切换为 1 后必须原样保存。载入旧规则时仍按上述兼容规则补成 `mqtt_json + qos: 1`，不能套用新建表单默认值。

## 六、发送流程

每条启用规则继续只创建一个 ROS subscriber。回调先按规则执行限频，再按 `transport` 分支：

### 6.1 MQTT JSON

保持现有流程：调用 `ros_msg_to_dict()`，为每个 target 构造完整 `FleetData`，发布到 `robot/{src}/to/{dst}`。发布时显式使用规则的 `qos`。

### 6.2 MQTT Binary

1. 对收到的 ROS 消息调用一次 `serialize()`，同一规则包含多个 target 时复用这份 bytes，不重复序列化。
2. 为本条源消息生成一个 `seq`。同一消息发往多个 target 时可复用 `seq`，因为接收端缓存键还包含 `src_id`，且每个目标只订阅发往自己的 MQTT topic。
3. 为每个 target 构造包含各自 `dst_topic` 的 envelope。
4. 使用相同 QoS 依次发布 envelope 和 binary payload，均设置 `retain=false`。
5. 不调用 `ros_msg_to_dict()`，也不把完整 payload 写入 `/fleet/incoming`。

源端 `serialize()` 抛出异常，或者结果不是 bytes 类型时，当前消息立即改走 6.1 的 JSON 路径。合法的零长度 ROS serialized body 仍按 binary 发送。告警按 `(src_topic, msg_type)` 限频，同类错误最多每 10 秒记录一次；回退消息仍遵守原规则的 `freq_limit` 和 `qos`，不会重复计入限频。

MQTT publish 返回明确失败状态时记录错误。本次不在 Agent 内建立额外重发队列，避免高频数据在断网或 Broker 过载时积压。

## 七、接收、配对与发布

接收端维护两个有界缓存：binary envelope 缓存和 binary body 缓存，键均为 `(src_id, seq)`。无论 envelope 还是 `/bin` 先到，都先校验并写入对应缓存；两侧齐全后立即弹出并处理。

缓存边界固定为：

- 单侧条目存活时间 2 秒；
- 每个缓存最多 256 条；
- 每次收到新的 fleet envelope 或 binary payload 时执行过期清理；
- 达到上限时先删除最早写入的条目并记录限频告警。

配对后按以下顺序处理：

1. 验证 `Message.dst` 等于本机 robot ID、`data_type=ros_topic`、encoding 和 payload format 受支持；
2. 验证关联头 `seq`、ROS body 长度和 envelope `payload_size` 一致；
3. 通过 `msg_type` 加载 ROS message class，创建对象并调用 `deserialize(body)`；
4. `frame_policy=namespace` 时，对 ROS 对象调用现有 `namespace_ros_message_frames()`；
5. 复用 `(dst_topic, msg_type)` 对应的 ROS publisher 并发布；
6. 向 `/fleet/incoming` 发布轻量 JSON 摘要，只包含来源、目标 topic、类型、transport、seq、payload size 和时间戳。

目标端未知消息类型、消息定义不兼容、反序列化异常、尺寸不符或非法 `dst_topic` 时，只丢弃当前消息并记录限频错误。目标端不能自动回退 JSON，但后续合法消息必须继续处理。QoS 1 可能导致重复消息，本次保持至少一次语义，不按 `seq` 去重，避免错误吞掉发送端重连后重新使用序号的合法消息。

## 八、性能与可靠性策略

- `/odom`、IMU、点云状态等连续高频数据推荐 `mqtt_binary + qos: 0`，允许丢弃旧样本，优先控制延迟和积压。
- 导航目标、任务触发等关键低频数据推荐 `mqtt_binary + qos: 1`；若可读性和跨版本兼容比性能更重要，也可继续使用 `mqtt_json + qos: 1`。
- ROS 序列化在每条源消息上只执行一次，target 数量不会增加序列化次数。
- envelope 保持轻量 JSON，binary body 不做 Base64、不做 dict 转换、不做通用压缩。
- 接收端 ROS publisher 按 `(dst_topic, msg_type)` 缓存复用。
- 缓存有固定数量和时间边界，断包、乱序和恶意异常输入不能造成无限内存增长。

## 九、兼容性与安全边界

- 新 Agent 可以同时接收旧 JSON fleet 消息和新 binary fleet 消息。
- 旧 Agent 不订阅 `/bin` 且无法理解 binary envelope，因此只有确认目标机器人已升级后，才应将对应规则改为 `mqtt_binary`。
- 源、目标机器人必须安装相同 `msg_type`，自定义 ROS message 的定义和 MD5 必须兼容。
- `dst_topic` 必须是以 `/` 开头的绝对 ROS topic；空值或非法值不得创建 publisher。
- 接收端只处理 `Message.dst` 为本机的消息，即使 MQTT topic 被错误发布或订阅也不能跨机器人注入。
- binary body 大小必须与 envelope 一致，并受 MQTT Broker 的消息大小限制；本次不额外放宽 Broker 限制。

## 十、涉及模块

- `protocol/topics.py`：新增机器人间 binary topic 构造、通配符订阅和解析规则。
- `protocol/binary_payloads.py`：新增 fleet binary 关联头编码、解析和校验 helper。
- `agent/base_agent.py`：规范化并持久化 `qos`，发布/订阅 fleet binary，管理配对缓存和 JSON 回退入口。
- `agent/ros1_agent.py`：按规则选择 JSON 或 ROS1 serialized，反序列化并发布目标 ROS topic。
- `agent/frame_utils.py`：复用现有 ROS 对象 frame namespace 能力，不新建平行实现。
- `qt_frontend/panels/fleet_comm_panel.py`：编辑、保存、下发和回填 `transport`、`qos`。
- `qt_frontend/config/transmit_config.yaml` 与机器人配置示例：展示高频状态和关键低频消息的推荐组合。
- `tests/`：补充协议、Agent、ROS1Agent 和 Qt 面板的聚焦单元测试。

## 十一、测试与验收

### 11.1 单元测试

至少覆盖：

- fleet binary topic 构造、通配符和解析；
- 关联头往返、非法 magic、非法版本、截断和 payload size 不一致；
- 旧规则缺少 `transport`、`qos` 时的兼容默认值；
- 非法 transport 和 QoS 的规范化；
- JSON 规则继续调用现有 dict 转换路径；
- binary 规则只序列化一次，并向多个 target 发布各自 envelope 和共享 body；
- 源端序列化失败后自动发送完整 JSON，且告警限频；
- envelope 先到、binary 先到、缺少一侧、超时和缓存达到上限；
- 目标端反序列化、frame namespace、publisher 复用和轻量 `/fleet/incoming` 摘要；
- 未知消息类型、尺寸错误和 deserialize 异常不会阻断下一条消息；
- 前端配置的 transport、QoS 保存、下发和响应回填。

### 11.2 回归命令

```bash
python3 -m pytest tests/test_protocol_topics.py tests/test_binary_payloads.py tests/test_agent_topic_config.py tests/test_ros1_agent.py tests/test_panels.py -v
python3 -m pytest tests/ -v
ruff check protocol agent qt_frontend tests
```

如实际测试文件名与上述聚焦命令不同，实现计划必须先根据仓库现有文件确定正确路径，不得通过跳过测试规避失败。

### 11.3 双机器人运行态验收

在两个 ROS Noetic 机器人或 Turtlebot Docker 环境中，启用 `turtlebot_001:/odom -> turtlebot_002:/fleet/turtlebot_001/odom`：

- `mqtt_json + qos: 1` 保持可用，消息类型和 frame 行为与改造前一致；
- `mqtt_binary + qos: 0` 连续运行 60 秒，目标 ROS topic 平均频率达到配置 `freq_limit` 的 90% 以上；
- MQTT `/bin` payload 为二进制且 body 可由 `nav_msgs/Odometry.deserialize()` 解析；
- `frame_policy=namespace` 时目标消息 frame 带源机器人前缀；
- 人为制造源端序列化失败后能观察到 JSON 回退和限频告警；
- 人为丢弃一侧消息后缓存能在 2 秒后清理，后续消息仍正常发布；
- 对比相同频率下 JSON 与 binary 的 MQTT payload 字节数、Agent CPU、目标频率和延迟，记录实测结果。硬性通过条件是 binary 目标频率不低于 JSON，且 payload 总字节数低于 JSON；CPU 和延迟作为观测指标记录，不设置脱离运行环境的固定阈值。

完整运行态验证依赖 ROS Noetic、MQTT Broker 和双机器人环境。如果环境受限，必须完成无 roscore 单元测试，并明确列出未验证的频率、延迟、CPU、Broker 带宽和真实消息定义兼容风险。
