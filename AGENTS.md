# Repository Guidelines

## 项目结构与模块组织

本仓库实现基于 MQTT 的 ROS 多机器人地面站。共享协议代码位于 `protocol/`，必须保持零 ROS、Qt、MQTT 客户端依赖。机器人端桥接位于 `agent/`，包含 `ros1_agent.py`、`mock_agent.py`、话题处理和限频逻辑。地面站侧 MQTT 到 ROS 的转换位于 `bridge/`。桌面端应用位于 `qt_frontend/`，其中 PyQt5 面板在 `qt_frontend/panels/`，RViz C++ 胶水库在 `qt_frontend/native/`，运行配置在 `qt_frontend/config/`。Broker 与容器资源在 `broker/`、`docker/` 和 `docker-compose.yml`。测试位于 `tests/`，设计文档和工作日志位于 `docs/`。

## 构建、测试与开发命令

- `pip install -e ".[qt,dev]"`：安装 Qt 和开发依赖。
- `python3 -m pytest tests/ -v`：运行完整 pytest 测试套件。
- `ruff check .`：按 Python 3.8 目标执行 lint 检查。
- `cd qt_frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc)`：在 Ubuntu + ROS Noetic 环境构建嵌入式 RViz 所需的 `librviz_widget.so`。
- `python -m agent.main --agent-type mock`：启动无 ROS 依赖的 Mock Agent。
- `docker compose up -d robot-turtlebot-001`：启动 Turtlebot3 仿真容器。
- `./qt_frontend/scripts/start.sh`：启动本地地面站链路。

## 代码风格与命名约定

项目需兼容 ROS Noetic 的 Python 3.8。每个 Python 文件的首个 import 应为 `from __future__ import annotations`。使用 4 空格缩进；函数和变量使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_CASE`。类型标注使用 `Optional[X]`、`List[X]`、`Dict[K, V]`，不要使用 `X | None` 或 `list[X]`。路径处理使用 `pathlib.Path`。MQTT topic 构造集中在 `protocol/topics.py`，协议消息使用 `MessageFactory` 和 `Message.from_json()`。

## 测试指南

测试框架为 pytest。测试文件命名为 `test_*.py`，放在 `tests/`。修改 `protocol/`、ROS 消息转换、MQTT 路由、Bridge 行为或 PyQt 面板逻辑时，应补充聚焦的单元测试。除非变更目标就是 ROS 集成，否则优先编写不依赖 roscore 的测试。

## Commit 与 Pull Request 规范

提交信息遵循现有格式：`<type>: <中文简短描述>`，例如 `fix: 修复命令发送`。常用 type 包括 `feat`、`fix`、`refactor`、`docs`、`test`。Pull Request 应说明行为变化、列出已运行的验证命令、关联 issue 或工作日志；涉及 Qt 可视界面变化时，附截图或简短录屏。

## 架构注意事项

机器人 ROS 网络与地面站 ROS master 必须保持隔离。跨机器数据统一通过 `docs/protocol.md` 定义的 MQTT JSON topic 传输；RViz 只能看到 `bridge/mqtt_ros_bridge.py` 重新发布到本地 roscore 的 ROS topic。

## Agent 协作约定

与用户沟通时默认使用中文。修改代码前先阅读相关模块和文档，优先沿用仓库现有模式；不要回滚用户已有改动。涉及运行环境、ROS、Docker、RViz 或 MQTT 链路的变更，应在回复中明确验证范围和未验证风险。

## 工作日志写作风格

工作日志写入 `docs/work-log-YYYY-MM-DD.md`，标题使用 `# 工作日志 — YYYY年M月D日`。内容按工作模块组织，例如“今日概览”“问题排查与修复”“功能完善”“测试与验证”“当前状态”。语气保持正式、清晰，不写成聊天记录，也不要只罗列代码改动。每个模块说明做了什么、为什么做、解决了什么问题，并保留必要技术点，例如 `transmit_config.yaml`、机器人端 `config.yaml`、MQTT discover、保存/下发/拉取、订阅数统计等。验证部分列出实际执行的命令和结果；如有未验证风险或运行态配置未提交，应在“当前状态”中说明。
