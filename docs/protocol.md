# 通信协议文档

## 版本

- 协议版本: 1.0
- 更新日期: 2026-07-23

## 1. 设计原则

- 地面站与机器人通过 MQTT 通信，不依赖 rosmaster
- 控制面和 MQTT envelope 使用 JSON，便于调试和跨语言实现；ROS1 serialized body 按专用 binary 格式传输
- 话题传输按数据量分层，带宽可控
- 所有跨网络消息必须符合本文档定义的格式

## 2. 消息通用格式

所有控制面消息和 MQTT JSON envelope 均使用以下结构；ROS1 serialized binary body 不经过该 JSON 结构，而是由对应的 envelope 和 `/bin` topic 关联。

```json
{
  "ver": "1.0",
  "ts": 1712582400.0,
  "src": "robot_001",
  "dst": "station",
  "type": "status",
  "seq": 42,
  "data": { ... }
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| ver | string | 是 | 协议版本，当前为 "1.0" |
| ts | float | 是 | Unix 时间戳（秒） |
| src | string | 是 | 发送方标识（robot_id 或 "station"） |
| dst | string | 是 | 接收方标识（robot_id、"station" 或 "broadcast"） |
| type | string | 是 | 消息类型，见第4节 |
| seq | int | 是 | 消息序号，发送方递增 |
| data | object | 是 | 消息体，结构随 type 变化 |

## 3. MQTT Topic 规范

### 3.1 Topic 命名规则

| Topic | 方向 | QoS | 用途 |
|-------|------|-----|------|
| `robot/{id}/status` | Robot → Station | 1 | 心跳 + 状态上报 |
| `robot/{id}/sensor/{name}` | Robot → Station | 0/1 | 传感器 JSON 数据或 binary envelope |
| `robot/{id}/sensor/{name}/bin` | Robot → Station | 0/1 | ROS1 serialized binary sensor body |
| `robot/{id}/sensor/{name}/meta` | Robot → Station | 1 | 重量话题元信息 |
| `robot/{id}/cmd` | Station → Robot | 1 | 控制指令 |
| `robot/{id}/cmd/ack` | Robot → Station | 1 | 指令确认 |
| `robot/{id}/event` | Robot → Station | 1 | 告警/异常事件 |
| `robot/{src}/to/{dst}` | Robot → Robot | 0/1 | 机器人间 JSON 数据或 ROS1 binary envelope |
| `robot/{src}/to/{dst}/bin` | Robot → Robot | 0/1 | 机器人间 ROS1 serialized binary body |
| `robot/{src}/to/{dst}/meta` | Robot → Robot | 1 | 机器人间重量话题元信息（点云流地址等） |
| `station/discover` | Station → Robot | 1 | 发现请求 |
| `station/topic/request` | Station → Robot | 1 | Topic 订阅/取消请求 |
| `station/topic/response` | Robot → Station | 1 | Topic 请求响应 |

### 3.2 通配符订阅

地面站可使用 MQTT 通配符订阅所有机器人：

- `robot/+/status` — 所有机器人状态
- `robot/+/cmd/ack` — 所有指令确认
- `robot/+/event` — 所有事件
- `robot/+/sensor/+/bin` — 所有 ROS1 serialized binary sensor body
- `robot/+/sensor/+/meta` — 所有传感器元信息

机器人间通信使用目标 ID 通配符：

- `robot/+/to/{self_id}` — 所有发往本机的机器人间数据
- `robot/+/to/{self_id}/bin` — 所有发往本机的 ROS1 serialized binary body
- `robot/+/to/{self_id}/meta` — 所有发往本机的重量话题元信息

### 3.3 sensor name 映射

`sensor/{name}` 中的 name 为 ROS topic 去掉前导 `/` 并将 `/` 替换为 `.`：

| ROS Topic | MQTT sensor name |
|-----------|-----------------|
| `/camera/image_raw/compressed` | `camera.image_raw.compressed` |
| `/lidar/scan` | `lidar.scan` |
| `/imu/data` | `imu.data` |

## 4. 消息类型

### 4.1 status — 状态上报

Robot 定时发送（默认 1Hz），作为心跳和状态同步。

```json
{
  "type": "status",
  "data": {
    "battery": 72,
    "position": {"x": 1.2, "y": 3.4, "theta": 0.5},
    "velocity": {"linear": 0.3, "angular": 0.1},
    "mode": "auto",
    "ros_version": "1",
    "uptime": 3600,
    "ip": "192.168.1.101"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| battery | float | 电量百分比 (0-100) |
| position | object | 2D位置 {x, y, theta} |
| velocity | object | 速度 {linear, angular} |
| mode | string | 运行模式: auto/manual/stop/error |
| ros_version | string | ROS 版本: "1" 或 "2" |
| uptime | int | 运行时间（秒） |
| ip | string | 机器人 IP 地址 |

### 4.2 cmd — 控制指令

Station 发送给 Robot 的控制命令。

```json
{
  "type": "cmd",
  "data": {
    "action": "velocity",
    "params": {"linear": 0.5, "angular": 0.0},
    "exec_id": "a1b2c3d4e5f6"
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| action | string | 动作: velocity/mode/nav_goal/custom |
| params | object | 动作参数（随 action 变化） |
| exec_id | string | 指令唯一ID，用于匹配 ack |

**action=params 映射：**

| action | params | 说明 |
|--------|--------|------|
| velocity | {linear, angular} | 速度控制 |
| mode | {mode: "auto"/"manual"/"stop"} | 模式切换 |
| nav_goal | {x, y, theta} | 导航目标点 |
| custom | {topic, msg_type, data} | 自定义 ROS 消息发布 |

### 4.3 cmd_ack — 指令确认

Robot 收到指令后回复确认。

```json
{
  "type": "cmd_ack",
  "data": {
    "exec_id": "a1b2c3d4e5f6",
    "result": "ok",
    "message": ""
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| exec_id | string | 对应 cmd 的 exec_id |
| result | string | 结果: ok/failed/timeout |
| message | string | 附加信息（失败原因等） |

### 4.4 event — 告警/异常事件

Robot 主动上报的异常信息。

```json
{
  "type": "event",
  "data": {
    "level": "warning",
    "code": "BATTERY_LOW",
    "message": "Battery below 20%",
    "details": {"battery": 18}
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| level | string | 等级: info/warning/error/critical |
| code | string | 事件代码（预定义） |
| message | string | 人类可读描述 |
| details | object | 附加数据 |

### 4.5 discover — 发现请求

Station 广播发现请求，在线的 Robot 回复自身信息。

```json
// 请求
{
  "type": "discover",
  "dst": "broadcast",
  "data": {
    "request_id": "abcd1234"
  }
}

// 响应
{
  "type": "discover_resp",
  "data": {
    "request_id": "abcd1234",
    "robot_id": "robot_001",
    "ros_version": "1",
    "topics": ["/camera/image_raw", "/imu/data", "/cmd_vel"],
    "ip": "192.168.1.101",
    "uptime": 3600
  }
}
```

### 4.6 topic_request / topic_resp — Topic 订阅管理

Station 请求 Agent 订阅/取消订阅指定的 ROS topic。

```json
// 请求
{
  "type": "topic_request",
  "data": {
    "action": "subscribe",
    "topic": "/camera/image_raw/compressed",
    "msg_type": "sensor_msgs/CompressedImage",
    "freq_limit": 10,
    "transport": "auto",
    "compression": {
      "quality": 60,
      "resize": [320, 240],
      "voxel_size": 0.1
    }
  }
}

// 响应
{
  "type": "topic_resp",
  "data": {
    "request_id": "",
    "result": "ok",
    "message": "",
    "transport": "mqtt_binary",
    "stream_url": ""
  }
}
```

| 请求字段 | 类型 | 说明 |
|---------|------|------|
| action | string | subscribe / unsubscribe |
| topic | string | ROS topic 名称 |
| msg_type | string | ROS 消息类型 |
| freq_limit | float | 频率限制 (Hz)，null 为不限 |
| transport | string | 传输方式: auto/mqtt_json/mqtt_binary/http_stream |
| compression | object | 压缩选项（quality/resize/voxel_size） |

| 响应字段 | 类型 | 说明 |
|---------|------|------|
| result | string | ok/failed/not_found/unsupported |
| transport | string | 实际使用的传输方式 |
| stream_url | string | HTTP 流地址（重量话题） |

### 4.7 sensor_meta — 重量话题元信息

Agent 对重量话题（点云等）先发送元信息，地面站通过 HTTP 流拉取数据。

```json
{
  "type": "sensor_meta",
  "data": {
    "topic": "/lidar/points",
    "msg_type": "sensor_msgs/PointCloud2",
    "transport": "http_stream",
    "stream_url": "http://192.168.1.101:8080/stream/lidar.points",
    "size_bytes": 800000,
    "freq_hz": 5.0
  }
}
```

### 4.8 fleet_data — 机器人间数据

Robot 向其他 Robot 直接发送数据，不经过地面站中转。

**轻量自定义数据**（position / nav_goal / custom）直接通过 MQTT JSON 传输：

```json
{
  "type": "fleet_data",
  "dst": "robot_002",
  "data": {
    "data_type": "position",
    "payload": {"x": 1.2, "y": 3.4, "theta": 0.5},
    "ttl": 30.0
  }
}
```

**重量数据**（pointcloud）先通过 MQTT 发送 `fleet_data` 信令，接收方从 `stream_url` 通过 HTTP 直连拉取：

```json
{
  "type": "fleet_data",
  "dst": "robot_002",
  "data": {
    "data_type": "pointcloud",
    "payload": {
      "topic": "/fleet/points",
      "msg_type": "sensor_msgs/PointCloud2",
      "stream_url": "http://192.168.1.101:8080/stream/fleet/points",
      "size_bytes": 800000
    },
    "ttl": 30.0
  }
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| data_type | string | 数据类型: position/nav_goal/custom/pointcloud |
| payload | object | 数据内容，随 data_type 变化 |
| ttl | float | 有效时间（秒），超时可丢弃 |

**ROS topic 编队转发**使用 `data_type: ros_topic`，由 `fleet_rules.transport` 选择 JSON 或 ROS1 serialized binary。JSON 路径在主 topic 发送完整 `FleetData`；binary 路径在主 topic 发送不含 ROS body 的 JSON envelope，并在同一目标的 `/bin` topic 发送带 13 字节关联头的 ROS1 serialized body。关联头依次为 4 字节 magic `FRB1`、1 字节版本号和网络字节序的 8 字节无符号 `transfer_id`。目标 Agent 按 `transfer_id` 配对后校验 `msg_type` 对应 ROS class 的 MD5，再发布到 `dst_topic`。

```json
{
  "type": "fleet_data",
  "src": "robot_001",
  "dst": "robot_002",
  "data": {
    "data_type": "ros_topic",
    "binary": true,
    "transport": "mqtt_binary",
    "encoding": "ros1_serialized_v1",
    "payload_format": "ros1_serialized",
    "transfer_id": 4294967297,
    "payload_size": 718,
    "md5sum": "cd5e73d190d741a2f92e81eda573aca7",
    "src_topic": "/odom",
    "dst_topic": "/fleet/robot_001/odom",
    "msg_type": "nav_msgs/Odometry",
    "frame_policy": "namespace",
    "ttl": 1.0
  }
}
```

binary envelope 和 body 可以乱序到达；接收端使用 `(Message.src, transfer_id)` 配对，不能使用 `Message.seq` 或 ROS `header.seq`。ROS 网络仍保持隔离，编队消息不经过地面站 Bridge。

### 4.9 机器人间重量话题信令（fleet_data + meta topic）

机器人间重量话题复用 Agent 已有的 HTTP 流服务端。流程：

1. Robot A 将点云数据存入 `_stream_data`（复用 `_store_stream_data`）
2. Robot A 在 `robot/A/to/B/meta` 上发送 fleet_data 信令（含 stream_url）
3. Robot B 收到后通过 HTTP 直连 Robot A 的流服务端拉取二进制数据

MQTT topic: `robot/{src}/to/{dst}/meta`

```json
{
  "type": "fleet_data",
  "src": "robot_A",
  "dst": "robot_B",
  "data": {
    "data_type": "pointcloud",
    "payload": {
      "topic": "/fleet/points",
      "stream_url": "http://192.168.1.101:8080/stream/fleet/points",
      "size_bytes": 800000
    }
  }
}
```

## 5. 话题分层传输策略

### 5.1 默认传输策略

- 控制、状态、配置和简单标量：`mqtt_json`
- 常规 ROS topic：`mqtt_binary`，payload 使用 `ros1_serialized_v1`
- 大 payload：`http_stream`，MQTT 仅发送 meta，HTTP payload 使用 `ros1_serialized_v1`
- 未注册 ROS 消息类型：默认 `mqtt_binary`

### 5.2 分层定义

| 层级 | 条件 | 传输方式 | 典型消息 |
|------|------|---------|---------|
| light | 控制、状态、配置、简单标量 | MQTT + JSON | `std_msgs/String`、`std_msgs/Bool` |
| medium | 常规 ROS topic | MQTT + ROS1 序列化二进制 | Odometry、TF、JointState、压缩图像、LaserScan |
| heavy | 点云、OctoMap、PCL 等大 payload | HTTP 流 + MQTT 信令 | PointCloud2、Octomap |

### 5.3 自动分类规则

Agent 根据 `protocol/topic_registry.py` 中注册的消息类型自动选择传输层级。精确消息类型规则优先于包级通配符规则，例如 `sensor_msgs/PointCloud2` 先命中 `http_stream`，其它 `sensor_msgs/*` 常规话题默认走 `mqtt_binary`。未注册但合法的 ROS 消息类型默认走 `mqtt_binary`，运行时由 Agent 和 Bridge 尝试按 ROS1 消息类执行 serialize/deserialize。

### 5.4 压缩选项

| 选项 | 适用类型 | 说明 |
|------|---------|------|
| quality | 图像 | JPEG 质量 1-100，默认 60 |
| resize | 图像 | [width, height]，如 [320, 240] |
| voxel_size | 点云 | 体素降采样尺寸（米），如 0.1 |

### 5.5 频率控制

所有话题均支持 `freq_limit` 参数。Agent 内部为每个订阅维护独立的限频器，超过频率的帧直接丢弃。

## 6. 通信流程

### 6.1 机器人上线

```
Robot                     Station
  |                          |
  |--- status (心跳) ------->|  (定时，1Hz)
  |                          |
  |<-- discover ------------|  (Station 广播)
  |                          |
  |--- discover_resp ------>|  (Robot 回复自身信息)
  |                          |
```

### 6.2 Topic 订阅

```
Robot                     Station
  |                          |
  |<-- topic_request -------|  (请求订阅 /camera/image)
  |                          |
  |--- topic_resp --------->|  (确认，告知传输方式)
  |                          |
  |--- sensor_data -------->|  (开始按频率转发数据)
  |--- sensor_data -------->|
  |--- sensor_data -------->|
  |                          |
  |<-- topic_request -------|  (取消订阅)
  |                          |
  |--- topic_resp --------->|  (确认，停止转发)
```

### 6.3 控制指令

```
Robot                     Station
  |                          |
  |<-- cmd -----------------|  (速度控制)
  |                          |
  |--- cmd_ack ------------>|  (确认 ok/failed)
  |                          |
```

### 6.4 重量话题（点云/视频流）

```
Robot                     Station
  |                          |
  |<-- topic_request -------|  (订阅 /lidar/points)
  |                          |
  |--- topic_resp --------->|  (确认 transport=http_stream)
  |                          |
  |--- sensor_meta -------->|  (元信息 + 流地址)
  |                          |
  |<======= HTTP 流 ========|  (Station 拉取流数据)
  |                          |
```
