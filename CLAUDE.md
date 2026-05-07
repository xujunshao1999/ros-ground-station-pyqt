# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project overview

ROS Ground Station — an MQTT-based multi-robot control system. Robots run ROS locally; the Agent bridges ROS topics ↔ MQTT; the Station (PyQt5 + embedded RViz) displays robot state and sends commands. The Station is ROS-agnostic — it only speaks the MQTT protocol.

Development is done on **Ubuntu 20.04** (native Station + Docker robot containers) or **Windows with Mock Agent** (no ROS required). Real ROS Agents are tested either via Docker containers (`ros:noetic-robot` image) or on physical Linux machines.

## Directory structure

```
ROS_Project/
├── protocol/                        # 共享消息协议（Agent 和 Station 共用，零外部依赖）
│   ├── messages.py                  #   消息格式 (dataclass) + MessageFactory
│   ├── topics.py                    #   MQTT topic 命名/生成/解析
│   └── topic_registry.py            #   话题传输分层 (LIGHT/MEDIUM/HEAVY)
│
├── agent/                           # 机器人端 Agent（ROS ↔ MQTT 桥接）
│   ├── base_agent.py                #   抽象基类 + AgentConfig
│   ├── ros1_agent.py                #   ROS 1 实现（Linux, rospy）
│   ├── mock_agent.py                #   模拟 Agent（Windows/Linux, 无 ROS）
│   ├── topic_handler.py             #   话题分层处理（轻量/中等/重量）
│   ├── rate_limiter.py              #   按话题独立限频
│   ├── config.yaml                  #   Agent 配置文件
│   └── main.py                      #   启动入口
│
├── station/                         # 地面站
│   ├── backend/
│   │   ├── main.py                  #   启动入口 + 组件装配
│   │   ├── api.py                   #   FastAPI REST + WebSocket API
│   │   ├── mqtt_handler.py          #   MQTT 客户端（订阅/发布/重连）
│   │   ├── robot_manager.py         #   机器人状态管理 + 心跳检测
│   │   ├── ws_manager.py            #   WebSocket 连接池 + 线程安全广播
│   │   ├── database.py              #   SQLite 存储（同步 sqlite3）
│   │   ├── recorder.py              #   数据录制/回放
│   │   ├── alert_engine.py          #   告警规则引擎
│   │   ├── dependencies.py          #   依赖注入容器
│   │   └── config.yaml              #   Station 配置文件
│   └── station/                       # Vue 前端已废弃，由 qt-frontend 替代
│
├── qt-frontend/                      # PyQt5 桌面前端
│   ├── main.py                       #   QApplication 入口
│   ├── main_window.py                #   QMainWindow + RvizWidget (ctypes)
│   ├── mqtt_client.py                #   线程安全 MQTT (paho → Qt Signal)
│   ├── panels/                       #   面板
│   │   ├── robot_list_panel.py       #     机器人列表 + 心跳检测
│   │   ├── command_panel.py          #     速度/模式控制
│   │   ├── event_panel.py            #     事件/告警列表
│   │   ├── sensor_summary_panel.py   #     传感器数据摘要
│   │   ├── data_sender_panel.py      #     数据推送
│   │   ├── traffic_monitor.py        #     带宽流量监控
│   │   ├── topic_config_panel.py     #     话题订阅配置
│   │   └── fleet_comm_panel.py       #     编队通信规则
│   ├── native/                       #   C++ RViz 胶水库
│   │   ├── rviz_widget.h / .cpp      #     extern "C" 接口
│   │   └── CMakeLists.txt            #     CMake 构建
│   ├── config/                       #   配置文件
│   │   ├── config.yaml               #     MQTT/ROS/RViz 配置
│   │   ├── default.rviz              #     RViz 默认布局
│   │   └── transmit_config.yaml      #     话题订阅持久化
│   ├── scripts/                      #   启动/停止脚本
│   │   ├── start.sh / stop.sh
│   └── launch/                       #   ROS launch 文件
│       └── station.launch
│
├── broker/                          # MQTT Broker 配置
│   ├── mosquitto.conf               #   Mosquitto 配置（listener 1883）
│   ├── start_pybroker.py            #   纯 Python 备用 Broker（amqtt）
│   ├── start.sh                     #   Linux 启动脚本
│   └── start.bat                    #   Windows 启动脚本
│
├── docker/                          # Docker 构建文件
│   ├── Dockerfile.ros               #   ROS Noetic 机器人镜像
│   ├── Dockerfile.station           #   Station 后端镜像
│   ├── Dockerfile.mock              #   Mock Agent 镜像
│   ├── supervisord.conf             #   容器内进程管理
│   ├── sensor_simulator.py          #   ROS 传感器模拟器
│   └── mosquitto.conf               #   Docker 版 broker 配置（备用）
│
├── scripts/                         # 开发/测试辅助脚本
│   ├── start_hybrid_test.sh         #   混合测试一键启动
│   ├── stop_hybrid_test.sh          #   混合测试停止
│   └── test_hybrid.py               #   端到端自动化验证
│
├── tests/                           # 测试
│   ├── conftest.py                  #   pytest fixtures
│   ├── test_protocol_messages.py    #   消息格式测试
│   ├── test_protocol_topics.py      #   Topic 生成/解析测试
│   └── test_protocol_registry.py    #   话题注册表测试
│
├── docs/                            # 文档
│   ├── docker-hybrid-test.md        #   Docker 混合测试指南
│   ├── protocol.md                  #   通信协议文档
│   ├── tech-stack.md                #   技术栈详情
│   └── agents/                      #   Agent 工作流文档
│
├── docker-compose.yml               # Docker 编排（robot 容器）
├── pyproject.toml                   # 项目依赖/构建配置
├── CLAUDE.md                        # 本文件
└── project-plan.md                  # 架构与执行计划
```

## Commands

```bash
# Install (development)
pip install -e ".[station,dev]"

# Install with Qt frontend
pip install -e ".[qt,dev]"

# Build RViz C++ glue library (Ubuntu + ROS Noetic required)
cd qt-frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc)

# Run all tests
python3 -m pytest tests/ -v

# Run a single test file
python3 -m pytest tests/test_protocol_messages.py -v

# ============================================
# Station — Qt frontend (Ubuntu + ROS Noetic)
# ============================================

# Build RViz C++ library
cd qt-frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc)

# Start Qt frontend (requires roscore + mosquitto + built .so)
./qt-frontend/scripts/start.sh

# Or start manually
python3 qt-frontend/main.py

# ============================================
# Agent — three options
# ============================================

# 1. Mock Agent (Windows/Linux, no ROS needed)
python -m agent.main --agent-type mock

# 2. Docker hybrid test (Robots in Docker, Station native)
./scripts/start_hybrid_test.sh      # start broker + robot containers
python -m station.backend.main       # start station
python scripts/test_hybrid.py        # verify end-to-end

# 3. Real ROS1 Agent (Linux only, ROS Noetic required)
python -m agent.main --agent-type ros1 --broker-host <station-ip>
```

## Architecture

```
Robot (ROS) → Agent → MQTT Broker → Qt Frontend (PyQt5 + RViz 3D)
                                   → bridge/mqtt_ros_bridge.py → local roscore
```

### Data flow: Robot → Station

1. **Agent** subscribes to ROS topics. When the Station requests a topic via `station/topic/request`, the Agent starts forwarding.
2. **MqttClient** (`qt-frontend/mqtt_client.py`) receives MQTT messages on wildcard subscriptions and emits Qt Signals.
3. **Panels** (`qt-frontend/panels/`) receive data via Signal/Slot connections on the main thread.
4. **RViz** (`qt-frontend/native/`) renders ROS topics via the bridge on a local roscore.

### Data flow: Station → Robot (commands)

1. Frontend sends command via WebSocket → `api.py` REST endpoint → `MQTTHandler.send_command()` → MQTT topic `robot/{id}/cmd`
2. Agent receives command on `robot/{id}/cmd` → `_execute_command()` → publishes to ROS topic (e.g. `/cmd_vel`)
3. Agent sends ack on `robot/{id}/cmd/ack` → Station tracks via `pending_commands`

### Key design decisions

- **Python 3.8+** compatibility is required (ROS Noetic ships Python 3.8). Every `.py` file must start with `from __future__ import annotations` as the first import. Use `Optional[X]` and `List[X]` from `typing` — never `X | None` or `list[X]` as annotation syntax (PEP 604/585 not supported in Python 3.8). Ruff targets `py38`.
- **`protocol/` is shared code** — Agent and Station both import from it. It has no external dependencies (no paho-mqtt, no numpy).
- **Thread safety**: MQTT callbacks run in paho-mqtt's network thread. Data that crosses thread boundaries (Agent state, WsManager connections, RobotManager robots dict) must be protected by `threading.Lock`. Cross-thread asyncio calls go through `call_soon_threadsafe`.
- **Config validation**: Use `AgentConfig.from_yaml(path)` and `StationConfig.from_yaml(path)` — these validate field types/ranges and warn about unknown keys (typo prevention).
- **File paths**: Always use `pathlib.Path`, never string concatenation. This is a cross-platform project (Windows dev, Linux prod).

### Robot-to-Robot communication

Robots can send data directly to each other without station intervention. Light data (position, nav_goal, custom) goes through MQTT `robot/{src}/to/{dst}` with `MessageType.FLEET_DATA`. Heavy data (point clouds) reuses the Agent's HTTP stream server: the sender stores data via `_store_stream_data()`, sends a `fleet_data` meta signal on `robot/{src}/to/{dst}/meta`, and the receiver pulls via HTTP.

Key methods on `BaseAgent`:
- `send_to_robot(target_id, fleet_data)` — send light data via MQTT JSON
- `share_heavy_data(target_id, topic, data)` — share heavy data via HTTP stream + MQTT signaling
- `_on_fleet_message(src_id, data)` — abstract method, subclasses implement to handle incoming fleet data

### MQTT topic naming

All topics follow the pattern defined in `protocol/topics.py`:

| Topic | Direction | QoS | Purpose |
|---|---|---|---|
| `robot/{id}/status` | Robot → Station | 1 | Heartbeat + state |
| `robot/{id}/sensor/{name}` | Robot → Station | 0 | Sensor data |
| `robot/{id}/sensor/{name}/meta` | Robot → Station | 1 | Heavy topic stream URL |
| `robot/{id}/cmd` | Station → Robot | 1 | Control command |
| `robot/{id}/cmd/ack` | Robot → Station | 1 | Command ack |
| `robot/{id}/event` | Robot → Station | 1 | Alerts/events (incl. Last Will) |
| `robot/{src}/to/{dst}` | Robot → Robot | 1 | Robot-to-robot data (position/nav_goal/custom) |
| `robot/{src}/to/{dst}/meta` | Robot → Robot | 1 | Robot-to-robot heavy data stream URL |
| `station/discover` | Station → Robot | 1 | Discover online robots |
| `station/topic/request` | Station → Robot | 1 | Subscribe/unsubscribe topic |
| `station/topic/response/{id}` | Robot → Station | 1 | Subscription ack |

### Message format (all MQTT payloads)

```json
{"ver":"1.0","ts":1712582400.0,"src":"robot_001","dst":"station","type":"status","seq":42,"data":{...}}
```

Defined in `protocol/messages.py`. Use `MessageFactory` to create messages and `Message.from_json()` to parse them.

## 开发规范

### 版本控制（Git）

- **修改代码前必须 commit**：任何代码改动前，先将当前工作状态提交到 git。这使得改动可追溯、可回滚。
- **Commit message 格式**：`<type>: <简短描述>`，type 为 feat/fix/refactor/docs/test 之一。正文补充关键细节。
- **禁止 `git push --force`、`git reset --hard`、`git checkout --` 等不可逆操作**，除非用户明确要求。
- **Commit 粒度**：每个独立功能/修复完成后立即提交，不要攒大量改动。
- **`Co-Authored-By`**：所有 commit message 末尾添加 `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`。
- **未跟踪文件**：`demo/`、build 产物（`*.so`、`build/`）不纳入版本控制。
- **回滚**：如果某次改动引入了 bug 且短时间无法修复，先 `git stash` 或回退到上一个已知良好 commit，再分析根因。

### Python 规范
- Python 3.8+ 兼容性（ROS Noetic 要求）
- `from __future__ import annotations` 作为每个 `.py` 文件第一个 import
- 使用 `pathlib.Path` 处理文件路径，不拼接字符串
- 使用 `Optional[X]` / `List[X]`，不用 `X | None` / `list[X]`

### 测试规范
- 所有面板和协议模块必须有单元测试
- 测试运行：`python3 -m pytest tests/ -v`

## Key documents

| Document | Purpose |
|----------|---------|
| `docs/docker-hybrid-test.md` | Docker 混合测试环境完整指南（替代 step-1.5b 手动验证） |
| `docs/protocol.md` | MQTT 通信协议文档 |
| `docs/tech-stack.md` | 技术栈详情 |
| `project-plan.md` | 项目架构与分步执行计划 |

## Agent skills

### Issue tracker

GitHub Issues, operated via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — one `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.