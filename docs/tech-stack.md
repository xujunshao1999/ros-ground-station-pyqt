# ROS 地面站 - 技术选型说明

## 一、系统概述

本项目是一套基于 MQTT 的 ROS 多机器人地面站。机器人侧运行 ROS 和 Agent，地面站侧通过 MQTT 接收状态、传感器和事件数据，并用本地 ROS + RViz 做 3D 可视化。

核心原则：

- 机器人本地 ROS 不直接暴露给地面站。
- 控制面和 JSON envelope 使用 MQTT + JSON；常规 ROS topic 可使用 MQTT binary，重量数据使用 HTTP stream + MQTT meta。
- Station 与机器人侧 ROS 版本解耦，协议层只依赖标准库数据结构，不引入 ROS、Qt 或 MQTT client。
- 需要 RViz 原生显示能力时，在 Station 本机启动 roscore，并由 Bridge 把 MQTT 数据还原为 ROS 话题。

当前主线架构：

```text
Robot (ROS) -> Agent -> MQTT Broker -> Bridge -> local roscore -> PyQt5 + RViz
                    \                                /
                     -------- command / ack --------

Agent 间编队数据走独立的 MQTT fleet data path：源 Agent -> MQTT Broker -> 目标 Agent，
按 `fleet_rules.transport` 选择 JSON 或 ROS1 serialized binary，不经过 Station Bridge。
```

更完整的数据流：

```text
Robot container / physical robot
  roscore
  ROS topics: /odom /scan /imu /tf /map ...
  agent.ros1_agent
      |
      | MQTT JSON / MQTT binary / HTTP meta
      v
Station host
  Mosquitto
  bridge.mqtt_ros_bridge
      |
      | typed ROS messages
      v
  local roscore
  qt_frontend
    - PyQt5 panels
    - embedded RViz RenderPanel
    - MQTT command client
```

> 说明：早期文档中提到的 FastAPI + Vue Web 地面站不是当前实现主线。当前仓库以 `qt_frontend/` 桌面站、`bridge/` MQTT-ROS 桥和 `agent/` 机器人端 Agent 为核心。

---

## 二、技术选型总览

| 层级 | 当前选型 | 版本/依赖 | 说明 |
|------|----------|-----------|------|
| 跨机器通信 | MQTT | Mosquitto 2.x / paho-mqtt 2.x | 机器人、Bridge、Qt 前端之间的统一消息总线 |
| 消息序列化 | JSON + ROS1 serialized binary | `protocol/messages.py`、`protocol/binary_payloads.py` | 控制面/envelope 使用 JSON，ROS body 使用原生 serialized bytes |
| 协议层 | Python dataclass | Python 3.8+ | `protocol/` 零 ROS 依赖，Agent/Station 共用 |
| 机器人端 Agent | Python + rospy | ROS Noetic / Python 3.8 | ROS topic 与 MQTT 双向桥接 |
| 地面站 GUI | PyQt5 | Qt5 / PyQt5 | 机器人管理、控制、事件、话题配置等面板 |
| 3D 可视化 | RViz embedded | C++ glue + librviz | 原生 RViz Display 渲染，不为每种 ROS 消息手写前端组件 |
| MQTT-ROS Bridge | Python + rospy | bridge/mqtt_ros_bridge.py | 把 MQTT sensor 数据还原成本地 ROS 话题 |
| ROS 消息转换 | introspection | genpy / rospy | `ros_msg_to_dict()` 与 `dict_to_ros_msg()` 通用转换 |
| 配置 | YAML | pyyaml | Agent、Bridge、Qt 前端配置 |
| 测试 | pytest | tests/ | 协议、转换、MQTT 客户端、Qt 面板逻辑测试 |
| 仿真测试 | Docker + Turtlebot3 | ROS Noetic / Gazebo / gmapping | 机器人容器与宿主机 Station 通过 MQTT 隔离 |

---

## 三、逐项选型理由

### 1. MQTT：跨机器通信主干

| 对比项 | MQTT | ROS 原生通信 | gRPC | WebSocket |
|--------|------|--------------|------|-----------|
| ROS 版本解耦 | 强 | 弱，绑定 rosmaster / DDS | 强 | 强 |
| 一对多机器人 | 发布/订阅天然支持 | 需要额外命名空间和网络规划 | 需自建路由 | 需自建路由 |
| 断线重连 | 客户端和协议生态成熟 | 需要应用层处理 | 需要应用层处理 | 需要应用层处理 |
| 调试便利 | mosquitto_sub 可直接观察 | 依赖 ROS 工具链 | 需要专用客户端 | 一般 |
| 部署复杂度 | 低 | 跨主机 ROS 网络配置复杂 | 中 | 中 |

选择 MQTT 的主要原因：

- Station 不需要加入机器人侧 roscore，也不需要知道机器人 ROS 网络细节。
- 多机器人接入时只需要统一接入 Broker。
- Topic 通配符适合地面站订阅 `robot/+/status`、`robot/+/sensor/#` 这类全局数据。
- QoS、Last Will、重连机制适合机器人弱网场景。

当前 topic 规范由 `protocol/topics.py` 维护，主要包括：

| MQTT Topic | 方向 | 用途 |
|------------|------|------|
| `robot/{id}/status` | Robot -> Station | 心跳和状态 |
| `robot/{id}/sensor/{name}` | Robot -> Station | 传感器数据 |
| `robot/{id}/sensor/{name}/meta` | Robot -> Station | 重量数据元信息 |
| `robot/{id}/cmd` | Station -> Robot | 控制指令 |
| `robot/{id}/cmd/ack` | Robot -> Station | 指令确认 |
| `robot/{id}/event` | Robot -> Station | 事件和告警 |
| `station/discover` | Station -> Robot | 发现请求 |
| `station/topic/request` | Station -> Robot | 话题订阅管理 |
| `station/topic/response/{id}` | Robot -> Station | 订阅响应 |
| `station/{id}/config/*` | Station <-> Robot | 配置同步 |

### 2. Mosquitto：轻量 MQTT Broker

Mosquitto 适合本项目当前规模：

- 单机部署简单，配置文件少。
- 对几十到几百台机器人规模足够。
- Linux/Windows 都容易启动，方便 Mock Agent 开发。
- 仓库中保留 `amqtt` 作为纯 Python 开发备用 Broker。

本项目没有选择 EMQX/VerneMQ，主要是因为当前更关注本地部署、低运维和调试便利，而不是百万级连接。

### 3. Python Agent：贴近 ROS，开发成本低

机器人端 Agent 使用 Python 的原因：

- ROS Noetic 默认 Python 3.8，`rospy` 集成成本最低。
- Agent 的工作主要是 I/O 和消息转换，不是计算密集型任务。
- `protocol/` 可以被 Agent、Bridge、Qt 前端直接复用。
- Mock Agent 可以在无 ROS 环境运行，用于协议链路和界面调试。

项目要求保持 Python 3.8 兼容：

- 使用 `from __future__ import annotations`。
- 类型标注避免 `X | None` 和 `list[X]`。
- Ruff target 为 `py38`。

### 4. PyQt5 + RViz：当前地面站 GUI 主线

早期 Web 前端需要为每种 ROS 消息类型手写可视化组件，例如 LaserScan、Image、PointCloud2、TF、Map 等。当前改为 PyQt5 嵌入 RViz，核心收益是：

- RViz 已经支持 ROS 常用 Display，不需要重复实现 3D 可视化。
- 用户可以直接添加 Odometry、LaserScan、TF、Map、RobotModel 等 Display。
- PyQt5 适合快速实现机器人列表、控制面板、事件列表、话题配置等桌面工具界面。
- MQTT 客户端回调可通过 Qt Signal/Slot 安全切回主线程。

RViz 嵌入方式：

- `qt_frontend/native/rviz_widget.cpp` 使用 C++ 创建 RViz 组件。
- 对 Python 暴露 `extern "C"` 接口。
- `qt_frontend/main_window.py` 通过 `ctypes.CDLL` 加载 `librviz_widget.so`。
- PyQt5 使用原生窗口句柄把 RViz 面板嵌入主窗口。

Qt 前端中的话题健康面板不负责带宽统计；带宽、总流量和吞吐趋势由流量面板展示。健康面板只展示订阅状态、最近更新时间、transport/encoding、本地 ROS topic 和诊断说明，用来排查 MQTT、HTTP stream 与 Bridge 重发布链路是否一致。

已知工程约束：

- 需要 Ubuntu + ROS Noetic 才能构建和运行 RViz 胶水库。
- `load_config()` 曾导致 RViz 鼠标交互失效，目前采用手动创建基础 Display 的方式规避。
- pip 安装的 PyQt5 可能与系统 Qt/RViz 版本冲突，Ubuntu 上优先使用系统 PyQt5 包。

### 5. MQTT-ROS Bridge：让 RViz 看见真实 ROS 话题

Bridge 是当前架构的关键组件。它订阅 MQTT 传感器数据，再发布到 Station 本地 roscore：

```text
robot/turtlebot_001/sensor/scan
  -> bridge parses JSON
  -> dict_to_ros_msg(sensor_msgs/LaserScan)
  -> publish /turtlebot_001/scan
  -> RViz LaserScan Display
```

Bridge 的设计要点：

- 优先使用 Station 已知订阅表中的 msg_type。
- 未注册话题可从 MQTT payload 的 `_msg_type` 自动检测 ROS 类型。
- `/tf`、`/tf_static` 走标准 ROS 话题名，而不是强行加机器人前缀。
- 普通话题发布为 `/{robot_id}/{original_topic}`，例如 `/turtlebot_001/odom` 和 `/turtlebot_001/joint_states`。
- 多机器人 TF 命名空间前缀由 `namespace_tf_frames` 配置控制。

这让 Station 可以同时做到：

- MQTT 层保持 ROS 版本解耦。
- RViz 层仍然使用原生 ROS 话题和原生插件。

### 6. 通用 ROS 消息转换

项目中有两个互逆转换：

- `agent/ros_msg_converter.py`：ROS message -> dict。
- `bridge/dict_to_ros_msg.py`：dict -> ROS message。

选择通用字段内省而不是硬编码类型的原因：

- ROS 标准消息类型很多，手写维护成本高。
- RViz 常用 Display 覆盖 Odometry、LaserScan、Imu、PointCloud2、OccupancyGrid、Marker、TF 等多类消息。
- 自定义消息也可以在字段结构兼容时复用通用转换逻辑。

当前 `protocol/topic_registry.py` 已覆盖 41 种常见 ROS 消息类型，并按数据量分为轻量、中等、重量话题。

### 7. 分层传输策略

控制面和小型自定义数据仍以 JSON 为主：

- 方便直接用 `mosquitto_sub -v` 查看 payload。
- 方便 pytest 构造测试数据。
- 方便 Mock Agent 和非 ROS 工具参与调试。
- 高频 ROS topic 已支持 ROS1 serialized binary，按规则显式选择并保留 JSON 回退。

数据量分层策略：

| 分层 | 典型类型 | 当前/目标传输方式 |
|------|----------|-------------------|
| LIGHT | 控制、状态、配置和简单自定义数据 | MQTT + JSON |
| MEDIUM | Odometry、TF、LaserScan、CompressedImage、OccupancyGrid 小地图 | MQTT + ROS1 serialized binary，必要时 JSON 回退 |
| HEAVY | 原始 Image、PointCloud2、大地图 | HTTP stream + MQTT meta，后续优化 |

近期日志中记录了 `/map` OccupancyGrid 大消息的 Bridge 发布问题，这是当前需要继续排查的重点之一。

### 8. Docker Turtlebot3：真实链路测试环境

当前推荐的集成测试方式是机器人跑在 Docker 容器，Station 跑在宿主机：

```text
Docker: turtlebot-001
  roscore
  Gazebo Turtlebot3
  gmapping
  ros1_agent
      |
      | MQTT
      v
Host:
  Mosquitto
  mqtt_ros_bridge
  roscore
  Qt frontend + RViz
```

这样可以验证两个关键边界：

- 机器人 ROS 网络与 Station ROS 网络完全隔离。
- 所有跨机器数据都必须经过 MQTT 协议。

常用启动流程见 `README.md`，核心命令是：

```bash
docker compose up -d robot-turtlebot-001
./qt_frontend/scripts/start.sh
```

### 9. 配置和持久化

当前主要使用 YAML 配置：

- `agent/config.yaml`：机器人 ID、Broker、状态频率、默认订阅等。
- `bridge/bridge_config.yaml`：Broker、ROS topic 前缀、TF namespace 策略等。
- `qt_frontend/config/config.yaml`：Qt 前端连接和显示配置。
- `qt_frontend/config/transmit_config.yaml`：话题订阅持久化。

SQLite、录制和回放在早期设计中出现过，但当前代码主线的重点仍是通信链路、RViz 显示和控制链路。后续实现录制回放时，再以 SQLite 作为本地单机存储是合理选择。

---

## 四、关键架构决策

| 决策 | 当前选择 | 理由 |
|------|----------|------|
| 跨机器通信 | MQTT | ROS 解耦、一对多、弱网恢复、调试便利 |
| Station 可视化 | PyQt5 + embedded RViz | 复用 RViz 原生 ROS Display |
| Station 本地 ROS | 需要 | 仅用于 RViz/Bridge，不直接连接机器人 roscore |
| ROS 数据还原 | Bridge 发布本地 ROS 话题 | 让 RViz 订阅真实 typed ROS messages |
| Agent 语言 | Python | rospy 集成简单，协议代码可复用 |
| 消息格式 | 控制面/envelope 使用 JSON，ROS body 按数据层使用 binary 或 HTTP stream | 兼顾可调试性、吞吐和大 payload 隔离 |
| 话题命名 | 普通话题 `/{robot_id}/{topic}`，仅 `/tf` 和 `/tf_static` 使用公共话题 | 多机器人隔离，同时兼容 RViz TF 习惯 |
| 仿真验证 | Docker Turtlebot3 + 宿主机 Station | 模拟真实多机边界，避免单 roscore 假联通 |
| Python 版本 | 3.8+ | 兼容 ROS Noetic |

---

## 五、当前进度

| 模块 | 状态 | 说明 |
|------|------|------|
| 协议层 `protocol/` | 已实现 | 消息格式、topic 生成/解析、话题注册表 |
| Mock Agent | 已实现 | 无 ROS 环境可验证 MQTT 协议链路 |
| ROS1 Agent | 已实现 | 支持 ROS topic 订阅、命令下发、配置同步 |
| 通用 ROS 序列化 | 已实现 | `ros_msg_to_dict()` 支持字段内省 |
| MQTT-ROS Bridge | 已实现，仍有待排查项 | TF、scan、odom、imu、joint_states 已验证 |
| PyQt5 前端 | 已实现主框架 | 主窗口、RViz 嵌入、机器人/命令/事件/话题等面板 |
| RViz C++ 胶水 | 已实现 | 支持嵌入 RenderPanel 和 Display 面板 |
| Turtlebot3 Docker 仿真 | 已实现 | Gazebo + gmapping + Agent 容器化 |
| 命令链路 | 已验证 | Qt -> MQTT -> Agent -> `/cmd_vel` -> Gazebo |

当前已验证数据流：

```text
Turtlebot3 /odom /scan /imu /tf /joint_states
  -> ros1_agent
  -> MQTT
  -> mqtt_ros_bridge
  -> host roscore (/turtlebot_001/odom, /turtlebot_001/joint_states, /tf ...)
  -> RViz / Qt frontend
```

当前已验证命令流：

```text
Qt CommandPanel
  -> robot/{id}/cmd
  -> Agent _handle_command(action="velocity")
  -> ROS /cmd_vel
  -> Gazebo robot moves
```

---

## 六、待完成和已知问题

| 项目 | 状态 | 说明 |
|------|------|------|
| `/map` OccupancyGrid 发布 | 待排查 | MQTT 侧有数据，Bridge 内大消息发布链路仍需诊断 |
| `/tf_static` latched topic | 有 workaround | 当前用 `station.launch` 补静态 TF，根因仍需查 |
| 多机器人 TF namespace | 待验证 | Bridge 已有配置项，需要多容器实测 |
| ROS2 Agent | 未开始 | 协议层支持方向明确，但尚未实现 |
| 录制与回放 | 未完成 | 后续可用 SQLite 本地存储状态、事件和传感器摘要 |
| MessagePack / 二进制优化 | 未开始 | 等协议稳定和性能瓶颈明确后再做 |
| TLS / 鉴权 | 未开始 | 生产部署前需要补齐 Broker 安全配置 |

---

## 七、历史方案说明

早期设计曾规划：

- FastAPI + WebSocket 后端。
- Vue 3 + TypeScript + Vite Web 前端。
- Three.js 点云和自定义图像/传感器组件。

这些方案适合浏览器仪表盘，但在本项目当前目标下存在一个核心问题：ROS 可视化组件需要大量重复实现。当前已经转向 PyQt5 + RViz，是因为 RViz 原生支持绝大多数机器人可视化场景，开发重点可以放在通信、控制、多机器人管理和部署稳定性上。

因此，后续文档和开发应以 `README.md`、`docs/qt-rviz-station-plan-B.md`、`docs/work-log-2026-05-08.md`、`docs/work-log-2026-05-09.md` 记录的 PyQt5/RViz 路线为准。
