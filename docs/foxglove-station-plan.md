# Foxglove Studio 地面站 — 实施方案

## 为什么 Foxglove 比 Qt+Rviz 更合适

| 对比维度 | Qt+Rviz 方案 | Foxglove 方案 |
|----------|-------------|---------------|
| C++ 代码量 | ~3000 行 | **0** |
| RViz 原生渲染 | ✅ 需要编译链接 librviz | ✅ **内置，零配置** |
| 3D 可视化 | 手动嵌 QWidget | **内置 3D Panel** |
| Display 管理 | 嵌 RViz 原生面板 | **内置 Displays 侧栏** |
| 图像显示 | 手写 QLabel/QDockWidget | **内置 Image Panel** |
| 时序图表 | 手写 QCustomPlot | **内置 Plot Panel** |
| 数据录制 | 搭 Station 后端 | **内置 MCAP 录制** |
| 跨平台 | 仅 Linux (librviz 依赖) | **Win/Mac/Linux** |
| 自定义面板 | C++ QWidget | **TypeScript (React)** |
| 面板热重载 | 需要重编译 | **秒级 HMR** |
| Agent 改动 | 相同（通用化 ros_msg_to_dict） | **相同** |
| Python 桥接 | 相同（dict_to_ros_msg） | **相同** |

**结论：** Foxglove 已经内置了 RViz 的所有可视化能力 + 3D 面板 + Plot + Image + 录制，我们只需要写 Python 桥接 + 几个 TypeScript 自定义扩展面板，开发量是 Qt 方案的 1/5。

---

## 架构

```
机器人端（Agent 改动和 Qt 方案完全相同）          地面站（Ubuntu/Win/Mac）
┌──────────────────────┐          ┌──────────────────────────────────────────────┐
│ Agent (ros1_agent.py)│  MQTT    │                                              │
│   ros_msg_to_dict()  │────────► │  ┌────────────────────────────┐             │
│   publish_sensor_data│  port    │  │ Python MQTT-ROS 桥接       │             │
│   _execute_command() │  1883    │  │ (mqtt_ros_bridge.py)       │             │
└──────────────────────┘          │  │                            │             │
                                  │  │ robot/+/sensor/# → rospy   │             │
                                  │  │ robot/+/status   → rospy   │             │
                                  │  │ robot/+/event    → rospy   │             │
                                  │  │                            │             │
                                  │  │ 命令代理:                   │             │
                                  │  │   ROS /cmd/* → MQTT cmd    │             │
                                  │  └──────────┬─────────────────┘             │
                                  │             │ ROS topics                    │
                                  │  ┌──────────▼─────────────────┐             │
                                  │  │ foxglove_bridge             │             │
                                  │  │ (ROS 节点，WebSocket 服务)   │             │
                                  │  │ ws://localhost:8765          │             │
                                  │  └──────────┬─────────────────┘             │
                                  │             │ WebSocket                     │
                                  │  ┌──────────▼─────────────────┐             │
                                  │  │ Foxglove Studio (桌面应用)   │             │
                                  │  │                            │             │
                                  │  │ ┌──────────┬─────────────┐ │             │
                                  │  │ │ 左侧面板  │ 中间         │ │             │
                                  │  │ │-机器人列表│  3D Panel    │ │             │
                                  │  │ │-控制面板  │  Image Panel │ │             │
                                  │  │ │-传输配置  │  Plot Panel  │ │             │
                                  │  │ │-事件日志  │             │ │             │
                                  │  │ │ (自写扩展)│  (Foxglove   │ │             │
                                  │  │ │           │   内置)      │ │             │
                                  │  │ └──────────┴─────────────┘ │             │
                                  │  └────────────────────────────┘             │
                                  └──────────────────────────────────────────────┘
```

## 数据流

**正向（机器人 → 地面站 → Foxglove 3D）：**
```
ROS 话题 → Agent ros_msg_to_dict() → MQTT
  → Python 桥接 → dict_to_ros_msg() → rospy 发布到本地 roscore
  → foxglove_bridge → WebSocket → Foxglove 3D/Image/Plot Panel 渲染
```

**反向（Foxglove 扩展面板 → 机器人）：**
```
Foxglove 扩展 TypeScript → publish() ROS话题
  → foxglove_bridge → 本地 roscore
  → Python 桥接订阅 /cmd/* → MQTT robot/{id}/cmd
  → Agent _execute_command() → ROS /cmd_vel
```

**话题订阅：**
```
Foxglove 传输配置面板 → publish() ROS 话题 /station/topic_request
  → Python 桥接 → MQTT station/topic/request
  → Agent 创建 ROS Subscriber → 开始转发
```

## 目录结构

```
station/foxglove/
├── README.md
├── foxglove.json                           # Foxglove 布局配置
├── config/
│   ├── transmit_config.yaml                # 话题传输配置（和 Qt 方案共享格式）
│   └── foxglove_bridge.yaml                # foxglove_bridge 参数
├── bridge/
│   ├── mqtt_ros_bridge.py                  # MQTT→ROS 桥接（和 Qt 方案共享）
│   └── dict_to_ros_msg.py                  # 通用反序列化（和 Qt 方案共享）
├── extensions/
│   ├── package.json                        # 扩展包依赖
│   ├── tsconfig.json
│   ├── src/
│   │   ├── RobotListPanel/
│   │   │   ├── index.ts                    # 机器人列表面板
│   │   │   └── RobotCard.tsx               # 单个机器人卡片组件
│   │   ├── CommandPanel/
│   │   │   └── index.ts                    # 控制面板
│   │   ├── TopicConfigPanel/
│   │   │   └── index.ts                    # 话题传输配置面板
│   │   ├── EventPanel/
│   │   │   └── index.ts                    # 事件/告警面板
│   │   ├── FleetCommPanel/
│   │   │   └── index.ts                    # 编队通信配置面板
│   │   ├── ConfigSyncDialog/
│   │   │   └── index.ts                    # 配置冲突对比弹窗
│   │   └── types/
│   │       └── index.ts                    # 共享类型定义
│   └── foxglove-extension.yml              # 扩展注册清单
├── launch/
│   └── station.launch                      # roslaunch: roscore + 桥接 + foxglove_bridge
├── scripts/
│   ├── start.sh
│   ├── stop.sh
│   └── dev.sh                              # 开发模式：启动扩展 HMR
└── tests/
    └── test_bridge.py
```

## 关键组件详解

### 1. foxglove_bridge

一个 ROS 节点（`ros-foxglove-bridge`），把 ROS master 的所有话题/服务通过 WebSocket 暴露给 Foxglove Studio。

```bash
# foxglove_bridge 不在标准 ROS apt 仓库中，需从 Foxglove 官方 GitHub Release 下载预编译 .deb 或源码编译
# 预编译包: https://github.com/foxglove/ros-foxglove-bridge/releases
# 源码编译: git clone + catkin_make / catkin build
# 安装后确认: rosrun foxglove_bridge foxglove_bridge --help
```

```xml
<!-- launch/station.launch -->
<launch>
  <!-- roscore 由 roslaunch 自动启动（检测到无 rosmaster 时自动拉起） -->

  <!-- Python MQTT-ROS 桥接 -->
  <node name="mqtt_ros_bridge" pkg="station_foxglove" type="mqtt_ros_bridge.py" output="screen" />

  <!-- Foxglove WebSocket 桥接 -->
  <node name="foxglove_bridge" pkg="foxglove_bridge" type="foxglove_bridge">
    <param name="port" value="8765" />
    <param name="max_update_frequency" value="30.0" />
    <param name="use_compression" value="true" />
  </node>
</launch>
```

Foxglove Studio 连接 `ws://localhost:8765` 后，自动发现所有 ROS 话题：`/robot_001/odom`、`/robot_001/scan`、`/robot_001/camera/image_raw` 等。

### 2. Python MQTT-ROS 桥接（和 Qt 方案完全相同）

`bridge/mqtt_ros_bridge.py` — 唯一需要和 Qt 方案共享的 Python 代码。

```
MQTT 侧:
  订阅 robot/+/sensor/#       → dict_to_ros_msg() → rospy 发布
  订阅 robot/+/status          → rospy 发布 /{robot_id}/status (自定义 ROS 消息)
  订阅 robot/+/event           → rospy 发布 /{robot_id}/event
  订阅 robot/+/cmd/ack         → rospy 发布 /{robot_id}/cmd_ack
  订阅 station/topic/response/+ → rospy 发布 /station/topic_response

ROS 侧:
  订阅 /station/topic_request  → MQTT station/topic/request
  订阅 /station/config_sync    → MQTT station/config/sync
  订阅 /cmd/{robot_id}/command → MQTT robot/{id}/cmd
  订阅 /station/discover       → MQTT station/discover
```

**关键：** 桥接把 MQTT 的状态/事件/指令也映射成 ROS 话题。Foxglove 扩展面板只和 ROS 话题交互，不需要知道 MQTT 的存在。

**多机器人命名空间：** 所有机器人共享同一个 roscore，必须给每个机器人的话题加上命名空间前缀，避免冲突。桥接在发布 ROS 话题时统一添加 robot_id 前缀：`robot/001/sensor/odom` → 桥接还原为 ROS 消息 → 发布到 `/{robot_id}/odom`（如 `/robot_001/odom`、`/robot_002/odom`）。foxglove_bridge 原生支持命名空间，3D Panel 中话题按 robots 分组显示。

### 3. Foxglove 自定义扩展面板

Foxglove Extension API 提供 TypeScript 接口，每个扩展是一个独立的 React 组件。

**扩展上下文 (`PanelExtensionContext`)：**

```typescript
interface PanelExtensionContext {
  // 订阅/发布 ROS 话题
  subscribe(topic: string, options?: { fields?: string[] }): Subscription;
  publish(topic: string, message: Message): void;
  advertise(topic: string, schemaName: string, options?: AdvertiseOptions): void;
  
  // 读取面板配置
  panel: { config: Record<string, unknown> };
  
  // 布局
  layout: LayoutActions;
  
  // 主题
  theme: Theme;
  
  // 保存面板内部状态
  saveState(state: Record<string, unknown>): void;
}
```

**机器人列表面板 (RobotListPanel)：**

```typescript
// extensions/src/RobotListPanel/index.ts

import { PanelExtensionContext } from "@foxglove/studio";
import { useEffect, useState } from "react";

// 订阅 /robot_001/status, /robot_002/status 等
// 桥接把 MQTT robot/{id}/status → ROS /{id}/status

type RobotInfo = {
  robotId: string;
  online: boolean;
  battery: number;
  mode: string;
  position: { x: number; y: number; theta: number };
};

function RobotListPanel({ context }: { context: PanelExtensionContext }) {
  const [robots, setRobots] = useState<Map<string, RobotInfo>>(new Map());
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    // 自动发现：桥接把所有在线机器人的 status 发布到 ROS
    const statusPattern = "/+/status";  // 匹配 /robot_001/status, /robot_002/status

    // Foxglove 目前不支持通配符订阅，所以通过桥接的 /station/robot_list 聚合话题
  }, []);

  // 选择机器人 → publish 到 /station/selected_robot → 其他面板订阅此话题联动
  function selectRobot(id: string) {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedIds(next);
    context.publish("/station/selected_robots", {
      robot_ids: Array.from(next)
    });
  }

  return (
    <div className="robot-list">
      {Array.from(robots.values()).map(robot => (
        <RobotCard
          key={robot.robotId}
          robot={robot}
          selected={selectedIds.has(robot.robotId)}
          onSelect={() => selectRobot(robot.robotId)}
          onDiscover={() => context.publish("/station/discover", {})}
        />
      ))}
    </div>
  );
}
```

**控制面板 (CommandPanel)：**

```typescript
// 发布命令到 /cmd/{robotId}/command → 桥接 → MQTT robot/{id}/cmd

function CommandPanel({ context }: { context: PanelExtensionContext }) {
  const [linear, setLinear] = useState(0);
  const [angular, setAngular] = useState(0);

  function sendVelocity(robotId: string) {
    context.publish(`/cmd/${robotId}/command`, {
      action: "velocity",
      params: { linear, angular }
    });
  }

  function emergencyStop() {
    // 向所有在线机器人发送急停
    robotIds.forEach(id => {
      context.publish(`/cmd/${id}/command`, {
        action: "velocity",
        params: { linear: 0, angular: 0 }
      });
    });
  }

  return (
    <div className="command-panel">
      <label>Linear (m/s): <Slider min={-1} max={1} step={0.1} value={linear} onChange={setLinear} /></label>
      <label>Angular (rad/s): <Slider min={-1} max={1} step={0.1} value={angular} onChange={setAngular} /></label>
      <button onClick={() => sendVelocity(selectedRobotId)}>Send</button>
      <button className="emergency-stop" onClick={emergencyStop}>🛑 全部急停</button>
    </div>
  );
}
```

**话题传输配置面板 (TopicConfigPanel)：**

```typescript
// 管理话题订阅：发布 /station/topic_request → 桥接 → MQTT → Agent

function TopicConfigPanel({ context }: { context: PanelExtensionContext }) {
  const [subscriptions, setSubscriptions] = useState<TopicSub[]>([]);

  function addSubscription(topic: string, msgType: string, freq: number) {
    context.publish("/station/topic_request", {
      action: "subscribe",
      topic,
      msg_type: msgType,
      freq_limit: freq,
      robot_id: selectedRobotId
    });
  }

  function removeSubscription(topic: string) {
    context.publish("/station/topic_request", {
      action: "unsubscribe",
      topic,
      robot_id: selectedRobotId
    });
  }

  // ... 渲染表格，每行有 Subscribe/Unsubscribe 按钮
}
```

### 4. Foxglove 内置面板（零代码）

| 面板 | 功能 | 在我们系统中的用法 |
|------|------|-------------------|
| **3D Panel** | 3D 场景渲染（点云/TF/Odometry/Path/Marker...） | 连上 roscore 直接渲染 `/robot_001/odom`、`/robot_001/scan` 等 |
| **Image Panel** | 实时图像（`sensor_msgs/Image`、`CompressedImage`） | 渲染 `/robot_001/camera/image_raw` |
| **Plot Panel** | 时间序列曲线（任意数值字段） | 绘制电量、速度、IMU 加速度等 |
| **Raw Message Panel** | 查看话题原始数据 | 调试用，查看最新一帧传感器数据摘要 |
| **State Transitions** | 状态机可视化 | 机器人模式切换追踪（Auto/Manual/Stop） |
| **Diagnostics** | 诊断数据 | `/diagnostics` 话题 |
| **Log Panel** | ROS 日志 | rocout |
| **MCAP Recording** | 录制所有话题到 `.mcap` 文件 | 录制回放 |

### 5. Foxglove 布局配置

Foxglove 的布局（面板排列、话题选择、Display 配置）可以保存为 JSON 文件（`.foxglove-layout.json`），团队共享。

```json
{
  "configById": {
    "3d-panel!left": {
      "cameraState": { "perspective": true, "distance": 10 },
      "followTf": "robot_001/base_link",
      "topics": {
        "/robot_001/odom": { "displayType": "Odometry" },
        "/robot_001/scan": { "displayType": "LaserScan" },
        "/robot_002/odom": { "displayType": "Odometry" }
      }
    },
    "image-panel!right": {
      "topic": "/robot_001/camera/image_raw",
      "smooth": true
    },
    "plot-panel!bottom": {
      "paths": [
        { "topicPath": "/robot_001/imu.angular_velocity.z", "label": "Yaw Rate" },
        { "topicPath": "/robot_001/status.battery", "label": "Battery" }
      ]
    }
  },
  "layout": "custom_layout_v1",
  "panels": {
    "RobotListPanel": { "side": "left", "width": 280 },
    "3D Panel": { "side": "center", "flex": 1 },
    "TopicConfigPanel": { "side": "right", "width": 320 },
    "Image Panel": { "side": "bottom", "height": 240 }
  }
}
```

启动 Foxglove 后加载这个布局文件，所有 Display 和面板自动就位。

---

## Foxglove 地面站 UI 布局

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│  Foxglove Studio — 窗口标题: ROS Ground Station                                           │
│  [菜单: File | View | Layout | Help]                                   [连接: ● ws://8765]│
├──────────────┬─────────────────────────────────┬─────────────────────────────────────────┤
│  左侧面板     │       中间区域                    │   右侧面板                               │
│  (280px)     │                                  │   (320px)                               │
│              │  ┌────────────────────────────┐  │                                          │
│  ┌─────────┐ │  │                            │  │  ┌────────────────────────────────────┐  │
│  │🔍 机器人 │ │  │                            │  │  │ 📺 3D Panel — Topics              │  │
│  │─────────│ │  │                            │  │  │────────────────────────────────────│  │
│  │         │ │  │     3D Panel               │  │  │ 可视化话题:                         │  │
│  │ ┌─────┐ │ │  │     (Foxglove 内置)         │  │  │  ☑ /robot_001/odom → Odometry     │  │
│  │ │● r1 │ │ │  │                            │  │  │  ☑ /robot_001/scan → LaserScan    │  │
│  │ │● r2 │ │ │  │     点云 / TF / Odometry   │  │  │  ☑ /robot_001/camera → Image      │  │
│  │ │○ r3 │ │ │  │     Path / Marker / Map    │  │  │  ☐ /robot_002/odom → Odometry     │  │
│  │ └─────┘ │ │  │                            │  │  │                                    │  │
│  │ [发现]   │ │  │                            │  │  │  选中话题的属性:                    │  │
│  └─────────┘ │  │                            │  │  │    Topic: /robot_001/odom          │  │
│              │  └────────────────────────────┘  │  │    Type: nav_msgs/Odometry          │  │
│  ┌─────────┐ │                                  │  │    Frame: robot_001/odom            │  │
│  │🖥 状态   │ │  ┌────────────────────────────┐  │  │    Color: blue                      │  │
│  │─────────│ │  │  Image Panel               │  │  └────────────────────────────────────┘  │
│  │r1: 85%  │ │  │  (Foxglove 内置)            │  │                                          │
│  │  manual  │ │  │  /robot_001/camera/image    │  │  ┌────────────────────────────────────┐  │
│  │  0.5m/s │ │  └────────────────────────────┘  │  │ 📊 传感器摘要 (自写扩展)             │  │
│  └─────────┘ │                                  │  │────────────────────────────────────│  │
│              │  ┌────────────────────────────┐  │  │ LaserScan /robot1/scan:             │  │
│  ┌─────────┐ │  │  Plot Panel                │  │  │   ranges: 360  near: 0.83m          │  │
│  │🎮 控制   │ │  │  (Foxglove 内置)            │  │  │ Image /robot1/camera:               │  │
│  │─────────│ │  │                            │  │  │   640×480  12.3 FPS  JPEG 85%       │  │
│  │→ 0.5 ██│ │  │  Battery ────────────────   │  │  │ Odometry /robot1/odom:              │  │
│  │↻ 0.1 ██│ │  │  Velocity ────────          │  │  │   x:1.23 y:-0.45 θ:0.78             │  │
│  │[急停🛑]│ │  │                            │  │  └────────────────────────────────────┘  │
│  │[回家🏠]│ │  └────────────────────────────┘  │                                          │
│  └─────────┘ │                                  │  ┌────────────────────────────────────┐  │
│              │                                  │  │ 📨 发送数据 (自写扩展)               │  │
│  ┌─────────┐ │                                  │  │ 目标: [robot_001 ▼]                 │  │
│  │📋 事件   │ │                                  │  │ 话题: [/custom/data]                │  │
│  │─────────│ │                                  │  │ [发送 JSON] [发送二进制]             │  │
│  │🔴 batt  │ │                                  │  └────────────────────────────────────┘  │
│  │🟡 pos   │ │                                  │                                          │
│  │🔵 mode  │ │                                  │  ┌────────────────────────────────────┐  │
│  └─────────┘ │                                  │  │ 📈 流量监控 (自写扩展)               │  │
│              │                                  │  │ /odom     ████ 45 KB/s              │  │
│  [⚙ 配置] Tab│   [📡 传输] [🔗 编队]              │  │ /scan     ██   12 KB/s              │  │
│  ┌─────────┐ │                                  │  │ /camera   ██████ 89 KB/s            │  │
│  │📡 传输   │ │                                  │  └────────────────────────────────────┘  │
│  │─────────│ │                                  │                                          │
│  │已订阅(3) │ │                                  │  ┌────────────────────────────────────┐  │
│  │/odom 10Hz│ │                                  │  │ Raw Message Panel (Foxglove内置)    │  │
│  │/scan 10Hz│ │                                  │  │ 选中的话题原始 JSON/二进制数据       │  │
│  │/cam  5Hz │ │                                  │  └────────────────────────────────────┘  │
│  │[+添加]   │ │                                  │                                          │
│  │[💾同步]  │ │                                  │                                          │
│  └─────────┘ │                                  │                                          │
├──────────────┴──────────────────────────────────┴──────────────────────────────────────────┤
│  [状态栏: 在线机器人: 2 | 已订阅话题: 5 | MQTT: 1.2MB/0.3MB | 录制: ⏺ 00:15:32]             │
└──────────────────────────────────────────────────────────────────────────────────────────┘
```

左侧面板从上到下：机器人列表 → 状态 → 控制 → 事件 → 配置 Tab (传输/编队)

中间从上到下：3D Panel → Image Panel → Plot Panel（可拖拽调整大小）

右侧从上到下：3D Topics 列表 + 属性 → 传感器摘要 → 发送数据 → 流量监控 → Raw Message

Foxglove 的面板全部可拖拽、可浮动、可关闭、可保存布局。用户可以根据自己习惯任意重排。

---

## Qt+Rviz vs Foxglove：功能逐项对照

| # | 功能 | Qt+Rviz 方案 | Foxglove 方案 | 谁更优 |
|---|------|-------------|---------------|--------|
| 1 | 3D 可视化(点云/TF/Odometry) | 嵌 librviz，~200 行 C++ | **内置 3D Panel，零代码** | Foxglove |
| 2 | Display 管理(树/勾选/属性) | 嵌 RViz 原生 DisplaysPanel | **内置 Topics 侧栏** | 平手 |
| 3 | 图像显示 | 手写 QLabel/QDockWidget | **内置 Image Panel** | Foxglove |
| 4 | 时间序列曲线(Plot) | 手写 QCustomPlot | **内置 Plot Panel** | Foxglove |
| 5 | 录制回放 | 复用 station/backend/recorder.py | **内置 MCAP Recording** | Foxglove |
| 6 | 原始消息查看 | 手写 QTextEdit | **内置 Raw Message Panel** | Foxglove |
| 7 | 机器人列表 | C++ QTreeWidget, ~150 行 | TypeScript/React, ~150 行 | 平手 |
| 8 | 机器人状态显示 | C++ QWidget, ~100 行 | 合并到 RobotListPanel, ~50 行 | Foxglove |
| 9 | 指令控制(速度/模式) | C++ QSlider/QPushButton, ~120 行 | TypeScript/React, ~120 行 | 平手 |
| 10 | 急停按钮 | 工具栏全局可见 | **需额外处理** — Foxglove 无自定义工具栏 | ⚠️ Qt 更优 |
| 11 | 话题传输配置 | C++ QTreeWidget, ~200 行 | TypeScript/React, ~200 行 | 平手 |
| 12 | 编队通信配置 | C++ QTreeWidget, ~150 行 | TypeScript/React, ~150 行 | 平手 |
| 13 | 事件/告警面板 | C++ QListWidget, ~80 行 | TypeScript/React, ~80 行 | 平手 |
| 14 | 传感器摘要(最新帧详情) | C++ QTreeWidget, ~100 行 | TypeScript/React, ~100 行 | 平手 |
| 15 | 数据发送(任意话题) | C++ QWidget, ~80 行 | TypeScript/React, ~80 行 | 平手 |
| 16 | 流量监控(带宽统计) | C++ QProgressBar, ~60 行 | TypeScript/React, ~60 行 | 平手 |
| 17 | 配置 YAML 双向同步 | ✅ 完整方案 | ✅ 桥接 ROS topic 代理 | 平手 |
| 18 | 配置冲突对比弹窗 | ✅ QDialog | ✅ TypeScript/React | 平手 |
| 19 | 话题自动发现(不背类型名) | ✅ Agent 上报 | ✅ Agent 上报(共享) | 平手 |
| 20 | 取消订阅=停传 | ✅ | ✅ (共享同一套 Agent 逻辑) | 平手 |
| 21 | 多个 3D Viewport | 需手写多个 RvizWidget | **内置支持多 Viewport** | Foxglove |
| 22 | 跨平台(Linux/Win/Mac) | ❌ 仅 Linux | ✅ | Foxglove |
| 23 | 面板布局自定义 | QDockWidget 可拖 | ✅ 全部可拖 + 保存 JSON | Foxglove |
| 24 | 编译/构建 | CMake + 编译 ROS 依赖 | **零构建** | Foxglove |
| 25 | 热重载开发 | 重编译 C++ | ✅ 秒级 HMR | Foxglove |

### Foxglove 的 2 个弱项及补丁

**弱项 1：无全局工具栏，急停按钮无法常驻顶部**

补丁：
- 方案 A：在 Foxglove 布局最顶部固定一个窄条 Panel，里面只有一个红色大按钮。关闭拖拽和标题栏，模拟工具栏效果
- 方案 B：桥接监听键盘快捷键（如空格键），触发急停 ROS topic

**弱项 2：扩展面板不能读本地 YAML，也不能直接连 MQTT**

补丁（已在方案中）：
- 桥接把 `transmit_config.yaml` 内容通过 ROS topic `/station/config` 推给扩展面板
- 桥接把 MQTT 的状态/事件/指令/配置请求全部映射到 ROS topic，扩展面板不需要直接碰 MQTT

### Foxglove 独有的优势（Qt 做不到或很麻烦）

| 优势 | 说明 |
|------|------|
| **Plot Panel** | 电池曲线、速度曲线、IMU 时序 — 直接选 topic 里的字段就出图，Qt 方案要手写 QCustomPlot |
| **多 Viewport** | 同时看俯视图 + 前视图 + 3D 自由视角，Qt 方案需要手写多个 RvizWidget 并管理同步 |
| **MCAP 录制** | 点一下按钮就录所有话题，回放直接拖时间轴。Qt 方案要复用 station/backend + 写回放 UI |
| **布局分享** | 布局存成一个 JSON 文件，同事直接导入就用 |
| **跨平台** | 桥接跑在 Linux 上，Foxglove 桌面端可以在 Windows/Mac 笔记本上远程连接 |

### 不需要写的代码

| Qt 方案需要写 | Foxglove |
|--------------|----------|
| `RvizWidget.h/.cpp` (200 行 C++) | **内置 3D Panel** |
| `MqttClient.h/.cpp` (300 行 C++) | **桥接里的 paho-mqtt (已有)** |
| `RobotManager.h/.cpp` (250 行 C++) | **桥接订阅 MQTT → ROS topic** |
| `CommandManager.h/.cpp` (150 行 C++) | **桥接转 ROS topic** |
| `MessageRouter.h/.cpp` (100 行 C++) | **桥接 + foxglove_bridge** |
| `DisplayTreePanel` 等 Display 管理 | **内置 Displays 侧栏** |
| `CMakeLists.txt` + 编译系统 | **不需要** |
| Image Panel / Plot Panel | **内置** |
| 录制引擎 | **内置 MCAP Recording** |

### 还需要写的代码

| 组件 | 语言 | 预估工作量 |
|------|------|-----------|
| `mqtt_ros_bridge.py` + `dict_to_ros_msg.py` | Python | 600-700 行（350 + 250，比 Qt 方案估计略高） |
| Agent `ros_msg_converter.py` | Python | 150 行（和 Qt 方案完全相同） |
| `RobotListPanel` 扩展 | TypeScript/React | 150 行 |
| `CommandPanel` 扩展 | TypeScript/React | 120 行 |
| `TopicConfigPanel` 扩展 | TypeScript/React | 200 行 |
| `EventPanel` 扩展 | TypeScript/React | 80 行 |
| `FleetCommPanel` 扩展 | TypeScript/React | 150 行 |
| `ConfigSyncDialog` 扩展 | TypeScript/React | 120 行 |
| Foxglove 布局 JSON + 配置 | JSON/YAML | 50 行 |
| **总计** | | **~1650 行** |

**Qt 方案 ~3000 行 C++ + 500 行 Python = 3500 行。Foxglove 方案 ~650 行 Python + ~1000 行 TypeScript = ~1650 行。仍不到 Qt 方案的一半。**

### Foxglove 的限制

| 限制 | 影响 | 解决方案 |
|------|------|---------|
| 扩展面板不能读取本地文件 | 不能直接在面板里解析 YAML | 桥接把 YAML 内容通过 ROS topic `/station/config` 传给扩展 |
| 扩展面板不能直接连 MQTT | 无法在面板里用 MQTT.js | 通过桥接的 ROS topic 代理 |
| 不支持通配符订阅 | 无法订阅 `robot/+/status` | 桥接聚合为 `/station/robot_list` 单一话题 |
| 扩展 UI 用 React | 学习成本 | TypeScript + React，前端开发基本技能 |
| macOS/Windows 上用不了 rospy | 地面站必须在 Linux 上跑桥接 | 桥接跑在 Linux 上，Foxglove 桌面应用可以远程连接 |

---

## 详细实施规格

### 阶段一：Agent 通用序列化（机器人端）

**目标：** 让 Agent 能序列化任意 ROS 消息类型，不再限制于硬编码的 7 种。

**涉及文件：**

| 文件 | 操作 | 说明 |
|------|------|------|
| `agent/ros_msg_converter.py` | **新建** | 通用序列化器，利用 `__slots__` 内省递归遍历 ROS 消息字段 |
| `agent/ros1_agent.py` | **修改** | 删除原有硬编码的 `ros_msg_to_dict()` (第45-115行)，改用新转换器；`_get_available_topics()` 改用 `rospy.get_published_topics()` 返回带类型的话题列表 |
| `protocol/messages.py` | **修改** | `DiscoverResponseData.topics` 从 `List[str]` 改为 `List[Dict[str,str]]`，存储 `{topic, msg_type}` 对象 |

**`ros_msg_converter.py` 规格：**
- 输入：任意 ROS 消息对象（有 `__slots__` 属性）
- 输出：JSON 可序列化的 dict
- 处理规则：
  - 基础类型 (int/float/str/bool) → 原样
  - bytes → int list（JSON 不支持 bytes）
  - list/tuple → 递归处理每个元素
  - numpy 类型 → Python 原生类型
  - 嵌套 ROS 消息 → 递归调用自身
  - ROS time (有 `secs`/`nsecs`) → `{secs, nsecs}`
  - ROS duration (有 `to_sec()`) → float 秒数
  - 嵌套 dict → 递归处理每个 value
  - 未知类型 → `str(val)` 兜底

**`_get_available_topics()` 改动规格：**
- 调用 `rospy.get_published_topics()` 获取机器人所有活跃话题
- 过滤 `/rosout`、`/log` 等内部话题
- 返回格式：`[{"topic": "/odom", "msg_type": "nav_msgs/Odometry"}, ...]`

**验收：**
1. 用 `sensor_msgs/Imu`、`nav_msgs/Odometry`、`sensor_msgs/LaserScan`、`sensor_msgs/CompressedImage`、`sensor_msgs/PointCloud2`、自定义消息各测试一帧，确认序列化后字段完整
2. `_get_available_topics()` 返回的列表包含话题名和消息类型
3. Discover 响应中 topics 字段为带类型的对象数组
4. 现有 89 个 protocol 测试仍全部通过

---

### 阶段二：Python MQTT-ROS 桥接

**目标：** 实现地面站端 MQTT ↔ ROS 双向桥接，MQTT 传感器数据还原为 ROS 消息发布到本地 roscore，Foxglove 扩展面板的请求通过 ROS topic 转发到 MQTT。

**涉及文件：**

| 文件 | 操作 | 说明 |
|------|------|------|
| `station/foxglove/bridge/dict_to_ros_msg.py` | **新建** | dict → ROS 消息的通用反序列化，约 200-300 行（需处理固定/动态数组、嵌套消息递归、ROS Time/Duration 还原、bytes 字段转换，且自定义消息类型需预先安装在桥接机器上） |
| `station/foxglove/bridge/mqtt_ros_bridge.py` | **新建** | 双向桥接主程序，约 350 行 |
| `station/foxglove/bridge/bridge_config.yaml` | **新建** | 桥接配置（Broker 地址、ROS master URI） |
| `station/foxglove/config/transmit_config.yaml` | **新建** | 话题传输配置，初始为空 |
| `station/foxglove/launch/station.launch` | **新建** | roslaunch 文件 |

**`dict_to_ros_msg.py` 规格：**
- 函数 `dict_to_ros_msg(data: dict, msg_type: str) -> ROS Message`
- 利用 `rospy.msg.get_message_class(msg_type)` 动态加载消息类，无需预编译
- 递归处理嵌套消息、bytes 还原、list 填充、ROS time/duration 还原
- 未知类型字段静默跳过，日志 throttle 警告

**`mqtt_ros_bridge.py` 规格：**

核心数据结构 `RobotState`：
- `robot_id: str`
- `online: bool`（30s 心跳超时自动标记离线）
- `status: dict`（最新 status 消息）
- `available_topics: List[dict]`（Agent 上报的可用话题）
- `subscriptions: Dict[str, dict]`（当前订阅话题）

MQTT → ROS 方向（6 条通道）：

| MQTT Topic | 处理逻辑 | 发布到 ROS Topic |
|------------|---------|-----------------|
| `robot/+/sensor/#` | JSON 解码 → `dict_to_ros_msg()` 还原 | `/{robot_id}{原始ROS话题}` |
| `robot/+/status` | 更新 RobotState，聚合所有机器人状态 | `/station/robot_list`（JSON） |
| `robot/+/event` | 转发事件数据 | `/{robot_id}/event`（JSON） |
| `robot/+/cmd/ack` | 转发指令确认 | `/{robot_id}/cmd_ack`（JSON） |
| `station/topic/response/+` | 更新订阅状态 + 维护话题映射表 | `/{robot_id}/topic_response`（JSON） |
| (discover 响应) | 更新 available_topics | — |

ROS → MQTT 方向（6 条通道）：

| ROS Topic | 触发来源 | 转发到 MQTT |
|-----------|---------|------------|
| `/station/topic_request` | Foxglove 扩展面板 | `station/topic/request` |
| `/station/config_sync` | Foxglove 扩展面板 | `station/config/sync`（同时写本地 YAML） |
| `/station/discover` | Foxglove 扩展面板 | `station/discover` |
| `/cmd/+/command` | Foxglove CommandPanel | `robot/{id}/cmd` |
| `/station/config_query` | Foxglove 扩展面板 | 直接返回 `/station/config_response`（本地数据，不走 MQTT） |
| `/station/available_topics_query` | Foxglove 扩展面板 | 直接返回 `/{robot_id}/available_topics`（本地缓存） |

话题映射维护（关键逻辑）：
- 收到 `topic_response (action=subscribe, result=ok)` 时，计算 `sensor_name = topic.lstrip('/').replace('/', '_')`
- 存入 `_topic_map[robot_id][sensor_name] = (ros_topic, msg_type)`
- 后续收到 `robot/{id}/sensor/{sensor_name}` 时，通过此映射确定还原到哪个 ROS 话题和消息类型

启动恢复：
- 连接 MQTT → 发 discover → 加载 `transmit_config.yaml` → 逐条恢复订阅
- 同时恢复编队通信规则

**验收：**
1. 启动桥接 + foxglove_bridge，Foxglove 连接后能看到 `/station/robot_list` 话题
2. 模拟器运行时，Foxglove 3D Panel 能看到 `/robot_001/camera_image` 话题
3. Foxglove TopicConfigPanel 发订阅 → MQTT station/topic/request 正确生成
4. Agent 回复 topic_response → 桥接正确更新话题映射
5. 取消订阅 → Agent 停止转发 → 桥接不再接收该话题数据

---

### 阶段三：Foxglove 扩展面板（TypeScript）

**目标：** 用 Foxglove Extension API 实现 6 个自定义面板，通过 ROS topic（经 foxglove_bridge）与桥接通信。

**面板间通信机制：**
所有面板通过 ROS topic 通信，不直接调用对方。选中的机器人 ID 通过 `/station/selected_robots` 广播，其他面板订阅此话题获取。

**共享类型定义 (`extensions/src/types/index.ts`)：**

| 接口 | 字段 | 用途 |
|------|------|------|
| `RobotInfo` | robot_id, online, battery, position, velocity, mode, available_topics, subscribed_topics | `/station/robot_list` 的 JSON schema |
| `TopicEntry` | topic, msg_type | 可用话题条目 |
| `TopicSubscription` | topic, msg_type, freq_limit, transport, status(pending/active/failed) | 订阅状态 |
| `FleetRule` | topic, msg_type, target, freq_limit, transport, enabled | 编队通信规则 |
| `ConfigDiff` | matched, conflict, local_only, remote_only, unavailable | 配置对比结果 |

**面板 1：RobotListPanel（约 200 行）**

- **数据来源：** 订阅 `/station/robot_list`（桥接每秒聚合发布）
- **UI：** 顶部标题栏（在线数/总数 + 全选/清除/发现按钮），中间可滚动的机器人卡片列表，底部选中计数
- **机器人卡片：** 在线绿点/离线红点，robot_id，模式标签（manual=橙/stop=红/auto=绿），电池百分比，已订阅话题数，速度值
- **交互：** 点击卡片切换选中，多选支持；"发现"按钮触发 `/station/discover`
- **输出：** 选中变化时 publish `/station/selected_robots` 通知其他面板联动

**面板 2：CommandPanel（约 180 行）**

- **数据来源：** 订阅 `/station/selected_robots` 获取当前选中目标
- **UI 分区：**
  - 速度控制区：Linear 滑杆(-1~1 m/s)、Angular 滑杆(-1~1 rad/s)、发送按钮
  - 急停按钮：占满宽度、红色背景、大字体，始终可见
  - 模式切换：Manual/Auto 两个按钮
  - 返回 Home 按钮
- **未选中机器人时：** 所有控件 disabled，显示"未选中机器人"
- **输出：** publish `/cmd/{robot_id}/command`（JSON: {action, params}）

**面板 3：TopicConfigPanel（约 280 行）**

- **数据来源：** 订阅 `/{robot_id}/topic_response` 更新订阅状态
- **UI 分区：**
  - 订阅列表表格：话题名、类型缩写、频率、状态指示灯(绿/黄/红)、删除按钮
  - 工具栏按钮：拉取可用话题、添加话题、同步配置
  - 添加话题弹窗（覆盖层）：可用话题快捷选择列表（从机器人拉取）+ 手动输入（话题名、消息类型、频率、传输层级），确认/取消
  - 配置对比弹窗（覆盖层）：5 类差异分组展示（一致/冲突/仅本地/仅远端/不可用），三个全局操作按钮（使用本地/使用远端/逐条确认）
- **交互细节：**
  - "拉取话题"按钮 → 触发 discover → 订阅 `/{robot_id}/available_topics`（一次性，3s 超时）
  - "添加话题" → 发布 `/station/topic_request (action=subscribe)` → 列表插入 pending 条目
  - "删除话题" → 发布 `/station/topic_request (action=unsubscribe)` → 从列表移除
  - "同步配置" → 发布 `/station/config_sync`（写 YAML + 同步 Agent）

**面板 4：EventPanel（约 80 行）**

- **数据来源：** 订阅 `/{robot_id}/event`
- **UI：** QListWidget 风格的告警列表，每行色标 + 机器人 ID + 事件内容 + 时间，自动滚动到最新

**面板 5：FleetCommPanel（约 150 行）**

- **数据来源：** 订阅 `/station/fleet_rules`
- **UI：** 通信规则表（源机器人 → 目标机器人、话题、频率、状态切换开关），添加/编辑弹窗（源/目标选择、话题输入、数据用途选择、频率、QoS），下发/拉取按钮
- **输出：** 修改规则后 publish `/station/config_sync`（含 fleet_rules）

**面板 6：TrafficMonitor（约 60 行）**

- **数据来源：** 订阅 `/station/traffic_stats`
- **UI：** 每个已订阅话题一行：话题名 + 水平柱状图 + KB/s 数值，按带宽降序排列
- **桥接端：** 在 `_handle_sensor_data()` 中累加每个话题的字节数，每秒发布一次统计到 `/station/traffic_stats`

**扩展注册清单 (`foxglove-extension.yml`)：** 列出 6 个面板的入口文件、名称、描述。

**验收：**
1. 6 个面板能在 Foxglove 中加载，不报错
2. 机器人列表自动发现并展示在线机器人
3. 选中机器人后，TopicConfigPanel 显示该机器人的订阅状态
4. 添加话题 → Agent 开始转发 → Foxglove 3D Panel 能看到新话题
5. 速度指令 → 机器人 velocity 更新 → 3D 中位姿变化
6. 急停按钮 → 机器人速度归零

---

### 阶段四：Foxglove 布局 + 启动脚本

**Foxglove 布局 JSON：**
- 预设面板排列（3D Panel 居中占主体，左侧放 RobotList/Command/TopicConfig 纵向排列，右侧放 TrafficMonitor/RawMessage）
- 预设 3D Panel 的 Grid + TF Display
- 文件路径：`station/foxglove/layout/ground_station.json`
- 用户可按需拖拽调整后保存个人布局

**启动脚本 (`scripts/start.sh`)：**
- 检查 roscore 是否运行 → 未运行则启动
- 启动 Python MQTT-ROS 桥接
- 启动 foxglove_bridge（参数化端口和 buffer 大小）
- 启动 Foxglove Studio 并传入 ws:// 连接地址
- Ctrl+C 全部停止
- 所有组件后台运行，日志输出到终端

**验收：**
1. `./start.sh` 一键启动，Foxglove 自动连上
2. 加载布局文件后面板排列与预设一致
3. 重启后 transmit_config.yaml 中的订阅自动恢复

---

## 与现有 Station Backend 的关系

Foxglove 方案实施后，Foxglove Studio 替代现有 Vue 前端做可视化和控制，MQTT-ROS 桥接替代 `station/backend/mqtt_handler.py` 做协议转换。现有 station/backend/ 各组件的去留：

| 组件 | 去留 | 说明 |
|------|------|------|
| `mqtt_handler.py` | **废弃** | 被 `mqtt_ros_bridge.py` 替代 |
| `robot_manager.py` | **废弃** | 机器人状态存储在桥接的 `RobotState` 中，通过 ROS topic 暴露 |
| `ws_manager.py` | **废弃** | 被 foxglove_bridge 的 WebSocket 替代 |
| `api.py` | **废弃** | REST API 不再需要，所有交互通过 ROS topic |
| `database.py` | **保留/迁移** | 如需长期存储，可改为 ROS service 或让桥接写 SQLite |
| `recorder.py` | **废弃** | MCAP Recording 替代软件录制 |
| `alert_engine.py` | **保留/迁移** | 告警逻辑可搬到桥接进程，通过 `/station/alerts` topic 推送 |
| `dependencies.py` | **废弃** | 依赖注入不再需要（单进程模式） |

**过渡策略：** 两个方案可短暂并行——现有 Station backend 继续运行维持 Vue 前端，桥接以独立进程并行运行供 Foxglove 使用，两者共享同一 MQTT broker 不会冲突（MQTT 支持多订阅者）。Foxglove 方案稳定后，停用现有 backend。

---

## 运维可靠性

### 进程守护

桥接 (`mqtt_ros_bridge.py`) 是整个地面站的数据中枢，崩溃后会丢失所有机器人连接。建议使用 systemd 守护：

```ini
# /etc/systemd/system/mqtt-ros-bridge.service
[Unit]
Description=MQTT-ROS Bridge for Foxglove Ground Station
After=network.target

[Service]
Type=simple
User=lab118
ExecStart=/usr/bin/python3 -m station.foxglove.bridge.mqtt_ros_bridge
Restart=always
RestartSec=5
Environment="ROS_MASTER_URI=http://localhost:11311"

[Install]
WantedBy=multi-user.target
```

### 自动重连

| 连接 | 断连场景 | 恢复策略 |
|------|---------|---------|
| MQTT Broker | Broker 重启/网络闪断 | paho-mqtt 内置 loop/reconnect_delay_set，指数退避 (1s→2s→4s→...→max 60s)，重连后自动恢复所有订阅 |
| ROS Master | roscore 重启 | rospy 内置重连 + `on_shutdown` 回调，Master 恢复后自动注册 |
| foxglove_bridge | bridge 进程崩溃 | 由 roslaunch respawn 或 systemd 独立管理，与桥接解耦 |

### 健康监控

桥接通过 MQTT `station/bridge/status` 每 10s 发布心跳 (JSON: `{online: true, mqtt_connected: true, ros_connected: true, uptime: 3600}`)，可与机器人一同在 Foxglove 面板中显示。

---

## 错误处理规格

桥接在消息处理中遇到异常时的行为矩阵：

| 场景 | 处理策略 | 日志级别 |
|------|---------|---------|
| MQTT 消息 JSON 解析失败 | 丢弃，计数器 +1，不中断处理 | WARN (每 60s throttle 1 条) |
| `dict_to_ros_msg()` 反序列化失败 | 丢弃该帧，计数器 +1 | WARN (每 60s throttle 1 条) |
| 收到未知 `sensor_name`（不在 `_topic_map` 中） | 丢弃，可能为旧话题残留 | DEBUG |
| 收到未知 `robot_id` 的 sensor 数据 | 丢弃 | DEBUG |
| ROS topic publish 失败 | 重试 3 次，仍失败则丢弃 | ERROR |
| MQTT publish 失败 | 放入发送队列，3 秒超时 | ERROR |
| `transmit_config.yaml` 读取失败 | 使用空白默认配置，不从 MQTT 恢复订阅 | ERROR |
| `rospy.msg.get_message_class()` 找不到消息类型 | 丢弃该帧，计数器 +1 | WARN (throttle) |

**监控端点：** 桥接暴露 HTTP `:9090/metrics`（Prometheus 格式），包括各通道消息速率、反序列化错误计数、重连次数、队列深度。

---

## TypeScript 扩展测试策略

Foxglove 扩展面板是一个个 React 组件，使用 `@foxglove/studio` 提供的 `PanelExtensionContext`。测试方案：

```typescript
// 使用 vitest + @testing-library/react

// Mock PanelExtensionContext
function createMockContext(overrides?: Partial<PanelExtensionContext>): PanelExtensionContext {
  return {
    subscribe: vi.fn().mockReturnValue({ unsubscribe: vi.fn() }),
    publish: vi.fn(),
    advertise: vi.fn(),
    panel: { config: {} },
    layout: { addPanel: vi.fn(), removePanel: vi.fn() },
    theme: { palette: 'dark', primaryColor: '#1976d2' },
    saveState: vi.fn(),
    ...overrides,
  } as unknown as PanelExtensionContext;
}
```

| 面板 | 测试要点 |
|------|---------|
| RobotListPanel | 渲染 `robot_list` 数据 → 卡片显示正确；选中/取消选中 → `selected_robots` topic 发布正确 |
| CommandPanel | 滑块变化 → state 更新；发送按钮 → publish `/cmd/{id}/command` 格式正确；急停 → 所有选中机器人收到 velocity=0 |
| TopicConfigPanel | 添加/删除 → topic_request 正确生成；pending→active 状态转换；配置对比弹窗分组逻辑 |
| EventPanel | 事件消息 → 列表渲染；自动滚动到最新 |
| FleetCommPanel | 规则 CRUD → config_sync 发布正确 |

**CI 集成：** `./extensions/` 目录下运行 `pnpm test`，配置 GitHub Actions 或本地 pre-commit hook。

---

## 安全考量

| 层面 | 风险 | 缓解措施 |
|------|------|---------|
| MQTT Broker | 无认证，任何人可连接并发布伪造传感器数据/指令 | Mosquitto 配置 `allow_anonymous false` + `password_file`；Agent/Station 各用独立账号 |
| foxglove_bridge WebSocket | 无鉴权，局域网内任何人可连接并订阅所有话题 | 仅监听 `127.0.0.1:8765`（本地 Foxglove Studio 直连）；如需远程，走 SSH tunnel 或 VPN |
| 机器人指令 `/cmd/{id}/command` | 任何人都可通过 ROS topic 发控制指令 | 桥接在转 MQTT 之前校验消息来源（仅接受 foxglove_bridge 转发的消息，非随机 ROS node） |
| 敏感数据 | 传感器数据、机器人位姿可能含敏感信息 | 网络隔离（VPN/VLAN），MQTT TLS（mosquitto 配置 listener 8883 + 证书） |

**默认安全配置：** 开发环境关闭认证方便调试，生产部署时必须启用上述所有措施。

---

## 验证方案

```bash
# 启动
source /opt/ros/noetic/setup.bash
roslaunch station/foxglove/launch/station.launch

# 打开 Foxglove Studio → 连接 ws://localhost:8765 → 加载布局文件

# 测试1：机器人发现
# → RobotListPanel 显示所有在线机器人

# 测试2：3D 渲染
# → 3D Panel 自动显示 /robot_001/odom、/robot_001/scan

# 测试3：话题订阅
# → TopicConfigPanel 添加话题 → Agent 开始转发 → 3D Panel 即时渲染

# 测试4：指令控制
# → CommandPanel 发 velocity → 机器人速度更新 → 3D 中位姿移动

# 测试5：录制回放
# → 点 MCAP Recording → 跑一段 → 停止 → 加载 .mcap 文件 → 拖动时间轴回看
```
