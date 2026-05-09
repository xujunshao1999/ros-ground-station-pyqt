# ROS Ground Station

基于 MQTT 的 ROS 地面站控制系统，PyQt5 + RViz 嵌入式 3D 可视化，实现一对多机器人管理。Station 与 ROS 版本的解耦——仅通过 MQTT 协议通信。

## 架构

```
Robot (ROS) ──► Agent ──MQTT──► Mosquitto Broker ──MQTT──► Bridge ──► roscore (宿主机) ──► Qt 前端 + RViz
```

- **Agent**：运行在机器人端（Docker 容器或物理机），桥接 ROS 话题 ↔ MQTT
- **Bridge** (`mqtt_ros_bridge`)：宿主机 MQTT ↔ ROS 双向翻译，自动类型检测
- **Qt 前端**：PyQt5 桌面应用，嵌入式 RViz 3D 渲染，话题订阅、命令控制面板
- **MQTT Broker**：Mosquitto，消息中枢

## 快速开始（Ubuntu 20.04 + ROS Noetic）

```bash
# 1. 系统依赖
sudo apt install mosquitto mosquitto-clients python3-pip
pip install -e ".[qt,dev]"

# 2. 构建 RViz C++ 胶水库
cd qt_frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc) && cd ../../..

# 3. Docker 混合测试（Turtlebot3 仿真 + 地面站）
docker compose up -d robot-turtlebot-001        # 启动仿真容器（Gazebo + gmapping + RViz）
./qt_frontend/scripts/start.sh                  # 启动地面站（自动拉起 roscore + broker + bridge）

# 4. 停止
./qt_frontend/scripts/stop.sh
docker compose stop robot-turtlebot-001
```

> 仿真容器首次构建约需 20 分钟（需下载 Gazebo 等依赖）。详见 `docs/work-log-2026-05-08.md`。

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
│   │   └── ...                   #     传感器摘要、数据推送等
│   ├── native/                   #   C++ RViz 胶水库
│   │   ├── rviz_widget.h / .cpp  #     extern "C" 接口
│   │   └── CMakeLists.txt
│   ├── config/                   #   配置文件
│   ├── launch/                   #   ROS launch
│   │   └── station.launch        #     静态 TF 变换
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
└── CLAUDE.md                     # 项目指南（AI 开发用）
```

## 常用命令

```bash
# 测试
python3 -m pytest tests/ -v

# 仅启模拟 Agent（无 ROS）
python -m agent.main --agent-type mock

# 查看宿主机话题
source /opt/ros/noetic/setup.bash && rostopic list
```

## 文档

| 文档 | 内容 |
|------|------|
| [`CLAUDE.md`](CLAUDE.md) | 项目架构、开发规范、命令速查 |
| [`docs/work-log-2026-05-08.md`](docs/work-log-2026-05-08.md) | Docker Turtlebot3 仿真搭建 |
| [`docs/work-log-2026-05-09.md`](docs/work-log-2026-05-09.md) | Bridge 数据流修复 + 命令/LaserScan 修复 |
| [`docs/protocol.md`](docs/protocol.md) | MQTT 通信协议文档 |
| [`docs/tech-stack.md`](docs/tech-stack.md) | 技术栈详情 |

## License

MIT
