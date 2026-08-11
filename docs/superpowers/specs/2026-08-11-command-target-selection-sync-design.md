# 机器人选择与控制目标同步设计

## 目标

修复机器人列表与命令面板“目标机器人”下拉框显示不一致的问题。用户在机器人列表中点击某台机器人后，命令面板的内部控制目标、下拉框显示和方向按钮可用状态必须指向同一台机器人，避免界面显示一台机器人而命令实际发往另一台机器人。

本次不新增机器人列表取消选择功能，也不改变速度命令格式、MQTT 发送链路或批量模式命令行为。

## 架构

`RobotListPanel` 继续通过 `robot_selected(str)` 发出列表选择结果，`MainWindow` 继续把该信号连接到 `CommandPanel.on_robot_selected()`。同步逻辑集中在 `CommandPanel` 内部，由同一个入口同时维护下拉框、内部目标和方向按钮状态，避免 `MainWindow` 直接操作命令面板的私有控件。

## 技术栈

- Python 3.8
- PyQt5 的 `QComboBox`、signal/slot
- pytest 与 `QT_QPA_PLATFORM=offscreen`

## 术语与执行约定

- **机器人列表选择**：用户在 `RobotListPanel` 表格中点击的机器人，由 `robot_selected(str)` 信号携带机器人 ID。
- **目标机器人下拉框**：`CommandPanel._robot_combo`，显示单机器人速度控制命令的目标；首项“-- 选择 --”对应空目标。
- **内部控制目标**：`CommandPanel._selected_robot`，方向按钮发送速度命令时实际使用的机器人 ID。
- **同步**：列表选择机器人时，下拉框显示同一机器人，内部控制目标也设置为同一机器人；用户直接改变下拉框时，现有回调继续更新内部控制目标。
- **在线列表刷新**：机器人在线集合变化时重建目标下拉框。若原目标已不在列表中，沿用现有行为清空目标并禁用方向按钮。

## 根因

`MainWindow` 已将机器人列表的 `robot_selected` 信号连接到 `CommandPanel.on_robot_selected()`。该方法目前只更新 `_selected_robot` 和方向按钮状态，没有设置 `_robot_combo`。因此列表点击后，速度命令使用新的内部目标，但下拉框仍显示原来的机器人。

## 方案

修改 `CommandPanel.on_robot_selected()`：

1. 使用下拉框 item data 查找传入的机器人 ID，而不是依赖显示文本。
2. 找到目标时，将下拉框切换到对应项；传入空 ID 时切换到“-- 选择 --”。
3. 更新下拉框期间阻断其信号，避免 `_on_robot_combo_changed()` 再次进入 `on_robot_selected()`。
4. 下拉框中不存在非空机器人 ID 时，不伪造选项，而是清空目标并禁用方向按钮。这样点击已离线但仍保留在列表中的行，也不会重新造成显示目标与实际控制目标分离。
5. 保持方向按钮根据内部目标是否为空启用或禁用。

用户直接选择下拉框时，现有 `_on_robot_combo_changed()` 继续调用 `on_robot_selected()`，因此两种入口最终经过同一状态更新逻辑。

## 测试与验证

在 `tests/test_panels.py::TestCommandPanel` 增加聚焦回归测试：先填充两台在线机器人并让下拉框选择第一台，再调用 `on_robot_selected()` 模拟列表选择第二台，断言下拉框 item data、显示文本和 `_selected_robot` 均为第二台。测试应在修改生产代码前因下拉框仍显示第一台而失败。

实现后运行：

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_panels.py -v
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_main_window.py -v
ruff check qt_frontend/panels/command_panel.py tests/test_panels.py
```

真实 ROS、MQTT、Docker 与 RViz 链路不受协议或发送逻辑修改；本次以离屏 Qt 单元测试验证选择联动，不需要重启机器人容器。
