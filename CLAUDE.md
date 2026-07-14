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
- **Commit message 格式**：`<type>: <中文简短描述>`，type 为 feat/fix/refactor/docs/test 之一。正文用中文补充关键细节。
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

<!-- superpowers-zh:begin (do not edit between these markers) -->
# Superpowers-ZH 中文增强版

本项目已安装 superpowers-zh 技能框架（20 个 skills）。

## 核心规则

1. **收到任务时，先检查是否有匹配的 skill** — 哪怕只有 1% 的可能性也要检查
2. **设计先于编码** — 收到功能需求时，先用 brainstorming skill 做需求分析
3. **测试先于实现** — 写代码前先写测试（TDD）
4. **验证先于完成** — 声称完成前必须运行验证命令

## 可用 Skills

Skills 位于 `.claude/skills/` 目录，每个 skill 有独立的 `SKILL.md` 文件。

- **brainstorming**: 在任何创造性工作之前必须使用此技能——创建功能、构建组件、添加功能或修改行为。在实现之前先探索用户意图、需求和设计。
- **chinese-code-review**: 中文 review 沟通参考——话术模板、分级标注（必须修复/建议修改/仅供参考）、国内团队常见反模式应对。仅在用户显式 /chinese-code-review 时调用，不要根据上下文自动触发。
- **chinese-commit-conventions**: 中文 commit 与 changelog 配置参考——Conventional Commits 中文适配、commitlint/husky/commitizen 中文模板、conventional-changelog 中文配置。仅在用户显式 /chinese-commit-conventions 时调用，不要根据上下文自动触发。
- **chinese-documentation**: 中文文档排版参考——中英文空格、全半角标点、术语保留、链接格式、中文文案排版指北约定。仅在用户显式 /chinese-documentation 时调用，不要根据上下文自动触发。
- **chinese-git-workflow**: 国内 Git 平台配置参考——Gitee、Coding.net、极狐 GitLab、CNB 的 SSH/HTTPS/凭据/CI 接入差异与镜像同步配置。仅在用户显式 /chinese-git-workflow 时调用，不要根据上下文自动触发。
- **dispatching-parallel-agents**: 当面对 2 个以上可以独立进行、无共享状态或顺序依赖的任务时使用
- **executing-plans**: 当你有一份书面实现计划需要在单独的会话中执行，并设有审查检查点时使用
- **finishing-a-development-branch**: 当实现完成、所有测试通过、需要决定如何集成工作时使用——通过提供合并、PR 或清理等结构化选项来引导开发工作的收尾
- **mcp-builder**: MCP 服务器构建方法论 — 系统化构建生产级 MCP 工具，让 AI 助手连接外部能力
- **receiving-code-review**: 收到代码审查反馈后、实施建议之前使用，尤其当反馈不明确或技术上有疑问时——需要技术严谨性和验证，而非敷衍附和或盲目执行
- **requesting-code-review**: 完成任务、实现重要功能或合并前使用，用于验证工作成果是否符合要求
- **subagent-driven-development**: 当在当前会话中执行包含独立任务的实现计划时使用
- **systematic-debugging**: 遇到任何 bug、测试失败或异常行为时使用，在提出修复方案之前执行
- **test-driven-development**: 在实现任何功能或修复 bug 时使用，在编写实现代码之前
- **using-git-worktrees**: 当需要开始与当前工作区隔离的功能开发，或在执行实现计划之前使用——通过原生工具或 git worktree 回退机制确保隔离工作区存在
- **using-superpowers**: 在开始任何对话时使用——确立如何查找和使用技能，要求在任何响应（包括澄清性问题）之前调用 Skill 工具
- **verification-before-completion**: 在宣称工作完成、已修复或测试通过之前使用，在提交或创建 PR 之前——必须运行验证命令并确认输出后才能声称成功；始终用证据支撑断言
- **workflow-runner**: 在 Claude Code / OpenClaw / Cursor 中直接运行 agency-orchestrator YAML 工作流——无需 API key，使用当前会话的 LLM 作为执行引擎。当用户提供 .yaml 工作流文件或要求多角色协作完成任务时触发。
- **writing-plans**: 当你有规格说明或需求用于多步骤任务时使用，在动手写代码之前
- **writing-skills**: 当创建新技能、编辑现有技能或在部署前验证技能是否有效时使用

## 如何使用

当任务匹配某个 skill 时，使用 `Skill` 工具加载对应 skill 并严格遵循其流程。绝不要用 Read 工具读取 SKILL.md 文件。

如果你认为哪怕只有 1% 的可能性某个 skill 适用于你正在做的事情，你必须调用该 skill 检查。
<!-- superpowers-zh:end -->
