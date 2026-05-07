# Qt+Rviz 地面站 — 任务清单

基于方案 B (plan-b-hazy-music.md) 的实施任务分解。总约 2500 行 Python + 350 行测试，约 25 个文件。

---

## 当前进度

| # | 任务 | 预计行数 | 状态 |
|---|------|----------|------|
| 1 | pyproject.toml 更新 (PyQt5 依赖 + 包发现) | 5 | ✅ 完成 |
| 2 | protocol/messages.py 新增 CONFIG 消息类型 | 35 | ✅ 完成 |
| 3 | protocol/topics.py 新增 config topic 函数 | 35 | ✅ 完成 |
| 4 | agent/base_agent.py + config.yaml 配置同步 | 100 | ✅ 完成 |
| 5 | qt-frontend/__init__.py + main_window.py | 400 | ✅ 完成 |
| 6 | qt-frontend/mqtt_client.py | 280 | ✅ 完成 |
| 7 | 左侧栏面板 (RobotList, Command, Event) | 500 | ✅ 完成 |
| 8 | 右侧栏面板 (Sensor, Sender, Traffic, Config, Fleet) | 810 | ✅ 完成 |
| 9 | 配置文件与启动脚本 | 120 | ✅ 完成 |
| 10 | 测试 (test_mqtt_client.py + test_panels.py + conftest) | 620 | ✅ 完成 |
| 11 | CLAUDE.md 与文档集成 | 30 | ✅ 完成 |

---

## 任务 1：pyproject.toml 更新

**修改文件**：`pyproject.toml`

- `dependencies` 新增 `"pyqt5>=5.15"`
- `[project.optional-dependencies]` 新增 `qt = ["pyqt5>=5.15"]`
- `[tool.setuptools.packages.find].include` 新增 `"qt_frontend*"`

✅ 已完成

---

## 任务 2：protocol/messages.py 新增 CONFIG 消息类型

**修改文件**：`protocol/messages.py`

- `MessageType` 枚举新增：`CONFIG_SYNC = "config_sync"`、`CONFIG_QUERY = "config_query"`、`CONFIG_RESPONSE = "config_response"`
- 新增 dataclass `ConfigSyncData(subscriptions: list, fleet_rules: list)`
- 新增 dataclass `ConfigResponseData(robot_id: str, subscriptions: list, fleet_rules: list)`
- `MessageFactory` 新增 `config_sync()`, `config_query()`, `config_response()`
- `_make()` 的 isinstance 检查新增 ConfigSyncData、ConfigResponseData

✅ 已完成

---

## 任务 3：protocol/topics.py 新增 config topic 函数

**修改文件**：`protocol/topics.py`

- `station_config_sync(robot_id)` → `"station/{robot_id}/config/sync"`
- `station_config_query(robot_id)` → `"station/{robot_id}/config/query"`
- `station_config_response(robot_id)` → `"station/{robot_id}/config/response"`
- `TOPIC_QOS` 新增 `config_sync`, `config_query`, `config_response` (qos=1)
- `parse_station_topic()` 更新：识别 `config/sync`、`config/query`、`config/response`

✅ 已完成

---

## 任务 4：Agent 端配置同步改动

**修改文件**：`agent/base_agent.py`（约 100 行改动）、`agent/config.yaml`

### base_agent.py 改动：
- **imports 更新**：
  - messages 新增 `ConfigSyncData`, `ConfigResponseData`
  - topics 新增 `station_config_sync`, `station_config_query`, `station_config_response`
- **AgentConfig dataclass 新增字段**：
  - `subscriptions: list = field(default_factory=list)`
  - `fleet_rules: list = field(default_factory=list)`
- **AgentConfig.from_yaml()**：
  - `known_keys` 新增 `"subscriptions"`, `"fleet_rules"`
  - 构造参数新增 `subscriptions=`, `fleet_rules=`
- **`_on_connect()`**：新增订阅 `station_config_sync(robot_id)` qos=1, `station_config_query(robot_id)` qos=1
- **`_handle_message()`**：新增路由 `CONFIG_SYNC → _handle_config_sync`, `CONFIG_QUERY → _handle_config_query`
- **新增方法 `_handle_config_sync(msg)`**：
  - 解析 subscriptions + fleet_rules
  - 合并到 self.config
  - 调用 `_save_config()` 持久化
  - 逐条恢复订阅（调 `_on_topic_subscribed`）
  - 回复 `config_response` ack
- **新增方法 `_handle_config_query(msg)`**：
  - 返回当前 subscriptions + fleet_rules 作为 ConfigResponseData
- **新增方法 `_load_subscriptions_from_config()`**：
  - 遍历 `self.config.subscriptions`，逐条恢复订阅
  - 在 `_on_connect` 中 `_start_status_loop()` 之前调用
- **新增方法 `_save_config()`**：
  - 将当前配置（含 subscriptions、fleet_rules）写回 `agent/config.yaml`

### config.yaml 新增：
- 末尾新增 `subscriptions: []` 和 `fleet_rules: []`

---

## 任务 5：qt-frontend/__init__.py + main_window.py

**新建文件**：`qt-frontend/__init__.py`、`qt-frontend/main_window.py`（约 400 行）

### __init__.py
- 空文件，标记 `qt_frontend` 为 Python 包

### main_window.py

**RvizWidget(QWidget)**（约 80 行内部类）：
- 类变量 `_lib`：`ctypes.CDLL("native/build/librviz_widget.so")`，设置 argtypes/restype
- `__init__`：
  1. 调 C `create_rviz_widget(None)` → void*
  2. 调 C `get_window_id(void*)` → X11 WId
  3. `QWindow.fromWinId(wid)` → `QWidget.createWindowContainer()`
  4. 加载失败：QLabel("RViz not available — build native/ first") 占位
- `load_config(config_path)` / `set_fixed_frame(frame)` / `cleanup()`

**MainWindow(QMainWindow)**（约 320 行）：
- `__init__` 调用链：`_init_window()` → `_init_rviz()` → `_init_menu_and_toolbar()` → `_init_central_widget()` → `_init_status_bar()` → `_init_mqtt()` → `_init_startup_sequence()`
- `_init_window()`：标题 "ROS Ground Station"，1600×900 默认
- `_init_rviz()`：创建 RvizWidget，调 `load_config("config/default.rviz")`
- `_init_menu_and_toolbar()`：
  - 菜单：连接(连接/断开/退出) | 机器人(发现/全部急停) | 录制(开始/停止) | 视图(重置布局/切换面板) | 帮助(关于)
  - 工具栏：连接状态(绿/红圆点) + Broker 地址 + 在线数 + 帧率 + 录制计时 + **红色急停按钮**
- `_init_central_widget()`：
  - QSplitter 三栏水平，初始比例 [250, 800, 350]
  - 左：QTabWidget("机器人" Tab=RobotListPanel+CommandPanel, "事件" Tab=EventPanel)
  - 中：RvizWidget + QDockWidget 摄像头占位
  - 右：QTabWidget("Display" | "传感器摘要" | "发送数据" | "流量" | "编队通信")
  - 左右可折叠
- `_init_status_bar()`：永久标签 — 话题数 | MQTT 收发 | 录制(●/○) | ROS Master(✓/✗)
- `_init_mqtt()`：创建 MqttClient，连接 Signal→Slot（`_on_mqtt_connected/disconnected/error/robot_status/robot_event/cmd_ack`）
- `_init_startup_sequence()`：加载 `transmit_config.yaml` → 遍历恢复订阅 → 逐条发 `station/topic/request`
- `closeEvent`：MqttClient 断开 → RViz cleanup → accept

---

## 任务 6：qt-frontend/mqtt_client.py

**新建文件**：`qt-frontend/mqtt_client.py`（约 280 行）

### MqttSignals(QObject)（~12 个 Signal）
- `connected()`, `disconnected()`, `connection_error(str)`
- `message_received(str, object)` — (mqtt_topic, Message)
- `status_received(str, dict)` — (robot_id, status_data)
- `event_received(str, dict)` — (robot_id, event_data)
- `cmd_ack_received(str, dict)` — (robot_id, ack_data)
- `sensor_data_received(str, str, object)` — (robot_id, sensor_name, payload)
- `topic_response_received(str, dict)` — (robot_id, response_data)
- `config_response_received(str, dict)` — (robot_id, config_data)
- `discover_response_received(str, dict)` — (robot_id, response_data)

### MqttClient 类
- `__init__(broker_host, broker_port, client_id)`：
  - 初始化参数、`self.signals = MqttSignals()`、`self._lock = threading.Lock()`
- `connect()` → paho Client(VERSION2) → 设置回调 → `loop_start()` → `connect()`
- `disconnect()` → `loop_stop()` + `disconnect()`
- `subscribe(topic, qos)` / `publish(topic, payload, qos)`
- `publish_message(message: Message)` — 按 dst + type 路由 MQTT topic
- `send_discover()` → 发布 `station/discover`
- `send_cmd(robot_id, cmd_data)` → 发布 `robot/{id}/cmd`
- `send_topic_request(robot_id, req_data)` → 发布 `station/topic/request`
- `send_emergency_stop(robot_ids)` → 遍历发 velocity(0,0) + mode(stop)
- `send_config_sync(robot_id, config_data)` → `station/{id}/config/sync`
- `send_config_query(robot_id)` → `station/{id}/config/query`

### paho 回调（在 paho 网络线程，只 emit Signal）：
- `_on_connect(client, userdata, flags, rc, props)`：
  - rc=0 成功 → 订阅通配符：
    - `robot/+/status` (qos=1), `robot/+/event` (qos=1)
    - `robot/+/cmd/ack` (qos=1), `robot/+/sensor/#` (qos=0)
    - `station/topic/response/+` (qos=1)
    - `station/+/config/response` (qos=1)
  - emit `connected`
  - rc≠0 → emit `connection_error(str(rc))`
- `_on_disconnect()` → emit `disconnected`
- `_on_message(client, userdata, msg)` → `Message.from_json()` → `parse_robot_topic()` / `parse_station_topic()` 分发 → emit 对应 Signal

---

## 任务 7：左侧栏面板（3 个文件，约 500 行）

### `qt-frontend/panels/robot_list_panel.py`（约 180 行）
- `RobotInfo` dataclass：robot_id, online, battery, mode, position, velocity, last_seen, subscriptions_count
- QPushButton("发现机器人") + QTreeWidget(5 列：状态灯/ID/电量/模式/订阅数)
- 心跳超时(30s)自动标灰离线
- 下方 QGroupBox 详情：位姿(x,y,θ)、速度(linear,angular)、电量条(ProgressBar)
- 空状态显示"未发现机器人"
- Signal: `robot_selected(str)`, `robot_deselected()`
- Slot: `on_status_received`, `on_discover_response`, `on_heartbeat_timer`
- `selected_robot() -> Optional[str]` / `get_online_robots() -> List[str]` 属性
- QTreeWidgetItem 自定义颜色：在线=绿●，离线=灰○

### `qt-frontend/panels/command_panel.py`（约 180 行）
- QComboBox 选目标机器人（同步自 RobotListPanel）
- QGroupBox("速度控制")：线速度 QSlider(-100~100→-1.0~1.0) + 角速度 + 当前值 QLabel + "发送速度"按钮
- QGroupBox("模式控制")：手动/自动/停止/急停(红色大按钮)/回家 按钮
- 校验：未选目标禁用发送；急停无需选中目标
- Signal: `command_sent(robot_id, action, params)`
- Slot: `on_robot_selected`, `on_robot_list_changed`, `on_cmd_ack`
- 滑块映射：`_slider_to_value(int) -> float`, `_value_to_slider(float) -> int`

### `qt-frontend/panels/event_panel.py`（约 140 行）
- QComboBox 机器人筛选(全部/robot_001/...) + QListWidget 事件列表
- 四级颜色：CRITICAL=深红白字 / ERROR=红背景 / WARNING=橙背景 / INFO=默认
- 格式：`[HH:MM:SS] [ROBOT_ID] [LEVEL] CODE: message`，tooltip 显示 details
- QCheckBox("自动滚动") + QPushButton("清空")
- 上限 1000 条，超出自动裁剪最早的
- 右键菜单：复制消息 / 复制全部 / 清空
- 纯逻辑可测方法：`_level_to_color(level) -> QColor`, `_format_event(event) -> str`, `_trim_events(max_count)`

---

## 任务 8：右侧栏面板（5 个文件，约 810 行）

### `qt-frontend/panels/sensor_summary_panel.py`（约 120 行）
- 选中已订阅话题后实时摘要：
  - LaserScan：ranges 数、距离范围、角度、丢帧
  - Image/CompressedImage：分辨率、JPEG质量、帧率(5s均值)、压缩比
  - Odometry：位姿(x,y,θ)、10帧轨迹线、child_frame_id
  - PointCloud2：点数、体素、XYZ范围、帧率
  - Imu：角速度、线加速度、协方差
- QTextBrowser 格式化展示
- Slot: `on_sensor_data_received(robot_id, sensor_name, data)`
- 纯逻辑方法：`_summarize_laserscan(data)`, `_summarize_image(data)`, `_summarize_odometry(data)` 等

### `qt-frontend/panels/data_sender_panel.py`（约 100 行）
- QComboBox 目标机器人 + QLineEdit ROS 话题 + QTextEdit JSON 内容
- QPushButton("发送 JSON") / QPushButton("发送二进制(选择文件)")
- JSON 格式校验（`json.loads` try/except，失败标红）
- 单文件选择对话框 QFileDialog

### `qt-frontend/panels/traffic_monitor.py`（约 130 行）
- QTableWidget：列=[话题, 机器人, 传输方式, 带宽(PogressBar), 频率(Hz)]
- 底部 QLabel("总带宽: X.XX MB/s")
- QComboBox 刷新间隔(0.5/1/2/5s) + QPushButton("重置计数")
- `BandwidthEntry` dataclass：topic, robot_id, bytes_received, last_bytes, last_time, current_bps
- QTimer 定时调用 `_update_stats()`：EMA 平滑计算各话题带宽
- Slot: `on_sensor_data_received` → 累计字节
- 纯逻辑方法：`_calculate_bandwidth(entry) -> float`, `_ema_smooth(old, new, alpha=0.3) -> float`

### `qt-frontend/panels/topic_config_panel.py`（约 280 行）
- QComboBox 选目标机器人 + QTableWidget 已订阅表：[话题, 类型, 频率上限, 传输, 状态]
  - 状态：pending(灰) / active(绿) / failed(红) / inactive(灰)
- 按钮行：[+ 添加话题] [删除] [保存配置] [下发配置到机器人] [从机器人拉取话题]
- QGroupBox("添加/编辑话题") 可折叠折叠：
  - QLineEdit ROS 话题名(必须以/开头)
  - QComboBox ROS 类型(预填常见类型+手动输入+从机器人拉取)
  - QComboBox 传输层级(AUTO/LIGHT mqtt_json/MEDIUM mqtt_binary/HEAVY http_stream)
  - QDoubleSpinBox 频率上限(0=不限)
  - 压缩选项(仅MEDIUM/HEAVY显示)：JPEG质量、缩放宽高、体素大小
  - QComboBox QoS
  - [确认] [取消]
- 启动恢复：加载 `transmit_config.yaml` → 发 config/query → 对比冲突对话框
- 纯逻辑方法：`_validate_topic(topic)`, `_validate_msg_type(msg_type)`, `_transport_from_tier(tier)`
- `SubscriptionEntry` dataclass：topic, msg_type, freq_limit, transport, status, compression

### `qt-frontend/panels/fleet_comm_panel.py`（约 180 行）
- QTableWidget 通信规则：[源机器人, 目标, 话题, 类型, 频率, 状态, 操作]
  - 状态：●传输中 / ○已停止
- 按钮行：[+添加规则] [删除] [暂停/恢复] [下发全部] [拉取当前]
- QGroupBox("添加/编辑规则")：
  - QComboBox 源 + QComboBox 目标(支持多选) + QLineEdit 话题 + QComboBox 类型
  - QDoubleSpinBox 频率上限
  - QRadioButton 用途：位置共享/导航目标/自定义/点云重量
  - QComboBox QoS
  - [确认] [取消]
- 规则 → `station/config/sync` 下发 → Agent 创建 robot-to-robot 订阅
- 持久化到 `transmit_config.yaml` 的 `fleet_rules`
- 纯逻辑方法：`_validate_fleet_rule(src, dst, topic) -> bool`

### `qt-frontend/panels/__init__.py`
- 导出所有面板类：RobotListPanel, CommandPanel, EventPanel, SensorSummaryPanel, DataSenderPanel, TrafficMonitor, TopicConfigPanel, FleetCommPanel

---

## 任务 9：配置文件与启动脚本（5 个文件，约 120 行）

### `qt-frontend/config/default.rviz`（约 30 行 YAML）
```yaml
Panels:
  - Class: rviz/Displays / Name: Displays
  - Class: rviz/Views / Name: Views
Visualization Manager:
  Displays:
    - Class: rviz/Grid / Name: Grid / Enabled: true
    - Class: rviz/TF / Name: TF / Enabled: true
  Global Options:
    Fixed Frame: map
    Frame Rate: 30
  Views:
    Current:
      Class: rviz/Orbit / Distance: 10 / Focal Point: [0, 0, 0]
```

### `qt-frontend/config/transmit_config.yaml`（初始空模板）
```yaml
robots: {}
```

### `qt-frontend/scripts/start.sh`（约 60 行）
- 前置检查：Python≥3.8、`librviz_widget.so` 存在可加载、roscore 可达(`rostopic list`)、mosquitto 运行中(`pgrep mosquitto`)、`transmit_config.yaml` 存在
- source `/opt/ros/noetic/setup.bash`
- 启动 `bridge/mqtt_ros_bridge.py`（后台）
- 启动 `python3 qt-frontend/main.py`
- trap SIGINT 清理：kill bridge + pkill main.py

### `qt-frontend/scripts/stop.sh`（约 10 行）
```bash
pkill -f "qt-frontend/main.py" 2>/dev/null || true
pkill -f "mqtt_ros_bridge.py" 2>/dev/null || true
```

### `qt-frontend/launch/station.launch`（约 20 行 roslaunch XML）
- `<node>` bridge `mqtt_ros_bridge.py`
- `<node>` qt_frontend `main.py` (type=, no ROS node needed)

---

## 任务 10：测试（3 个文件，约 620 行）

### `tests/test_mqtt_client.py`（约 250 行，~15 测试）
- Mock `paho.mqtt.client.Client`
- TestMqttClientInit：默认参数正确、signals 实例化
- TestMqttConnect：`connect()` 调 paho、rc=0 通配符订阅 6 个话题、rc≠0 emit error
- TestMqttDisconnect：`disconnect()` 调 `loop_stop()` + `disconnect()`
- TestMqttPublish：`publish()` / `subscribe()` 参数正确
- TestOnMessageStatus：status topic → `status_received` signal 数据正确
- TestOnMessageEvent：event topic → `event_received` signal
- TestOnMessageCmdAck：cmd_ack topic → `cmd_ack_received` signal
- TestOnMessageSensor：sensor topic → `sensor_data_received` signal
- TestOnMessageTopicResponse：station response → `topic_response_received` signal
- TestOnMessageConfigResponse：config response → `config_response_received` signal
- TestSendEmergencyStop：每台机器人 velocity(0,0)+mode(stop)，topic 正确
- TestSendCmd：topic=`robot/{id}/cmd` 且 payload 正确
- TestSendDiscover / TestSendTopicRequest / TestSendConfigSync

### `tests/test_panels.py`（约 350 行，~20 测试）— 纯逻辑，无 QWidget
- TestRobotInfo：dataclass 字段、在线/离线、30s 超时判定
- TestCommandPanel：滑块映射(-100→-1.0, 0→0, 100→1.0)、未选目标校验、急停 payload 包含 velocity(0,0)+mode(stop)
- TestTopicConfigPanel：
  - SubscriptionEntry dataclass
  - topic 必须以 `/` 开头校验（`_validate_topic`）
  - msg_type 必须含 `/` 校验（`_validate_msg_type`）
  - 频率≥0 校验
  - LIGHT→mqtt_json, MEDIUM→mqtt_binary, HEAVY→http_stream 映射
  - 状态转换 pending→active, active→inactive
- TestEventPanel：等级→颜色映射、格式化字符串 `[HH:MM:SS] [ID] [LEVEL] CODE: msg`、超 1000 条裁剪保留最新 1000
- TestFleetCommPanel：源≠目标、topic 必须以 `/` 开头
- TestTrafficMonitor：BandwidthEntry dataclass、带宽计算(bytes/time_delta)、EMA 平滑、总带宽求和

### `tests/conftest.py`（约 20 行）
- 新增 `mqtt_signals` fixture：创建 MqttSignals 实例
- 新增 `sample_message_factory` fixture：`MessageFactory(src="test_qt")`

---

## 任务 11：CLAUDE.md 与文档

**修改文件**：`CLAUDE.md`

- 目录结构新增 `qt-frontend/` 分支
- 架构图更新：`Vue 3 Frontend` → `PyQt5 Frontend (Qt+Rviz)`
- 新增构建命令：`cd qt-frontend/native && mkdir build && cd build && cmake .. && make -j$(nproc)`
- 新增启动命令：`./qt-frontend/scripts/start.sh`
- 更新"关键设计决策"：Qt Signal/Slot 线程安全、ctypes 嵌入 RViz、QSplitter 三栏布局

---

## 依赖关系

```
 任务1 ─┬─► 任务5(main_window) ─► 任务7(左侧面板) ─┬─► 任务10(测试) ─► 任务11(文档)
 任务2 ─┤                                          │
 任务3 ─┤                                          ├─────────────────┘
 任务4 ─┤                                          │
        └─► 任务6(mqtt_client) ─► 任务8(右侧面板) ─┘
                                       │
                                       └──► 任务9(配置脚本)
```

- 任务 1-4 为基础层，可并行
- 任务 5-6 为 Qt 核心层，依赖基础层完成
- 任务 7-8 为面板层，依赖 Qt 核心层
- 任务 9 可与面板并行
- 任务 10-11 收尾

---

## 复用的现有模块（零改动）

| 模块 | 用途 |
|------|------|
| `protocol/topic_registry.py` | TopicTier → TransportType 映射 |
| `protocol/messages.py` | Message/MessagFactory 序列化 |
| `protocol/topics.py` | MQTT topic 命名、parse_robot_topic |
| `bridge/mqtt_ros_bridge.py` | MQTT↔ROS 桥接（独立进程） |
| `bridge/dict_to_ros_msg.py` | dict→ROS 消息转换 |
| `agent/base_agent.py` | 机器人端核心逻辑 |
| `agent/topic_handler.py` | LIGHT/MEDIUM/HEAVY 分层处理 |
| `agent/rate_limiter.py` | 按话题限频 |

## 关键设计决策

| 决策 | 选择 |
|------|------|
| MQTT 线程安全 | Qt Signal/Slot 桥接（paho 回调→emit→主线程 slot），不手动 QTimer 轮询 |
| RViz 嵌入 | `extern "C"` + `ctypes.CDLL` + `QWindow.fromWinId` + `createWindowContainer` |
| 布局 | QSplitter 三栏，左右可折叠，左侧 QTabWidget 叠放面板 |
| 右侧面板 | QTabWidget 分离（Display/传感器摘要/发送数据/流量/编队） |
| 配置持久化 | 地面站 `transmit_config.yaml` + Agent `config.yaml` 双向同步 |
| Python 兼容 | Python 3.8+，`from __future__ import annotations`，typing 用 Optional/List |
| 测试策略 | 纯逻辑单元测试 + Mock paho client，跳过 QTest/Xvfb 渲染测试 |

---

## Verification

```bash
# 1. 编译 C++ RViz 胶水库
cd qt-frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc)
nm -D librviz_widget.so | grep rviz_widget  # 确认 5 个导出符号

# 2. 安装全部依赖
pip install -e ".[qt,dev]"

# 3. 单元测试
python -m pytest tests/test_mqtt_client.py tests/test_panels.py -v

# 4. 完整测试套件
python -m pytest tests/ -v

# 5. 启动地面站（需 roscore + mosquitto + 编译好的 .so）
./qt-frontend/scripts/start.sh
```
