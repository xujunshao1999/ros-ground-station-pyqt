# RViz 机器人视角切换实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 在机器人列表中选中机器人时，可以让 RViz fixed frame 跟随切换到该机器人的局部 frame；同时提供一键回到 `global_map` 的全局视角入口，并让用户始终知道当前 RViz 视角。

**架构：** 新增一个不依赖 Qt 和 ROS 的 frame 策略模块，集中处理 `global_map`、`{robot_id}/base_link` 和机器人级覆盖配置。`RobotListPanel` 只负责显示和发出用户意图，`MainWindow` 负责把机器人选择、全局视角按钮和 RViz C++ 接口连接起来。C++ RViz 胶水层补充一个 frame 可解析性检查函数，Python 层用它给出状态提示，但不让检查结果阻止用户切换到一个等待 TF 到达的 frame；Python 层必须兼容尚未重新构建、暂不包含该 C++ 符号的旧 `librviz_widget.so`。

**技术栈：** Python 3.8、PyQt5、pytest、ctypes、RViz C++ 胶水库、ROS Noetic TF/RViz fixed frame。

---

## 术语与执行约定

- `fixed frame`：RViz 的全局参考坐标系。所有 Display 都会尝试把自己的数据转换到这个 frame 下显示。例如 `global_map` 适合看多机器人全局位置，`husky_001/base_link` 适合贴近观察 `husky_001` 周围传感器。
- `global_map`：地面站侧用于多机器人统一显示的全局 fixed frame。Bridge 会通过 `fleet_frames` 发布 `global_map -> <robot_id>/map` 这类静态 TF，让 RViz 可以把各机器人局部地图挂到同一个全局树下。
- `机器人局部 frame`：以机器人 ID 为命名空间的局部坐标系，例如 `husky_001/base_link`、`turtlebot_001/base_link`。本计划第一版默认使用 `{robot_id}/base_link`，同时支持在配置中给单台机器人覆盖。
- `跟随选中机器人`：机器人列表中的开关。开启时，用户选中 `husky_001` 会触发 RViz fixed frame 切换到 `husky_001/base_link`；关闭时，选中机器人只影响命令面板目标，不改变 RViz 视角。
- `全局视角`：机器人面板中的按钮。点击后 RViz fixed frame 切换到配置中的全局 frame，默认是 `global_map`。
- `frame 可解析性检查`：C++ 层用 RViz `FrameManager` 查询“目标 frame 到当前 fixed frame”当前是否能完成 TF 变换。它不是完整的 frame 存在性校验，也不订阅新的 TF 数据；检查失败时 Python 层显示“已切换但 TF 暂不可解析”的状态提示，因为 RViz 在后续 TF 到达后可以自动恢复显示。
- `当前视角`：机器人面板显示的用户可见状态，例如 `当前视角: global_map` 或 `当前视角: husky_001/base_link`。它表示前端最后一次请求 RViz 设置的 fixed frame，不等同于 TF 一定已经可解析。

执行约定：

- 第一版不增加 ROS topic 订阅，不在 Python 层主动读取 `/tf`，避免给前端引入新的 ROS 线程和运行时依赖。
- 点击机器人列表继续保留现有语义：选中机器人会传给命令面板作为控制目标。RViz 跟随是这个选择事件的可关闭副作用。
- 当前用户入口是 `qt_frontend/main.py` 创建的 `qt_frontend.main_window.MainWindow`，本计划优先覆盖这个入口。`qt_frontend/panels_setup.py` 是备用 C++ 嵌入入口，本计划不接入其 RViz frame 切换；执行本计划后，该备用入口仍会使用 `map` 且不会响应新增视角控件。如果测试、演示或发布流程会通过 `qt_frontend/native/rviz_app.cpp` 调用 `panels_setup.py`，必须先扩展本计划，把备用入口的 `RvizPanelWrapper.set_fixed_frame()` 和新增信号接入同一套策略函数。
- 机器人 fixed frame 的默认规则是 `{robot_id}/base_link`。如果 `qt_frontend/config/config.yaml` 中存在 `rviz.robot_fixed_frames.<robot_id>`，优先使用覆盖值。
- frame 字符串统一去掉首尾空白和开头 `/`。RViz/TF frame ID 使用 `husky_001/base_link`，不使用 `/husky_001/base_link`。
- `global_frame` 默认为 `global_map`。保留现有 `rviz.fixed_frame` 字段作为启动 fixed frame 的兼容字段，并把仓库默认值从 `map` 调整为 `global_map`。
- 所有新增 Python 文件首个 import 必须是 `from __future__ import annotations`；新增或修改代码中的非显而易见逻辑要有中文注释。

## 文件职责

- 创建：`qt_frontend/rviz_frame_policy.py`
  - 提供纯函数：读取 RViz frame 配置、规范化 frame ID、推导全局 fixed frame、推导某台机器人 fixed frame、读取“跟随选中机器人”的默认值。
  - 不导入 PyQt5、ROS、ctypes，保证可用普通 pytest 单测覆盖。

- 修改：`qt_frontend/panels/robot_list_panel.py`
  - 在“发现机器人”按钮旁新增“全局视角”按钮。
  - 在同一行新增“跟随选中”复选框。
  - 在详情区域显示当前 RViz 视角。
  - 新增信号 `global_frame_requested` 和 `follow_frame_changed`。

- 修改：`qt_frontend/main_window.py`
  - 连接机器人列表新增信号。
  - 将机器人选择事件转为 RViz fixed frame 切换。
  - 封装 `_set_rviz_fixed_frame()`，集中处理 RViz 未初始化、frame 为空、frame 暂不可解析、状态栏提示和面板显示同步。
  - 初始化 ctypes 时注册新的 C++ `can_resolve_frame` 函数签名。

- 修改：`qt_frontend/native/rviz_widget.h`
  - 声明 `can_resolve_frame(void* widget_ptr, const char* frame)`。

- 修改：`qt_frontend/native/rviz_widget.cpp`
  - 实现 `can_resolve_frame()`，使用 RViz `FrameManager` 判断目标 frame 当前是否能转换到 RViz fixed frame。
  - 保留现有 `set_fixed_frame()` 行为，不改变 RViz Display 加载逻辑。

- 修改：`qt_frontend/config/config.yaml`
  - 将默认 RViz fixed frame 调整为 `global_map`。
  - 增加 `global_frame`、`robot_frame_template`、`follow_selected_robot_frame`、`robot_fixed_frames` 示例配置。

- 创建：`tests/test_rviz_frame_policy.py`
  - 覆盖 frame 策略纯函数。

- 修改：`tests/test_panels.py`
  - 覆盖机器人面板新增控件、信号和当前视角显示。

- 修改：`tests/test_main_window.py`
  - 覆盖 MainWindow 中机器人选择、跟随开关、全局按钮、真实信号接线、RViz 未初始化后延迟应用 pending frame，以及 frame 暂不可解析的行为。

- 修改：`tests/test_rviz_config_loading.py`
  - 用静态测试覆盖 C++ 头文件、实现文件和 ctypes 签名。
  - 覆盖前端默认配置使用 `global_map`。

## 任务 1：新增 RViz frame 策略纯函数

**文件：**
- 创建：`qt_frontend/rviz_frame_policy.py`
- 创建：`tests/test_rviz_frame_policy.py`

- [x] **步骤 1：编写失败测试**

创建 `tests/test_rviz_frame_policy.py`：

```python
from __future__ import annotations

from qt_frontend.rviz_frame_policy import (
    follow_selected_robot_default,
    global_fixed_frame_for,
    normalize_frame_id,
    robot_fixed_frame_for,
)


def test_normalize_frame_id_strips_space_and_leading_slash() -> None:
    assert normalize_frame_id(" /husky_001/base_link ") == "husky_001/base_link"


def test_global_fixed_frame_defaults_to_global_map() -> None:
    assert global_fixed_frame_for({}) == "global_map"


def test_global_fixed_frame_prefers_explicit_global_frame() -> None:
    config = {"rviz": {"fixed_frame": "map", "global_frame": "global_map"}}

    assert global_fixed_frame_for(config) == "global_map"


def test_robot_fixed_frame_uses_default_template() -> None:
    assert robot_fixed_frame_for("husky_001", {}) == "husky_001/base_link"


def test_robot_fixed_frame_uses_robot_override() -> None:
    config = {
        "rviz": {
            "robot_frame_template": "{robot_id}/base_link",
            "robot_fixed_frames": {
                "husky_001": "husky_001/base_footprint",
            },
        }
    }

    assert robot_fixed_frame_for("husky_001", config) == "husky_001/base_footprint"
    assert robot_fixed_frame_for("turtlebot_001", config) == "turtlebot_001/base_link"


def test_robot_fixed_frame_falls_back_when_template_is_invalid() -> None:
    config = {"rviz": {"robot_frame_template": "base_link"}}

    assert robot_fixed_frame_for("husky_001", config) == "husky_001/base_link"


def test_robot_fixed_frame_falls_back_when_template_has_unknown_field() -> None:
    config = {"rviz": {"robot_frame_template": "{robot_id}/{bad_field}"}}

    assert robot_fixed_frame_for("husky_001", config) == "husky_001/base_link"


def test_follow_selected_robot_defaults_to_enabled() -> None:
    assert follow_selected_robot_default({}) is True
    assert follow_selected_robot_default(
        {"rviz": {"follow_selected_robot_frame": False}}
    ) is False
```

- [x] **步骤 2：运行测试验证失败**

```bash
python3 -m pytest tests/test_rviz_frame_policy.py -v
```

预期：失败，提示 `ModuleNotFoundError: No module named 'qt_frontend.rviz_frame_policy'`。

- [x] **步骤 3：实现最少策略模块**

创建 `qt_frontend/rviz_frame_policy.py`：

```python
from __future__ import annotations

from typing import Any, Dict


DEFAULT_GLOBAL_FRAME = "global_map"
DEFAULT_ROBOT_FRAME_TEMPLATE = "{robot_id}/base_link"


def _rviz_config(config: Dict[str, Any]) -> Dict[str, Any]:
    raw = config.get("rviz", {})
    if isinstance(raw, dict):
        return raw
    return {}


def normalize_frame_id(frame: str) -> str:
    # TF frame ID 不使用开头斜杠，避免 RViz/TF2 对同一 frame 出现两种写法。
    return frame.strip().lstrip("/")


def global_fixed_frame_for(config: Dict[str, Any]) -> str:
    rviz_cfg = _rviz_config(config)
    frame = rviz_cfg.get("global_frame") or rviz_cfg.get("fixed_frame")
    if isinstance(frame, str) and frame.strip():
        return normalize_frame_id(frame)
    return DEFAULT_GLOBAL_FRAME


def follow_selected_robot_default(config: Dict[str, Any]) -> bool:
    rviz_cfg = _rviz_config(config)
    value = rviz_cfg.get("follow_selected_robot_frame", True)
    return bool(value)


def robot_fixed_frame_for(robot_id: str, config: Dict[str, Any]) -> str:
    clean_robot_id = robot_id.strip()
    if not clean_robot_id:
        return ""

    rviz_cfg = _rviz_config(config)
    robot_frames = rviz_cfg.get("robot_fixed_frames", {})
    if isinstance(robot_frames, dict):
        override = robot_frames.get(clean_robot_id)
        if isinstance(override, str) and override.strip():
            return normalize_frame_id(override)

    template = rviz_cfg.get("robot_frame_template", DEFAULT_ROBOT_FRAME_TEMPLATE)
    if not isinstance(template, str) or "{robot_id}" not in template:
        template = DEFAULT_ROBOT_FRAME_TEMPLATE

    try:
        formatted = template.format(robot_id=clean_robot_id)
    except (KeyError, IndexError, ValueError):
        # 配置模板只能引用 robot_id；误写其他占位符时回退到稳定默认值。
        formatted = DEFAULT_ROBOT_FRAME_TEMPLATE.format(robot_id=clean_robot_id)
    return normalize_frame_id(formatted)
```

- [x] **步骤 4：运行测试验证通过**

```bash
python3 -m pytest tests/test_rviz_frame_policy.py -v
```

预期：8 个测试通过。

- [x] **步骤 5：Commit**

```bash
git add qt_frontend/rviz_frame_policy.py tests/test_rviz_frame_policy.py
git commit -m "feat: 增加RViz视角frame策略"
```

## 任务 2：扩展机器人列表面板的视角控件

**文件：**
- 修改：`qt_frontend/panels/robot_list_panel.py`
- 修改：`tests/test_panels.py`

- [x] **步骤 1：编写失败测试**

在 `tests/test_panels.py` 的 import 中增加：

```python
from PyQt5.QtWidgets import QApplication, QCheckBox, QHeaderView, QLabel
```

在 `TestRobotListSubscriptions` 后新增测试类：

```python
class TestRobotListFrameControls:
    def test_global_frame_button_emits_request(self, qt_app):
        panel = RobotListPanel()
        emitted = []
        panel.global_frame_requested.connect(lambda: emitted.append(True))

        panel._btn_global_frame.click()

        assert emitted == [True]

    def test_follow_frame_checkbox_emits_state(self, qt_app):
        panel = RobotListPanel()
        emitted = []
        panel.follow_frame_changed.connect(lambda enabled: emitted.append(enabled))

        panel.set_follow_selected_robot_enabled(False)

        assert emitted == [False]
        assert panel.follow_selected_robot_enabled() is False
        assert isinstance(panel._chk_follow_frame, QCheckBox)

    def test_current_fixed_frame_label_updates(self, qt_app):
        panel = RobotListPanel()

        panel.set_current_fixed_frame("husky_001/base_link")

        assert panel._lb_current_frame.text() == "当前视角: husky_001/base_link"
```

- [x] **步骤 2：运行测试验证失败**

```bash
python3 -m pytest tests/test_panels.py::TestRobotListFrameControls -v
```

预期：失败，提示 `RobotListPanel` 没有 `global_frame_requested` 或相关属性。

- [x] **步骤 3：修改面板 import 和信号**

在 `qt_frontend/panels/robot_list_panel.py` 的 Widgets import 中加入 `QCheckBox`，并在 `RobotListPanel` 信号区增加：

```python
    global_frame_requested = pyqtSignal()
    follow_frame_changed = pyqtSignal(bool)
```

- [x] **步骤 4：替换按钮行 UI**

将 `__init__()` 中“发现按钮”区域替换为：

```python
        # 视角控制和发现操作放在同一行，减少用户在机器人面板内寻找入口的成本。
        btn_row = QHBoxLayout()
        btn_discover = QPushButton("发现机器人")
        btn_discover.clicked.connect(self.discover_requested.emit)
        btn_row.addWidget(btn_discover)

        self._btn_global_frame = QPushButton("全局视角")
        self._btn_global_frame.clicked.connect(self.global_frame_requested.emit)
        btn_row.addWidget(self._btn_global_frame)

        self._chk_follow_frame = QCheckBox("跟随选中")
        self._chk_follow_frame.setChecked(True)
        self._chk_follow_frame.toggled.connect(self.follow_frame_changed.emit)
        btn_row.addWidget(self._chk_follow_frame)
        btn_row.addStretch()
        layout.addLayout(btn_row)
```

- [x] **步骤 5：在详情区域显示当前视角**

在 `detail_layout.addWidget(self._lb_velocity)` 后加入：

```python
        self._lb_current_frame = QLabel("当前视角: --")
        detail_layout.addWidget(self._lb_current_frame)
```

- [x] **步骤 6：新增面板公共接口**

在 `get_online_robots()` 后加入：

```python
    def follow_selected_robot_enabled(self) -> bool:
        return self._chk_follow_frame.isChecked()

    def set_follow_selected_robot_enabled(self, enabled: bool) -> None:
        self._chk_follow_frame.setChecked(enabled)

    def set_current_fixed_frame(self, frame: str) -> None:
        text = frame.strip() if frame.strip() else "--"
        self._lb_current_frame.setText("当前视角: %s" % text)
```

- [x] **步骤 7：运行测试验证通过**

```bash
python3 -m pytest tests/test_panels.py::TestRobotListFrameControls -v
```

预期：3 个测试通过。

- [x] **步骤 8：Commit**

```bash
git add qt_frontend/panels/robot_list_panel.py tests/test_panels.py
git commit -m "feat: 增加机器人视角切换控件"
```

## 任务 3：在主窗口接入 RViz fixed frame 切换

**文件：**
- 修改：`qt_frontend/main_window.py`
- 修改：`tests/test_main_window.py`

- [x] **步骤 1：编写失败测试**

在 `tests/test_main_window.py` 中新增测试类：

```python
class TestMainWindowRvizFrameSwitch:
    def _window_with_fake_rviz(self, qt_app, monkeypatch, config=None):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)
        window = MainWindow(config or {})

        class FakeRvizLib:
            def __init__(self):
                self.frames = []
                self.resolvable = True

            def can_resolve_frame(self, ptr, frame):
                return 1 if self.resolvable else 0

            def set_fixed_frame(self, ptr, frame):
                self.frames.append(frame.decode("utf-8"))

        fake = FakeRvizLib()
        window._rviz_lib = fake
        window._rviz_ptr = 123
        return window, fake

    def test_robot_selection_switches_rviz_frame_when_follow_enabled(
        self,
        qt_app,
        monkeypatch,
    ):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)

        window._on_robot_selected_for_rviz("husky_001")

        assert fake.frames == ["husky_001/base_link"]
        assert window._current_fixed_frame == "husky_001/base_link"
        assert window._robot_list._lb_current_frame.text() == (
            "当前视角: husky_001/base_link"
        )

    def test_robot_selection_does_not_switch_when_follow_disabled(
        self,
        qt_app,
        monkeypatch,
    ):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)
        window._robot_list.set_follow_selected_robot_enabled(False)

        window._on_robot_selected_for_rviz("husky_001")

        assert fake.frames == []

    def test_switch_to_global_frame_sets_global_map(self, qt_app, monkeypatch):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)

        window._switch_to_global_frame()

        assert fake.frames == ["global_map"]
        assert window._current_fixed_frame == "global_map"

    def test_robot_list_frame_signals_are_connected(self, qt_app, monkeypatch):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)
        window._robot_list.on_status_received("husky_001", {"battery": 90.0})
        item = window._robot_list._tree.topLevelItem(0)
        item.setSelected(True)
        fake.frames = []

        window._robot_list.global_frame_requested.emit()
        window._robot_list.robot_selected.emit("husky_001")
        window._robot_list.set_follow_selected_robot_enabled(False)
        window._robot_list.set_follow_selected_robot_enabled(True)

        assert fake.frames == [
            "global_map",
            "husky_001/base_link",
            "husky_001/base_link",
        ]

    def test_rviz_init_applies_pending_fixed_frame_after_dock_host_setup(self):
        import inspect

        source = inspect.getsource(MainWindow._init_rviz)
        apply_call = 'self._set_rviz_fixed_frame(requested_frame, "初始视角")'
        dock_host_call = (
            "lib.set_dock_host(rviz_ptr, ctypes.c_void_p(image_dock_host_ptr))"
        )

        assert "requested_frame = (" in source
        assert (
            "self._pending_fixed_frame or global_fixed_frame_for(self._config)"
            in source
        )
        assert dock_host_call in source
        assert apply_call in source
        assert source.index(dock_host_call) < source.index(apply_call)

    def test_missing_resolve_checker_still_switches_frame(self, qt_app, monkeypatch):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)
        window = MainWindow({})

        class FakeRvizLibWithoutChecker:
            def __init__(self):
                self.frames = []

            def set_fixed_frame(self, ptr, frame):
                self.frames.append(frame.decode("utf-8"))

        fake = FakeRvizLibWithoutChecker()
        window._rviz_lib = fake
        window._rviz_ptr = 123

        ok = window._set_rviz_fixed_frame("global_map", "全局视角")

        assert ok is True
        assert fake.frames == ["global_map"]
        assert window._current_fixed_frame == "global_map"

    def test_missing_rviz_defers_requested_frame(self, qt_app, monkeypatch):
        monkeypatch.setattr(QTimer, "singleShot", lambda *args, **kwargs: None)
        monkeypatch.setattr(MainWindow, "_check_ros", lambda self: None)
        window = MainWindow({})

        ok = window._set_rviz_fixed_frame("global_map", "全局视角")

        assert ok is False
        assert window._pending_fixed_frame == "global_map"
        assert window._robot_list._lb_current_frame.text() == "当前视角: global_map"

    def test_unresolved_frame_still_switches_and_reports_status(
        self,
        qt_app,
        monkeypatch,
    ):
        window, fake = self._window_with_fake_rviz(qt_app, monkeypatch)
        fake.resolvable = False
        messages = []
        monkeypatch.setattr(
            window.statusBar(),
            "showMessage",
            lambda text, timeout=0: messages.append(text),
        )

        ok = window._set_rviz_fixed_frame("husky_001/base_link", "机器人视角")

        assert ok is True
        assert fake.frames == ["husky_001/base_link"]
        assert any("TF 暂不可解析" in text for text in messages)
```

- [x] **步骤 2：运行测试验证失败**

```bash
python3 -m pytest tests/test_main_window.py::TestMainWindowRvizFrameSwitch -v
```

预期：失败，提示 `MainWindow` 没有 `_on_robot_selected_for_rviz`、`_set_rviz_fixed_frame`，或 `_init_rviz()` 尚未应用 pending frame。

- [x] **步骤 3：导入 frame 策略函数**

在 `qt_frontend/main_window.py` import 区加入：

```python
from qt_frontend.rviz_frame_policy import (
    follow_selected_robot_default,
    global_fixed_frame_for,
    normalize_frame_id,
    robot_fixed_frame_for,
)
```

- [x] **步骤 4：初始化 RViz frame 状态字段**

在 `MainWindow.__init__()` 中 `_ros_check_inflight = False` 后加入：

```python
        self._current_fixed_frame = ""
        self._pending_fixed_frame: Optional[str] = None
```

- [x] **步骤 5：连接机器人列表信号**

在 `_init_panels()` 中现有机器人选择连接后加入：

```python
        self._robot_list.robot_selected.connect(self._on_robot_selected_for_rviz)
        self._robot_list.global_frame_requested.connect(self._switch_to_global_frame)
        self._robot_list.follow_frame_changed.connect(self._on_follow_frame_changed)
        self._robot_list.set_follow_selected_robot_enabled(
            follow_selected_robot_default(self._config)
        )
        self._robot_list.set_current_fixed_frame(global_fixed_frame_for(self._config))
```

- [x] **步骤 6：新增 RViz frame 切换方法**

在 `# RViz` 分节前加入：

```python
    def _on_robot_selected_for_rviz(self, robot_id: str) -> None:
        if not self._robot_list.follow_selected_robot_enabled():
            return
        frame = robot_fixed_frame_for(robot_id, self._config)
        self._set_rviz_fixed_frame(frame, "机器人视角")

    def _on_follow_frame_changed(self, enabled: bool) -> None:
        if not enabled:
            return
        robot_id = self._robot_list.selected_robot()
        if robot_id:
            self._on_robot_selected_for_rviz(robot_id)

    def _switch_to_global_frame(self) -> None:
        self._set_rviz_fixed_frame(global_fixed_frame_for(self._config), "全局视角")

    def _rviz_frame_is_resolvable(self, frame: str) -> bool:
        if not self._rviz_lib or not self._rviz_ptr:
            return False
        checker = getattr(self._rviz_lib, "can_resolve_frame", None)
        if checker is None:
            return True
        return bool(checker(self._rviz_ptr, frame.encode("utf-8")))

    def _set_rviz_fixed_frame(self, frame: str, source: str) -> bool:
        clean_frame = normalize_frame_id(frame)
        if not clean_frame:
            self.statusBar().showMessage("RViz 视角切换失败：frame 为空", 4000)
            return False

        # RViz 初始化前记录用户意图，初始化完成后再补一次 set_fixed_frame。
        self._robot_list.set_current_fixed_frame(clean_frame)
        if not self._rviz_lib or not self._rviz_ptr:
            self._pending_fixed_frame = clean_frame
            self.statusBar().showMessage(
                "RViz 未就绪，已记录%s：%s" % (source, clean_frame),
                4000,
            )
            return False

        resolvable = self._rviz_frame_is_resolvable(clean_frame)
        self._rviz_lib.set_fixed_frame(self._rviz_ptr, clean_frame.encode("utf-8"))
        self._current_fixed_frame = clean_frame
        self._pending_fixed_frame = None

        if resolvable:
            self.statusBar().showMessage(
                "已切换 RViz %s：%s" % (source, clean_frame),
                3000,
            )
        else:
            self.statusBar().showMessage(
                "已切换 RViz %s：%s，TF 暂不可解析" % (source, clean_frame),
                5000,
            )
        return True
```

- [x] **步骤 7：RViz 初始化后应用配置和待处理 frame**

在 `_init_rviz()` 注册 ctypes 函数签名区域中，`lib.set_fixed_frame.restype = None` 后加入。这里必须用 `try/except AttributeError`，因为任务 3 可能先于任务 4 提交；旧的 `librviz_widget.so` 尚未包含 `can_resolve_frame` 符号时，前端仍应能启动，只是暂时跳过可解析性检查：

```python
            try:
                lib.can_resolve_frame.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
                lib.can_resolve_frame.restype = ctypes.c_int
            except AttributeError:
                logger.warning(
                    "librviz_widget.so does not expose can_resolve_frame; "
                    "RViz frame resolution checks are disabled"
                )
```

在 `_init_rviz()` 成功设置 dock host 后加入：

```python
        requested_frame = (
            self._pending_fixed_frame or global_fixed_frame_for(self._config)
        )
        self._set_rviz_fixed_frame(requested_frame, "初始视角")
```

- [x] **步骤 8：运行测试验证通过**

```bash
python3 -m pytest tests/test_main_window.py::TestMainWindowRvizFrameSwitch -v
```

预期：8 个测试通过。

- [x] **步骤 9：Commit**

```bash
git add qt_frontend/main_window.py tests/test_main_window.py
git commit -m "feat: 接入RViz fixed frame切换"
```

## 任务 4：补充 C++ frame 可解析性检查

**文件：**
- 修改：`qt_frontend/native/rviz_widget.h`
- 修改：`qt_frontend/native/rviz_widget.cpp`
- 修改：`tests/test_rviz_config_loading.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_rviz_config_loading.py` 中增加：

```python
def test_rviz_native_exposes_can_resolve_frame() -> None:
    header = _read_repo_file("qt_frontend/native/rviz_widget.h")
    source = _read_repo_file("qt_frontend/native/rviz_widget.cpp")

    assert "int can_resolve_frame(void* widget_ptr, const char* frame);" in header
    assert "int can_resolve_frame(void* widget_ptr, const char* frame)" in source
    assert "getFrameManager()" in source
    assert "getTransform(" in source


def test_main_window_registers_can_resolve_frame_ctypes_signature() -> None:
    source = _read_repo_file("qt_frontend/main_window.py")

    assert "lib.can_resolve_frame.argtypes" in source
    assert "lib.can_resolve_frame.restype = ctypes.c_int" in source
    assert "except AttributeError" in source
```

- [ ] **步骤 2：运行测试验证失败**

```bash
python3 -m pytest tests/test_rviz_config_loading.py::test_rviz_native_exposes_can_resolve_frame tests/test_rviz_config_loading.py::test_main_window_registers_can_resolve_frame_ctypes_signature -v
```

预期：`test_rviz_native_exposes_can_resolve_frame` 失败，提示 C++ 声明或实现缺失；`test_main_window_registers_can_resolve_frame_ctypes_signature` 在任务 3 已完成后应通过。

- [ ] **步骤 3：修改头文件声明**

在 `qt_frontend/native/rviz_widget.h` 中加入：

```cpp
int can_resolve_frame(void* widget_ptr, const char* frame);
```

- [ ] **步骤 4：修改 C++ include**

在 `qt_frontend/native/rviz_widget.cpp` 的 RViz include 区加入：

```cpp
#include <rviz/frame_manager.h>
#include <OGRE/OgreQuaternion.h>
#include <OGRE/OgreVector3.h>
```

- [ ] **步骤 5：实现 `can_resolve_frame()`**

在 `set_fixed_frame()` 后加入：

```cpp
int can_resolve_frame(void* widget_ptr, const char* frame) {
    if (!widget_ptr || !frame) return 0;
    auto it = g_instances.find(widget_ptr);
    if (it == g_instances.end()) return 0;

    RvizInstance* instance = it->second;
    if (!instance->manager || !instance->manager->getFrameManager()) return 0;

    Ogre::Vector3 position;
    Ogre::Quaternion orientation;
    // 只做当前 TF tree 的可解析性探测；Python 层仍会允许切换，等待后续 TF 到达。
    return instance->manager->getFrameManager()->getTransform(
        QString::fromUtf8(frame).toStdString(),
        ros::Time(0),
        position,
        orientation) ? 1 : 0;
}
```

- [ ] **步骤 6：运行静态测试验证通过**

```bash
python3 -m pytest tests/test_rviz_config_loading.py::test_rviz_native_exposes_can_resolve_frame tests/test_rviz_config_loading.py::test_main_window_registers_can_resolve_frame_ctypes_signature -v
```

预期：2 个测试通过。

- [ ] **步骤 7：构建原生 RViz 胶水库**

```bash
cd qt_frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc)
```

预期：`librviz_widget.so` 构建成功。如果编译器提示 `getTransform()` 参数类型不匹配，将 frame 参数改为当前 ROS Noetic RViz 头文件要求的字符串类型，并保持函数名、返回值和 Python ctypes 签名不变。

- [ ] **步骤 8：Commit**

```bash
git add qt_frontend/native/rviz_widget.h qt_frontend/native/rviz_widget.cpp tests/test_rviz_config_loading.py
git commit -m "feat: 增加RViz frame可解析性检查"
```

## 任务 5：更新默认配置和完整验证

**文件：**
- 修改：`qt_frontend/config/config.yaml`
- 修改：`tests/test_rviz_config_loading.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_rviz_config_loading.py` 中增加：

```python
def test_frontend_config_declares_rviz_frame_switching_defaults() -> None:
    import yaml

    config = yaml.safe_load(
        _read_repo_file("qt_frontend/config/config.yaml")
    )
    rviz = config["rviz"]

    assert rviz["fixed_frame"] == "global_map"
    assert rviz["global_frame"] == "global_map"
    assert rviz["robot_frame_template"] == "{robot_id}/base_link"
    assert rviz["follow_selected_robot_frame"] is True
    assert rviz["robot_fixed_frames"]["husky_001"] == "husky_001/base_link"
```

- [ ] **步骤 2：运行测试验证失败**

```bash
python3 -m pytest tests/test_rviz_config_loading.py::test_frontend_config_declares_rviz_frame_switching_defaults -v
```

预期：失败，提示配置字段缺失或 `fixed_frame` 仍为 `map`。

- [ ] **步骤 3：更新默认配置**

将 `qt_frontend/config/config.yaml` 的 `rviz` 段调整为：

```yaml
rviz:
  default_config: "config/default.rviz"
  fixed_frame: "global_map"
  global_frame: "global_map"
  robot_frame_template: "{robot_id}/base_link"
  follow_selected_robot_frame: true
  robot_fixed_frames:
    husky_001: "husky_001/base_link"
```

- [ ] **步骤 4：运行配置测试验证通过**

```bash
python3 -m pytest tests/test_rviz_config_loading.py::test_frontend_config_declares_rviz_frame_switching_defaults -v
```

预期：测试通过。

- [ ] **步骤 5：运行相关 Python 测试**

```bash
python3 -m pytest tests/test_rviz_frame_policy.py tests/test_panels.py::TestRobotListFrameControls tests/test_main_window.py::TestMainWindowRvizFrameSwitch tests/test_rviz_config_loading.py -v
```

预期：所有相关测试通过。

- [ ] **步骤 6：运行 lint**

```bash
ruff check qt_frontend/rviz_frame_policy.py qt_frontend/panels/robot_list_panel.py qt_frontend/main_window.py tests/test_rviz_frame_policy.py tests/test_panels.py tests/test_main_window.py tests/test_rviz_config_loading.py
```

预期：无 lint 错误。

- [ ] **步骤 7：构建原生库**

```bash
cd qt_frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc)
```

预期：`qt_frontend/native/build/librviz_widget.so` 更新成功。

- [ ] **步骤 8：运行态验证全局和机器人视角**

启动地面站链路：

```bash
./qt_frontend/scripts/start.sh
```

在另一个终端验证 TF：

```bash
timeout 6 rosrun tf tf_echo global_map husky_001/base_link
```

预期：

- 命令能输出 `global_map` 到 `husky_001/base_link` 的 transform；如果当前环境没有 Husky TF，命令会提示无法解析，此时 UI 应显示“TF 暂不可解析”提示。
- 打开 Qt 前端后，机器人面板显示 `当前视角: global_map`。
- 点击 `husky_001` 后，若“跟随选中”开启，当前视角显示 `husky_001/base_link`。
- 点击“全局视角”后，当前视角显示 `global_map`。
- 关闭“跟随选中”后再点击机器人，命令面板目标机器人仍会变化，但当前视角不跟随变化。

- [ ] **步骤 9：Commit**

```bash
git add qt_frontend/config/config.yaml tests/test_rviz_config_loading.py
git commit -m "feat: 配置RViz视角切换默认值"
```

## 总体验证命令

完成全部任务后运行：

```bash
python3 -m pytest tests/test_rviz_frame_policy.py tests/test_panels.py tests/test_main_window.py tests/test_rviz_config_loading.py -v
ruff check qt_frontend/rviz_frame_policy.py qt_frontend/panels/robot_list_panel.py qt_frontend/main_window.py tests/test_rviz_frame_policy.py tests/test_panels.py tests/test_main_window.py tests/test_rviz_config_loading.py
cd qt_frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc)
```

涉及 ROS、RViz、TF 的运行态验证必须记录：

- 使用的机器人 ID，例如 `husky_001`。
- 点击机器人前后的当前视角标签文本。
- RViz Display 是否仍能响应鼠标交互。
- `global_map` 与机器人 frame 不可解析时 UI 是否给出状态栏提示。

## 自检

- 本计划不依赖此前聊天记录即可理解目标、frame 命名、配置字段和执行顺序。
- 新增术语覆盖了 `fixed frame`、`global_map`、机器人局部 frame、跟随选中、全局视角和 frame 可解析性检查。
- 每个关键行为都有对应测试：策略推导、模板误写回退、面板信号、主窗口真实信号接线、RViz pending frame 初始化后应用、C++ 符号暴露、配置默认值和运行态 RViz/TF 验证。
- 第一版不读取 ROS master、不新增 TF 订阅、不改 Bridge frame 发布逻辑，范围集中在前端视角切换。
- 计划没有使用未定义的函数名或类型；所有新增 Python 接口都在对应任务中定义。
