# 机器人 Agent 间编队 ROS1 Serialized 传输设计

## 一、背景与范围

当前机器人编队通信由源机器人 `ROS1Agent` 订阅本机 ROS topic，将消息转换为 Python 字典并封装成 `FleetData`，再经共享 MQTT Broker 发送给目标机器人 Agent。目标 Agent 解析 JSON、重建 ROS 消息，并发布到编队规则指定的目标机器人本地 `dst_topic`。

现有 JSON 路径通用且便于调试，但高频消息需要经历 `ROS 对象 -> dict -> JSON -> dict -> ROS 对象`。消息频率和数组长度增加后，Python 转换开销、MQTT payload 体积及 Broker 压力会同时增长，目标机器人实际接收频率可能低于 ROS 源频率或规则的 `freq_limit`。

本设计只改造以下链路：

```text
源机器人 ROS topic
  -> 源机器人 ROS1Agent
  -> MQTT Broker
  -> 目标机器人 ROS1Agent
  -> 目标机器人本地 ROS dst_topic
```

这是机器人 Agent 之间的编队通信数据面。数据不经过地面站 `bridge/mqtt_ros_bridge.py`，不会发布到地面站 ROS master，也不改变普通“机器人 Agent -> 地面站 Bridge”的 sensor 转发链路。机器人 ROS master 继续相互隔离。

## 二、目标与非目标

### 2.1 目标

- 让 `fleet_rules.transport` 真正控制 Agent 间编队数据面；
- `mqtt_json` 保持现有 JSON 编队转发行为；
- `mqtt_binary` 直接传输 ROS1 原生 serialized bytes；
- 源端 ROS 序列化失败时，当前消息自动回退到 MQTT JSON；
- 目标 Agent 继续按 `dst_topic` 发布原 ROS 消息类型，并保持既有 `frame_policy` 语义；
- 同一源 ROS topic 只创建一个 subscriber，同一回调中的 ROS 消息最多序列化一次、最多转字典一次；
- 对双 MQTT topic 乱序、缺包、大 payload、缓存积压和 Agent 重启后的标识碰撞提供明确边界；
- 高频实时状态可使用 QoS 0 控制延迟，关键低频消息可使用 QoS 1。

### 2.2 非目标

- 不修改地面站 Bridge 或其 ROS topic 发布行为；
- 不修改普通 sensor 的 MQTT JSON、MQTT binary 和 HTTP snapshot 数据面；
- 不迁移现有 `share_heavy_data()` 和 HTTP pointcloud snapshot 链路；
- 不让 PointCloud2 默认走 Agent 间 MQTT binary，大点云继续使用 HTTP snapshot；
- 不增加 Base64 或通用压缩，避免重新引入体积或 CPU 开销；
- 不实现端到端 ACK、应用层重传、严格一次投递或 Agent capability 协商；
- 不把任意嵌套 ROS message 的所有 frame 字段递归改名；本次保持现有 frame helper 的支持范围。

## 三、术语与执行约定

- **Agent**：运行在每台机器人 ROS 网络内的进程，负责本机 ROS 与 MQTT 之间的数据转换。
- **编队通信**：一个机器人 Agent 将本机 ROS topic 转发给另一个机器人 Agent，并由目标 Agent 发布为目标机器人本地 ROS topic。
- **编队规则（`fleet_rules`）**：定义源 ROS topic、消息类型、目标机器人、目标 ROS topic、限频、传输方式、QoS 和 frame 策略的配置。
- **ROS1 serialized**：通过 ROS1 消息对象 `serialize()` 得到的原生字节序列。目标 Agent 必须安装相同消息类型，且 ROS message 定义和 MD5 兼容。
- **binary envelope**：通过主 MQTT topic 发送的轻量 JSON 路由信息，不包含 ROS 字段 payload。
- **binary body**：最小关联头加 ROS1 serialized bytes，通过独立 `/bin` MQTT topic 发送。
- **`transfer_id`**：只用于配对一次 Agent 间 binary envelope 和 body 的 64 位传输标识，不等同于统一 `Message.seq` 或 ROS `header.seq`。
- **自动回退**：源 Agent 对当前 ROS 消息序列化失败时，改走已有完整 JSON 路径；规则配置仍保持 `mqtt_binary`，后续消息继续尝试二进制。
- **`frame_policy: preserve`**：目标 Agent 保留消息中现有 frame 名称。
- **`frame_policy: namespace`**：目标 Agent 使用源机器人 ID 为现有 helper 支持的 `header.frame_id`、顶层 `child_frame_id` 和 TF `transforms` 添加命名空间。
- **QoS 0**：最多投递一次，可能丢包但不会因 MQTT 重传积压，适合 `/odom`、IMU、LaserScan 等连续状态。
- **QoS 1**：至少投递一次，可能重复，适合导航目标、任务触发等关键低频消息。
- **TTL**：`FleetData.ttl` 表示消息从源 Agent 创建起允许存活的秒数。接收端使用统一 `Message.ts` 计算传输年龄。

## 四、组件职责

### 4.1 `protocol/`

协议层保持零 ROS、Qt 和 MQTT 客户端依赖，负责：

- MQTT topic 构造与解析；
- `FleetBinaryEnvelopeData` 结构化消息；
- binary 关联头编码、解析和基础长度校验；
- `ros1_serialized_v1` 等协议常量。

协议层不导入 ROS message class，也不执行 `serialize()` 或 `deserialize()`。

### 4.2 `BaseAgent`

`BaseAgent` 负责 MQTT 客户端边界：

- 生成线程安全的 `transfer_id`；
- 发布 JSON fleet 消息、binary envelope 和 binary body；
- 根据 MQTT topic 在 UTF-8 解码前分流原始 binary payload；
- 配对 envelope/body，执行 TTL、大小、缓存数量和缓存字节数校验；
- 配对完成后把 envelope 和原始 ROS bytes 交给子类 hook。

`BaseAgent` 不导入 ROS，不反序列化 ROS body。

### 4.3 `ROS1Agent`

`ROS1Agent` 负责 ROS 边界：

- 按源 topic 合并编队规则并创建 ROS subscriber；
- 对 ROS 消息执行一次 serialize 或 dict 转换；
- 序列化失败时执行 JSON 回退；
- 接收配对后的 binary body，按 `msg_type` 创建 ROS 对象并 deserialize；
- 应用现有 frame namespace helper；
- 复用 ROS publisher 并发布到 `dst_topic`；
- 向 `/fleet/incoming` 发布不含完整 payload 的轻量调试摘要。

`MockAgent` 实现相同 binary hook，但只记录摘要，不引入 ROS 依赖。

## 五、MQTT Topic 与消息格式

### 5.1 Topic

```text
robot/{src_id}/to/{dst_id}      完整 JSON FleetData 或 binary envelope
robot/{src_id}/to/{dst_id}/bin  带关联头的 ROS1 serialized body
robot/{src_id}/to/{dst_id}/meta 现有 HTTP 重量数据 meta，保持不变
```

每个 Agent 连接 Broker 后订阅：

```text
robot/+/to/{self_robot_id}
robot/+/to/{self_robot_id}/bin
robot/+/to/{self_robot_id}/meta
```

`protocol/topics.py` 为 `/bin` 增加独立构造函数、订阅通配符及 `to_robot_binary` 解析类型。MQTT 的单层 `+` 不会让主 topic 订阅自动覆盖 `/bin`，因此三类 topic 必须显式订阅。

### 5.2 Binary Envelope

在 `protocol/messages.py` 新增 `FleetBinaryEnvelopeData` dataclass，并由 `MessageFactory.fleet_binary_envelope()` 构造 `type=fleet_data` 的统一 `Message`。不得在业务层手写顶层 JSON。

envelope 的 `data` 至少包含：

```json
{
  "data_type": "ros_topic",
  "binary": true,
  "transport": "mqtt_binary",
  "encoding": "ros1_serialized_v1",
  "payload_format": "ros1_serialized",
  "transfer_id": 1311768464867721258,
  "payload_size": 736,
  "src_topic": "/odom",
  "dst_topic": "/fleet/turtlebot_001/odom",
  "msg_type": "nav_msgs/Odometry",
  "frame_policy": "namespace",
  "stamp": 1784250000.125,
  "ttl": 1.0
}
```

`Message.src`、`Message.dst`、`Message.seq` 和 `Message.ts` 继续使用统一协议语义。binary 配对只使用 `Message.src + data.transfer_id`；不得用 `Message.seq` 或 ROS `header.seq` 配对。`payload_size` 只表示 ROS1 serialized 主体长度，不包含关联头。

### 5.3 `transfer_id`

每个 Agent 启动时生成随机 32 位 `session_nonce`，并维护线程安全的 32 位递增计数。二者组合为：

```text
transfer_id = (session_nonce << 32) | counter
```

计数在同一源 ROS 消息第一次需要 binary 转发时递增。同一消息发往多个 target 时复用 `transfer_id` 和 serialized body。计数回绕前重新生成 `session_nonce`。生成过程由锁保护，避免多个 ROS subscriber 回调并发产生重复值。

顶层 `Message.seq` 仍由 `MessageFactory` 为每个目标消息独立生成，不参与 body 配对。

### 5.4 Binary 关联头

不同 MQTT topic 之间不能依赖到达顺序。binary payload 在 ROS bytes 前增加固定 13 字节关联头：

```text
magic:       4 bytes  ASCII "FRB1"
version:     1 byte   unsigned integer，首版固定为 1
transfer_id: 8 bytes  big-endian unsigned integer
body:        N bytes  ROS1 serialized payload
```

`protocol/binary_payloads.py` 提供专用 encode/decode helper。业务代码不得手工切片。helper 必须验证 magic、version、最小长度，并返回 `transfer_id` 和原始 ROS body。

## 六、编队规则配置

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

兼容与规范化规则：

- `transport` 缺失时默认 `mqtt_json`；
- 只接受 `mqtt_json` 和 `mqtt_binary`，其他值回落为 `mqtt_json` 并限频告警；
- `qos` 缺失时默认 `1`，保持现有 fleet 发布语义；
- `qos` 只接受 `0` 或 `1`，非法值规范化为 `1`；
- 同一条规则的所有 target 共用 `transport`、`qos`、`freq_limit` 和 `frame_policy`；
- `freq_limit <= 0` 表示 Agent 不主动限频；
- 同一 `src_topic` 配置不同 `msg_type` 时整组规则不启用，并记录明确错误，避免用错误类型订阅同一个 ROS topic。

Qt 编队面板增加 transport 和 QoS 控件，并在规则表中显示实际配置。载入、编辑、保存、下发和配置响应回填必须保留字段。由于本次不增加目标 Agent capability 协商，新建规则默认 `mqtt_json + qos: 1`，不能无提示地向旧 Agent 发送 binary，也不能默认以 QoS 0 发送导航目标。高频规则由用户显式选择 `mqtt_binary + qos: 0`。

## 七、源 Agent 发送流程

### 7.1 按源 Topic 合并

`ROS1Agent` 按 `(src_topic, msg_type)` 聚合启用规则，每组只创建一个 ROS subscriber。回调为每条规则独立维护基于 `time.monotonic()` 的限频状态，然后收集本次到期的 routes。

每次 ROS 回调遵循：

- 没有 route 到期时直接返回；
- 至少一个 binary route 到期时最多执行一次 ROS serialize；
- 至少一个 JSON route 到期时最多执行一次 `ros_msg_to_dict()`；
- binary serialize 失败且存在到期 binary route 时，最多再执行一次 `ros_msg_to_dict()`，供所有失败 route 共用；
- 同一结果发往多个 target 时复用 bytes 或 dict，不重复转换。

### 7.2 JSON Route

为每个到期 target 构造现有完整 `FleetData`，发布到 `robot/{src}/to/{dst}`，显式使用规则 QoS。现有 JSON 接收与类型化 ROS 发布行为保持不变。

### 7.3 Binary Route

1. 使用 `io.BytesIO` 调用 ROS 消息对象 `serialize(buff)`，取得原生 bytes；合法零长度 body 仍可发送。
2. 为本次源消息生成一个 `transfer_id`，构造一次带关联头的 binary payload。
3. 为每个 target 构造带各自 `dst_topic` 的 `FleetBinaryEnvelopeData`。
4. 使用相同 QoS 依次发布 envelope 和 binary body，均设置 `retain=false`。
5. 不把 ROS body 转为 Base64、dict 或完整 `/fleet/incoming` JSON。

现有 `_serialize_ros_message()` 调整为只返回 bytes 或 `None`，不在 helper 内逐条打印 warning。调用方按 `(src_topic, msg_type)` 对序列化失败告警限频，同类错误最多每 10 秒一次，然后把当前到期 binary routes 全部回退到 JSON。JSON 转换也失败时丢弃当前 routes 并记录限频错误。

## 八、目标 Agent 接收流程

### 8.1 原始 MQTT 分流

`BaseAgent._on_message()` 必须先调用 `parse_robot_topic(msg.topic)`：

```text
to_robot_binary
  -> 不执行 UTF-8 decode
  -> 直接解析 msg.payload 的关联头和 ROS body

其他 MQTT topic
  -> UTF-8 decode
  -> Message.from_json()
  -> 现有消息分派
```

binary topic 解析出的 `src_id` 来自 MQTT topic。所有 `to_robot` 主 topic 消息必须验证 `Message.type=fleet_data`、`Message.src` 与 topic 中的源 ID 一致、`Message.dst` 与 topic 中的目标 ID 及本机 robot ID 一致。

主 topic 的 `Message.data.binary=true` 时，`BaseAgent` 将数据解析为 `FleetBinaryEnvelopeData` 并进入 envelope cache，不调用现有 `_on_fleet_message()`；`binary` 缺失或为 `false` 时继续构造完整 `FleetData` 并走现有 JSON 回调。

### 8.2 配对缓存与资源边界

`BaseAgent` 维护 envelope cache 和 body cache，键均为 `(src_id, transfer_id)`。两个缓存由同一把锁保护，使用 `time.monotonic()` 记录写入时间，支持 envelope/body 任意顺序到达。

固定边界为：

- 单侧条目逻辑存活时间 2 秒；
- envelope cache 最多 256 条；
- body cache 最多 256 条；
- 单个 ROS body 最大 8 MiB；
- body cache 总字节数最大 64 MiB；
- envelope 声明 `payload_size` 超限时不得写入缓存；
- body 实际大小超限时不得写入缓存；
- 达到条数或总字节上限时，先移除最早写入的条目，再决定是否接收新条目；
- 每次收到 fleet envelope/body 时清理过期项，状态循环也调用同一清理函数；
- 过期条目不得再参与配对，实际删除最迟发生在下一次 fleet 消息或状态循环。

配对完成后立即从两个缓存弹出，再验证 envelope `payload_size` 与 body 长度一致。缓存超限、过期、缺少一侧或尺寸不符只影响当前 transfer，不得阻断后续消息。

### 8.3 TTL

完整 JSON fleet 消息和 binary envelope 都在 `BaseAgent` 分派给子类前执行 TTL 校验：

```text
ttl <= 0              -> 不做应用层过期判断
now - Message.ts > ttl -> 丢弃
Message.ts > now + 5s  -> 视为时钟异常并丢弃
```

TTL 依赖机器人系统时钟同步，部署环境必须使用 NTP 或等效机制。缓存的 2 秒超时只解决 envelope/body 缺包，不替代端到端 TTL。

### 8.4 ROS 反序列化与发布

配对完成后，`BaseAgent` 调用子类 binary hook，传入源 ID、结构化 envelope 和 ROS body。`ROS1Agent`：

1. 验证 `data_type=ros_topic`、encoding、payload format、绝对 `dst_topic` 和非空 `msg_type`；
2. 通过 `msg_type` 加载 ROS message class；
3. 创建消息对象并调用 `deserialize(body)`；
4. `frame_policy=namespace` 时调用现有 `namespace_ros_message_frames()`；
5. 复用 `(dst_topic, msg_type)` 对应的 ROS publisher；
6. 发布 ROS 消息；
7. 复用单个 `/fleet/incoming` publisher 发布轻量摘要，只包含来源、目标 topic、类型、transport、`transfer_id`、payload size 和时间戳。

本次 frame namespace 明确只保证现有 helper 支持的 `header.frame_id`、顶层 `child_frame_id` 和 TF `transforms`。包含更深层嵌套 frame 的自定义消息使用 `preserve`，或另行扩展 helper 并补充 Bridge 回归测试。

## 九、MQTT 发布、QoS 与失败语义

`BaseAgent._mqtt_publish()` 调整为返回 publish 是否成功进入 Paho 客户端发送队列，判断依据是 `MQTTMessageInfo.rc == mqtt.MQTT_ERR_SUCCESS`。现有调用方可以忽略返回值，fleet binary 发送必须检查。不得在 ROS 回调中调用阻塞式 `wait_for_publish()`。

Agent 初始化共享 MQTT client 时显式设置：

```text
max_queued_messages = 1000
max_inflight_messages = 20
```

队列上限与当前 Broker `max_queued_messages 1000` 对齐，避免断线竞态下 QoS 1 消息无限占用客户端内存。高频 fleet 数据推荐 QoS 0；QoS 1 只用于低频关键数据。Paho 返回队列满或未连接时，当前 fleet publish 失败，不建立应用层重发队列。

项目当前由一个 MQTT client 同时承载状态、控制、普通 sensor 和 fleet 消息，因此这个队列上限是 Agent 级资源保护，会对共享 client 的所有 QoS 1 publish 生效，但不改变非 fleet 消息的 topic、编码或正常发送行为。队列满时现有非 fleet 调用方仍保持当前“不重试”的行为；实现和运行态验证必须确认 fleet 高负载不会持续占满共享队列。拆分 fleet 专用 MQTT client 属于后续隔离优化，不在本次范围。

envelope 和 body 是两次独立 publish，无法事务回滚：

- 任一 publish 明确失败时记录限频错误；
- 另一侧已发布的消息由目标缓存超时清理；
- 源端不得因为 MQTT publish 失败改发 JSON，否则可能让目标收到 binary 和 JSON 两份逻辑相同的数据；
- 自动 JSON 回退只针对 ROS serialize 失败，不能扩展为 MQTT 发送失败回退。

QoS 1 允许重复投递。本次保持至少一次语义，不对完成配对的 `transfer_id` 建立长期去重缓存；重复 envelope/body 可能再次发布 ROS 消息。需要严格幂等的任务控制不应仅依赖通用 fleet topic 转发，应由上层命令协议使用业务执行 ID 去重。

## 十、性能与可靠性策略

- `/odom`、IMU、LaserScan 等连续中型数据推荐 `mqtt_binary + qos: 0`；
- 导航目标、任务触发等关键低频数据推荐 `mqtt_binary + qos: 1`，旧 Agent 混用期间继续使用 `mqtt_json + qos: 1`；
- PointCloud2、原始图像等大数据默认不走本链路，继续使用现有 HTTP snapshot 或专用数据面；
- 一个源 topic 只创建一个 ROS subscriber；
- 一次 ROS 回调最多 serialize 一次、转 dict 一次；
- binary body 不做 Base64、通用压缩或 JSON 字段展开；
- ROS publisher 和 `/fleet/incoming` publisher 都缓存复用；
- cache 同时受时间、条数、单体大小和总字节数限制；
- 高性能目标是减少转换、带宽和排队，不承诺超过源 ROS topic 频率或规则 `freq_limit`。

## 十一、兼容性与信任边界

- 新 Agent 同时支持旧完整 JSON fleet 消息和新 binary fleet 消息；
- 旧 Agent 不订阅 `/bin` 且不能理解 binary envelope，因此未增加 capability 协商前，必须由操作者确认目标 Agent 已升级后再启用 `mqtt_binary`；
- 源、目标 Agent 必须安装相同 `msg_type`，自定义 ROS message 定义和 MD5 必须兼容；
- `dst_topic` 必须是以 `/` 开头的绝对 ROS topic；
- MQTT topic 中的源/目标 ID与 `Message.src`、`Message.dst` 必须一致，防止普通误路由；
- 当前 Broker 允许匿名连接且未启用 ACL，因此上述校验不是身份认证，不能阻止恶意客户端伪造来源和目标；
- 本设计假设 Broker 运行在可信机器人网络。MQTT 用户认证、topic ACL 和 TLS 属于独立安全加固任务；
- 8 MiB 单体上限是 Agent 侧资源保护，不要求放宽 Broker 的消息大小限制。

## 十二、涉及模块

- `protocol/messages.py`
  - 新增 `FleetBinaryEnvelopeData` 和 `MessageFactory.fleet_binary_envelope()`。
- `protocol/topics.py`
  - 新增 Agent 间 `/bin` topic 构造、通配符和解析类型。
- `protocol/binary_payloads.py`
  - 新增 fleet binary 关联头 encode/decode helper。
- `agent/base_agent.py`
  - 规范化 fleet transport/QoS、生成 transfer ID、发布 binary、原始 topic 分流、TTL、配对缓存和资源保护。
- `agent/ros1_agent.py`
  - 按源 topic 合并规则、serialize/JSON 回退、deserialize、frame 策略和目标 ROS 发布。
- `agent/mock_agent.py`
  - 实现 binary hook 的无 ROS 摘要处理。
- `agent/frame_utils.py`
  - 只复用现有 helper，本次不扩展其递归范围。
- `qt_frontend/panels/fleet_comm_panel.py`
  - 编辑、保存、下发和回填 fleet transport/QoS。
- `qt_frontend/config/transmit_config.yaml`、`agent/configs/*.yaml`
  - 示例中区分高频状态和关键低频规则；不得覆盖用户已有运行态配置。
- `tests/`
  - 补充协议、BaseAgent、ROS1Agent、MockAgent 和 Qt 面板的聚焦测试。

地面站 `bridge/mqtt_ros_bridge.py`、普通 sensor 传输和 RViz 不在实现文件范围内。只有共享 `frame_utils` 行为发生变化时才需要追加 Bridge 回归测试；本设计不要求该变化。

## 十三、测试与验收

### 13.1 协议测试

- fleet binary topic 构造、通配符和解析；
- `FleetBinaryEnvelopeData` 经 `MessageFactory` 序列化和 `Message.from_json()` 解析；
- 关联头往返、非法 magic、非法版本、截断和零长度 ROS body；
- `Message.seq`、ROS `header.seq` 与 `transfer_id` 相互独立；
- session nonce、递增计数和计数回绕时重新生成 nonce 的组合规则；随机 nonce 碰撞属于可量化的极低概率风险，不表述为绝对不可能。

### 13.2 BaseAgent 测试

- `/bin` payload 在 UTF-8 decode 前分流；
- JSON fleet 路径保持兼容；
- envelope 先到、body 先到、任一侧缺失和 QoS 1 重复；
- TTL 有效、过期、禁用和未来时钟异常；
- 单条 8 MiB 边界、缓存 64 MiB 边界、条数上限和过期清理；
- topic 源/目标与 Message 字段不一致时拒绝；
- `_mqtt_publish()` 成功、未连接和队列满返回值；
- envelope/body 任一 publish 失败时不触发 JSON 回退。
- fleet 高负载达到共享 Paho 队列边界后，缓存和客户端内存保持有界，后续状态与控制 publish 的失败行为可观察。

### 13.3 ROS1Agent 与 Qt 测试

- 同一源 topic 多规则只创建一个 ROS subscriber；
- route 独立限频，serialize/dict 每次回调最多各执行一次；
- binary 向多个 target 复用 transfer ID/body，并保留各自 `dst_topic`；
- serialize 失败自动回退完整 JSON，且告警限频；
- 未知 ROS 类型、MD5/deserialize 失败不阻断下一条消息；
- namespace/preserve、publisher 复用和轻量 `/fleet/incoming` 摘要；
- 缺失或非法 transport/QoS 的兼容规范化；
- Qt 保存、下发、拉取和响应回填 transport/QoS；
- 新建 Qt 规则默认 `mqtt_json + qos: 1`。

### 13.4 回归命令

```bash
python3 -m pytest tests/test_protocol_messages.py tests/test_protocol_topics.py tests/test_binary_payloads.py -v
python3 -m pytest tests/test_agent_topic_config.py tests/test_ros1_agent.py tests/test_panels.py -v
python3 -m pytest tests/ -v
ruff check protocol agent qt_frontend tests
```

### 13.5 双机器人运行态验收

在两个 ROS Noetic 机器人或 Turtlebot Docker 环境中，启用：

```text
turtlebot_001:/odom
  -> MQTT Agent 间编队链路
  -> turtlebot_002:/fleet/turtlebot_001/odom
```

验收步骤和条件：

- 先确认源 `/odom` 平均频率不低于配置 `freq_limit`，否则目标频率比例不具有判定意义；
- `mqtt_json + qos: 1` 保持可用，消息类型和 frame 行为与改造前一致；
- `mqtt_binary + qos: 0` 连续运行 60 秒，目标平均频率达到配置 `freq_limit` 的 90% 以上；
- `/bin` body 可由 `nav_msgs/Odometry.deserialize()` 解析；
- `frame_policy=namespace` 时目标消息 frame 带源机器人前缀；
- 源端 serialize 失败时能观察到 JSON 回退，MQTT publish 失败时不会产生 JSON 重复消息；
- 人为丢弃 envelope 或 body 后，残留缓存过期且后续消息继续发布；
- 对比相同源频率下 JSON 与 binary 的 Agent CPU、MQTT 总字节数、目标频率及端到端延迟；
- 对 `/odom` 的硬性条件是 binary 目标频率不低于 JSON，且 envelope 加 binary body 的总字节数低于完整 JSON。

完整运行态验证依赖 ROS Noetic、MQTT Broker、双机器人环境和系统时钟同步。如果环境受限，必须完成无 roscore 单元测试，并明确列出未验证的实际频率、延迟、CPU、Broker 带宽、时钟偏差和真实 ROS message 兼容风险。
