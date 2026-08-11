# Repository Guidelines

## 项目结构与模块组织

本仓库实现基于 MQTT 的 ROS 多机器人地面站。共享协议代码位于 `protocol/`，必须保持零 ROS、Qt、MQTT 客户端依赖。机器人端桥接位于 `agent/`，包含 `ros1_agent.py`、`mock_agent.py`、话题处理和限频逻辑。地面站侧 MQTT 到 ROS 的转换位于 `bridge/`。桌面端应用位于 `qt_frontend/`，其中 PyQt5 面板在 `qt_frontend/panels/`，RViz C++ 胶水库在 `qt_frontend/native/`，运行配置在 `qt_frontend/config/`。Broker 与容器资源在 `broker/`、`docker/` 和 `docker-compose.yml`。测试位于 `tests/`，设计文档和工作日志位于 `docs/`；协议字段和 topic 的权威说明以 `docs/protocol.md` 为准。

## 构建、测试与开发命令

- `pip install -e ".[dev]"`：安装项目和开发依赖；PyQt5 已在项目主依赖中声明。
- `python3 -m pytest tests/ -v`：运行完整 pytest 测试套件。
- `ruff check <本次修改的 Python 文件>`：对本次修改的手写源文件执行 lint；`ruff check .` 仅用于查看全仓已知基线，不能单独作为完成判据。
- `./qt_frontend/scripts/build_rviz_widget.sh`：在 Ubuntu + ROS Noetic 环境构建并验证嵌入式 RViz 的 `librviz_widget.so`；可用 `ROS_SETUP` 和 `JOBS` 覆盖默认值。
- `python3 -m agent.main --agent-type mock`：启动无 ROS 依赖的 Mock Agent。
- `docker compose up -d robot-turtlebot-001`：启动单个 Turtlebot3 仿真容器。
- `docker compose up -d robot-turtlebot-001 robot-turtlebot-002`：启动两台 Turtlebot3，用于编队通信集成验证；不要覆盖用户已有容器或运行态配置。
- `./qt_frontend/scripts/start.sh`：启动本地地面站链路。

## 代码风格与命名约定

项目需兼容 ROS Noetic 的 Python 3.8。新增或实质修改的手写 Python 模块应在模块 docstring 后使用 `from __future__ import annotations`；不要为生成文件、空 `__init__.py` 或第三方代码做无关清理。使用 4 空格缩进；函数和变量使用 `snake_case`，类使用 `PascalCase`，常量使用 `UPPER_CASE`。类型标注使用 `Optional[X]`、`List[X]`、`Dict[K, V]`，不要使用 `X | None` 或 `list[X]`。路径处理使用 `pathlib.Path`。协议边界、兼容回退、资源限制和其他非显而易见逻辑使用中文注释；直观赋值和标准调用不要求逐行注释。MQTT topic 构造集中在 `protocol/topics.py`。JSON 协议消息使用 `MessageFactory` 和 `Message.from_json()`；ROS1 serialized binary body 必须使用 `protocol/binary_payloads.py` 的 encode/decode helper，且必须在 UTF-8/JSON 解码前按 topic 分流。

## 测试指南

测试框架为 pytest。测试文件命名为 `test_*.py`，放在 `tests/`。修改 `protocol/`、ROS 消息转换、MQTT 路由、Bridge 行为或 PyQt 面板逻辑时，应补充聚焦的单元测试。验证分三层：纯协议/Agent/面板逻辑优先使用无 roscore 的 pytest；Qt 测试使用 `QT_QPA_PLATFORM=offscreen`；涉及 ROS、MQTT、Docker 或编队链路时，再使用真实双机器人容器验证，并在工作日志或回复中说明未覆盖的环境风险。Mock Agent 通过不等同于真实 ROS 编队链路通过。

## Commit 与 Pull Request 规范

提交信息遵循现有格式：`<type>: <中文简短描述>`，例如 `fix: 修复命令发送`。常用 type 包括 `feat`、`fix`、`refactor`、`docs`、`test`、`perf`、`config` 和 `chore`。Pull Request 应说明行为变化、列出已运行的验证命令、关联 issue 或工作日志；涉及 Qt 可视界面变化时，附截图或简短录屏。

## 架构注意事项

机器人 ROS 网络与地面站 ROS master 必须保持隔离。跨网络数据统一经过 `docs/protocol.md` 定义的 MQTT/HTTP 协议层：控制、状态、配置和 JSON envelope 使用 JSON；普通 ROS topic 可使用 MQTT binary；大 payload 使用 HTTP stream + MQTT meta。机器人到地面站的 sensor 数据由 `bridge/mqtt_ros_bridge.py` 重新发布到地面站本地 roscore，供 RViz 使用。机器人 Agent 间编队由 `fleet_rules.transport` 选择 `mqtt_json` 或 `mqtt_binary`（ROS1 serialized），数据不经过地面站 Bridge，目标 Agent 直接发布到目标 ROS topic。

## 任务规模与沟通约定

- 对于单文件、小范围的小功能或小 Bug 修复，采用轻量流程：先检查相关代码和现有改动，直接实施最小修改，补充必要的聚焦测试并完成验证即可。除非任务确实需要，不强制编写单独的设计文档、实现计划或复杂的多阶段审查；仍需说明根因、验证命令和未覆盖风险。
- 对于面向用户的每次回复，正文最前面必须加上两个字母 `JS`。该约定适用于进度更新、澄清问题、测试结果和最终回复。

## 计划文档写作约定

制定或实质更新实现计划时，应假设后续执行者来自新对话，只能看到计划文件和仓库代码。计划必须独立说明为什么做、要改哪里、怎么改、如何验证，以及执行前需要理解的术语和约束。

每份新建或实质更新的计划都应在文件前部补充 `## 术语与执行约定` 章节，放在目标、架构、技术栈之后；如果计划没有这些固定章节，应放在目标说明之后、任务拆分之前。该章节应解释计划中反复出现的项目术语、缩写、协议名、配置项、运行链路、匹配规则、默认策略和易混淆概念，并用自然语言说明其输入输出、作用或最小例子。例如出现 `wildcard`、`serialized`、`meta`、`payload`、`transport: auto`、HTTP snapshot、Bridge、Agent 等词时，要说明它在本项目里的具体含义，避免执行者凭通用含义误解。

计划自检必须覆盖：

- 不看聊天记录也能理解任务背景；
- 术语与执行约定覆盖新概念和易混淆点；
- 每个关键行为都有对应测试或验证命令；
- 没有“待定”“TODO”“类似处理”“适当处理”等占位表达。

制定或更新实现计划后，必须按任务顺序做一次“新对话干跑审查”：

- 每个任务能独立执行，任务完成后仓库仍可运行或可验证；
- 后续任务依赖的函数、符号、配置项、测试夹具和运行脚本已在前序任务中定义或显式说明；
- 每个“预期失败”都说明失败应由哪个目标缺口触发，避免测试因 import、fixture、环境或顺序问题提前失败；
- 涉及 C++、ROS、Qt、RViz、Docker、MQTT 或外部库 API 时，已对照本地头文件、源码、现有调用方式或项目文档确认关键签名、符号和兼容策略；
- 存在主入口、备用入口、脚本入口或运行环境差异时，明确覆盖范围、未覆盖风险和后续补齐条件。

## Agent 协作约定

与用户沟通时默认使用中文。开始工作前检查当前分支、worktree 和 `git status`；修改代码前先阅读相关模块和文档，优先沿用仓库现有模式；不要回滚用户已有改动。只暂存本次任务文件，不得把 `.agents/`、`.codex/`、`.claude/skills/` 等本地工具目录加入提交。合并、提交或清理 worktree 前重新核对状态。涉及运行环境、ROS、Docker、RViz 或 MQTT 链路的变更，应在回复中明确验证范围和未验证风险。

## 工作日志写作风格

工作日志写入 `docs/work-log-YYYY-MM-DD.md`，标题使用 `# 工作日志 — YYYY年M月D日`。工作日志的目标是生成后可以直接作为个人工作日志使用，而不是只作为代码变更摘要、提交记录或任务清单。可优先参考 `docs/work-log-2026-06-10.md` 的结构、颗粒度和叙述方式，但不要机械照抄固定章节，应根据当天实际工作内容组织。

内容按工作模块组织，例如“今日概览”“问题排查与修复”“功能完善”“配置调整”“测试与验证”“当前状态”等。章节名称可以根据当天工作内容灵活调整，但应使用清晰的中文标题，建议采用 `## 一、今日概览` 这类编号形式，方便阅读和后续摘录。

工作日志的默认读者是之后回看工作的自己，而不是正在审查代码 diff 的开发者。写作时应优先保证“不看代码也能读懂今天做了什么、为什么做、做到什么程度”。技术名词可以保留，但首次出现时要用一句自然语言解释清楚它在本项目里的含义，例如 HTTP snapshot、meta、payload、serialized、Bridge、Agent 等，不要默认读者已经知道上下文。

章节标题应尽量描述工作目标、问题或结果，避免只使用内部实现名词或缩写。比如可以写“Agent 侧支持缓存大数据并发送取数提示”，不要写成“Agent HTTP Snapshot Meta 发布能力”；可以写“扩展点云取数说明信息”，不要写成“SensorMetaData 协议字段扩展”。如果标题或段落离开代码上下文就难以理解，应改成更通俗的业务、链路或问题描述。

每个模块应围绕一个相对独立的工作闭环展开，说明：

- 这项工作的背景或原因；
- 原来存在的问题或限制；
- 今天具体做了哪些处理；
- 解决了什么问题或达到了什么效果；
- 是否有验证结果、剩余问题或后续计划。

不要写成聊天记录，也不要只罗列代码改动、文件清单、commit hash 或任务编号。提交记录可以在“今日概览”中简要列出，但正文应按工作内容和处理过程展开，避免写成“提交列表说明”或“任务完成情况汇总”。

涉及代码、配置或运行链路时，应保留必要技术点，例如 `transmit_config.yaml`、机器人端 `config.yaml`、MQTT discover、保存/下发/拉取、订阅数统计、ROS topic、Docker、RViz、Bridge、Agent 等。技术点要服务于工作说明，不要堆成纯实现细节。

“测试与验证”部分必须列出实际执行的命令和结果。涉及 ROS、Docker、RViz、MQTT 或运行态配置时，应说明验证范围、观察到的现象，以及未验证或受环境限制的部分。

“当前状态”部分应说明：

- 已完成的功能、修复或配置；
- 当前代码或运行态配置状态；
- 是否已提交；
- 是否还有未完成任务；
- 是否存在未验证风险或未提交的运行态配置。

写完工作日志后应自检：

- 是否不看代码也能理解今天做了什么；
- 是否每个主要章节都说明了背景、处理过程和结果；
- 是否避免了按 commit、文件清单或任务编号机械组织；
- 是否保留了必要技术点，但没有堆成纯实现细节；
- 是否写清楚验证命令、验证结果、当前状态和剩余风险。
