# ROS Ground Station

基于 MQTT 的地面站控制系统，实现一对多机器人管理。Station 与 ROS 版本解耦，只认 MQTT 协议。

## 架构

```
Robot (ROS) ──► Agent (Python) ──MQTT──► Mosquitto Broker ──MQTT──► Station (FastAPI) ──WebSocket──► Vue 3 前端
```

- **Agent**：运行在机器人端，桥接 ROS 话题 ↔ MQTT 消息
- **Station**：地面站，FastAPI 后端 + Vue 3 前端，ROS 无关
- **MQTT Broker**：Mosquitto，消息中枢

## 快速开始（Ubuntu 20.04）

```bash
# 1. 安装系统依赖
sudo apt install mosquitto mosquitto-clients python3-pip python3-venv
sudo systemctl stop mosquitto && sudo systemctl disable mosquitto

# 2. 克隆项目
git clone https://github.com/xujunshao1999/ros-ground-station.git
cd ros-ground-station

# 3. 安装 Python 依赖
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[station,dev]"

# 4. Docker 混合测试
./scripts/start_hybrid_test.sh          # 启动 broker + 2 个机器人容器
python -m station.backend.main          # 启动地面站
python scripts/test_hybrid.py           # 自动化验证

# 5. 运行单元测试
python -m pytest tests/ -v
```

详细指南见 [`docs/docker-hybrid-test.md`](docs/docker-hybrid-test.md)。

## Windows 开发（Mock Agent）

```powershell
# 安装依赖
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[station,dev]"

# 启动 Mock Agent（无需 ROS）
python -m agent.main --agent-type mock

# 启动地面站
python -m station.backend.main
```

## 目录结构

```
ROS_Project/
├── protocol/                     # 共享消息协议（零外部依赖）
│   ├── messages.py               #   消息格式 + MessageFactory
│   ├── topics.py                 #   MQTT topic 命名/解析
│   └── topic_registry.py         #   话题传输分层 (LIGHT/MEDIUM/HEAVY)
├── agent/                        # 机器人端 Agent
│   ├── base_agent.py             #   抽象基类
│   ├── ros1_agent.py             #   ROS 1 实现 (rospy)
│   ├── mock_agent.py             #   模拟 Agent（无 ROS）
│   ├── topic_handler.py          #   话题分层处理
│   ├── rate_limiter.py           #   按话题限频
│   └── main.py                   #   启动入口
├── station/
│   ├── backend/                  # FastAPI 后端
│   │   ├── api.py                #   REST + WebSocket API
│   │   ├── mqtt_handler.py       #   MQTT 客户端
│   │   ├── robot_manager.py      #   机器人状态管理
│   │   ├── ws_manager.py         #   WebSocket 连接池
│   │   ├── database.py           #   SQLite 存储
│   │   ├── recorder.py           #   数据录制/回放
│   │   ├── alert_engine.py       #   告警规则引擎
│   │   └── main.py               #   启动入口
│   └── frontend/                 # Vue 3 + TypeScript
├── docker/                       # Docker 镜像
│   ├── Dockerfile.ros            #   ROS Noetic 机器人
│   ├── sensor_simulator.py       #   ROS 传感器模拟器
│   └── supervisord.conf          #   容器内进程管理
├── scripts/                      # 辅助脚本
│   ├── start_hybrid_test.sh      #   混合测试启动
│   ├── stop_hybrid_test.sh       #   混合测试停止
│   └── test_hybrid.py            #   端到端验证
├── tests/                        # 单元测试 (89 tests)
├── docs/                         # 文档
│   ├── docker-hybrid-test.md     #   Docker 测试指南
│   ├── protocol.md               #   通信协议
│   └── tech-stack.md             #   技术栈
├── docker-compose.yml            # Docker 编排
├── pyproject.toml                # 依赖配置
└── CLAUDE.md                     # Claude Code 项目指南
```

## 测试

```bash
python -m pytest tests/ -v                       # 全部测试 (89)
python -m pytest tests/test_protocol_messages.py -v  # 单文件
```

## 文档

| 文档 | 内容 |
|------|------|
| [`CLAUDE.md`](CLAUDE.md) | 项目架构、开发规范、命令速查 |
| [`docs/docker-hybrid-test.md`](docs/docker-hybrid-test.md) | Docker 混合测试完整指南 |
| [`docs/protocol.md`](docs/protocol.md) | MQTT 通信协议文档 |
| [`docs/tech-stack.md`](docs/tech-stack.md) | 技术栈详情 |
| [`project-plan.md`](project-plan.md) | 分步执行计划 |

## License

MIT
