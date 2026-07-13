# ROS Ground Station

基于 MQTT 的 ROS 多机器人地面站控制系统，PyQt5 + RViz 嵌入式 3D 可视化，实现机器人发现、话题传输配置、命令控制、传感器数据展示、编队通信规则下发和统一 TF 可视化。Station 与机器人 ROS 网络保持隔离，仅通过 MQTT 协议通信。

## 架构

```
Robot (ROS) ──► Agent ──MQTT──► Mosquitto Broker ──MQTT──► Bridge ──► roscore (宿主机) ──► Qt 前端 + RViz
```

- **Agent**：运行在机器人端（Docker 容器或物理机），桥接 ROS 话题 ↔ MQTT
- **Bridge** (`mqtt_ros_bridge`)：宿主机 MQTT ↔ ROS 双向翻译，自动类型检测，并负责地面站本地 ROS topic 与 TF 重发布
- **Qt 前端**：PyQt5 桌面应用，嵌入式 RViz 3D 渲染，话题订阅、命令控制、编队通信配置
- **MQTT Broker**：Mosquitto，消息中枢

## 主要能力

- 多机器人在线发现、状态显示、命令控制和事件告警。
- 通过前端传输面板配置每台机器人需要上报的 ROS topic，支持保存、下发和从机器人拉取当前配置。
- 通过编队通信面板配置机器人之间的 ROS topic 转发规则，支持按源机器人分组下发、拉取、合并和本地持久化。
- Agent 端支持 `subscriptions` 和 `fleet_rules` 启动恢复，并将运行态配置写回机器人自己的配置文件。
- Bridge 端将 MQTT 数据重新发布到地面站本地 roscore，RViz 只依赖地面站本地 ROS master。
- 支持多机器人 TF 命名空间化和 `global_map -> robot/map` 统一坐标根，机器人 `/tf_static` 通过 MQTT retained 消息转发并在 Bridge 侧缓存重发。
- 地面站本地 ROS 中仅 `/tf`、`/tf_static` 使用标准公共话题；普通传感器和状态话题按机器人隔离，例如 `/turtlebot_001/odom`、`/turtlebot_001/joint_states`。
- 话题健康面板按机器人展示订阅话题的链路状态、最近更新时间、传输方式和 Bridge 本地 ROS 发布目标，用于排查 MQTT、HTTP stream 和 ROS topic 重发布链路。

## 快速开始（Ubuntu 20.04 + ROS Noetic）

```bash
# 1. 系统依赖
sudo apt install mosquitto mosquitto-clients python3-pip
pip install -e ".[qt,dev]"

# 2. 构建 RViz C++ 胶水库
cd qt_frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc) && cd ../../..

# 3. Docker 混合测试（TurtleBot3 仿真 + 地面站）
docker compose up -d robot-turtlebot-001        # 启动单机器人仿真容器
./qt_frontend/scripts/start.sh                  # 启动地面站（自动拉起 roscore + broker + bridge）

# 4. 可选：启动第二台 TurtleBot3，用于多机器人和编队通信测试
docker compose up -d robot-turtlebot-002

# 5. 停止
./qt_frontend/scripts/stop.sh
docker compose stop robot-turtlebot-001 robot-turtlebot-002
```

> 仿真容器首次构建约需 20 分钟（需下载 Gazebo 等依赖）。详见 `docs/work-log-2026-05-08.md`。

## 配置文件

| 路径 | 作用 |
|------|------|
| `qt_frontend/config/transmit_config.yaml` | 地面站侧配置，保存每台机器人的 `subscriptions` 和跨机器人视角的 `fleet_rules` |
| `agent/configs/default.yaml` | 默认机器人端配置，适合单 Agent 或单机器人物理部署 |
| `agent/configs/<robot_id>.yaml` | 多机器人部署或仿真时每台机器人的独立 Agent 配置，避免不同机器人互相覆盖 |
| `bridge/bridge_config.yaml` | Bridge 配置，包括 MQTT、ROS topic 发布和 fleet TF 配置 |

实际机器人部署时，每台机器人使用自己的 `agent/configs/<robot_id>.yaml`，或在单机器人机器上直接维护 `agent/configs/default.yaml`；地面站维护跨机器人视角的 `transmit_config.yaml`，并通过 MQTT `config_sync` / `config_query` 与机器人端同步。

## 编队通信规则

编队通信面板用于描述“源机器人某个 ROS topic 转发给目标机器人某个 ROS topic”。地面站保存规则时会保留 `src_robot`，便于按源机器人分组下发：

```yaml
fleet_rules:
  - enabled: true
    src_robot: turtlebot_001
    src_topic: /odom
    msg_type: nav_msgs/Odometry
    dst_robot: turtlebot_002
    dst_topic: /fleet/turtlebot_001/odom
    freq_limit: 10.0
    transport: mqtt_json
    frame_policy: namespace
```

下发到源机器人后，Agent 端配置只保留自身需要执行的协议规则：

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

下发时按源机器人合并发送。例如 `turtlebot_001` 有 3 条规则、`turtlebot_002` 有 2 条规则，地面站会发送 2 次 `config_sync`，而不是逐条发送 5 次。

## 目录结构

```
ros-ground-station-pyqt/
├── protocol/                     # 共享消息协议（Agent / Bridge 共用，零外部依赖）
│   ├── messages.py               #   消息格式 (dataclass) + MessageFactory
│   ├── topics.py                 #   MQTT topic 命名/生成/解析
│   └── topic_registry.py         #   话题传输分层（41 种 ROS 类型）
├── agent/                        # 机器人端 Agent（ROS ↔ MQTT 桥接）
│   ├── base_agent.py             #   抽象基类 + AgentConfig
│   ├── ros1_agent.py             #   ROS 1 实现 (rospy)
│   ├── mock_agent.py             #   模拟 Agent（无 ROS）
│   ├── topic_handler.py          #   话题分层处理
│   ├── rate_limiter.py           #   按话题独立限频
│   ├── ros_msg_converter.py      #   ROS 消息 → dict
│   ├── config.yaml               #   Agent 配置文件
│   └── main.py                   #   启动入口
├── bridge/                       # 宿主机 MQTT-ROS 桥接
│   ├── mqtt_ros_bridge.py        #   双向翻译核心
│   ├── dict_to_ros_msg.py        #   dict → ROS 消息 通用反序列化
│   └── bridge_config.yaml        #   Bridge 配置
├── qt_frontend/                  # PyQt5 桌面端
│   ├── main.py                   #   QApplication 入口
│   ├── main_window.py            #   QMainWindow + RViz 嵌入 (ctypes)
│   ├── mqtt_client.py            #   线程安全 MQTT (paho → Qt Signal)
│   ├── panels/                   #   面板
│   │   ├── robot_list_panel.py   #     机器人列表 + 心跳检测
│   │   ├── command_panel.py      #     速度/模式控制
│   │   ├── event_panel.py        #     事件/告警列表
│   │   └── ...                   #     话题健康、数据推送等
│   ├── native/                   #   C++ RViz 胶水库
│   │   ├── rviz_widget.h / .cpp  #     extern "C" 接口
│   │   └── CMakeLists.txt
│   ├── config/                   #   配置文件
│   ├── launch/                   #   ROS launch
│   │   └── station.launch        #     地面站 ROS 启动入口
│   └── scripts/
│       ├── start.sh              #     一键启动
│       └── stop.sh               #     一键停止
├── docker/                       # Docker 构建
│   ├── Dockerfile.ros            #   ROS Noetic 基础镜像
│   ├── supervisord.conf          #   机器人容器进程管理
│   ├── supervisord-turtlebot3.conf  # Turtlebot3 仿真容器进程管理
│   └── sensor_simulator.py       #   传感器模拟器
├── tests/                        # 单元测试
├── docs/                         # 文档 + 工作日志
├── docker-compose.yml            # Docker 编排
├── pyproject.toml                # 依赖/构建配置
├── AGENTS.md                     # 项目指南（AI 开发用）
└── CLAUDE.md                     # 兼容旧工具的项目指南
```

## 常用命令

```bash
# 测试
python3 -m pytest tests/ -v

# 仅启模拟 Agent（无 ROS）
python -m agent.main --agent-type mock

# 启动双 TurtleBot3 仿真容器
docker compose up -d robot-turtlebot-001 robot-turtlebot-002

# 查看宿主机话题
source /opt/ros/noetic/setup.bash && rostopic list

# 查看某台机器人转发后的关节状态
source /opt/ros/noetic/setup.bash && rostopic echo -n 1 /turtlebot_001/joint_states/header

# 查看地面站本地 TF
source /opt/ros/noetic/setup.bash && rosrun tf view_frames
```

## 文档

| 文档 | 内容 |
|------|------|
| [`AGENTS.md`](AGENTS.md) | 项目架构、开发规范、命令速查 |
| [`docs/work-log-2026-05-08.md`](docs/work-log-2026-05-08.md) | Docker TurtleBot3 仿真搭建 |
| [`docs/work-log-2026-05-09.md`](docs/work-log-2026-05-09.md) | Bridge 数据流修复 + 命令/LaserScan 修复 |
| [`docs/work-log-2026-05-20.md`](docs/work-log-2026-05-20.md) | 多机器人 topic 转发和编队通信基础能力 |
| [`docs/work-log-2026-05-22.md`](docs/work-log-2026-05-22.md) | 双 TurtleBot、统一 TF 和 `/tf_static` 转发修复 |
| [`docs/work-log-2026-06-04.md`](docs/work-log-2026-06-04.md) | 编队通信规则 UI、下发/拉取和持久化完善 |
| [`docs/protocol.md`](docs/protocol.md) | MQTT 通信协议文档 |
| [`docs/tech-stack.md`](docs/tech-stack.md) | 技术栈详情 |

## License

MIT
