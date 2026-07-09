# 话题健康面板实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将现有传感器摘要面板调整为“话题健康面板”，用于判断每个订阅话题的链路是否正常、配置与实际传输是否一致、Bridge 最终应发布到哪个本地 ROS topic。

**架构：** 继续复用现有 `SensorSummaryPanel` 文件和主窗口接线，避免第一版引入大范围重命名。面板接收订阅配置、MQTT sensor envelope、HTTP stream meta 和普通 JSON sensor 数据，生成每个 `(robot_id, sensor_name)` 的健康快照；流量面板继续负责带宽和吞吐统计，健康面板不显示 KB/s、总流量或带宽进度条。

**技术栈：** Python 3.8、PyQt5、pytest、现有 MQTT client signal、现有 `TopicConfigPanel.normalize_transmit_subscriptions()`、ROS topic 命名约定。

---

## 术语与执行约定

- `话题健康面板`：本计划改造后的右侧诊断面板。它不展示完整 ROS message 内容，而是展示“链路是否通、最后一次数据何时到达、实际 transport 是什么、Bridge 应该发布到哪里”。例如 `/joint_states` 的健康详情应显示本地 ROS topic 为 `/husky_001/joint_states`。
- `流量面板`：现有 `TrafficMonitor`，负责回答“数据量有多大、谁占带宽、吞吐是否异常”。本计划不把 KB/s、总带宽、带宽进度条搬到健康面板，避免重复。
- `sensor envelope`：Agent 通过 MQTT 发出的轻量 JSON 说明。对于 `mqtt_binary`，它通常包含 `binary=true`、`topic`、`msg_type`、`encoding=ros1_serialized_v1`、`payload_format`、`payload_size`。它不是 ROS message 本体。
- `sensor meta`：HTTP stream 话题的取数说明，通常由 MQTT topic `robot/<id>/sensor/<name>/meta` 发送，payload 中包含 `transport=http_stream`、`stream_url`、`payload_size`、`encoding` 和 `payload_format`。
- `本地 ROS topic`：Bridge 在地面站本机 roscore 中重新发布的 topic。当前约定是 `/tf` 和 `/tf_static` 使用公共 topic；普通 topic 使用 `/{robot_id}/{original_topic}`，例如 `/husky_001/joint_states`、`/husky_001/hdl_graph_slam/odom`。
- `健康状态`：面板中的用户可读状态。第一版只使用四类：`等待数据`、`正常`、`断流`、`配置不一致`。`配置不一致` 指订阅配置中的明确 transport 与实际 envelope/meta 中的 transport 不一致；订阅配置为 `auto` 时不标记不一致，因为 `auto` 本来就会解析为实际传输方式。
- `更新`：距离最近一次 MQTT sensor envelope、sensor meta 或普通 JSON sensor 数据到达的时间。超过现有 2 秒阈值显示为 `断流`。

执行约定：

- 第一版不读 ROS master，不调用 `rostopic`，只基于前端已收到的 MQTT 和配置数据判断健康。这样不会引入额外线程或 ROS 环境依赖。
- 第一版保留文件名 `qt_frontend/panels/sensor_summary_panel.py` 和类名 `SensorSummaryPanel`，只改变 UI 文案、数据模型和行为；本计划不包含类名、文件名或主窗口 import 的重命名。
- 上方总览表只保留 5 列：`话题`、`机器人`、`健康`、`更新`、`本地 ROS`。顶部指标区也不再突出 `Hz`；`Hz` 只放到下方详情中作为辅助诊断，避免和流量面板重复。
- 下方详情继续使用 `QTextBrowser` 文本详情区展示选中话题的诊断字段：消息类型、期望 transport、实际 transport、encoding、payload format、payload size、Hz、本地 ROS topic、诊断说明。

## 文件职责

- 修改：`qt_frontend/panels/sensor_summary_panel.py`
  - 将面板 UI 文案从“传感器摘要/话题状态”调整为“话题健康”。
  - 将 `TopicSnapshot` 扩展为健康快照，记录 transport、encoding、payload size、本地 ROS topic 和诊断说明。
  - 总览表改为 5 列，顶部指标区收敛为健康/更新/本地 ROS/消息数，详情区显示选中话题的健康字段。
  - 保留旧的 message 内容摘要 helper，但只作为详情中的“补充摘要”，不再作为主价值。

- 修改：`qt_frontend/main_window.py`
  - 让 `sensor_meta_received` 同时进入健康面板和流量面板。
  - 保持普通 sensor 数据进入健康面板和流量面板的现有批处理路径。

- 测试：`tests/test_panels.py`
  - 现有测试类名是 `TestSensorSummary`，不是 `TestSensorSummaryPanel`。
  - 覆盖总览表列结构、joint_states 本地 ROS topic 推导、TF 公共 topic 推导、binary envelope 详情、http_stream meta 详情、配置不一致诊断。

## 任务 1：提取话题健康推导逻辑

**文件：**
- 修改：`qt_frontend/panels/sensor_summary_panel.py`
- 测试：`tests/test_panels.py`

- [x] **步骤 1：编写失败测试**

在 `tests/test_panels.py` 的 `TestSensorSummary` 中增加：

```python
def test_local_ros_topic_uses_robot_namespace_except_tf(self):
    assert SensorSummaryPanel.local_ros_topic_for(
        "husky_001",
        "/joint_states",
    ) == "/husky_001/joint_states"
    assert SensorSummaryPanel.local_ros_topic_for(
        "husky_001",
        "/hdl_graph_slam/odom",
    ) == "/husky_001/hdl_graph_slam/odom"
    assert SensorSummaryPanel.local_ros_topic_for(
        "husky_001",
        "/tf",
    ) == "/tf"
    assert SensorSummaryPanel.local_ros_topic_for(
        "husky_001",
        "/tf_static",
    ) == "/tf_static"
```

- [x] **步骤 2：运行测试确认失败**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_local_ros_topic_uses_robot_namespace_except_tf -q
```

预期：失败，提示 `SensorSummaryPanel` 没有 `local_ros_topic_for`。

- [x] **步骤 3：实现最小推导函数**

在 `SensorSummaryPanel` 的纯逻辑方法区域增加：

```python
    @staticmethod
    def local_ros_topic_for(robot_id: str, ros_topic: str) -> str:
        topic = ros_topic.strip()
        if not topic.startswith("/"):
            topic = "/" + topic
        if topic in ("/tf", "/tf_static"):
            return topic
        return "/%s%s" % (robot_id, topic)
```

- [x] **步骤 4：运行测试确认通过**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_local_ros_topic_uses_robot_namespace_except_tf -q
```

预期：通过。

- [x] **步骤 5：Commit**

```bash
git add qt_frontend/panels/sensor_summary_panel.py tests/test_panels.py
git commit -m "feat: 增加话题健康ROS落点推导"
```

## 任务 2：扩展健康快照字段

**文件：**
- 修改：`qt_frontend/panels/sensor_summary_panel.py`
- 测试：`tests/test_panels.py`

- [x] **步骤 1：编写失败测试**

在 `tests/test_panels.py` 的 `TestSensorSummary` 中增加：

```python
def test_binary_envelope_builds_topic_health_snapshot(self):
    data = {
        "binary": True,
        "topic": "/joint_states",
        "msg_type": "sensor_msgs/JointState",
        "encoding": "ros1_serialized_v1",
        "payload_format": "ros1_serialized",
        "payload_size": 208,
    }

    snapshot = SensorSummaryPanel.build_topic_snapshot(
        robot_id="husky_001",
        sensor_name="joint_states",
        data=data,
        now=100.0,
        previous=None,
    )

    assert snapshot.msg_type == "sensor_msgs/JointState"
    assert snapshot.transport == "mqtt_binary"
    assert snapshot.encoding == "ros1_serialized_v1"
    assert snapshot.payload_format == "ros1_serialized"
    assert snapshot.payload_size == 208
    assert snapshot.local_ros_topic == "/husky_001/joint_states"
    assert snapshot.health_status == "正常"
    assert "MQTT binary envelope" in snapshot.diagnostic
```

- [x] **步骤 2：运行测试确认失败**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_binary_envelope_builds_topic_health_snapshot -q
```

预期：失败，提示 `TopicSnapshot` 没有 `transport` 等字段。

- [x] **步骤 3：扩展 `TopicSnapshot`**

将 dataclass 扩展为：

```python
@dataclass
class TopicSnapshot:
    robot_id: str
    sensor_name: str
    msg_type: str
    summary_lines: List[str]
    first_time: float
    last_time: float
    frame_count: int = 1
    sample_times: List[float] = field(default_factory=list)
    transport: str = "mqtt_json"
    expected_transport: str = ""
    encoding: str = ""
    payload_format: str = ""
    payload_size: int = 0
    local_ros_topic: str = ""
    health_status: str = "正常"
    diagnostic: str = "消息持续到达"
```

- [x] **步骤 4：增加 envelope 解析 helper**

在纯逻辑方法区域增加：

```python
    @staticmethod
    def infer_transport(data: Dict[str, Any], config_transport: str = "") -> str:
        transport = data.get("transport")
        if isinstance(transport, str) and transport:
            return transport
        if data.get("binary") is True:
            return "mqtt_binary"
        if config_transport:
            return config_transport
        return "mqtt_json"

    @staticmethod
    def payload_size_from_data(data: Dict[str, Any]) -> int:
        value = data.get("payload_size")
        if isinstance(value, int) and value >= 0:
            return value
        value = data.get("_payload_bytes")
        if isinstance(value, int) and value >= 0:
            return value
        return 0

    @staticmethod
    def diagnostic_for(data: Dict[str, Any], transport: str) -> str:
        if transport == "http_stream":
            return "HTTP stream meta 正常到达"
        if data.get("binary") is True:
            return "MQTT binary envelope 正常到达"
        return "MQTT JSON 数据正常到达"
```

- [x] **步骤 5：更新 `build_topic_snapshot()`**

在 `build_topic_snapshot()` 内推导新字段：

```python
        ros_topic = str(data.get("topic") or "/" + sensor_name)
        transport = SensorSummaryPanel.infer_transport(data)
        encoding = str(data.get("encoding") or "")
        payload_format = str(data.get("payload_format") or "")
        payload_size = SensorSummaryPanel.payload_size_from_data(data)
        local_ros_topic = SensorSummaryPanel.local_ros_topic_for(robot_id, ros_topic)
        diagnostic = SensorSummaryPanel.diagnostic_for(data, transport)
```

创建 `TopicSnapshot` 时传入：

```python
                transport=transport,
                encoding=encoding,
                payload_format=payload_format,
                payload_size=payload_size,
                local_ros_topic=local_ros_topic,
                health_status="正常",
                diagnostic=diagnostic,
```

更新 previous 分支也传入同样字段。

- [x] **步骤 6：运行测试确认通过**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_binary_envelope_builds_topic_health_snapshot -q
```

预期：通过。

- [x] **步骤 7：Commit**

```bash
git add qt_frontend/panels/sensor_summary_panel.py tests/test_panels.py
git commit -m "feat: 记录话题健康快照字段"
```

## 任务 3：将总览表改为健康视角

**文件：**
- 修改：`qt_frontend/panels/sensor_summary_panel.py`
- 测试：`tests/test_panels.py`

- [x] **步骤 1：编写失败测试**

在 `tests/test_panels.py` 的 `TestSensorSummary` 中增加：

```python
def test_topic_health_overview_uses_compact_columns(self, qt_app):
    panel = SensorSummaryPanel()
    panel.show()

    headers = [
        panel._topic_table.horizontalHeaderItem(index).text()
        for index in range(panel._topic_table.columnCount())
    ]

    assert headers == ["话题", "机器人", "健康", "更新", "本地 ROS"]

def test_waiting_topic_uses_subscription_topic_for_local_ros_target(self, qt_app):
    panel = SensorSummaryPanel()
    panel.show()
    panel.on_subscriptions_changed(
        "husky_001",
        [{
            "topic": "/joint_states",
            "msg_type": "sensor_msgs/JointState",
            "status": "active",
        }],
    )
    panel._refresh_current_view(force=True)

    assert panel._topic_table.item(0, 2).text() == "等待数据"
    assert panel._topic_table.item(0, 4).text() == "/husky_001/joint_states"
```

- [x] **步骤 2：运行测试确认失败**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_topic_health_overview_uses_compact_columns tests/test_panels.py::TestSensorSummary::test_waiting_topic_uses_subscription_topic_for_local_ros_target -q
```

预期：失败，当前表头仍包含 `状态`、`Hz`、`摘要` 等旧列，等待态也还没有稳定使用订阅配置中的原始 ROS topic。

- [x] **步骤 3：修改标题和表头**

在 `__init__()` 中把标题改为：

```python
        header = QLabel("话题健康")
```

把总览表列定义改为：

```python
        self._topic_table.setColumnCount(5)
        self._topic_table.setHorizontalHeaderLabels(
            ["话题", "机器人", "健康", "更新", "本地 ROS"]
        )
```

把列宽设置调整为：

```python
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.Stretch)
```

- [x] **步骤 4：让订阅记录保留原始 ROS topic**

等待数据时还没有 MQTT envelope，不能从运行时数据里取 `topic` 字段；必须使用订阅配置里的原始 ROS topic 推导本地 ROS 发布目标。先扩展 `ObservedTopic`：

```python
@dataclass
class ObservedTopic:
    robot_id: str
    sensor_name: str
    ros_topic: str = ""
    msg_type: str = ""
    status: str = "pending"
```

在 `on_subscriptions_changed()` 创建 `ObservedTopic` 时传入配置中的原始 topic：

```python
            self._observed_topics[key] = ObservedTopic(
                robot_id=robot_id,
                sensor_name=sensor_name,
                ros_topic=topic,
                msg_type=msg_type,
                status=status,
            )
```

- [x] **步骤 5：更新 `_refresh_topic_table()`**

将 `values` 改为：

```python
            if snapshot is None:
                status = "等待数据"
                age = "--"
                local_ros_topic = self.local_ros_topic_for(
                    topic.robot_id,
                    topic.ros_topic or "/" + topic.sensor_name,
                )
            else:
                status = (
                    "断流"
                    if snapshot.is_stale(now, self._STALE_THRESHOLD_SECONDS)
                    else snapshot.health_status
                )
                age = self.format_age(snapshot.age(now))
                local_ros_topic = snapshot.local_ros_topic
            values = [
                topic.sensor_name,
                topic.robot_id,
                status,
                age,
                local_ros_topic,
            ]
```

- [x] **步骤 6：运行测试确认通过**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_topic_health_overview_uses_compact_columns tests/test_panels.py::TestSensorSummary::test_waiting_topic_uses_subscription_topic_for_local_ros_target -q
```

预期：通过。

- [x] **步骤 7：收敛顶部指标区**

现有指标区包含 `Hz` 和 `帧数`，容易和流量面板重复。第一版保留四个 QLabel，减少 UI 布局改动，但改变含义：

```python
        self._lb_status = self._build_metric_label("健康: 等待数据")
        self._lb_hz = self._build_metric_label("本地 ROS: --")
        self._lb_age = self._build_metric_label("更新: --")
        self._lb_frames = self._build_metric_label("消息数: 0")
```

在 `_render_snapshot()` 中同步改为：

```python
        self._lb_status.setText(f"健康: {status}")
        self._lb_hz.setText(f"本地 ROS: {snapshot.local_ros_topic or '-'}")
        self._lb_age.setText(f"更新: {self.format_age(snapshot.age(now))}")
        self._lb_frames.setText(f"消息数: {snapshot.frame_count}")
```

在 `_render_waiting_topic()` 中同步改为：

```python
        self._lb_status.setText("健康: 等待数据")
        self._lb_hz.setText(
            "本地 ROS: %s" % self.local_ros_topic_for(
                topic.robot_id,
                topic.ros_topic or "/" + topic.sensor_name,
            )
        )
        self._lb_age.setText("更新: --")
        self._lb_frames.setText("消息数: 0")
```

虽然内部属性名仍叫 `_lb_hz`，但这是为了控制第一版改动范围；本计划不重命名内部属性。

- [x] **步骤 8：更新既有表格测试**

修改同一测试类里的 `test_status_table_shows_subscribed_topic_summary`，让它匹配新的健康总览表：

```python
        assert panel._topic_table.columnCount() == 5
        assert panel._topic_table.item(0, 2).text() == "正常"
        assert panel._topic_table.item(0, 4).text() == "/r1/map"
```

这个测试原来断言第 6 列显示 `OccupancyGrid: 20×10`。新设计中内容摘要已经移动到详情区，不再出现在总览表。

- [x] **步骤 9：运行任务 3 相关测试确认通过**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_topic_health_overview_uses_compact_columns tests/test_panels.py::TestSensorSummary::test_waiting_topic_uses_subscription_topic_for_local_ros_target tests/test_panels.py::TestSensorSummary::test_status_table_shows_subscribed_topic_summary -q
```

预期：通过。

- [x] **步骤 10：Commit**

```bash
git add qt_frontend/panels/sensor_summary_panel.py tests/test_panels.py
git commit -m "refactor: 收敛话题健康总览表"
```

## 任务 4：增加选中话题详情区

**文件：**
- 修改：`qt_frontend/panels/sensor_summary_panel.py`
- 测试：`tests/test_panels.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_panels.py` 的 `TestSensorSummary` 中增加：

```python
def test_selected_topic_detail_shows_transport_and_ros_target(self, qt_app):
    panel = SensorSummaryPanel()
    panel.show()
    panel.on_sensor_data_received(
        "husky_001",
        "joint_states",
        {
            "binary": True,
            "topic": "/joint_states",
            "msg_type": "sensor_msgs/JointState",
            "encoding": "ros1_serialized_v1",
            "payload_format": "ros1_serialized",
            "payload_size": 208,
        },
    )
    panel._refresh_current_view(force=True)

    detail = panel._detail_browser.toPlainText()

    assert "transport: mqtt_binary" in detail
    assert "encoding: ros1_serialized_v1" in detail
    assert "payload_size: 208 bytes" in detail
    assert "本地 ROS: /husky_001/joint_states" in detail
    assert "MQTT binary envelope 正常到达" in detail
```

- [ ] **步骤 2：运行测试确认失败**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_selected_topic_detail_shows_transport_and_ros_target -q
```

预期：失败，当前没有 `_detail_browser`。

- [ ] **步骤 3：增加详情区 UI**

在 `__init__()` 中用 `_detail_browser` 替代旧 `_browser` 的主展示职责：

```python
        self._detail_browser = QTextBrowser()
        self._detail_browser.setOpenExternalLinks(False)
        layout.addWidget(self._detail_browser, 1)
        self._browser = self._detail_browser
```

保留 `self._browser` 是为了兼容现有测试；本计划不删除这个兼容属性。

- [ ] **步骤 4：更新 `_render_snapshot()` 详情内容**

将详情内容改为健康字段优先：

```python
            lines = [
                f"机器人: {snapshot.robot_id}",
                f"话题: {snapshot.sensor_name}",
                f"类型: {snapshot.msg_type}",
                f"健康: {'断流' if stale else snapshot.health_status}",
                f"Hz: {self.format_rate(snapshot.hz)}",
                f"更新: {self.format_age(snapshot.age(now))}",
                "",
                "传输:",
                f"- transport: {snapshot.transport}",
                f"- encoding: {snapshot.encoding or '-'}",
                f"- payload_format: {snapshot.payload_format or '-'}",
                f"- payload_size: {snapshot.payload_size} bytes",
                "",
                f"本地 ROS: {snapshot.local_ros_topic or '-'}",
                "",
                "诊断:",
            ]
            if stale:
                lines.append(
                    f"- {self.format_age(snapshot.age(now))} 未收到新消息，可能断流或已取消订阅"
                )
            else:
                lines.append(f"- {snapshot.diagnostic}")
            if snapshot.summary_lines:
                lines.extend(["", "补充摘要:"])
                lines.extend("- " + line for line in snapshot.summary_lines[:4])
```

- [ ] **步骤 5：运行测试确认通过**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_selected_topic_detail_shows_transport_and_ros_target -q
```

预期：通过。

- [ ] **步骤 6：Commit**

```bash
git add qt_frontend/panels/sensor_summary_panel.py tests/test_panels.py
git commit -m "feat: 显示选中话题健康详情"
```

## 任务 5：让 HTTP stream meta 进入健康面板

**文件：**
- 修改：`qt_frontend/main_window.py`
- 修改：`qt_frontend/panels/sensor_summary_panel.py`
- 测试：`tests/test_panels.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_panels.py` 的 `TestSensorSummary` 中增加：

```python
def test_http_stream_meta_shows_stream_diagnostic(self, qt_app):
    panel = SensorSummaryPanel()
    panel.show()
    panel.on_sensor_data_received(
        "husky_001",
        "velodyne_points",
        {
            "type": "sensor_meta",
            "topic": "/velodyne_points",
            "msg_type": "sensor_msgs/PointCloud2",
            "transport": "http_stream",
            "encoding": "ros1_serialized_v1",
            "payload_format": "ros1_serialized",
            "payload_size": 5132,
            "stream_url": "http://localhost:18080/stream/velodyne_points",
        },
    )
    panel._refresh_current_view(force=True)

    detail = panel._detail_browser.toPlainText()

    assert "transport: http_stream" in detail
    assert "payload_size: 5132 bytes" in detail
    assert "本地 ROS: /husky_001/velodyne_points" in detail
    assert "HTTP stream meta 正常到达" in detail
```

- [ ] **步骤 2：运行测试确认失败**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_http_stream_meta_shows_stream_diagnostic -q
```

预期：如果任务 4 已实现详情区但 meta 诊断不完整，则断言失败。

- [ ] **步骤 3：补充 meta stream URL 详情**

扩展 `TopicSnapshot`：

```python
    stream_url: str = ""
```

在 `build_topic_snapshot()` 中读取：

```python
        stream_url = str(data.get("stream_url") or "")
```

创建 snapshot 时传入 `stream_url=stream_url`。在 `_render_snapshot()` 的传输段中增加：

```python
                f"- stream_url: {snapshot.stream_url or '-'}",
```

- [ ] **步骤 4：让主窗口把 meta 送给健康面板**

修改 `MainWindow._on_sensor_meta()`：

```python
    def _on_sensor_meta(self, robot_id: str, sensor_name: str, data: object) -> None:
        if isinstance(data, dict):
            self._sensor_panel.on_sensor_data_received(
                robot_id,
                sensor_name,
                data,
            )
        self._traffic_monitor.on_sensor_data_received(
            robot_id,
            sensor_name,
            data,
            now=time.monotonic(),
        )
```

- [ ] **步骤 5：运行测试确认通过**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_http_stream_meta_shows_stream_diagnostic -q
```

预期：通过。

- [ ] **步骤 6：Commit**

```bash
git add qt_frontend/main_window.py qt_frontend/panels/sensor_summary_panel.py tests/test_panels.py
git commit -m "feat: 在话题健康面板显示HTTP流状态"
```

## 任务 6：配置不一致诊断

**文件：**
- 修改：`qt_frontend/panels/sensor_summary_panel.py`
- 测试：`tests/test_panels.py`

- [ ] **步骤 1：编写失败测试**

在 `tests/test_panels.py` 的 `TestSensorSummary` 中增加：

```python
def test_health_marks_transport_mismatch(self, qt_app):
    panel = SensorSummaryPanel()
    panel.show()
    panel.on_subscriptions_changed(
        "husky_001",
        [{
            "topic": "/joint_states",
            "msg_type": "sensor_msgs/JointState",
            "transport": "mqtt_json",
            "status": "active",
        }],
    )
    panel.on_sensor_data_received(
        "husky_001",
        "joint_states",
        {
            "binary": True,
            "topic": "/joint_states",
            "msg_type": "sensor_msgs/JointState",
            "encoding": "ros1_serialized_v1",
            "payload_format": "ros1_serialized",
            "payload_size": 208,
        },
    )
    panel._refresh_current_view(force=True)

    snapshot = panel._snapshots[("husky_001", "joint_states")]

    assert snapshot.expected_transport == "mqtt_json"
    assert snapshot.transport == "mqtt_binary"
    assert snapshot.health_status == "配置不一致"
    assert "期望 mqtt_json，实际 mqtt_binary" in snapshot.diagnostic

def test_transport_auto_does_not_mark_mismatch(self, qt_app):
    panel = SensorSummaryPanel()
    panel.show()
    panel.on_subscriptions_changed(
        "husky_001",
        [{
            "topic": "/joint_states",
            "msg_type": "sensor_msgs/JointState",
            "transport": "auto",
            "status": "active",
        }],
    )
    panel.on_sensor_data_received(
        "husky_001",
        "joint_states",
        {
            "binary": True,
            "topic": "/joint_states",
            "msg_type": "sensor_msgs/JointState",
            "encoding": "ros1_serialized_v1",
            "payload_format": "ros1_serialized",
            "payload_size": 208,
        },
    )
    panel._refresh_current_view(force=True)

    snapshot = panel._snapshots[("husky_001", "joint_states")]

    assert snapshot.expected_transport == "auto"
    assert snapshot.transport == "mqtt_binary"
    assert snapshot.health_status == "正常"
```

- [ ] **步骤 2：运行测试确认失败**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_health_marks_transport_mismatch tests/test_panels.py::TestSensorSummary::test_transport_auto_does_not_mark_mismatch -q
```

预期：失败，当前未记录 expected transport，也不会正确区分明确 transport 和 `auto`。

- [ ] **步骤 3：在 `ObservedTopic` 中记录 transport**

在任务 3 已加入 `ros_topic` 的基础上，扩展 dataclass：

```python
@dataclass
class ObservedTopic:
    robot_id: str
    sensor_name: str
    ros_topic: str = ""
    msg_type: str = ""
    status: str = "pending"
    transport: str = ""
```

在 `on_subscriptions_changed()` 中写入：

```python
            transport = str(item.get("transport") or "")
```

创建 `ObservedTopic` 时保留已有 `ros_topic=topic`，并增加 `transport=transport`。

- [ ] **步骤 4：让 pending 数据携带期望 transport**

在 `_process_pending_data()` 中取出 observed topic：

```python
            observed = self._observed_topics.get(key)
            expected_transport = observed.transport if observed else ""
```

调用 `build_topic_snapshot()` 时增加参数：

```python
                expected_transport=expected_transport,
```

将 `build_topic_snapshot()` 签名改为：

```python
        expected_transport: str = "",
```

- [ ] **步骤 5：实现不一致诊断**

在 `build_topic_snapshot()` 中推导：

```python
        health_status = "正常"
        if (
            expected_transport
            and expected_transport != "auto"
            and expected_transport != transport
        ):
            health_status = "配置不一致"
            diagnostic = "期望 %s，实际 %s" % (expected_transport, transport)
```

创建 snapshot 时传入：

```python
                expected_transport=expected_transport,
                health_status=health_status,
                diagnostic=diagnostic,
```

- [ ] **步骤 6：运行测试确认通过**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary::test_health_marks_transport_mismatch tests/test_panels.py::TestSensorSummary::test_transport_auto_does_not_mark_mismatch -q
```

预期：通过。

- [ ] **步骤 7：Commit**

```bash
git add qt_frontend/panels/sensor_summary_panel.py tests/test_panels.py
git commit -m "feat: 标记话题传输配置不一致"
```

## 任务 7：回归验证与文档更新

**文件：**
- 修改：`README.md`
- 修改：`docs/tech-stack.md`
- 测试：`tests/test_panels.py`

- [ ] **步骤 1：运行面板测试**

```bash
python3 -m pytest tests/test_panels.py::TestSensorSummary -q
```

预期：`TestSensorSummary` 全部通过。

- [ ] **步骤 2：运行相关前端测试**

```bash
python3 -m pytest tests/test_panels.py -q
```

预期：`tests/test_panels.py` 全部通过。

- [ ] **步骤 3：运行 lint**

```bash
ruff check qt_frontend/panels/sensor_summary_panel.py qt_frontend/main_window.py tests/test_panels.py
```

预期：无新增 lint 错误。如果命令暴露既有无关错误，只记录具体文件和规则，不在本任务中重构无关区域。

- [ ] **步骤 4：更新 README**

在 `README.md` 的主要能力列表中，将传感器摘要相关描述调整为：

```markdown
- 话题健康面板按机器人展示订阅话题的链路状态、最近更新时间、传输方式和 Bridge 本地 ROS 发布目标，用于排查 MQTT、HTTP stream 和 ROS topic 重发布链路。
```

如果 README 中没有单独提到摘要面板，只在目录结构注释中将：

```text
传感器摘要、数据推送等
```

改为：

```text
话题健康、数据推送等
```

- [ ] **步骤 5：更新技术栈文档**

在 `docs/tech-stack.md` 的 Bridge 或 Qt 前端说明中补充：

```markdown
- 话题健康面板不负责带宽统计；带宽、总流量和吞吐趋势由流量面板展示。健康面板只展示订阅状态、最近更新时间、transport/encoding、本地 ROS topic 和诊断说明。
```

- [ ] **步骤 6：空白检查**

```bash
git diff --check -- qt_frontend/panels/sensor_summary_panel.py qt_frontend/main_window.py tests/test_panels.py README.md docs/tech-stack.md
```

预期：无输出。

- [ ] **步骤 7：Commit**

```bash
git add qt_frontend/panels/sensor_summary_panel.py qt_frontend/main_window.py tests/test_panels.py README.md docs/tech-stack.md
git commit -m "docs: 说明话题健康面板职责"
```

## 自检

- 不看聊天记录也能理解任务背景：计划头部说明了摘要面板为什么要改成话题健康面板，以及它和流量面板的职责边界。
- 术语与执行约定覆盖了新概念：`sensor envelope`、`sensor meta`、`本地 ROS topic`、`transport: auto`、健康状态和断流阈值都已解释，并给出 `/joint_states`、`/tf`、`/tf_static` 示例。
- 本计划将健康面板和流量面板职责拆开：健康面板不显示 KB/s、总带宽或带宽进度条。
- 总览表只有 5 列，适合右侧窄面板；Hz 放入详情区作为辅助诊断，不作为总览主列。
- 计划覆盖了 `mqtt_binary` envelope、`http_stream` meta、`/tf` 公共 topic、`/joint_states` robot namespace topic、配置不一致诊断。
- 等待态的本地 ROS topic 使用订阅配置中的原始 ROS topic 推导，不依赖 Agent 展平后的 MQTT sensor name。
- `transport: auto` 不会被标记为配置不一致；只有明确配置为 `mqtt_json`、`mqtt_binary`、`http_stream` 等值时才做不一致诊断。
- 第一版不读 ROS master，不引入线程或 ROS CLI 调用，避免 UI 卡顿和环境依赖。
- 保留现有文件名和类名，降低主窗口 import 和测试迁移风险。
- 每个关键行为都有对应测试或验证命令：本地 ROS topic 推导、等待态表格、总览列结构、选中详情、HTTP stream meta、配置不一致、`auto` 例外、README 和技术栈文档更新都在任务中列出。
- 红旗词扫描已完成，未发现计划步骤中的空泛表达。
