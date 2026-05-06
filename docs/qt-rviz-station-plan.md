# Qt+Rviz 地面站前端 — 实施方案

## 背景

当前 Vue 前端有几个根本限制：
- 每种 ROS 消息类型都要手写渲染代码（ImageViewer、PointCloudViewer、LaserScan 表格...）
- 无法动态发现和可视化任意的 ROS 话题
- Agent 端有 `ros_msg_to_dict()` 但没有对应的逆操作把数据还原成 ROS 消息
- 加一种新传感器类型就要改前端代码

目标：用嵌入 RViz 的 Qt 应用替代 Vue 前端。从 Agent 订阅的任何 ROS 话题都会被转回真正的 ROS 话题，由 RViz 原生插件渲染——不需要为每种消息类型写显示代码。

**界面布局：三栏骨架 + QDockWidget 灵活面板**

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│  [Menu: 连接 | 机器人 | 录制 | 视图 | 帮助]                                              │
│  [Toolbar: 🟢已连接 | Broker:1883 | 在线:2 | 帧率:30fps | 录制:⏺ 00:15:32 | [急停]]    │
├──────────────┬───────────────────────────────────┬────────────────────────────────────┤
│  左侧栏       │         中间 3D 可视化              │  右侧栏 (RViz 原生 Displays 面板)   │
│  (自定义 Qt)  │                                    │  (librviz 自带组件，零自写代码)      │
│              │                                    │                                    │
│ ┌──────────┐ │  ┌──────────────────────────────┐  │  ┌──────────────────────────────┐  │
│ │🤖 机器人  │ │  │                              │  │  │ 📺 Displays           [Add]│  │
│ │──────────│ │  │                              │  │  │──────────────────────────────│  │
│ │robot1 ●  │ │  │                              │  │  │  ☑ Global Options           │  │
│ │robot2 ●  │ │  │     RViz RenderPanel         │  │  │    └ Fixed Frame: map       │  │
│ │robot3 ○  │ │  │     (librviz 嵌入)           │  │  │  ☑ Grid                     │  │
│ │          │ │  │                              │  │  │  ☑ TF                       │  │
│ │[🔍 发现]  │ │  │                              │  │  │  ☑ Odometry                 │  │
│ └──────────┘ │  │                              │  │  │    └ Topic: /robot1/odom    │  │
│              │  │                              │  │  │  ☑ LaserScan                │  │
│ ┌──────────┐ │  │                              │  │  │    └ Topic: /robot1/scan   │  │
│ │⚙ 配置标签 │ │  │                              │  │  │  ☑ Image                   │  │
│ │[📡传输] │ │  │                              │  │  │    └ Topic: /robot1/camera │  │
│ │[🔗编队] │ │  │                              │  │  │  ☐ PointCloud2             │  │
│ │──────────│ │  │                              │  │  │  ☐ Path                    │  │
│ │已订阅 (3) │ │  │                              │  │  │  ☐ RobotModel              │  │
│ │/odom  10Hz│ │  │                              │  │  │  ☐ Map                     │  │
│ │/scan  10Hz│ │  │                              │  │  └──────────────────────────────┘  │
│ │/camera 5Hz│ │  │                              │  │                                    │
│ │[+添加话题] │ │  │                              │  │  ┌──────────────────────────────┐  │
│ │[💾同步]   │ │  │                              │  │  │ 📊 传感器摘要                 │  │
│ └──────────┘ │  │                              │  │  │ /robot1/scan:                │  │
│              │  │                              │  │  │   ranges:360 near:0.83m      │  │
│ ┌──────────┐ │  │                              │  │  │ /robot1/camera:              │  │
│ │🎮 控制    │ │  │                              │  │  │   640×480 12FPS JPEG 85%    │  │
│ │──────────│ │  │                              │  │  └──────────────────────────────┘  │
│ │→ [0.5]m/s│ │  │                              │  │                                    │
│ │↻ [0.1]rad│ │  │                              │  │  ┌──────────────────────────────┐  │
│ │[急停]    │ │  │                              │  │  │ 📨 发送数据                   │  │
│ │[回家]    │ │  │                              │  │  │ 目标:[robot_001▼]            │  │
│ └──────────┘ │  │                              │  │  │ 话题:[/custom/data    ]      │  │
│              │  │                              │  │  │ [发送JSON] [发送二进制]       │  │
│ ┌──────────┐ │  └──────────────────────────────┘  │  └──────────────────────────────┘  │
│ │📋 事件    │ │                                    │                                    │
│ │🔴 battery│ │  ┌──────────────────────────────┐  │                                    │
│ │🟡 pos    │ │  │ 🖼 摄像头 (QDockWidget)      │  │                                    │
│ └──────────┘ │  │  可拖到任意位置或独立窗口     │  │                                    │
│              │  └──────────────────────────────┘  │                                    │
├──────────────┴───────────────────────────────────┴────────────────────────────────────┤
│  [状态栏: 已订阅 5 个话题 | MQTT收发: 1.2MB/0.3MB | 录制: ● 00:15:32 | ROS Master ✓]    │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

**关键设计：**
- 左右侧栏用 `QSplitter`，可拖拽调整宽度，可折叠
- 右侧 Display 面板 = 原生 RViz 的 Display 面板 + 话题订阅入口 + 自定义功能按钮
- 摄像头小窗用 `QDockWidget`，可拖到任意位置或独立窗口
- 发送数据面板可以直接向机器人的任意话题推送数据（JSON 或二进制）
- 话题流量监控实时显示各话题带宽
- 底部状态栏一目了然

## 架构

```
机器人端（不动）                            地面站（Ubuntu 20.04 + ROS Noetic）
┌──────────────────────┐          ┌──────────────────────────────────────────────────────┐
│ roscore              │          │                                                      │
│ Agent (ros1_agent.py)│  MQTT    │  roscore (localhost:11311)                           │
│   ros_msg_to_dict()  │────────► │    /robot_001/odom, /robot_001/scan, ...            │
│   publish_sensor_data│  port    │    /tf, /tf_static                                   │
│   _execute_command() │  1883    │                                                      │
│ sensor_simulator.py  │          │  ┌─────────────────────┐   ┌────────────────────┐   │
└──────────────────────┘          │  │ Python MQTT 桥接    │   │ Qt5 C++ 应用       │   │
                                  │  │ (mqtt_ros_bridge.py)│   │                    │   │
                                  │  │                     │   │ QMainWindow        │   │
                                  │  │ paho-mqtt 订阅      │   │ ┌────────┬───────┐ │   │
                                  │  │ robot/+/sensor/#    │   │ │左侧面板│ RViz  │ │   │
                                  │  │                     │   │ │-机器人 │ QWidget│ │   │
                                  │  │ dict_to_ros_msg()   │   │ │ 列表   │       │ │   │
                                  │  │ rospy.Publisher     │   │ │-状态   │ 3D    │ │   │
                                  │  │   → 本地 roscore    │   │ │-控制   │ 视图  │ │   │
                                  │  └─────────────────────┘   │ │-话题   │       │ │   │
                                  │                            │ │ 管理   │       │ │   │
                                  │                            │ │-事件   │       │ │   │
                                  │                            │ └────────┴───────┘ │   │
                                  │                            │                    │   │
                                  │                            │ MqttClient (paho)  │   │
                                  │                            │  订阅:             │   │
                                  │                            │   robot/+/status   │   │
                                  │                            │   robot/+/event    │   │
                                  │                            │   robot/+/cmd/ack  │   │
                                  │                            │  发布:             │   │
                                  │                            │   robot/{id}/cmd   │   │
                                  │                            │   station/discover │   │
                                  │                            │   station/topic/req│   │
                                  │                            │                    │   │
                                  │                            │ 三栏布局:           │   │
                                  │                            │ 左:机器人+控制      │   │
                                  │                            │ 中:RViz 3D视图     │   │
                                  │                            │ 右:Display面板     │   │
                                  │                            └────────────────────┘   │
                                  └──────────────────────────────────────────────────────┘
```

## Agent 端改造：通用化 ros_msg_to_dict

**现状问题：** `agent/ros1_agent.py:45-115` 的 `ros_msg_to_dict()` 只支持 7 种 ROS 类型：
Imu、Odometry、LaserScan、CompressedImage、NavSatFix、Twist，其余走 `json.loads(str(msg))` 回退，基本不可用。

**解决方案：** 利用 ROS 消息的 `__slots__` 内省实现通用的序列化/反序列化。

```python
# agent/ros_msg_converter.py（新增，替代硬编码的 ros_msg_to_dict）

import numpy as np
from typing import Any, Dict, List

_BUILTIN_TYPES = (int, float, str, bool, bytes)

def ros_msg_to_dict(msg) -> dict:
    """通用 ROS 消息 → dict，支持所有标准 ROS 消息类型"""
    if not hasattr(msg, '__slots__'):
        return {"_raw": str(msg)}
    result = {}
    for slot in msg.__slots__:
        val = getattr(msg, slot)
        result[slot] = _serialize_field(val)
    return result

def _serialize_field(val):
    """递归序列化单个字段"""
    if val is None:
        return None
    if isinstance(val, _BUILTIN_TYPES):
        if isinstance(val, bytes):
            return list(val)  # JSON 不能直接序列 bytes
        return val
    if isinstance(val, (list, tuple)):
        return [_serialize_field(v) for v in val]
    if isinstance(val, np.ndarray):
        return val.tolist()
    if isinstance(val, np.generic):
        return val.item()
    # 嵌套 ROS 消息
    if hasattr(val, '__slots__'):
        return ros_msg_to_dict(val)
    # 时间类型
    if hasattr(val, 'to_sec'):
        return val.to_sec()
    if hasattr(val, 'secs') and hasattr(val, 'nsecs'):
        return {"secs": val.secs, "nsecs": val.nsecs}
    return str(val)
```

```python
# station/qt-frontend/bridge/dict_to_ros_msg.py（对应逆操作）

from rospy.msg import get_message_class

def dict_to_ros_msg(data: dict, msg_type: str):
    """通用 dict → ROS 消息"""
    cls = get_message_class(msg_type)
    if cls is None:
        raise ValueError(f"Unknown message type: {msg_type}")
    msg = cls()
    _deserialize_into(msg, data)
    return msg

def _deserialize_into(msg, data: dict):
    """递归反序列化填充 ROS 消息"""
    if not hasattr(msg, '__slots__') or not isinstance(data, dict):
        return
    for slot in msg.__slots__:
        if slot not in data:
            continue
        val = data[slot]
        target = getattr(msg, slot)
        field_type = type(target)
        # 嵌套消息
        if hasattr(target, '__slots__'):
            _deserialize_into(target, val)
        # bytes (从 list 还原)
        elif isinstance(target, bytes) and isinstance(val, list):
            setattr(msg, slot, bytes(val))
        # list/array
        elif isinstance(target, (list, tuple)):
            setattr(msg, slot, list(val) if isinstance(val, (list, tuple)) else [val])
        # 时间
        elif hasattr(target, 'secs') and hasattr(target, 'nsecs') and isinstance(val, dict):
            target.secs = val.get('secs', 0)
            target.nsecs = val.get('nsecs', 0)
        elif hasattr(target, 'to_sec') and isinstance(val, (int, float)):
            target.from_sec(val)
        # 基础类型
        else:
            try:
                setattr(msg, slot, val)
            except (TypeError, AttributeError):
                pass
```

**效果：** 任意 ROS 标准消息类型（`sensor_msgs/PointField`、`geometry_msgs/PoseWithCovariance`、`nav_msgs/Path`、自定义消息...）都能自动序列化/反序列化，不再受硬编码限制。

**Agent 话题发现改进：**

```python
# agent/ros1_agent.py _get_available_topics() 改进
def _get_available_topics(self) -> list:
    """返回 [{topic: '/odom', msg_type: 'nav_msgs/Odometry'}, ...]"""
    topics = []
    for topic, msg_type in rospy.get_published_topics():
        # 过滤掉内部话题
        if not topic.startswith('/rosout') and not topic.startswith('/log'):
            topics.append({"topic": topic, "msg_type": msg_type})
    return topics
```

Discover 响应里 `available_topics` 就变成 `[{topic, msg_type}, ...]` 而不是 `["/odom", ...]`。

## 数据流

**正向（机器人 → 地面站 → RViz）：**
```
ROS话题 → Agent ros_msg_to_dict() → MQTT robot/{id}/sensor/{name}
    → Python桥接 解析 → dict_to_ros_msg() → rospy.Publisher → 本地roscore
    → RViz（订阅 /robot_{id}/{话题名}）→ 原生渲染
```

**反向（地面站 Qt 面板 → 机器人）：**
```
Qt CommandPanel → MqttClient.publish(robot/{id}/cmd, JSON)
    → Agent _handle_command() → rospy.Publisher(/cmd_vel) → ROS节点
    → Agent 回复 cmd_ack → Qt CommandManager 更新指令状态
```

**话题订阅（端到端）：**
```
Qt TopicManagerPanel → MQTTHandler.publish(station/topic/request)
    → Agent _handle_topic_request() → 创建 ROS subscriber
    → Agent 回复 topic_response (action, topic, msg_type, result)
    → Qt 更新订阅状态 (pending→active)
    → Agent 开始转发数据 → 桥接还原 → RViz 显示
```

## 目录结构

```
station/qt-frontend/
├── CMakeLists.txt
├── config/
│   ├── config.yaml              # Broker地址、ROS master URI
│   └── default.rviz             # 默认RViz布局
├── launch/
│   └── station.launch           # roslaunch: roscore + 桥接 + Qt应用
├── src/
│   ├── main.cpp
│   ├── mqtt/
│   │   ├── MqttClient.h/.cpp    # paho-mqtt-cpp 封装
│   │   └── MessageTypes.h       # 协议结构体（对应 protocol/messages.py）
│   ├── core/
│   │   ├── RobotManager.h/.cpp       # 机器人列表、心跳、状态管理
│   │   ├── SubscriptionManager.h/.cpp # 话题订阅状态机
│   │   ├── CommandManager.h/.cpp     # exec_id 追踪、超时处理
│   │   └── MessageRouter.h/.cpp      # MQTT消息 → 管理器分发
│   ├── rviz/
│   │   ├── RvizWidget.h/.cpp    # 嵌入 RViz（librviz）
│   │   └── RvizConfig.h/.cpp    # 保存/加载 .rviz 配置
│   ├── panels/
│   │   ├── RobotListPanel.h/.cpp    # 机器人选择器（在线/离线）
│   │   ├── RobotStatusPanel.h/.cpp   # 电量、位姿、速度、模式
│   │   ├── CommandPanel.h/.cpp      # 速度滑杆、模式按钮
│   │   ├── TopicManagerPanel.h/.cpp # 订阅/取消订阅话题
│   │   └── EventPanel.h/.cpp        # 告警/事件日志
│   └── dialogs/
│       ├── ConnectDialog.h/.cpp     # Broker连接设置
│       └── SubscribeDialog.h/.cpp   # 频率限制 + 压缩选项
├── bridge/
│   ├── mqtt_ros_bridge.py       # MQTT订阅 → ROS发布
│   ├── dict_to_ros_msg.py       # ros_msg_to_dict() 的逆操作
│   └── bridge_config.yaml
├── resources/
│   ├── resources.qrc
│   └── icons/
├── scripts/
│   ├── start.sh
│   └── stop.sh
└── tests/
    ├── test_bridge.py
    └── test_mqtt_client.cpp
```

## 关键设计决策

### 为什么 C++ 写 Qt + Python 写桥接

- **RViz 嵌入只能 C++**：`librviz` 是 C++ 库，提供 `rviz::RenderPanel`（QWidget 子类）和 `rviz::VisualizationManager`，没有 Python 绑定
- **dict_to_ros_msg() 用 Python**：ROS Noetic 的 rospy 可以动态构造任意消息类型（`roslib.message.get_message_class()`），C++ 需要每种消息类型的编译头文件
- **两者独立通信**：都直接连 MQTT，桥接只关心 `robot/+/sensor/#`，Qt 关心 `robot/+/status`、事件、指令。不需要直接的进程间通信

### 话题命名规范

机器人 N 的 ROS 话题在地面站 roscore 上发布为 `/robot_{N}/{原始话题名}`：

- Agent 发 `/odom` → 桥接发 `/robot_001/odom`
- Agent 发 `/scan` → 桥接发 `/robot_001/scan`
- Agent 发 `/camera/image_raw` → 桥接发 `/robot_001/camera/image_raw`

多机器人数据天然隔离，RViz 里分别添加对应的 Display 即可。

### dict_to_ros_msg() — 核心环节

这是 Agent 端 `ros_msg_to_dict()`（agent/ros1_agent.py:45-115）的逆操作。对每种消息类型，从 dict 重建 ROS 消息：

| ROS 类型 | dict_to_ros_msg 构造 | Agent 的 ros_msg_to_dict 提取 |
|----------|---------------------|------------------------------|
| `sensor_msgs/Imu` | `Imu()` 填 orientation, angular_velocity, linear_acceleration | orientation(x,y,z,w), angular_vel, linear_accel |
| `nav_msgs/Odometry` | `Odometry()` 填 pose, twist | pose(x,y,z,qw,qx,qy,qz), twist(linear,angular) |
| `sensor_msgs/LaserScan` | `LaserScan()` 填 ranges | angle_min/max, range_min/max, ranges[] |
| `sensor_msgs/CompressedImage` | `CompressedImage()` 填 data | format, data[] |
| `sensor_msgs/Image` | `Image()` 从 base64 解码 | base64 → 解码 → Image data |
| `sensor_msgs/PointCloud2` | `PointCloud2()` 从二进制 | float32 xyz 字节 → PointCloud2 |
| `sensor_msgs/NavSatFix` | `NavSatFix()` | latitude, longitude, altitude |
| `geometry_msgs/Twist` | `Twist()` | linear(x,y,z), angular(x,y,z) |
| `tf2_msgs/TFMessage` | `TFMessage()` 从 odom 的 child_frame_id | transforms |

未注册的类型走通用回退：`rospy.msg.get_message_class(msg_type)` 动态加载消息类，按字段名 setattr 赋值。

### Qt 组件策略

核心用 `QSplitter` 实现三栏可拖拽布局，`QDockWidget` 让面板可拖出独立窗口，`QTabWidget` 在侧栏内叠放多个面板节省空间。

| Qt 组件 | 用途 |
|---------|------|
| `QSplitter` | 三栏水平分割，可拖拽调整宽度，可折叠到侧边 |
| `QDockWidget` | 摄像头小窗、发送数据面板等可拖出独立显示 |
| `QTabWidget` | 左右侧栏空间有限时叠放面板（如"状态/控制/事件"合成一个 Tab） |
| `QTreeWidget` | Display 树、机器人列表 |
| `QToolBar` | 顶部快捷操作栏 |
| `QStatusBar` | 底部连接状态、帧率、带宽 |

### 面板详细设计

**左侧栏（机器人管理 + 配置 Tab + 控制 + 事件）：**

左侧栏空间有限，用 `QTabWidget` 把话题传输配置和编队通信配置叠在同一个区域，切换标签查看。

| 面板 | 数据来源 | 功能 |
|------|---------|------|
| RobotListPanel | MQTT `robot/+/status` + discover | 机器人列表，在线●/离线○，点击选中，支持多选批量操作 |
| RobotStatusPanel | MQTT `robot/{id}/status` | 选中机器人的电量条、位姿(x,y,θ)、速度(linear,angular)、运行模式 |
| CommandPanel | MQTT 发布 → `robot/{id}/cmd` | 线性/角速度 QSlider(-1~1m/s, -1~1rad/s)、模式切换(Manual/Auto/Stop)、急停按钮、回家按钮 |
| EventPanel | MQTT `robot/{id}/event` | 告警日志 QListWidget，🚨/⚠️/ℹ️ 色标，自动滚动到最新 |
| FleetCommPanel | MQTT 下发规则 + config 持久化 | 配置机器人间互相发送的话题，管理通信规则，支持位置共享/传感器共享/点云共享 |

**中间（3D 可视化）：**

| 面板 | 依赖 | 功能 |
|------|------|------|
| RvizWidget | librviz + roscore | RViz RenderPanel 嵌入 QWidget，原生渲染 |
| CameraOverlay (QDockWidget) | RViz Image Display 或独立 QLabel | 摄像头画面可拖到角落或独立窗口 |

**右侧栏（RViz 原生 Display 面板 + 自定义辅助面板）：**

librviz 自带 `rviz::DisplaysPanel`、`rviz::DisplayGroup` 等组件，包括完整的 Display 树、Add Display 对话框（可按类型或话题浏览）、属性编辑面板。**右侧栏的主体直接嵌入这些原生组件，零自写代码。**

| 面板 | 来源 | 功能 |
|------|------|------|
| DisplayTreePanel | **RViz 原生** | QTreeWidget 显示已添加的 Display，勾选 enabled，展开编辑属性 |
| AddDisplayDialog | **RViz 原生** | 按 Display Type 选择（如 rviz/Odometry），或按 Topic 浏览本地 roscore 已有话题 |
| TopicPropertyPanel | **RViz 原生** | 选中 Display 后的属性编辑（Topic、Frame、Color、Size 等） |
| DataSenderPanel | 自定义 | 向机器人任意话题推送数据：选择目标机器人 → ROS 话题 → 内容 → [JSON] [二进制] |
| TrafficMonitorPanel | 自定义 | 实时显示各订阅话题的 MQTT 带宽统计 |

**RViz 原生 Add Display 的工作流 + MQTT 订阅联动：**

```
用户点 RViz 的 [Add] → 弹出原生 AddDisplay 对话框
  → 按话题浏览 → 显示本地 roscore 已有话题（/robot_001/odom, /robot_001/scan...）
  → 这些话题是 Python 桥接还原后发布的
  → 用户直接选话题 → RViz 创建 Display → 即时渲染

如果用户想要的话题不在列表里（还没订阅）：
  → 回到左侧"话题传输配置"面板
  → 输入话题名 + 类型 → 下发订阅
  → 桥接立即开始发布到本地 roscore
  → 回到 RViz Add Display → 话题已出现 → 选中添加
```

右侧三个组件（Display 树 + Add 对话框 + 属性面板）全是 RViz 原生，左侧的"话题传输配置"是我们自定义的，控制 MQTT 订阅。两者通过本地 roscore 的话题列表自然衔接。

### 自定义话题传输配置（核心功能）

这是整个系统灵活性的关键。用户可以在 Qt 前端**自定义配置要传输的 ROS 话题列表**，
然后一键下发给 Agent，Agent 按配置启动 ROS Subscriber 并转发数据。

**传输配置面板（可在右侧栏新增 Tab 或独立对话框）：**

```
┌──────────────────────────────────────────┐
│ 📡 话题传输配置                            │
│──────────────────────────────────────────│
│ 机器人: [robot_001 ▼]                     │
│                                           │
│ ┌─ 已配置传输的话题 ──────────────────────┐│
│ │ 话题名        类型           频率  层级  ││
│ │ /odom         Odometry      10Hz  LIGHT││
│ │ /scan         LaserScan     10Hz  MEDIUM││
│ │ /camera/image Image         5Hz   MEDIUM││
│ │ /velodyne_pnts PointCloud2  2Hz   HEAVY ││
│ │ [+ 添加话题]    [🗑 删除]   [📋 保存配置]││
│ └────────────────────────────────────────┘│
│                                           │
│ ┌─ 添加/编辑话题 ─────────────────────────┐│
│ │ ROS 话题:  [/camera/image_raw     ]     ││
│ │ ROS 类型:  [sensor_msgs/Image ▼]        ││
│ │            (或手动输入: [___________])   ││
│ │ 传输层级:  ○ LIGHT  ● MEDIUM  ○ HEAVY   ││
│ │ 频率上限:  [5.0] Hz                      ││
│ │ 压缩选项:  JPEG质量 [80]                 ││
│ │            缩放 [640]×[480]              ││
│ │            体素 [0.1]m                   ││
│ │ QoS:       ○ AtMostOnce ● AtLeastOnce   ││
│ │ [✅ 确认]  [❌ 取消]                     ││
│ └────────────────────────────────────────┘│
│                                           │
│ [📤 下发配置到机器人]  [📥 从机器人拉取话题列表]│
└──────────────────────────────────────────┘
```

**传输配置的工作流：**

1. **发现话题**：点击"从机器人拉取话题列表"→ 发 MQTT discover → Agent 返回 `available_topics`（带 msg_type）→ 自动填入表格
2. **自定义添加**：点击"添加话题"→ 手动输入 ROS 话题名 + 选择/输入消息类型 → 选择传输层级（LIGHT/MEDIUM/HEAVY）→ 设频率、压缩参数
3. **下发配置**：点击"下发配置到机器人"→ 遍历配置列表 → 逐条发 `station/topic/request`（action=subscribe, topic, msg_type, freq_limit, transport, compression）→ Agent 逐条创建 ROS Subscriber 并回复 ack
4. **保存/加载**：配置存为 `transmit_config.yaml`，包含机器人 ID + 话题列表（topic/msg_type/freq/transport/compression）

### 启动时自动恢复订阅 + 同步 Display

```
地面站启动
  → 加载 transmit_config.yaml
  → 连接 MQTT Broker
  → 遍历配置中的话题列表:
      逐条发 station/topic/request (action=subscribe, topic, msg_type, freq, ...)
  → Agent 逐条响应 topic_response (result=ok)
  → Qt 收到 ack → 订阅状态标记 active
  → Python 桥开始接收 MQTT 数据 → 发布到本地 roscore
  → Qt 自动在 Display 面板创建对应的 RViz Display:
      - /odom + nav_msgs/Odometry → 自动添加 rviz/Odometry
      - /scan + sensor_msgs/LaserScan → 自动添加 rviz/LaserScan
      - /camera/image_raw + sensor_msgs/Image → 自动添加 rviz/Image
      - /velodyne_points + sensor_msgs/PointCloud2 → 自动添加 rviz/PointCloud2
      - 未知类型 → 不自动添加，用户手动选择 Display 类型
  → 加载 default.rviz（包含 Grid、TF 等基础 Display）
  → 前端就绪，所有 Display 已就位，数据已在传输
```

**关键：** 地面站启动完成后，用户看到的是一个"已经配好"的界面——Display 面板里自动有已订阅的话题，3D 视图里数据已经在新一帧帧渲染。不需要手动一个个添加。

5. **配置热更新**：运行时新增/删除话题，自动写入 `transmit_config.yaml`，下次启动保留

### 配置持久化与双向同步

**配置文件位置：**
- 地面站：`station/qt-frontend/config/transmit_config.yaml`
- Agent 端：`agent/config.yaml`（已有文件，新增 `subscriptions` 字段）

**地面站 `transmit_config.yaml`：**
```yaml
# 各机器人的话题传输配置
robots:
  robot_001:
    subscriptions:
      - topic: "/odom"
        msg_type: "nav_msgs/Odometry"
        freq_limit: 10.0
        transport: "mqtt_json"
      - topic: "/scan"
        msg_type: "sensor_msgs/LaserScan"
        freq_limit: 10.0
        transport: "mqtt_binary"
      - topic: "/camera/image_raw"
        msg_type: "sensor_msgs/Image"
        freq_limit: 5.0
        transport: "mqtt_binary"
        compression:
          quality: 80
          resize: [640, 480]
  robot_002:
    subscriptions:
      - topic: "/odom"
        msg_type: "nav_msgs/Odometry"
        freq_limit: 5.0
```

**Agent 端 `config.yaml` 新增 subscriptions 字段：**
```yaml
robot_id: "robot_001"
broker_host: "host-gateway"
broker_port: 1883
http_stream_port: 8080
default_freq_limit: 10.0
# 新增：持久化的订阅列表
subscriptions:
  - topic: "/odom"
    msg_type: "nav_msgs/Odometry"
    freq_limit: 10.0
    transport: "mqtt_json"
```

**下发 + 同步流程：**
```
Qt 前端 [保存 transmit_config.yaml]
   → 下发订阅: MQTT station/topic/request (subscribe, topic, msg_type, freq,...)
   → MQTT station/config/sync {robot_id, subscriptions: [...]}
   
Agent 收到 config/sync
   → base_agent.py _handle_config_sync()           # 新增方法
   → 写入 agent/config.yaml（合并 subscriptions）
   → Agent 下次启动时自动从 config.yaml 加载订阅
   → 回复 config_sync_ack

Qt 前端收到 ack
   → 更新 UI：config 状态显示 ✅ 已同步到机器人
```

**Agent 启动时自动恢复订阅：**
```python
# agent/base_agent.py 新增
def _load_subscriptions_from_config(self):
    """启动时从 config.yaml 加载持久化的订阅列表"""
    subs = self.config.subscriptions  # 从 AgentConfig 读取
    for sub in subs:
        self._handle_topic_request(Message(
            type=MessageType.TOPIC_REQUEST,
            data={"action": "subscribe", "topic": sub["topic"],
                  "msg_type": sub["msg_type"], "freq_limit": sub["freq_limit"]}
        ))
```

**效果：** Agent 重启后自动恢复所有订阅，不需要地面站重新下发。

### 配置不一致时的冲突处理

地面站的 `transmit_config.yaml` 和机器人的 `config.yaml` 可能因离线修改、部分同步失败等原因不一致。

**启动时的协商流程：**

```
地面站启动，连接 MQTT
  → 加载本地 transmit_config.yaml
  → 发 MQTT station/config/query → Agent

Agent 收到 config/query
  → 返回 config/response {robot_id, subscriptions: [...]}
  → 同时返回当前在线状态

地面站收到 Agent 配置
  → 对比本地配置 vs Agent 配置:
      ┌─ 两边都有，参数一致     → ✅ 直接标记 active
      ├─ 两边都有，参数不一致     → ⚠️ 冲突
      ├─ 仅地面站有              → ➕ 待下发
      ├─ 仅 Agent 有             → 📥 待拉取
      └─ Agent 的话题实际不存在   → ❌ 不可用（Agent 侧标记）
  → 弹出配置对比对话框:
```

**配置对比对话框：**

```
┌──────────────────────────────────────────────────────────┐
│ ⚠ 配置不一致 — 请确认如何处理                              │
│──────────────────────────────────────────────────────────│
│ 机器人: robot_001                                         │
│                                                           │
│ ✅ 一致 (2):                                              │
│   /odom (10Hz, mqtt_json)                                │
│   /scan (10Hz, mqtt_binary)                              │
│                                                           │
│ ⚠ 参数不一致 (1):                                         │
│   /camera: 地面站 5Hz ←→ 机器人 10Hz                     │
│   [使用地面站] [使用机器人]                                │
│                                                           │
│ ➕ 仅地面站有 (1):                                        │
│   /imu/data                                               │
│   [下发到机器人] [跳过]                                    │
│                                                           │
│ 📥 仅机器人有 (1):                                        │
│   /velodyne_points (Agent 重启后自恢复)                   │
│   [拉取到本地] [取消机器人端]                              │
│                                                           │
│ ❌ 不可用 (1):                                            │
│   /camera/depth — 机器人上该话题不存在                     │
│   [移除] [重试]                                           │
│                                                           │
│ [全部使用地面站] [全部使用机器人] [逐条确认]                │
└──────────────────────────────────────────────────────────┘
```

**处理规则：**
- 默认策略：地面站配置为准，不一致时覆盖机器人端
- 用户可逐条选择，也可一键"全部使用地面站/机器人"
- 确认后：下发 → Agent 更新 config.yaml → 同步完成
- 如果用户跳过对话框（无 GUI 模式），默认"地面站覆盖机器人"

**持续同步：**
- 在线期间，地面站每次修改配置都即时同步到 Agent 的 config.yaml
- Agent 端 `config.yaml` 的 `subscriptions` 字段始终反映最近一次地面站下发的状态

**和右侧 Display 面板的关系：**
- **传输配置面板** = 控制"传不传、怎么传"（Agent 端行为）
- **Display 面板** = 控制"显示不显示、怎么显示"（RViz 端行为）
- 两者独立但联动：传输配置订阅的话题会自动出现在桥接的 roscore 上 → Display 面板可以直接选来添加 RViz 渲染

### 取消订阅 = 立即停止传输

这是一个保证传输效率和带宽可控的关键设计。取消订阅的完整链路：

```
Qt 前端取消订阅
 → 发 MQTT station/topic/request {action: "unsubscribe", topic: "/odom"}
 → Agent _handle_topic_request() (base_agent.py:610-624)
     → self._subscribed_topics.pop(topic)        # 移除订阅记录
     → self._rate_limiter.remove_limit(topic)     # 清理限频
     → _on_topic_unsubscribed(topic)              # 通知子类
         → ros1_agent.py: sub.unregister()        # 注销 ROS Subscriber
         → self._sensor_data.pop(topic)           # 清理缓存
     → 回复 topic_response {result: "ok", action: "unsubscribe"}
 → Agent 停止向 MQTT 发布该话题数据
 → Python 桥接收不到数据 → 停止向本地 roscore 发布
 → RViz Display 数据断流（但不崩溃，只是没有新数据）
 → 话题流量监控中该话题带宽归零
 → Qt 前端更新订阅状态为已取消
```

**效果：** 取消订阅后，该话题在 MQTT 上的带宽立即释放，不再占用网络资源。Agent 端也不再消耗 CPU 序列化该话题。

**前端解散时的批量清理：**
Agent 监听 MQTT Last Will — 当 Qt 前端意外断开时，Agent 自动注销该 Station 发起的所有订阅，防止"僵尸传输"持续占用带宽。

右侧 Display 面板的核心价值：**用户不需要写任何代码，只要输入话题名和消息类型，即可在 RViz 中可视化**。链路：选 Display 类型 → 填话题 → MQTT 订阅 → Agent 转发 → 桥接还原 → RViz 渲染。

### 代码改动范围

| 模块 | 改动 | 说明 |
|------|------|------|
| `agent/ros_msg_converter.py` | **新增** | 通用的 `ros_msg_to_dict()`/`dict_to_ros_msg()`，利用 `__slots__` 内省 |
| `agent/ros1_agent.py` | **小改** | `_get_available_topics()` 改用 `rospy.get_published_topics()` 返回带类型的话题列表 |
| `protocol/messages.py` | **小改** | `DiscoverResponseData.topics` 从 `List[str]` 改为 `List[dict]` |
| `protocol/topics.py` | 不改 | parse_robot_topic()、话题命名 |
| `protocol/topic_registry.py` | 不改 | 传输层级判断 |
| `agent/base_agent.py` | **小改** | 新增 `_handle_config_sync()`、`_load_subscriptions_from_config()` |
| `agent/config.yaml` | **小改** | 新增 `subscriptions` 字段，启动时自动恢复 |

### 完全复用的代码（零改动）

| 模块 | 谁用 | 用途 |
|------|------|------|
| `protocol/topics.py` | Python 桥接 + Qt | 话题命名、parse_robot_topic() |
| `protocol/topic_registry.py` | Python 桥接 | 传输层级判断 |
| `agent/base_agent.py` | 机器人端 | 话题请求/响应、指令执行、心跳上报 |
| `agent/topic_handler.py` | 机器人端 | LIGHT/MEDIUM/HEAVY 分层处理 |
| `agent/rate_limiter.py` | 机器人端 | 按话题独立限频 |

## 实施步骤

### 阶段一：Agent 端通用序列化 + 话题发现改进
- 新增 `agent/ros_msg_converter.py`：通用 `ros_msg_to_dict()`/`dict_to_ros_msg()` 对，利用 `__slots__` 内省支持任意 ROS 消息类型，替换现有的硬编码 7 种类型
- 改进 `_get_available_topics()`：调用 `rospy.get_published_topics()` 返回 `[{topic, msg_type}]` 而非纯字符串数组
- 改进 Discover 响应：`DiscoverResponseData.topics` 改为 `List[dict]`，包含 `topic` 和 `msg_type`
- 用传感器模拟器 + 自定义 ROS 话题验证：确认任意类型都能正确序列化/反序列化

### 阶段二：Python MQTT-ROS 桥接 + dict_to_ros_msg
- 实现 `bridge/mqtt_ros_bridge.py`：paho-mqtt 订阅 `robot/+/sensor/#` → rospy 发布到本地 roscore
- 实现 `bridge/dict_to_ros_msg.py`：通用逆操作，配合 Agent 端的新序列化器
- 验证：Agent 发的 odom/scan/image + 自定义话题都能在 RViz 中显示

### 阶段三：Qt 骨架 + RViz 嵌入
- CMakeLists.txt 配置 Qt5 + librviz
- `main.cpp`：ros::init、QApplication、MainWindow
- `RvizWidget`：嵌入 RViz RenderPanel + VisualizationManager
- `MqttClient`：paho-mqtt-cpp 连接、订阅、发布、重连
- 验证：Qt 窗口内显示 RViz，带 Grid + TF

### 阶段四：核心管理器
- `RobotManager`：解析 status MQTT 消息、管理机器人列表、心跳超时
- `CommandManager`：通过 MQTT 发指令、exec_id 追踪、处理 cmd_ack
- `SubscriptionManager`：发话题请求、匹配响应、状态机（pending→active→failed）
- `MessageRouter`：MQTT 回调 → 对应管理器

### 阶段五：自定义面板
- `RobotListPanel` + `RobotStatusPanel`
- `CommandPanel`：速度/模式控制
- `TopicManagerPanel`：带订阅对话框
- `EventPanel`：告警展示

### 阶段六：打磨
- `ConnectDialog`：启动时配置 Broker
- 深色主题 QSS
- RViz 配置存取
- 启动脚本

### 用户角度体验改进

**1. 急停全局可见（安全硬需求）：**
- 顶部工具栏右侧固定一个**红色大按钮 [🛑 全部急停]**，始终可见，无需切面板
- 按下后向所有在线机器人同时发送 `velocity {linear: 0, angular: 0}` + `mode stop`
- 左侧 CommandPanel 里保留单独的急停按钮（按选中机器人）

**2. 传感器数据摘要面板（调试必备）：**
- 右侧 Display 面板下方新增"传感器摘要"Tab
- 选中某个 Display 后，显示最新一帧数据的实时摘要：

| Display 类型 | 摘要内容 |
|-------------|---------|
| LaserScan | ranges 数量、最近/最远距离、扫描角度范围、丢帧计数 |
| Image/CompressedImage | 分辨率、压缩比、JPEG 质量、实际帧率（近 5 秒均值） |
| Odometry | 最新位姿 (x,y,θ)、最近 10 帧的轨迹线预览、child_frame_id |
| PointCloud2 | 点数、体素大小、XYZ 范围、实际帧率 |
| Imu | 角速度/线加速度当前值、协方差标志 |

**3. 录制与回放：**
- 复用现有 `station/backend/recorder.py` + `station/backend/database.py`，保持 SQLite 存储
- Qt 前端通过工具栏录制按钮控制：点录制 → 后台发 REST 给 Station 后端 → Station 开始把所有已订阅话题的 MQTT 数据写库
- 回放：加载 SQLite → Python 桥按原始时间戳逐帧发布到本地 roscore → RViz 重新渲染
- Station 后端作为录制服务独立运行（FastAPI 的 `station/backend/main.py` 保持，但不连前端）

**4. 话题自动发现（添加话题时不需背类型名）：**
- "添加话题"对话框自动拉取机器人当前可用 ROS 话题列表（`[{topic, msg_type}]`）
- 用户从列表里选，不需要手动输入类型名
- 也可以手动输入自定义话题名 + 类型（不在列表中的）

**5. 机器人间通信配置面板（Fleet Communication）：**

机器人之间可以直接通过 MQTT 交换数据，不需要地面站中转。协议已支持（`robot/{src}/to/{dst}`），但缺少配置界面。

```
┌──────────────────────────────────────────────┐
│ 🔗 机器人间通信配置                            │
│──────────────────────────────────────────────│
│                                              │
│ ┌─ 已有通信规则 ─────────────────────────────┐│
│ │ 源机器人    目标机器人   话题       状态     ││
│ │ robot_001 → robot_002  /odom      ● 传输中 ││
│ │ robot_001 → robot_002  /scan      ● 传输中 ││
│ │ robot_002 → robot_001  /camera    ● 传输中 ││
│ │ robot_001 → robot_003  /pos       ○ 已停   ││
│ │ [+ 添加规则]  [🗑 删除]  [⏸ 暂停]         ││
│ └────────────────────────────────────────────┘│
│                                              │
│ ┌─ 添加/编辑通信规则 ────────────────────────┐│
│ │ 源机器人:   [robot_001 ▼]                  ││
│ │ 目标机器人: [robot_002 ▼] (或多选: [全选])  ││
│ │                                              ││
│ │ ROS 话题:  [/odom              ]            ││
│ │ 消息类型:  [nav_msgs/Odometry ▼]            ││
│ │ 频率上限:  [2.0] Hz                         ││
│ │                                              ││
│ │ 数据用途:  ○ 位置共享                       ││
│ │           ○ 导航目标                        ││
│ │           ● 自定义传感器数据                 ││
│ │           ○ 点云/重量数据 (HTTP 流)         ││
│ │                                              ││
│ │ QoS:       ● At Least Once                  ││
│ │                                              ││
│ │ [✅ 确认]  [❌ 取消]                         ││
│ └──────────────────────────────────────────────┘│
│                                              │
│ [📤 下发全部规则]  [📥 拉取当前规则]            │
└──────────────────────────────────────────────┘
```

**工作流：**
1. 用户在面板添加规则：`robot_001` 的 `/odom` 以 2Hz 发给 `robot_002`
2. 地面站发 MQTT 给 `robot_001` 的 Agent：订阅 `/odom`，配置转发规则
3. Agent 收到 `/odom` 数据后，额外发布到 `robot/robot_001/to/robot_002`（FLEET_DATA 类型）
4. `robot_002` 的 Agent 收到 `robot/+/to/robot_002` 消息 → 解析 → 发布到本地 ROS `/fleet/from_robot_001/odom`
5. 如果是重量数据（点云），走 HTTP 流 + meta 信令通道

**Agent 端已有支持：**
- `base_agent.send_to_robot(target_id, fleet_data)` → MQTT `robot/{src}/to/{dst}`
- `base_agent.share_heavy_data(target_id, topic, data)` → HTTP 流
- ros1_agent 的 `_on_fleet_message()` → 发布到 `/fleet/incoming`

**需要新增：**
- `base_agent.py`: `_handle_fleet_config()` 接收地面站下发的通信规则
- Agent 按规则自动将订阅的话题数据转发给目标机器人

**配置持久化（和话题传输配置同一套机制）：**

地面站 `transmit_config.yaml` 扩展为统一配置文件：
```yaml
# station/qt-frontend/config/transmit_config.yaml
robots:
  robot_001:
    subscriptions:       # 机器人→地面站的话题
      - topic: "/odom"
        msg_type: "nav_msgs/Odometry"
        freq_limit: 10.0
    fleet_rules:         # 机器人→其他机器人的话题
      - topic: "/odom"
        msg_type: "nav_msgs/Odometry"
        target: "robot_002"
        freq_limit: 2.0
      - topic: "/camera/image_raw"
        msg_type: "sensor_msgs/Image"
        target: "robot_002"
        freq_limit: 1.0
        transport: "mqtt_binary"
```

Agent 端 `config.yaml` 同步扩展：
```yaml
# agent/config.yaml
robot_id: "robot_001"
subscriptions:
  - topic: "/odom"
    msg_type: "nav_msgs/Odometry"
    freq_limit: 10.0
fleet_rules:            # 地面站下发后同步写入
  - topic: "/odom"
    msg_type: "nav_msgs/Odometry"
    target: "robot_002"
    freq_limit: 2.0

# Agent 启动时：
# 1. 从 subscriptions 恢复话题转发（→ MQTT → 地面站）
# 2. 从 fleet_rules 恢复编队通信（→ MQTT robot/{src}/to/{dst}）
```

地面站 FleetCommPanel 修改规则后 → 即时下发到 Agent → Agent 同步写 `config.yaml`。两边一致，启动自动恢复，和话题传输配置完全一样的流程。

**5. 远期优化（记录，本次不实现）：**
- 多人协作控制权提示/互斥
- 指令执行状态直观反馈（RViz 小窗弹绿色勾动画）
- 自定义 Dashboard 布局保存

```bash
# 启动完整环境
./scripts/start_hybrid_test.sh        # Broker + Docker 机器人
source /opt/ros/noetic/setup.bash
roslaunch station/qt-frontend/launch/station.launch

# 测试1：机器人发现
# → RobotListPanel 显示 robot_001、robot_002，绿灯在线

# 测试2：话题订阅
# → TopicManagerPanel 点击 /odom 的 Subscribe
# → 状态 pending → active
# → RViz 添加 Odometry Display，topic 选 /robot_001/odom，看到位姿箭头

# 测试3：指令控制
# → CommandPanel 设 linear=0.3, angular=0.1
# → 机器人 velocity 更新，RViz 中位姿移动
# → CommandManager 显示 ack_ok

# 测试4：各类传感器
# → 订阅 /scan → RViz LaserScan 渲染 360° 扫描
# → 订阅 /imu/data → RViz Imu 显示姿态
# → 订阅 /camera/image_raw → RViz Image 显示摄像头画面
```
