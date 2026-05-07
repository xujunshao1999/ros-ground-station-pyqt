# Qt+Rviz 地面站 — 方案 B 实施计划

## 背景

当前 Vue 3 前端每种 ROS 消息类型都需手写渲染代码，无法动态可视化任意话题。方案 B 用 **PyQt5 桌面应用嵌入 RViz** 替代，实现任意 ROS 话题的原生 3D 可视化。现有后端基础设施（protocol、agent、MQTT-ROS 桥接、144 个测试）已完成，直接复用。

## 架构

```
机器人 (ROS) → Agent → MQTT Broker → Python MQTT-ROS 桥接 → 本地 roscore → RViz (3D)
                                   → PyQt5 前端 (面板、MQTT 客户端)
```

- **面板/MQTT/逻辑**：Python/PyQt5（约 1500 行）
- **RViz 3D 嵌入**：C++ 胶水（约 200 行），基于 `librviz`，通过 `ctypes.CDLL` 加载
- **MQTT 线程安全**：paho-mqtt 回调 emit Qt Signal → 主线程 slot 更新 UI
- **三栏布局**：QSplitter 左（机器人+控制+事件）/ 中（RViz 3D + 摄像头 QDockWidget）/ 右（原生 Display 面板 + 传感器摘要 + 数据发送 + 流量监控）
- **菜单栏**：连接 | 机器人 | 录制 | 视图 | 帮助
- **工具栏**：连接状态 | Broker 地址 | 在线数 | 帧率 | 录制计时 | [急停按钮]
- **状态栏**：已订阅话题数 | MQTT 收发流量 | 录制状态 | ROS Master 状态

## 实施阶段

### 阶段三：C++ RvizWidget 胶水库（约 200 行，约 30 分钟）

**新建文件：**
- `qt-frontend/native/rviz_widget.h` — `extern "C"` 接口声明
  - `void* create_rviz_widget(void* parent_ptr)` — 创建 RViz RenderPanel 实例
  - `int load_config(void* widget_ptr, const char* config_path)` — 加载 .rviz 配置文件
  - `void set_fixed_frame(void* widget_ptr, const char* frame)` — 设置固定坐标系
  - `long get_window_id(void* widget_ptr)` — 返回原生窗口句柄（X11 WId），用于 PyQt5 嵌入
  - `void destroy_panel(void* widget_ptr)` — 销毁 RViz 面板释放资源
- `qt-frontend/native/rviz_widget.cpp` — 封装 `rviz::RenderPanel` + `rviz::VisualizationManager` + `rviz::DisplayGroup`，内部用 `RvizInstance` 结构体维护每个实例的 panel/manager/display_group 指针
- `qt-frontend/native/CMakeLists.txt` — Qt5 Widgets + rviz 依赖，编译 `librviz_widget.so`，C++14 标准，CMAKE_AUTOMOC ON

**编译与验证：**
```bash
cd qt-frontend/native && mkdir -p build && cd build && cmake .. && make -j$(nproc)
nm -D librviz_widget.so | grep rviz_widget  # 确认 5 个导出符号
python3 -c "import ctypes; lib=ctypes.CDLL('librviz_widget.so'); assert lib.create_rviz_widget(None)"  # 加载测试
```

### 阶段四：PyQt5 MainWindow + MQTT 客户端（约 600 行，约 1 小时）

**新建文件：**

**`qt-frontend/main.py`**（约 30 行）— QApplication 入口
- `from __future__ import annotations`
- `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` 确保能找到 protocol/bridge 包
- 加载 `config/config.yaml`
- 创建 `QApplication`，实例化 `MainWindow(config)`，调用 `app.exec_()`

**`qt-frontend/main_window.py`**（约 370 行）— QMainWindow 主窗口
- `RvizWidget(QWidget)` 内部类：
  - `load_library(lib_path)` 类方法：通过 `ctypes.CDLL` 加载 `librviz_widget.so`，设置各函数 restype/argtypes
  - `__init__`：调 `create_rviz_widget(None)` 创建 C++ 面板 → `get_window_id` 获取 WId → `QWindow.fromWinId(wid)` → `QWidget.createWindowContainer(window, self)` 嵌入
  - `load_config(config_path)`：调 C++ `load_config`
  - `set_fixed_frame(frame)`：调 C++ `set_fixed_frame`
  - `cleanup()`：调 `destroy_panel` 释放资源
  - 库加载失败时显示占位 `QLabel("RViz not available")`
- `MainWindow(QMainWindow)`：
  - `_init_window()`：标题"ROS Ground Station"，默认 1600×900
  - `_init_rviz()`：加载 C++ 库，设置库路径为 `native/build/librviz_widget.so`
  - `_init_menu_and_toolbar()`：
    - 菜单栏：文件（连接/断开/退出）| 机器人（发现/全部急停）| 录制（开始/停止）| 视图（重置布局/显示/隐藏面板）| 帮助（关于）
    - 工具栏：`QLabel` 连接状态（绿●已连接/红●已断开）+ `QLabel` Broker 地址 + `QLabel` 在线数 + `QLabel` 帧率 + `QLabel` 录制计时 + **红色大按钮 [全部急停]**（始终可见，`clicked` → 弹确认框 → 向所有在线机器人发 velocity(0,0) + mode(stop)）
  - `_init_central_widget()`：QSplitter 三栏水平分割
    - 左栏：QTabWidget（"机器人" Tab = RobotListPanel + CommandPanel，"事件" Tab = EventPanel）
    - 中栏：RvizWidget + 可选 QDockWidget 摄像头浮窗
    - 右栏：QTabWidget（"Display" Tab = RViz 原生 Display 面板嵌入,"传感器摘要" Tab = SensorSummaryPanel，"发送数据" Tab = DataSenderPanel，"流量" Tab = TrafficMonitor）
    - 初始比例 `[250, 800, 350]`，左右栏可折叠
  - `_init_status_bar()`：永久标签 — 已订阅 N 个话题 | MQTT: X MB/Y MB | 录制: ● 00:00:00 | ROS Master ✓/✗
  - `_init_mqtt()`：创建 `MqttClient`，连接各 Signal 到 slot（`_on_mqtt_connected`、`_on_mqtt_disconnected`、`_on_mqtt_error`、`_on_robot_status`、`_on_robot_event`、`_on_cmd_ack`）
  - `_init_startup_sequence()`：**启动时自动恢复订阅** — 加载 `transmit_config.yaml` → 遍历已配置话题 → 逐条发 `station/topic/request` → Agent 回复 ack → 标记 active → 自动创建对应 RViz Display（/odom+Odometry → rviz/Odometry，/scan+LaserScan → rviz/LaserScan，/camera+Image → rviz/Image，/velodyne+PointCloud2 → rviz/PointCloud2，未知类型不自动创建）
  - `closeEvent`：MqttClient 断开 → RViz cleanup → accept

**`qt-frontend/mqtt_client.py`**（约 260 行）— 线程安全 MQTT 客户端
- `MqttSignals(QObject)`：所有 Signal 在此定义（主线程创建 QObject 子类实例）
  - `connected = pyqtSignal()`
  - `disconnected = pyqtSignal()`
  - `connection_error = pyqtSignal(str)`
  - `message_received = pyqtSignal(str, object)` — (mqtt_topic, Message)
  - `status_received = pyqtSignal(str, dict)` — (robot_id, status_data)
  - `event_received = pyqtSignal(str, dict)` — (robot_id, event_data)
  - `cmd_ack_received = pyqtSignal(str, dict)` — (robot_id, ack_data)
  - `sensor_data_received = pyqtSignal(str, str, object)` — (robot_id, sensor_name, payload)
  - `topic_response_received = pyqtSignal(str, dict)` — (robot_id, response_data)
  - `config_response_received = pyqtSignal(str, dict)` — (robot_id, config_data)
- `MqttClient` 类：
  - `__init__(broker_host, broker_port, client_id)`：初始化参数，创建 `self.signals = MqttSignals()`，`self._lock = threading.Lock()`
  - `connect()`：创建 paho Client(VERSION2)，设置回调，`reconnect_delay_set(1, 30)`，`connect()` + `loop_start()`
  - `disconnect()`：`loop_stop()` + `disconnect()`
  - `subscribe(topic, qos)` / `publish(topic, payload, qos)`
  - `publish_message(message: Message)`：根据 message.type 解析目标 MQTT topic 并发布
  - `send_discover()`：发布到 `station/discover`
  - `send_cmd(robot_id, cmd_data)`：发布到 `robot/{id}/cmd`
  - `send_topic_request(robot_id, request_data)`：发布到 `station/topic/request`
  - `send_emergency_stop(robot_ids)`：遍历发 velocity(0,0) + mode(stop)
  - `send_config_sync(robot_id, config_data)`：发布到 `station/config/sync`
  - `send_config_query(robot_id)`：发布到 `station/config/query`
  - **paho 回调（在 paho 网络线程执行，只 emit Signal，不直接操作 UI）**：
    - `_on_connect`：连接成功 → 订阅通配符话题（`robot/+/sensor/#` qos=0、`robot/+/status` qos=1、`robot/+/event` qos=1、`robot/+/cmd/ack` qos=1、`station/topic/response/+` qos=1、`station/config/response/+` qos=1）→ emit `connected`
    - `_on_disconnect`：非正常断开 → emit `disconnected`
    - `_on_message`：解析 JSON → `Message.from_json(text)` → `parse_robot_topic(msg.topic)` 按类型分发 → emit 对应 Signal（status_received / event_received / cmd_ack_received / sensor_data_received / topic_response_received / config_response_received）
  - `_resolve_topic(message)`：根据 message.type 路由到正确的 MQTT topic
  - `is_connected` property：线程安全读取连接状态

**`qt-frontend/config/config.yaml`**（约 20 行）
```yaml
mqtt:
  broker_host: "localhost"
  broker_port: 1883
  client_id: "qt_frontend"
ros:
  master_uri: "http://localhost:11311"
  default_max_freq: 30.0
rviz:
  default_config: "config/default.rviz"
  fixed_frame: "map"
```

**验证：** 窗口显示三栏布局，MQTT 连接后状态栏变绿，急停按钮可发指令（`mosquitto_sub -t "robot/+/cmd"` 验证），启动时 transmit_config.yaml 中已有订阅自动恢复。

### 阶段五：面板（约 1200 行，约 1.5 小时）

#### 左侧栏面板

**`qt-frontend/panels/robot_list_panel.py`**（约 180 行）
- `RobotInfo` dataclass：robot_id, online, battery, mode, position, velocity, last_seen, subscriptions_count
- 上方 `QPushButton("发现机器人")` → 触发 `send_discover()`
- `QTreeWidget`：列 = [状态灯, 机器人ID, 电量, 模式, 订阅数]
  - ● 绿色 = 在线，○ 灰色 = 离线（30 秒心跳超时自动标灰）
  - 电量 `QProgressBar` 或百分比文本
  - 模式：auto/manual/stop/error
- 下方 `QGroupBox("选中机器人详情")` — RobotStatusPanel：
  - 选中机器人的位姿(x, y, θ)、速度(linear, angular)、电量条
- 空状态：树显示"未发现机器人"
- Signal: `robot_selected(str)` / `robot_deselected()`
- Slot: `on_status_received(robot_id, data)` → 更新树节点；`on_mqtt_connected()` → 自动发现；`on_discover_response(robot_id, topics)` → 添加新机器人
- `selected_robot() -> Optional[str]` / `get_online_robots() -> List[str]` 供其他面板调用

**`qt-frontend/panels/command_panel.py`**（约 180 行）
- `QComboBox` 选择目标机器人（从 RobotListPanel 同步列表）
- `QGroupBox("速度控制")`：
  - 线速度 `QSlider`（水平，-100~100 → -1.0~1.0 m/s）+ `QLabel` 显示当前值 + `QPushButton("发送速度")`
  - 角速度 `QSlider`（水平，-100~100 → -1.0~1.0 rad/s）+ `QLabel` 显示当前值
- `QGroupBox("模式控制")`：
  - `QPushButton("手动")` / `QPushButton("自动")` / `QPushButton("停止")` / `QPushButton("急停")`（红色大按钮，仅选中机器人）
  - `QPushButton("回家")`
- 校验：未选目标机器人时禁用发送按钮；急停无需选中目标也生效
- Signal: `command_sent(robot_id, action, params)`
- Slot: `on_robot_selected(robot_id)` / `on_robot_list_changed(robot_ids)` / `on_cmd_ack(robot_id, ack_data)` 更新指令状态

**`qt-frontend/panels/event_panel.py`**（约 140 行）
- `QComboBox` 机器人筛选（全部 / robot_001 / robot_002 ...）
- `QListWidget` 事件列表：
  - CRITICAL：深红背景白字
  - ERROR：红背景
  - WARNING：黄/橙背景
  - INFO：默认背景
  - 格式：`[HH:MM:SS] [ROBOT_ID] [LEVEL] CODE: message`
  - tooltip 显示完整 details
- `QCheckBox("自动滚动到最新")` + `QPushButton("清空")`
- 上限 1000 条，超出自动裁剪最早条目
- 右键菜单：复制消息 / 复制全部 / 清空
- Slot: `on_event_received(robot_id, event_data)` → 创建 `QListWidgetItem` 并插入

**`qt-frontend/panels/topic_config_panel.py`**（约 280 行）
- `QComboBox` 选择目标机器人
- `QTableWidget` 已配置订阅表：列 = [话题名, 消息类型, 频率上限, 传输方式, 状态]
  - 状态：pending（灰色）/ active（绿色）/ failed（红色）/ inactive（灰色）
- 按钮行：`[+ 添加话题]` `[删除]` `[保存配置]`
- `QGroupBox("添加/编辑话题")`（可折叠）：
  - `QLineEdit` ROS 话题名（必须以 `/` 开头）
  - `QComboBox` ROS 类型（下拉包含常见类型 + 可手动输入；点击"从机器人拉取"后自动填入机器人的 available_topics）
  - `QComboBox` 传输层级（AUTO / LIGHT mqtt_json / MEDIUM mqtt_binary / HEAVY http_stream）
  - `QDoubleSpinBox` 频率上限 Hz（0 = 不限）
  - `QGroupBox("压缩选项")`（传输为 MEDIUM/HEAVY 时显示）：
    - `QSpinBox` JPEG 质量 1-100
    - `QSpinBox` 缩放宽度 × `QSpinBox` 缩放高度
    - `QDoubleSpinBox` 体素大小 m
  - `QComboBox` QoS（AtMostOnce / AtLeastOnce）
  - `QPushButton("确认")` / `QPushButton("取消")`
- 按钮行：`[下发配置到机器人]` `[从机器人拉取话题列表]`
- **工作流**：
  1. 点击"从机器人拉取" → 发 MQTT discover → Agent 返回 `available_topics`（topic + msg_type）→ 自动填入类型下拉
  2. 点击"添加话题" → 填写表单 → 确认 → 添加到表格，状态 pending
  3. 点击"下发配置" → 遍历表格 → 逐条发 `station/topic/request`（action=subscribe）→ Agent 创建 ROS Subscriber → 回复 topic_response → 状态变 active → 同步发 `station/config/sync` 到 Agent 持久化
  4. 配置自动写 `transmit_config.yaml`
- **启动恢复**：MainWindow 启动时调用 `_load_config()` 读取 transmit_config.yaml → 恢复订阅
- Slot: `on_topic_response_received(robot_id, response)` → 更新状态
- `_validate_topic(topic)` / `_validate_msg_type(msg_type)` / `_transport_from_tier(tier)` 纯逻辑方法（可单独测试）

#### 右侧栏面板

**`qt-frontend/panels/sensor_summary_panel.py`**（约 120 行）
- 选中某个已订阅话题后，显示最新一帧数据的实时摘要
- 按 Display 类型显示不同内容：
  - LaserScan：ranges 数量、最近/最远距离(m)、扫描角度范围、丢帧计数
  - Image/CompressedImage：分辨率（宽×高）、JPEG 质量、实际帧率（近 5 秒均值）、压缩比
  - Odometry：最新位姿(x, y, θ)、最近 10 帧轨迹线预览、child_frame_id
  - PointCloud2：点数、体素大小(m)、XYZ 范围、实际帧率(Hz)
  - Imu：角速度(x, y, z) rad/s、线加速度(x, y, z) m/s²、协方差标志
- Slot: `on_sensor_data_received(robot_id, sensor_name, data)` → 解析并更新摘要文本
- 用 `QTextBrowser` 或格式化的 `QGroupBox` 展示

**`qt-frontend/panels/data_sender_panel.py`**（约 100 行）
- `QComboBox` 目标机器人
- `QLineEdit` ROS 话题名
- `QTextEdit` 内容输入区（JSON 模式）或 `QPushButton` 选择文件（二进制模式）
- `QPushButton("发送 JSON")` / `QPushButton("发送二进制")`
- 向机器人任意话题推送数据
- Slot: `on_robot_list_changed(robot_ids)` → 更新目标下拉

**`qt-frontend/panels/traffic_monitor.py`**（约 130 行）
- `QTableWidget`：列 = [话题, 机器人, 传输方式, 带宽, 频率]
  - 带宽列用 `QProgressBar`（0 ~ 可配置最大值, 如 1 MB/s）
- 底部 `QLabel("总带宽: X.XX MB/s")`
- `QComboBox` 刷新间隔（0.5s / 1s / 2s / 5s）
- `QPushButton("重置计数")`
- `BandwidthEntry` dataclass：topic, robot_id, bytes_received, last_bytes, last_time, current_bps
- `QTimer` 定时调用 `_update_stats()`：用指数移动平均计算各话题带宽，更新 ProgressBar
- Slot: `on_sensor_data_received(robot_id, sensor_name, data)` → 累计字节数
- `_calculate_bandwidth(entry)` → float bps（纯逻辑，可单独测试）

**`qt-frontend/panels/fleet_comm_panel.py`**（约 180 行）
- `QTableWidget` 已有通信规则：列 = [源机器人, 目标机器人, 话题, 类型, 频率, 状态, 操作]
  - 状态：● 传输中 / ○ 已停止
- 按钮行：`[+ 添加规则]` `[删除]` `[暂停/恢复]`
- `QGroupBox("添加/编辑通信规则")`：
  - `QComboBox` 源机器人
  - `QComboBox` 目标机器人（支持多选 `[全选]`）
  - `QLineEdit` ROS 话题
  - `QComboBox` 消息类型
  - `QDoubleSpinBox` 频率上限 Hz
  - `QRadioButton` 数据用途：位置共享 / 导航目标 / 自定义传感器数据 / 点云重量数据(HTTP 流)
  - `QComboBox` QoS
  - `QPushButton("确认")` / `QPushButton("取消")`
- 按钮行：`[下发全部规则]` `[拉取当前规则]`
- **工作流**：
  1. 用户添加规则：`robot_001` 的 `/odom` 以 2Hz 发给 `robot_002`
  2. 地面站发 MQTT `station/config/sync` 给 `robot_001` 的 Agent，包含 fleet_rules
  3. Agent 的 `_handle_fleet_config()` 按规则：收到 `/odom` 后额外发布到 `robot/robot_001/to/robot_002`（FLEET_DATA）
  4. `robot_002` 的 Agent 收到 `robot/+/to/robot_002` → 发布到本地 ROS `/fleet/from_robot_001/odom`
  5. 重量数据（点云）走 HTTP 流 + meta 信令通道
- 规则持久化到 `transmit_config.yaml` 的 `fleet_rules` 字段

**`qt-frontend/panels/__init__.py`** — 导出所有面板类

**验证：** 各面板正确显示在对应标签页中，MQTT 数据驱动面板更新，指令发送可通过 `mosquitto_sub -t "robot/+/cmd"` 验证字节内容，配置存盘后重启可恢复。

### 阶段六：RViz 配置 + 启动集成 + Agent 端改动 + 测试（约 30 分钟）

#### 配置文件

**`qt-frontend/config/default.rviz`**（约 30 行）
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

**`qt-frontend/config/transmit_config.yaml`**（初始空模板）
```yaml
robots: {}
```

#### 启动脚本

**`qt-frontend/scripts/start.sh`**（约 60 行）
- 前置检查：
  1. Python 版本 ≥ 3.8
  2. `librviz_widget.so` 存在且可被 `ctypes.CDLL` 加载
  3. `roscore` 可达（`rostopic list` 不报错）
  4. Mosquitto broker 运行中（`pgrep mosquitto`）
  5. `transmit_config.yaml` 存在
- source `/opt/ros/noetic/setup.bash`
- 启动 `bridge/mqtt_ros_bridge.py`（后台）
- 启动 `python3 qt-frontend/main.py`
- trap SIGINT 清理

**`qt-frontend/scripts/stop.sh`**（约 10 行）
```bash
pkill -f "qt-frontend/main.py" 2>/dev/null || true
pkill -f "mqtt_ros_bridge.py" 2>/dev/null || true
```

**`qt-frontend/launch/station.launch`**（约 20 行）
- roslaunch：启动 mqtt_ros_bridge 节点 + qt_frontend 节点

#### Agent 端改动

**`agent/base_agent.py` 新增方法**（约 60 行）：
- `_handle_config_sync(msg)` — 接收 `station/config/sync`，解析 subscriptions 和 fleet_rules，写入 `self.config`，持久化到 `agent/config.yaml`（合并已有字段），回复 config_sync_ack
- `_handle_config_query(msg)` — 接收 `station/config/query`，返回 `station/config/response`（包含当前 subscriptions 和 fleet_rules）
- `_load_subscriptions_from_config()` — 启动时调用，遍历 `self.config.subscriptions`，逐条调用 `self._handle_topic_request()` 恢复订阅；遍历 `self.config.fleet_rules`，逐条恢复编队规则
- 在 `_on_connect` 中新增订阅 `station/config/sync` 和 `station/config/query`
- 在 MQTT `_on_message` 路由中新增 `station/config/sync` → `_handle_config_sync()`、`station/config/query` → `_handle_config_query()`

**`agent/config.yaml` 新增字段**：
- `subscriptions`：`List[dict]`，每个 dict 含 topic/msg_type/freq_limit/transport/compression
- `fleet_rules`：`List[dict]`，每个 dict 含 topic/msg_type/target/freq_limit/transport

**`agent/base_agent.py` 的 `AgentConfig` dataclass** 需同步新增对应字段及默认值。

**新增 MQTT topic**（`protocol/topics.py` 新增函数）：
- `station_config_sync(robot_id)` → `station/{robot_id}/config/sync`
- `station_config_query(robot_id)` → `station/{robot_id}/config/query`
- `station_config_response(robot_id)` → `station/{robot_id}/config/response`

**`protocol/messages.py` 新增**：
- `MessageType` 枚举新增 `CONFIG_SYNC = "config_sync"`、`CONFIG_QUERY = "config_query"`、`CONFIG_RESPONSE = "config_response"`

#### 配置不一致时的冲突处理对话框

TopicConfigPanel 启动时：
1. 加载本地 `transmit_config.yaml`
2. 发 `station/config/query` 给各在线机器人
3. Agent 返回 `config/response`（当前 subscriptions）
4. 对比本地 vs Agent 配置，分类为：
   - 一致 → 直接标记 active
   - 参数不一致 → 弹冲突项（显示地面站值 vs 机器人值，可选"使用地面站"/"使用机器人"）
   - 仅地面站有 → 标记"待下发"
   - 仅 Agent 有 → 标记"待拉取"
   - Agent 话题不存在 → 标记"不可用"
5. 弹出 `QDialog` 配置对比对话框，用户逐条或一键选择 → 下发/拉取 → 同步完成
6. 默认策略：地面站配置为准，无 GUI 模式时自动覆盖机器人端

#### 录制与回放

- 工具栏录制按钮（红色圆点 ▶⏺）→ 发 REST 给 Station 后端（FastAPI `station/backend/main.py`）→ Station 将所有已订阅话题的 MQTT 数据写 SQLite（复用 `station/backend/recorder.py` + `station/backend/database.py`）
- 回放：加载 SQLite → Python 桥按原始时间戳逐帧发布到本地 roscore → RViz 重新渲染
- Station 后端作为独立录制服务运行（FastAPI），Qt 前端通过工具栏按钮控制

#### 测试

**`tests/test_mqtt_client.py`**（约 15 个测试，250 行）
- mock `paho.mqtt.client.Client`
- test_init：默认参数正确
- test_connect：`connect()` 调用 paho client
- test_subscribe / test_publish / test_disconnect
- test_on_connect_success：模拟 rc=0 回调 → connected signal 发射 + 通配符订阅
- test_on_connect_failure：模拟 rc≠0 → connection_error signal 发射
- test_on_disconnect：模拟断开 → disconnected signal
- test_on_message_status：模拟收到 status 消息 → status_received signal 发射且数据正确解析
- test_on_message_event / test_on_message_cmd_ack / test_on_message_sensor / test_on_message_topic_response / test_on_message_config_response
- test_send_emergency_stop：验证 velocity(0,0)+mode(stop) 发到所有机器人
- test_send_cmd：验证 topic 和 payload 正确

**`tests/test_panels.py`**（约 20 个测试，350 行）— 纯逻辑测试，不涉及 Qt Widget 渲染
- TestRobotListPanel：RobotInfo dataclass / 在线离线计数 / 空状态文本 / 30秒心跳超时判定
- TestCommandPanel：滑块值映射(-100~100 → -1.0~1.0) / 未选目标校验 / 急停 payload
- TestTopicConfigPanel：SubscriptionEntry dataclass / topic 必须以 / 开头校验 / msg_type 必须含 / 校验 / 频率 ≥ 0 校验 / LIGHT→mqtt_json, MEDIUM→mqtt_binary, HEAVY→http_stream 映射 / 状态转换 pending→active→inactive
- TestEventPanel：等级→颜色映射 / 事件格式化字符串 / 超 1000 条裁剪
- TestFleetCommPanel：规则校验（源≠目标, topic 合法）
- TestTrafficMonitor：带宽计算(bytes/time_delta) / 总带宽求和 / EMA 平滑

**`tests/test_e2e.sh`**（约 80 行）— 4 个集成测试场景
1. 机器人发现：启动 → RobotListPanel 显示在线机器人
2. 话题订阅：发 subscribe → status 变 active → roscore 出现对应话题
3. 指令控制：发 velocity → Agent 回复 cmd_ack → ack 状态更新
4. 传感器数据流：订阅 /odom → 桥接还原 → `rostopic echo /robot_001/odom` 有数据

#### pyproject.toml 改动

- `dependencies` 新增 `"pyqt5>=5.15"`
- `[project.optional-dependencies]` 新增 `qt = ["pyqt5>=5.15"]`
- `[tool.setuptools.packages.find].include` 新增 `"qt-frontend*"`、`"bridge*"`

## 关键设计决策

| 决策 | 选择 |
|------|------|
| MQTT 线程安全 | Qt Signal/Slot 桥接（paho 回调 → emit signal → 主线程 slot 更新 UI），不手动 QTimer 轮询 |
| RViz 嵌入方式 | `extern "C"` + `ctypes.CDLL` + `QWindow.fromWinId` + `createWindowContainer` |
| 面板布局 | QSplitter 三栏，左右可折叠，左侧用 QTabWidget 叠放面板节省空间 |
| 右侧面板 | QTabWidget 分离（Display tab + 传感器摘要 tab + 发送数据 tab + 流量 tab） |
| RViz 原生 vs 自定义 | 右侧 Display 树/Add 对话框/属性面板全用 RViz 原生组件（零自写代码），左侧话题传输配置是自定义的 |
| 配置持久化 | 地面站 `transmit_config.yaml`（subscriptions + fleet_rules）+ Agent `config.yaml` 同步写入 |
| 配置同步 | MQTT `station/config/sync`、`station/config/query`、`station/config/response` |
| 启动失败处理 | start.sh 前置检查（roscore + .so + mosquitto），不在 Qt 内做 graceful fallback |
| 测试策略 | 纯逻辑单元测试 + E2E shell 脚本，跳过 QTest + Xvfb 渲染测试 |
| Python 兼容 | Python 3.8+（ROS Noetic 要求），`from __future__ import annotations`，typing 用 Optional/List |
| 文件路径 | 统一使用 `pathlib.Path`，不拼接字符串路径 |

## 阶段依赖关系

```
阶段三 (C++ 胶水) ──► 阶段四 (MainWindow + MQTT) ──► 阶段五 (8 个面板) ──► 阶段六 (配置 + 脚本 + Agent改动 + 测试)
```

阶段三和阶段四可以并行（C++ 和 Python 独立）。阶段五依赖阶段四的 MainWindow 和 MqttClient。阶段六收尾整合。

## 复用的现有模块（零改动）

| 模块 | 谁用 | 用途 |
|------|------|------|
| `protocol/messages.py` | Qt + 桥接 | Message 格式、MessageFactory、序列化/反序列化 |
| `protocol/topics.py` | Qt + 桥接 | MQTT 话题命名、parse_robot_topic()、parse_station_topic() |
| `protocol/topic_registry.py` | 桥接 | 传输层级判断（LIGHT/MEDIUM/HEAVY） |
| `bridge/mqtt_ros_bridge.py` | 桥接进程 | MQTT↔ROS 双向翻译（6 进 6 出通道） |
| `bridge/dict_to_ros_msg.py` | 桥接 | 通用 dict→ROS 消息反序列化 |
| `agent/base_agent.py` | 机器人端 | 话题请求/响应、指令执行、心跳上报、MQTT 连接管理 |
| `agent/topic_handler.py` | 机器人端 | LIGHT/MEDIUM/HEAVY 分层处理（压缩、序列化） |
| `agent/rate_limiter.py` | 机器人端 | 按话题独立限频 |
| `agent/ros_msg_converter.py` | 机器人端 | 通用 `ros_msg_to_dict()` (`__slots__` 内省) |
| `station/backend/recorder.py` | 录制服务 | SQLite 数据录制 |
| `station/backend/database.py` | 录制服务 | SQLite 存储 |
