# 地面站 ROS Bag 数据录制实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在 PyQt5 地面站左侧增加可配置的 ROS bag 录制页签，允许用户选择本地 ROS 话题、自定义名称和常用录制参数，并安全管理 ROS Noetic `rosbag record` 的启动、状态显示和停止保存。

**架构：** 新建 `qt_frontend/recording.py` 承载录制配置、参数校验、话题分组纯逻辑和 `RosbagRecorder` 的 `QProcess` 状态机；新建 `qt_frontend/panels/recording_panel.py` 承载窄栏 UI。`MainWindow` 负责在线机器人、配置话题、本地 ROS 发现结果和录制服务之间的装配，并把状态同步到菜单、工具栏和状态栏。

**技术栈：** Python 3.8、PyQt5 `QProcess/QSettings/signal-slot`、ROS Noetic `rosbag record/rostopic list/rosbag info`、pytest、ruff。

## 术语与执行约定

- **本地 ROS 话题**：地面站本机 `ROS_MASTER_URI` 指向的 roscore 中，`rostopic list` 当前返回的话题。录制进程只订阅这一侧，不连接机器人自己的 ROS Master。
- **推荐话题**：同时存在于 `transmit_config.yaml`、对应机器人在线、并且已经出现在本地 ROS Master 的话题。推荐话题默认勾选，但用户可以取消。
- **公共 TF**：Bridge 把所有机器人的 `/tf` 和 `/tf_static` 发布到标准公共话题；其他配置话题映射为 `/{robot_id}/{原话题}`。推荐话题构造必须遵守该例外。
- **录制基础路径**：保存目录与用户名称组合出的、不带 `.bag` 的绝对路径，例如 `/data/records/patrol_01`；它作为 `rosbag record -O` 的值。
- **分包**：使用 `--split` 搭配 `--size` 或 `--duration`。分包时必须加 `--repeat-latched`，但禁止加入会删除旧文件的 `--max-splits`。
- **正常停止**：在 Linux/ROS Noetic 环境中，对 `QProcess.processId()` 使用 `os.kill(pid, signal.SIGINT)`。Qt `QProcess.terminate()` 发送的是 SIGTERM，不能替代本项目要求的 rosbag 正常收尾。
- **保存状态**：已发送 SIGINT、正在等待 rosbag 写入索引和关闭 `.active` 文件的阶段。该阶段禁止再次开始或重复停止。
- **完成与失败结果状态**：`COMPLETED` 和 `FAILED` 都保留结果页，不自动跳回空闲；用户点击“新建录制”或“返回配置”时调用 `reset()` 回到 `IDLE`。
- **主入口**：`./qt_frontend/scripts/start.sh` 最终执行 `python3 qt_frontend/main.py`，因此完整功能接入 `qt_frontend/main_window.py`。`qt_frontend/panels_setup.py` 是历史 C++ 容器入口，当前启动脚本不使用；本期只补充 `RecordingPanel` 导出，不在该备用入口复制录制服务装配。
- **预期失败**：每个 TDD 失败必须由本任务尚未实现的目标符号或行为触发。不得因缺少 Qt fixture、ROS 环境、错误 import 或前序任务未定义接口提前失败。

## 文件结构

- 创建 `qt_frontend/recording.py`：录制枚举和 dataclass、名称/路径/参数校验、命令数组、输出文件匹配、话题分组纯逻辑、`RosbagRecorder` 状态机。
- 创建 `qt_frontend/panels/recording_panel.py`：360 px 单列录制配置页与运行状态页、话题树、参数控件、偏好持久化和用户信号。
- 修改 `qt_frontend/panels/__init__.py`：导出 `RecordingPanel`。
- 修改 `qt_frontend/main_window.py`：创建录制服务和面板，接入左侧页签、菜单、工具栏、ROS 检测、在线机器人和关闭流程。
- 修改 `.gitignore`：忽略 `records/`、`*.bag` 和 `*.bag.active`。
- 创建 `tests/test_rosbag_recorder.py`：纯逻辑和假 `QProcess` 的录制服务测试。
- 创建 `tests/test_recording_panel.py`：Qt offscreen 面板结构与交互测试。
- 修改 `tests/test_main_window.py`：主窗口装配、全局状态和关闭行为测试。
- 创建 `tests/integration/test_rosbag_recording.py`：仅在显式 ROS 环境变量启用时执行真实 rosbag 集成验证，默认 pytest 不启动 roscore。

---

### 任务 1：定义录制配置、校验和 rosbag 参数构造

**文件：**
- 创建：`qt_frontend/recording.py`
- 创建：`tests/test_rosbag_recorder.py`

- [ ] **步骤 1：编写配置与命令构造的失败测试**

在 `tests/test_rosbag_recorder.py` 定义基础测试，先只导入尚不存在的符号：

```python
from pathlib import Path
from typing import List

import pytest

from qt_frontend.recording import (
    CompressionMode,
    RecordingConfig,
    SplitMode,
    build_rosbag_arguments,
    validate_recording_config,
)


def test_build_lz4_recording_arguments(tmp_path: Path) -> None:
    config = RecordingConfig(
        name="warehouse_patrol_01",
        output_dir=tmp_path,
        topics=["/tf", "/tf_static", "/turtlebot_001/odom"],
        compression=CompressionMode.LZ4,
        buffer_mib=256,
    )

    assert build_rosbag_arguments(config) == [
        "record",
        "-O",
        str(tmp_path / "warehouse_patrol_01"),
        "--lz4",
        "--buffsize=256",
        "/tf",
        "/tf_static",
        "/turtlebot_001/odom",
    ]


@pytest.mark.parametrize(
    ("split_mode", "expected"),
    [
        (SplitMode.SIZE, ["--split", "--size=4096", "--repeat-latched"]),
        (SplitMode.DURATION, ["--split", "--duration=60m", "--repeat-latched"]),
    ],
)
def test_split_arguments_include_repeat_latched(
    tmp_path: Path,
    split_mode: SplitMode,
    expected: List[str],
) -> None:
    config = RecordingConfig(
        name="mission",
        output_dir=tmp_path,
        topics=["/scan"],
        split_mode=split_mode,
        split_size_mib=4096,
        split_duration_value=60,
        split_duration_unit="m",
    )

    arguments = build_rosbag_arguments(config)
    for item in expected:
        assert item in arguments
    assert "--max-splits" not in arguments


def test_validate_rejects_path_separator_and_empty_topics(tmp_path: Path) -> None:
    config = RecordingConfig(
        name="bad/name",
        output_dir=tmp_path,
        topics=[],
    )

    assert validate_recording_config(config) == [
        "录制名称不能包含路径分隔符",
        "至少选择一个录制话题",
    ]
```

- [ ] **步骤 2：运行测试确认由目标模块缺失而失败**

运行：

```bash
python3 -m pytest tests/test_rosbag_recorder.py -v
```

预期：collection 阶段 FAIL，错误为 `ModuleNotFoundError: No module named 'qt_frontend.recording'`。不得出现 PyQt5、fixture 或 ROS import 错误。

- [ ] **步骤 3：实现最小配置模型和纯函数**

在 `qt_frontend/recording.py` 添加模块 docstring 和 `from __future__ import annotations`，定义：

```python
class CompressionMode(str, Enum):
    NONE = "none"
    LZ4 = "lz4"
    BZ2 = "bz2"


class SplitMode(str, Enum):
    NONE = "none"
    SIZE = "size"
    DURATION = "duration"


@dataclass
class RecordingConfig:
    name: str
    output_dir: Path
    topics: List[str]
    compression: CompressionMode = CompressionMode.LZ4
    split_mode: SplitMode = SplitMode.NONE
    split_size_mib: int = 4096
    split_duration_value: int = 60
    split_duration_unit: str = "m"
    buffer_mib: int = 256

    @property
    def output_base(self) -> Path:
        return self.output_dir / self.name.strip()
```

实现 `validate_recording_name()`、`validate_recording_config()` 和 `build_rosbag_arguments()`。规则必须逐项明确：

- 名称非空，允许 Unicode 字母、数字、中文、`-`、`_`，禁止 `/`、`\\` 和 `.`/`..`；
- `output_dir` 必须是绝对 `Path`，存在时必须为可写目录，不存在时父目录必须可写；
- `topics` 去重后按用户传入顺序保留，所有话题必须以 `/` 开头；
- `buffer_mib`、分包大小和分包时长必须为正整数；
- duration unit 只能是 `s`、`m`、`h`；
- 参数使用 `--buffsize=256`、`--size=4096`、`--duration=60m` 形式；
- 返回值只包含传给 `rosbag` 的 arguments，不包含程序名。

- [ ] **步骤 4：补充压缩、冲突和输出匹配测试**

增加以下行为：

```python
def test_bz2_and_uncompressed_arguments(tmp_path: Path) -> None:
    bz2 = RecordingConfig("bz2_run", tmp_path, ["/scan"], CompressionMode.BZ2)
    raw = RecordingConfig("raw_run", tmp_path, ["/scan"], CompressionMode.NONE)

    assert "--bz2" in build_rosbag_arguments(bz2)
    assert "--lz4" not in build_rosbag_arguments(bz2)
    assert "--bz2" not in build_rosbag_arguments(raw)
    assert "--lz4" not in build_rosbag_arguments(raw)


def test_existing_output_family_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "mission.bag.active").write_bytes(b"")
    config = RecordingConfig("mission", tmp_path, ["/scan"])

    assert "录制名称已存在" in validate_recording_config(config)
```

实现 `recording_output_paths(output_base: Path) -> List[Path]`，只在 `output_base.parent` 内匹配：

- `<name>.bag`
- `<name>.bag.active`
- `<name>_*.bag`
- `<name>_*.bag.active`

不要使用未限定目录的递归 glob。

- [ ] **步骤 5：运行聚焦测试和 lint**

运行：

```bash
python3 -m pytest tests/test_rosbag_recorder.py -v
ruff check qt_frontend/recording.py tests/test_rosbag_recorder.py
```

预期：全部 PASS，ruff 无错误。

- [ ] **步骤 6：提交任务 1**

```bash
git add qt_frontend/recording.py tests/test_rosbag_recorder.py
git commit -m "feat: 添加 rosbag 录制配置模型"
```

### 任务 2：实现推荐话题分组和选择保留逻辑

**文件：**
- 修改：`qt_frontend/recording.py`
- 修改：`tests/test_rosbag_recorder.py`

- [ ] **步骤 1：编写 Bridge 话题映射的失败测试**

```python
from qt_frontend.recording import (
    build_recording_topic_groups,
    parse_rostopic_list_verbose,
)


def test_build_topic_groups_maps_robot_topics_and_deduplicates_tf() -> None:
    subscriptions = {
        "turtlebot_001": [
            {"topic": "/odom", "msg_type": "nav_msgs/Odometry"},
            {"topic": "/tf", "msg_type": "tf2_msgs/TFMessage"},
        ],
        "turtlebot_002": [
            {"topic": "/tf", "msg_type": "tf2_msgs/TFMessage"},
            {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
        ],
    }
    local_topics = [
        "/tf",
        "/turtlebot_001/odom",
        "/turtlebot_002/scan",
        "/station/robot_list",
    ]

    groups = build_recording_topic_groups(
        subscriptions,
        ["turtlebot_001", "turtlebot_002"],
        local_topics,
    )

    assert [item.topic for item in groups.common] == ["/tf"]
    assert [item.topic for item in groups.robots["turtlebot_001"]] == [
        "/turtlebot_001/odom"
    ]
    assert [item.topic for item in groups.robots["turtlebot_002"]] == [
        "/turtlebot_002/scan"
    ]
    assert [item.topic for item in groups.other] == ["/station/robot_list"]


def test_parse_rostopic_verbose_deduplicates_publishers_and_subscribers() -> None:
    output = """
Published topics:
 * /scan [sensor_msgs/LaserScan] 1 publisher
 * /tf [tf2_msgs/TFMessage] 2 publishers

Subscribed topics:
 * /scan [sensor_msgs/LaserScan] 1 subscriber
 * /cmd_vel [geometry_msgs/Twist] 1 subscriber
"""

    assert parse_rostopic_list_verbose(output) == {
        "/cmd_vel": "geometry_msgs/Twist",
        "/scan": "sensor_msgs/LaserScan",
        "/tf": "tf2_msgs/TFMessage",
    }
```

- [ ] **步骤 2：运行测试确认目标函数缺失**

运行：

```bash
python3 -m pytest tests/test_rosbag_recorder.py::test_build_topic_groups_maps_robot_topics_and_deduplicates_tf -v
```

预期：FAIL，错误为无法导入 `build_recording_topic_groups`。

- [ ] **步骤 3：实现话题模型和隐藏话题判定**

定义：

```python
@dataclass(frozen=True)
class RecordingTopic:
    topic: str
    msg_type: str = ""
    robot_id: str = ""
    recommended: bool = False


@dataclass
class RecordingTopicGroups:
    common: List[RecordingTopic]
    robots: Dict[str, List[RecordingTopic]]
    other: List[RecordingTopic]
```

实现：

- `bridge_topic_for(robot_id, source_topic)`：`/tf`、`/tf_static` 保持公共名称，其余规范化为 `/{robot_id}/{source_topic.lstrip('/')}`；
- `is_hidden_ros_topic(topic)`：路径任一非空 segment 以 `_` 开头即为隐藏；
- `parse_rostopic_list_verbose(output)`：只解析 `Published topics:` 与 `Subscribed topics:` 下的 `* /topic [pkg/Type] ...` 行，按完整 topic 去重并优先保留非空类型；
- `build_recording_topic_groups(subscriptions, online_robot_ids, local_topics, local_topic_types=None)`；
- `reconcile_selected_topics(previous, groups)`：首次无 previous 时选中全部推荐话题；刷新时保留仍存在的选择，并把新出现的推荐话题加入选择。

排序规则固定为 `/tf`、`/tf_static` 优先，其余按完整话题字符串排序；机器人组按 robot ID 排序。

- [ ] **步骤 4：补充离线、隐藏和刷新选择测试**

覆盖：离线机器人配置不进入推荐组；配置存在但本地缺失不显示；隐藏话题默认仍在模型中但由面板过滤；刷新后消失话题从 selection 移除；新推荐话题自动选中，新增 other 话题不自动选中。

- [ ] **步骤 5：运行测试和 lint**

```bash
python3 -m pytest tests/test_rosbag_recorder.py -v
ruff check qt_frontend/recording.py tests/test_rosbag_recorder.py
```

预期：全部 PASS。

- [ ] **步骤 6：提交任务 2**

```bash
git add qt_frontend/recording.py tests/test_rosbag_recorder.py
git commit -m "feat: 添加录制话题分组逻辑"
```

### 任务 3：实现 `RosbagRecorder` QProcess 状态机

**文件：**
- 修改：`qt_frontend/recording.py`
- 修改：`tests/test_rosbag_recorder.py`

- [ ] **步骤 1：编写假进程和启动状态失败测试**

测试使用注入的 `process_factory`，不得实际启动 ROS：

```python
class FakeProcess:
    def __init__(self) -> None:
        self.program = ""
        self.arguments = []
        self.pid = 4321

    def setProgram(self, program: str) -> None:
        self.program = program

    def setArguments(self, arguments: List[str]) -> None:
        self.arguments = list(arguments)

    def processId(self) -> int:
        return self.pid


def test_recorder_starts_rosbag_with_structured_arguments(tmp_path: Path) -> None:
    process = FakeProcess()
    recorder = RosbagRecorder(process_factory=lambda parent: process)
    config = RecordingConfig("mission", tmp_path, ["/scan"])

    assert recorder.start(config) is True
    assert process.program == "rosbag"
    assert process.arguments == build_rosbag_arguments(config)
    assert recorder.state == RecorderState.STARTING
```

实际 FakeProcess 需要提供可手动 emit 的 `started`、`finished`、`errorOccurred`、`readyReadStandardError` 假信号，以及 `start()`、`readAllStandardError()`、`kill()` 方法。

- [ ] **步骤 2：运行测试确认 `RosbagRecorder` 缺失**

```bash
python3 -m pytest tests/test_rosbag_recorder.py::test_recorder_starts_rosbag_with_structured_arguments -v
```

预期：FAIL，错误为无法导入 `RosbagRecorder` 或 `RecorderState`。

- [ ] **步骤 3：实现状态枚举、信号和启动流程**

定义 `RecorderState(str, Enum)`：`IDLE`、`STARTING`、`RECORDING`、`STOPPING`、`COMPLETED`、`FAILED`。

`RosbagRecorder(QObject)` 至少提供：

```python
state_changed = pyqtSignal(object)  # RecorderState
stats_changed = pyqtSignal(float, int)
error_changed = pyqtSignal(str)
finished = pyqtSignal(bool, str)

def start(self, config: RecordingConfig) -> bool: ...
def stop(self) -> bool: ...
def force_kill(self) -> bool: ...
def is_active(self) -> bool: ...
def output_size_bytes(self) -> int: ...
```

构造器接受 `ros_master_uri: str`、`process_factory: Optional[Callable[[QObject], QProcess]]`、`kill_fn: Callable[[int, int], None] = os.kill`、`clock_fn=time.monotonic`，便于无 ROS 测试。生产环境使用 `QProcess(self)`，设置 separate channels，并连接 Qt 5.15 的 `started`、`finished`、`errorOccurred`、`readyReadStandardError`。

启动前使用 `QProcessEnvironment.systemEnvironment()` 构造环境；`ros_master_uri` 非空时覆盖 `ROS_MASTER_URI`，确保录制进程与主窗口 ROS 检测使用同一个 Master。不得丢失由 `start.sh` source ROS 后继承的 `PATH`、`PYTHONPATH` 和 ROS package 环境。

`start()` 必须先调用任务 1 的校验，创建缺失但允许创建的输出目录，记录 config/start_time，清空 stderr ring buffer，然后使用 `setProgram("rosbag")`、`setArguments(arguments)`、`start()`。重复启动返回 `False` 并发出明确错误。

- [ ] **步骤 4：编写并实现 SIGINT 正常停止测试**

```python
def test_stop_sends_sigint_to_qprocess_pid(tmp_path: Path) -> None:
    sent = []
    process = FakeProcess()
    recorder = RosbagRecorder(
        process_factory=lambda parent: process,
        kill_fn=lambda pid, sig: sent.append((pid, sig)),
    )
    recorder.start(RecordingConfig("mission", tmp_path, ["/scan"]))
    process.started.emit()

    assert recorder.stop() is True
    assert sent == [(4321, signal.SIGINT)]
    assert recorder.state == RecorderState.STOPPING
```

实现时只在 `RECORDING` 或 `STARTING` 且 PID 大于 0 时发送 SIGINT。`STOPPING` 重复调用返回 `False`；`IDLE` 返回 `False`。不要调用 `QProcess.terminate()`。

- [ ] **步骤 5：实现 stderr、完成、失败和统计刷新**

使用 `deque(maxlen=20)` 保存 stderr 最后 20 个非空行。进程正常退出且当前状态为 `STOPPING` 时发送成功完成；启动失败、CrashExit 或非零退出且非主动停止时进入 `FAILED`，错误摘要包含退出码和最后 stderr。

使用内部 1 秒 `QTimer` 在活动状态下发出 elapsed seconds 和 `output_size_bytes()`；完成后停止 timer。`output_size_bytes()` 只累计任务 1 的 `recording_output_paths()`。

- [ ] **步骤 6：补充强制终止和状态转换测试**

覆盖：

- `STARTING -> RECORDING -> STOPPING -> COMPLETED -> IDLE`；
- 启动错误进入 `FAILED`；
- 非零异常退出包含 stderr；
- `force_kill()` 只在活动状态调用 fake process `kill()`；
- `reset()` 只允许从 `COMPLETED` 或 `FAILED` 回到 `IDLE`；
- 输出大小只统计当前基础名称文件。

- [ ] **步骤 7：运行测试和 lint**

```bash
python3 -m pytest tests/test_rosbag_recorder.py -v
ruff check qt_frontend/recording.py tests/test_rosbag_recorder.py
```

预期：全部 PASS。

- [ ] **步骤 8：提交任务 3**

```bash
git add qt_frontend/recording.py tests/test_rosbag_recorder.py
git commit -m "feat: 实现 rosbag 录制进程管理"
```

### 任务 4：构建左侧 `RecordingPanel` 配置界面

**文件：**
- 创建：`qt_frontend/panels/recording_panel.py`
- 修改：`qt_frontend/panels/__init__.py`
- 创建：`tests/test_recording_panel.py`

- [ ] **步骤 1：编写面板结构的失败测试**

```python
def test_recording_panel_defaults(qt_app, tmp_path: Path) -> None:
    panel = RecordingPanel(settings=FakeSettings(), default_output_dir=tmp_path)

    assert panel.minimumWidth() <= 320
    assert panel._edit_name.text().startswith("recording_")
    assert panel._combo_compression.currentData() == CompressionMode.LZ4
    assert panel._combo_split.currentData() == SplitMode.NONE
    assert panel._spin_buffer.value() == 256
    assert panel._btn_start.isEnabled() is False
```

`FakeSettings` 实现 `value(key, defaultValue=None, type=None)` 与 `setValue(key, value)`，避免测试写用户配置。

- [ ] **步骤 2：运行测试确认面板模块缺失**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_recording_panel.py -v
```

预期：collection FAIL，错误为 `No module named 'qt_frontend.panels.recording_panel'`。

- [ ] **步骤 3：实现配置页单列控件**

`RecordingPanel(QWidget)` 使用模块 docstring 和 Python 3.8 类型标注，定义信号：

```python
refresh_requested = pyqtSignal()
start_requested = pyqtSignal(object)  # RecordingConfig
stop_requested = pyqtSignal()
force_kill_requested = pyqtSignal()
```

控件结构：

- ROS 状态标签与刷新图标按钮；
- 录制名称 `QLineEdit`；
- 话题搜索 `QLineEdit` 与 `QTreeWidget`；
- “显示隐藏话题”复选框；
- 可勾选的“推荐话题”“其他本地 ROS 话题”顶层项，推荐区内有“公共变换”和机器人子组；
- 保存目录 `QLineEdit` 与 `QFileDialog.getExistingDirectory()`；
- 压缩 `QComboBox`；
- 分包 `QComboBox`，按模式显示 `QSpinBox` 大小或 duration value/unit；
- buffer `QSpinBox`；
- 文件预览、选择摘要、校验错误标签；
- 开始按钮。

参数区用可折叠 `QGroupBox`，不要在窄栏内使用多列表格。完整话题和 msg type 放在 item tooltip 与 `Qt.UserRole` 数据中。

- [ ] **步骤 4：实现话题模型渲染和选择行为**

公开方法：

```python
def set_ros_available(self, available: bool, message: str = "") -> None: ...
def set_topic_groups(self, groups: RecordingTopicGroups) -> None: ...
def selected_topics(self) -> List[str]: ...
def set_online_robot_ids(self, robot_ids: List[str]) -> None: ...
```

第一次模型加载使用 `reconcile_selected_topics([], groups)` 默认勾选推荐话题；刷新使用现有 selection。搜索只隐藏不匹配项，不改变勾选。关闭隐藏话题显示时，若存在已选隐藏话题，先取消其选择并在摘要区提示取消数量，避免隐藏选择继续录制。

- [ ] **步骤 5：实现配置构造、校验与偏好持久化**

`current_config()` 从控件构造 `RecordingConfig`，output dir 使用 `Path(...).expanduser().resolve()`。任何字段变化都调用 `validate_recording_config()`，仅当 ROS 可用、至少一个话题和配置无错误时启用开始按钮。

使用注入的 `QSettings`，生产默认：

```python
QSettings("ros-ground-station", "qt-frontend")
```

键固定为：

```text
recording/output_dir
recording/compression
recording/split_mode
recording/split_size_mib
recording/split_duration_value
recording/split_duration_unit
recording/buffer_mib
recording/show_hidden_topics
```

名称不持久化，每次面板构造使用当前时间生成。

- [ ] **步骤 6：补充参数联动和文件预览测试**

覆盖：

- size 模式只显示大小控件，duration 模式只显示时长控件；
- BZ2 选择显示 CPU 提示；
- 名称变化实时更新 `<output_dir>/<name>.bag` 预览；
- 选择话题后 `start_requested` 发出的 `RecordingConfig` 内容正确；
- 非法名称、空话题、ROS 不可用时开始按钮禁用；
- 搜索、隐藏话题、刷新保留选择；
- 偏好写入并由新面板恢复。

- [ ] **步骤 7：运行 Qt 测试和 lint**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_recording_panel.py -v
ruff check qt_frontend/panels/recording_panel.py qt_frontend/panels/__init__.py tests/test_recording_panel.py
```

预期：全部 PASS。

- [ ] **步骤 8：提交任务 4**

```bash
git add qt_frontend/panels/recording_panel.py qt_frontend/panels/__init__.py tests/test_recording_panel.py
git commit -m "feat: 添加 rosbag 录制配置面板"
```

### 任务 5：实现录制中、保存和失败状态视图

**文件：**
- 修改：`qt_frontend/panels/recording_panel.py`
- 修改：`tests/test_recording_panel.py`

- [ ] **步骤 1：编写状态视图失败测试**

```python
def test_recording_state_locks_configuration_and_shows_stats(panel) -> None:
    panel.set_recorder_state(RecorderState.RECORDING, "")
    panel.set_recording_stats(755.0, 1932735283)

    assert panel._stack.currentWidget() is panel._running_page
    assert panel._lb_elapsed.text() == "00:12:35"
    assert panel._lb_size.text() == "1.8 GiB"
    assert panel._btn_stop.isEnabled() is True
    assert panel._edit_name.isEnabled() is False


def test_stopping_state_disables_repeated_stop(panel) -> None:
    panel.set_recorder_state(RecorderState.STOPPING, "正在保存")

    assert panel._btn_stop.text() == "正在保存..."
    assert panel._btn_stop.isEnabled() is False
```

- [ ] **步骤 2：运行测试确认缺少状态接口**

预期：FAIL，错误为 `RecordingPanel` 没有 `set_recorder_state`。

- [ ] **步骤 3：实现 `QStackedWidget` 状态页**

配置页和运行页放入 `QStackedWidget`。运行页展示状态、时长、大小、文件名、目录、话题数、压缩/分包/buffer 摘要、最近警告和停止按钮。

公开方法：

```python
def set_recorder_state(self, state: RecorderState, message: str = "") -> None: ...
def set_recording_stats(self, elapsed_seconds: float, size_bytes: int) -> None: ...
def set_active_config(self, config: RecordingConfig) -> None: ...
def show_stop_timeout(self) -> None: ...
```

`STOPPING` 显示“正在保存...”；`FAILED` 显示错误与“返回配置”；`COMPLETED` 显示最终文件和“新建录制”。超时区提供“继续等待”和“强制终止”两个明确操作，强制终止发出 `force_kill_requested`。

- [ ] **步骤 4：补充状态转换、错误和强制终止测试**

覆盖所有状态对应页、按钮可用性、错误文本、继续等待隐藏超时区、强制终止信号、完成后新名称重新生成但保留其他偏好。

- [ ] **步骤 5：运行测试和 lint**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_recording_panel.py -v
ruff check qt_frontend/panels/recording_panel.py tests/test_recording_panel.py
```

预期：全部 PASS。

- [ ] **步骤 6：提交任务 5**

```bash
git add qt_frontend/panels/recording_panel.py tests/test_recording_panel.py
git commit -m "feat: 完善录制运行状态界面"
```

### 任务 6：接入 MainWindow、菜单、工具栏和话题刷新

**文件：**
- 修改：`qt_frontend/main_window.py`
- 修改：`tests/test_main_window.py`

- [ ] **步骤 1：编写主窗口装配失败测试**

在 `MainWindow` 构造器新增可选 `recorder` 注入参数，并让 `command_window` fixture 传入 fake recorder，避免测试启动真实进程。构造器签名固定为：

```python
def __init__(
    self,
    config: dict,
    recorder: Optional[RosbagRecorder] = None,
) -> None:
```

测试：

```python
def test_main_window_has_left_recording_tab_and_menu_navigation(command_window) -> None:
    window = command_window

    assert window._left_tabs.indexOf(window._recording) >= 0
    window._act_rec_start.trigger()
    assert window._left_tabs.currentWidget() is window._recording
```

- [ ] **步骤 2：运行测试确认录制面板尚未装配**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_main_window.py::test_main_window_has_left_recording_tab_and_menu_navigation -v
```

预期：FAIL，缺少 `_recording` 或 `_left_tabs`。

- [ ] **步骤 3：创建面板和服务并接入左侧页签**

在 `_init_panels()` 创建 `self._recorder` 和 `self._recording`。`RosbagRecorder` 的 `ros_master_uri` 取 `self._config.get("ros", {}).get("master_uri", "http://localhost:11311")`；`RecordingPanel` 的默认输出目录为项目根目录下已被 `.gitignore` 忽略的 `records/`。在 `_init_central_widget()` 把局部变量 `left` 改为 `self._left_tabs`，按 `机器人 / 配置 / 录制 / 事件` 顺序添加页签。

把 `RecordingPanel.refresh_requested` 连接到 `_refresh_recording_topics()`，`start_requested` 连接 `_start_recording()`，停止和强制终止信号连接服务方法。录制服务信号统一连接 `_on_recorder_state_changed()`、`_on_recording_stats_changed()`、`_on_recording_finished()`。

- [ ] **步骤 4：实现后台 `rostopic list` 刷新**

沿用现有 ROS monitor 的线程模式，但录制刷新使用独立 `_recording_topic_refresh_inflight` 标志和 Qt signal：

```python
recording_topics_checked = pyqtSignal(bool, object, str)
```

worker 使用配置中的 `ROS_MASTER_URI`，运行：

```python
subprocess.run(
    ["rostopic", "list", "-v"],
    capture_output=True,
    text=True,
    timeout=3,
    env={**os.environ, "ROS_MASTER_URI": master_uri},
)
```

worker 把 stdout 交给任务 2 的 `parse_rostopic_list_verbose()`；解析结果为空但命令成功时，回退执行 `rostopic list` 并为每个话题保留空 msg type。结构化结果通过 signal 回到主线程，再调用任务 2 的 `build_recording_topic_groups()`。不得在 `MainWindow` 内重复实现 verbose 文本解析。

在线机器人来自 `self._robot_list.get_online_robots()`，配置订阅复用 `_configured_sensor_subscriptions`。`_on_online_robots_changed()` 和 `_refresh_robot_subscription_counts()` 完成后触发非阻塞刷新，但若已有刷新进行中只记录一次 pending refresh，避免并发启动线程。

- [ ] **步骤 5：接入菜单和全局状态控件**

菜单行为：

- “开始录制”切换录制页，录制中禁用；
- “停止录制”空闲禁用，录制中启用，保存中禁用。

工具栏在现有 `_lb_rec` 后增加带停止图标/文字的紧凑按钮 `_btn_rec_stop`，空闲隐藏。状态文本：

- idle：`录制: 就绪`；
- starting：`录制: 启动中`；
- recording：`● 录制中 HH:MM:SS`；
- stopping：`录制: 正在保存`；
- failed：`录制: 失败`。

状态栏 `_lb_rec_status` 同步显示更详细摘要。文件大小使用现有 `_format_bytes()` 扩展 GiB 分支，确保 `1.8 GiB` 格式测试稳定。

- [ ] **步骤 6：补充主窗口信号和状态测试**

覆盖：

- 在线机器人变化传给录制面板并触发话题刷新；
- topic worker 结果在主线程构造推荐分组；
- 开始动作调用 recorder 并自动切回机器人页；
- recording 状态更新菜单、工具栏、状态栏；
- 工具栏和菜单停止入口都只调用一次 `recorder.stop()`；
- failed/completed 状态恢复开始入口；
- 现有 ROS monitor 与录制刷新标志互不干扰。

- [ ] **步骤 7：运行聚焦 Qt 测试和 lint**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_main_window.py -v
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_recording_panel.py -v
python3 -m pytest tests/test_rosbag_recorder.py -v
ruff check qt_frontend/main_window.py qt_frontend/recording.py qt_frontend/panels/recording_panel.py tests/test_main_window.py tests/test_recording_panel.py tests/test_rosbag_recorder.py
```

预期：全部 PASS。

- [ ] **步骤 8：提交任务 6**

```bash
git add qt_frontend/main_window.py tests/test_main_window.py
git commit -m "feat: 接入地面站 rosbag 录制入口"
```

### 任务 7：实现停止超时、窗口关闭收尾和输出忽略规则

**文件：**
- 修改：`qt_frontend/recording.py`
- 修改：`qt_frontend/main_window.py`
- 修改：`qt_frontend/panels/recording_panel.py`
- 修改：`tests/test_rosbag_recorder.py`
- 修改：`tests/test_main_window.py`
- 修改：`.gitignore`

- [ ] **步骤 1：编写停止超时和关闭行为失败测试**

`RosbagRecorder` 新增单次 `QTimer`，停止后默认 10 秒触发 `stop_timed_out` signal。测试注入 fake timer 或直接调用 `_on_stop_timeout()`：

```python
def test_stop_timeout_does_not_kill_process_automatically(recorder) -> None:
    recorder._on_stop_timeout()

    assert recorder.state == RecorderState.STOPPING
    assert recorder._process.kill_calls == 0
```

主窗口测试构造 active fake recorder，调用 `closeEvent`：用户选择 Cancel 时 ignore；选择“停止并退出”时首次 ignore 并调用 stop，完成信号到来后通过 `QTimer.singleShot(0, self.close)` 重新关闭。

- [ ] **步骤 2：运行测试确认超时和异步关闭逻辑缺失**

预期：FAIL，由缺少 `stop_timed_out` 或关闭协调属性触发。

- [ ] **步骤 3：实现停止超时但不自动 kill**

`RosbagRecorder.stop()` 启动 10 秒 single-shot timer；进程完成时停止 timer。超时只发 `stop_timed_out`，不改变 STOPPING、不调用 kill。面板收到后显示继续等待与强制终止操作。

`force_kill()` 调用 `QProcess.kill()` 并保留“bag 可能需要 reindex”的失败摘要；它只能由用户明确操作触发。

- [ ] **步骤 4：实现异步 `closeEvent` 协调**

在 `MainWindow` 增加：

```python
self._close_after_recording = False
self._close_cleanup_done = False
```

关闭顺序固定为：

1. 若录制 active 且不是已经等待关闭，弹出“停止并退出 / 取消”；
2. 停止并退出：设置 `_close_after_recording=True`、调用 stop、`event.ignore()`；
3. recorder 正常结束后安排 `self.close()`；
4. 第二次进入 closeEvent 时再执行现有 RViz 配置保存提示；
5. 最后断开 MQTT 并 accept。

如果录制停止超时，用户只能在录制页选择继续等待或强制终止；主窗口不能在事件循环中阻塞等待。已有 RViz 保存逻辑保持原顺序和行为，不得因新增录制检查重复弹出或跳过 Cancel。

- [ ] **步骤 5：添加输出忽略规则**

在 `.gitignore` 的 Data 区增加：

```gitignore
# ROS bag recordings
records/
*.bag
*.bag.active
```

- [ ] **步骤 6：补充关闭、超时和强杀测试**

覆盖：

- 正常 stop timer 在完成后取消；
- timeout 不 kill；
- 用户强杀才调用 kill；
- active recording 关闭窗口时先 ignore；
- 录制完成后自动再次 close；
- 用户取消关闭不停止录制；
- RViz dirty + active recording 两阶段提示顺序正确；
- 无活动录制时沿用现有 closeEvent 测试。

- [ ] **步骤 7：运行测试和 lint**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_main_window.py -v
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_recording_panel.py -v
python3 -m pytest tests/test_rosbag_recorder.py -v
ruff check qt_frontend/recording.py qt_frontend/panels/recording_panel.py qt_frontend/main_window.py tests/test_rosbag_recorder.py tests/test_recording_panel.py tests/test_main_window.py
git diff --check
```

预期：全部 PASS，diff check 无输出。

- [ ] **步骤 8：提交任务 7**

```bash
git add .gitignore qt_frontend/recording.py qt_frontend/panels/recording_panel.py qt_frontend/main_window.py tests/test_rosbag_recorder.py tests/test_recording_panel.py tests/test_main_window.py
git commit -m "fix: 完善 rosbag 停止与退出收尾"
```

### 任务 8：真实 ROS Noetic 录制验证与入口范围核对

**文件：**
- 创建：`tests/integration/test_rosbag_recording.py`
- 修改：`docs/superpowers/plans/2026-08-12-rosbag-recording.md`（只勾选执行结果和记录命令，不改设计）

- [ ] **步骤 1：添加显式启用的集成测试骨架**

测试文件顶部：

```python
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_ROS_INTEGRATION") != "1",
    reason="set RUN_ROS_INTEGRATION=1 in a sourced ROS Noetic environment",
)
```

fixture 使用临时 `ROS_HOME`、独立临时输出目录和测试 topic。不要自动启动或停止用户已有 roscore；若 `rostopic list` 失败则明确 skip，并提示先启动本地 roscore。

- [ ] **步骤 2：验证非分包 LZ4 实际文件命名与可读性**

在已 source `/opt/ros/noetic/setup.bash` 且 roscore 可用的终端：

```bash
RUN_ROS_INTEGRATION=1 python3 -m pytest \
  tests/integration/test_rosbag_recording.py::test_lz4_recording_creates_readable_bag -v
```

测试发布 `std_msgs/String` 到唯一 topic，使用 `RosbagRecorder` 录制，等待至少 3 条消息，SIGINT 停止，然后运行 `rosbag info --yaml <actual_file>`。断言：

- 不存在 `.active`；
- compression 为 `lz4`；
- 只有所选测试 topic；
- messages 至少 3；
- 实际文件名与 UI 预览规则一致。

- [ ] **步骤 3：验证 BZ2、不压缩和分包**

分别运行短测试：

- BZ2 bag 可由 `rosbag info` 读取；
- 不压缩命令不含任何 compression 参数且 bag 可读；
- duration 分包使用短时长，至少生成两个可读分包；
- 每个分包不存在 `.active`；
- latched 测试 topic 在新分包中存在，验证 `--repeat-latched`。

大小分包测试使用足够小的 `--size` 和较大消息，避免长时间运行。

- [ ] **步骤 4：运行完整自动化验证**

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/ -v
ruff check qt_frontend/recording.py qt_frontend/panels/recording_panel.py qt_frontend/main_window.py tests/test_rosbag_recorder.py tests/test_recording_panel.py tests/test_main_window.py tests/integration/test_rosbag_recording.py
```

预期：完整 pytest 无失败；未设置 `RUN_ROS_INTEGRATION=1` 时真实 ROS 测试显示 SKIPPED，而不是失败。

- [ ] **步骤 5：按环境能力验证真实地面站链路**

在不覆盖用户现有容器或运行态配置的前提下，使用已有链路：

```bash
./qt_frontend/scripts/start.sh
```

人工检查：

- 左栏 360 px 下名称、话题树、折叠参数和按钮无重叠；
- 推荐话题只包含在线机器人且当前存在的 Bridge 本地话题；
- `/tf`、`/tf_static` 不重复；
- 录制时 RViz 保持可操作，工具栏显示时长与大小；
- 停止后 bag 可由 `rosbag info` 读取；
- 多机器人或大点云链路未运行时，在交付说明中明确未验证风险。

- [ ] **步骤 6：核对备用入口和外部终止风险**

确认 `qt_frontend/scripts/start.sh` 仍以 `qt_frontend/main.py` 为唯一生产入口。`panels_setup.py` 只导入新面板类型，不装配 recorder；在计划执行结果中记录该备用入口未提供录制功能。

当前 `qt_frontend/scripts/stop.sh` 通过外部信号停止前端，Python `closeEvent` 不保证在 SIGTERM 下运行。本期不扩大到 Unix signal 桥接；交付说明必须记录：录制中应先使用界面“停止并保存”，再运行 stop 脚本。若后续要求 stop 脚本也安全收尾，应另行设计 Python signal 到 Qt close 的桥接。

- [ ] **步骤 7：最终状态和提交范围检查**

```bash
git status --short --branch
git diff --check
git log -8 --oneline
```

确认没有暂存 `.agents/`、`.codex/`、`.claude/skills/`、bag 文件或用户已有 `qt_frontend/config/command_buttons.yaml` 改动。

- [ ] **步骤 8：提交集成验证文件**

```bash
git add tests/integration/test_rosbag_recording.py
git commit -m "test: 添加 rosbag 真实录制验证"
```

环境不允许运行真实 ROS 测试时，提交默认跳过的测试文件；最终回复必须列出未运行原因和剩余风险，不能声称真实 rosbag 链路通过。

## 新对话干跑审查

1. 任务 1 定义后续全部任务使用的 `RecordingConfig`、枚举、校验、参数和输出匹配，不依赖 Qt 界面或 ROS 环境。
2. 任务 2 只依赖任务 1 的模块，明确 Bridge 话题命名和公共 TF 例外；它完成后话题模型可独立测试。
3. 任务 3 在任务 1 的配置模型上建立 `RosbagRecorder`，假 `QProcess`、fake signal、`kill_fn` 和 `clock_fn` 都在本任务测试中定义，不依赖 roscore。
4. 任务 4 依赖任务 1、2 的稳定数据模型；测试注入 `FakeSettings`，不会因用户环境或配置目录提前失败。
5. 任务 5 只扩展任务 4 已存在的面板和任务 3 已存在的状态枚举，所有方法名在任务中给出一致签名。
6. 任务 6 才接触 `MainWindow`，前序已经提供面板和服务；测试通过构造器注入 fake recorder，避免 import 或真实进程造成错误失败。
7. 任务 7 依赖任务 3 的 stop 状态与任务 6 的主窗口接线，明确异步 close 的两次事件顺序，且保留现有 RViz 保存提示。
8. 任务 8 是唯一需要真实 ROS Noetic 的阶段；默认测试通过显式 skip 与普通 pytest 隔离，不会因 roscore、网络、`~/.ros` 权限或 ROS setup 缺失提前失败。
9. 本地 Qt 5.15 头文件确认 `QProcess.processId()` 可用；本地 ROS Noetic `rosbag_main.py` 确认 Python 入口会把 SIGINT 转发给 recorder 子进程，计划因此禁止使用 `terminate()` 代替 SIGINT。
10. 生产入口是 `qt_frontend/main.py`；备用 `panels_setup.py`、外部 SIGTERM 和 stop 脚本的未覆盖范围在任务 8 明确记录，没有用模糊占位语句隐藏风险。
