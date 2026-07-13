# 真实环境部署指南

本文档面向一台未部署过的地面站 PC 和多台机器人上位机 PC。默认场景是：地面站 PC 运行 MQTT Broker、MQTT-ROS Bridge 和 Qt 前端；每台机器人上位机只运行本机 ROS 系统和一个 Agent。各机器人 ROS 网络彼此隔离，跨机器数据统一通过 MQTT 传输。

## 一、部署拓扑

推荐拓扑如下：

```text
机器人 1 ROS ─ Agent ┐
机器人 2 ROS ─ Agent ├─ MQTT ─ Broker(地面站 PC) ─ Bridge ─ 地面站 roscore ─ Qt 前端/RViz
机器人 N ROS ─ Agent ┘
```

职责边界：

- 地面站 PC：运行 Broker、Bridge、Qt 前端和地面站本地 roscore。
- 机器人上位机 PC：运行机器人自己的 ROS master、驱动、SLAM、导航和 Agent。
- Agent：只在机器人端运行，一个机器人默认对应一个 Agent。
- Bridge：只在地面站端运行，把 MQTT 数据重新发布到地面站本地 ROS。
- RViz：只连接地面站本地 ROS master，不直接连接机器人 ROS master。

## 二、网络与端口规划

部署前先确定每台机器的固定 IP 或稳定主机名。

示例：

```text
地面站 PC: 192.168.1.10
机器人 1: 192.168.1.21, robot_id=turtlebot_001
机器人 2: 192.168.1.22, robot_id=husky_001
MQTT Broker: 192.168.1.10:1883
机器人 HTTP stream: 每台机器人默认 8080
```

网络要求：

- 所有机器人上位机可以访问地面站 PC 的 `1883` 端口。
- 如果订阅点云、压缩图像等 `http_stream` 话题，地面站 PC 必须能访问机器人上位机的 `http_stream_port`，默认是 `8080`。
- 地面站和机器人不要共用一个跨机器 ROS master。本项目的跨机器链路是 MQTT，不是 ROS master 直连。
- 每台机器人 `robot_id` 必须唯一，并且要和地面站配置中的机器人 key 一致。

Ubuntu 防火墙示例：

```bash
# 地面站 PC 开放 MQTT
sudo ufw allow 1883/tcp

# 机器人上位机如果使用 http_stream，开放 Agent HTTP stream 端口
sudo ufw allow 8080/tcp
```

## 三、地面站 PC 环境安装

地面站 PC 推荐 Ubuntu 20.04 + ROS Noetic。

安装系统依赖：

```bash
sudo apt update
sudo apt install -y \
  git \
  python3 \
  python3-pip \
  build-essential \
  cmake \
  curl \
  mosquitto \
  mosquitto-clients \
  ros-noetic-desktop-full \
  python3-catkin-tools
```

获取代码并安装 Python 依赖：

```bash
git clone https://github.com/xujunshao1999/ros-ground-station-pyqt.git
cd ros-ground-station-pyqt
pip3 install -e ".[qt,dev]"
```

默认部署建议直接使用系统 Python，这样 ROS Noetic 的 `rospy`、`roslaunch`、`rostopic` 等系统 Python 包最容易被项目访问。

如果需要隔离 Python 依赖，再额外安装 `python3-venv` 并创建带系统包访问能力的虚拟环境：

```bash
sudo apt install -y python3-venv
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e ".[qt,dev]"
```

不要使用不带 `--system-site-packages` 的普通 venv，否则容易找不到 ROS Noetic 的 Python 包。

构建嵌入式 RViz 组件：

```bash
./qt_frontend/scripts/build_rviz_widget.sh
```

构建完成后应存在：

```text
qt_frontend/native/build/librviz_widget.so
```

## 四、Broker 配置

默认部署中 Broker 跑在地面站 PC，配置文件是：

```text
broker/mosquitto.conf
```

内网调试可先使用默认配置：

```conf
listener 1883
allow_anonymous true
```

启动地面站脚本时会自动检查并启动 Mosquitto。如果需要单独验证 Broker：

```bash
./broker/start.sh
```

生产环境建议后续补充：

- 关闭匿名访问，配置 `password_file`。
- 使用 ACL 限制机器人只能访问自己的 topic。
- 跨不可信网络时启用 TLS。
- 给 Broker 配置 systemd 服务和日志轮转。

## 五、地面站配置文件

### 1. Qt 前端配置

文件：

```text
qt_frontend/config/config.yaml
```

如果 Broker 跑在地面站本机，`broker_host` 可以写 `localhost`。如果 Broker 独立部署，改为 Broker IP 或主机名。

示例：

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
  fixed_frame: "global_map"
  global_frame: "global_map"
  robot_frame_template: "{robot_id}/base_link"
  follow_selected_robot_frame: true
  robot_fixed_frames:
    husky_001: "husky_001/base_link"
```

说明：

- `global_frame` 是全局视角 fixed frame，通常保持 `global_map`。
- `robot_frame_template` 是未单独配置机器人时的局部视角 frame 生成规则。
- `robot_fixed_frames` 只在某些机器人不适合默认模板时填写。

### 2. Bridge 配置

文件：

```text
bridge/bridge_config.yaml
```

示例：

```yaml
mqtt:
  broker_host: "localhost"
  broker_port: 1883
  client_id: "mqtt_ros_bridge"

ros:
  master_uri: "http://localhost:11311"
  node_name: "mqtt_ros_bridge"
  max_update_frequency: 30.0
  namespace_tf_frames: true

heartbeat_timeout: 30.0
transmit_config_path: "../config/transmit_config.yaml"

fleet_frames:
  enabled: true
  global_frame: "global_map"
  robots:
    turtlebot_001:
      local_root_frame: "map"
      pose:
        x: 0.0
        y: 0.0
        z: 0.0
        roll: 0.0
        pitch: 0.0
        yaw: 0.0
    husky_001:
      local_root_frame: "map"
      pose:
        x: 5.0
        y: 0.0
        z: 0.0
        roll: 0.0
        pitch: 0.0
        yaw: 0.0
```

说明：

- `fleet_frames.robots` 必须包含需要在全局坐标中显示的机器人。
- `local_root_frame` 通常是机器人本地 SLAM 或里程计根 frame，例如 `map`。
- `pose` 是机器人本地 map 放到 `global_map` 下的初始外参。

### 3. 话题传输配置

文件：

```text
qt_frontend/config/transmit_config.yaml
```

该文件保存地面站希望每台机器人上报哪些 ROS topic。

示例：

```yaml
robots: {}
subscriptions:
  turtlebot_001:
    - topic: /odom
      msg_type: nav_msgs/Odometry
      freq_limit: 30.0
      transport: mqtt_binary
      qos: 0
      compression: {}
    - topic: /tf
      msg_type: tf2_msgs/TFMessage
      freq_limit: 0.0
      transport: mqtt_binary
      qos: 0
      compression: {}
    - topic: /tf_static
      msg_type: tf2_msgs/TFMessage
      freq_limit: 10.0
      transport: mqtt_binary
      qos: 1
      compression: {}
    - topic: /scan
      msg_type: sensor_msgs/LaserScan
      freq_limit: 0.0
      transport: mqtt_binary
      qos: 0
      compression: {}

  husky_001:
    - topic: /hdl_graph_slam/map_points
      msg_type: sensor_msgs/PointCloud2
      freq_limit: 0.5
      transport: http_stream
      qos: 0
      compression: {}
    - topic: /tf
      msg_type: tf2_msgs/TFMessage
      freq_limit: 0.0
      transport: mqtt_binary
      qos: 0
      compression: {}

fleet_rules: []
```

注意：

- `subscriptions` 的一级 key 必须和机器人端 `robot_id` 一致。
- `topic` 必须是机器人本机 ROS 中真实存在的话题。
- `msg_type` 必须和 `rostopic info <topic>` 显示的类型一致。
- 点云、较大图像建议使用 `http_stream`；普通状态、TF、里程计可使用 `mqtt_binary` 或 `mqtt_json`。

## 六、机器人上位机环境安装

每台机器人上位机推荐 Ubuntu 20.04 + ROS Noetic。机器人自身的驱动、底盘、传感器、SLAM 或导航依赖按机器人厂商或现有工作空间安装。

安装基础依赖：

```bash
sudo apt update
sudo apt install -y \
  git \
  python3 \
  python3-pip \
  mosquitto-clients \
  ros-noetic-ros-base
```

获取代码并安装 Agent 依赖：

```bash
git clone https://github.com/xujunshao1999/ros-ground-station-pyqt.git
cd ros-ground-station-pyqt
pip3 install -e .
```

机器人端不需要安装 Qt/RViz，也不需要运行 `qt_frontend/scripts/start.sh`。

如果机器人 ROS 工作空间在 `~/catkin_ws`，确认它能正常 source：

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
rostopic list
```

如果工作空间不在 `~/catkin_ws`，启动 Agent 时用 `ROBOT_WS_SETUP` 指定：

```bash
ROBOT_WS_SETUP=/path/to/catkin_ws/devel/setup.bash ./agent/scripts/start.sh
```

## 七、机器人 Agent 配置

默认配置文件：

```text
agent/configs/default.yaml
```

一台机器人上位机只运行一个 Agent 时，可以直接维护这个文件。多机器人部署中更推荐每台机器人一份独立配置，例如：

```text
agent/configs/turtlebot_001.yaml
agent/configs/husky_001.yaml
```

复制默认配置：

```bash
cp agent/configs/default.yaml agent/configs/turtlebot_001.yaml
cp agent/configs/default.yaml agent/configs/husky_001.yaml
```

TurtleBot 示例：

```yaml
robot_id: "turtlebot_001"
broker_host: "192.168.1.10"
broker_port: 1883

status_interval: 2.0
default_freq_limit: 30.0

http_stream_port: 8080
stream_public_host: "192.168.1.21"

ros_master_uri: "http://localhost:11311"
ros_namespace: "/"

subscriptions:
  - topic: "/odom"
    msg_type: "nav_msgs/Odometry"
    freq_limit: 30.0
    transport: "mqtt_binary"
    qos: 0
    compression: {}
  - topic: "/tf"
    msg_type: "tf2_msgs/TFMessage"
    freq_limit: 0.0
    transport: "mqtt_binary"
    qos: 0
    compression: {}
  - topic: "/tf_static"
    msg_type: "tf2_msgs/TFMessage"
    freq_limit: 10.0
    transport: "mqtt_binary"
    qos: 1
    compression: {}

fleet_rules: []
```

Husky 点云示例：

```yaml
robot_id: "husky_001"
broker_host: "192.168.1.10"
broker_port: 1883

http_stream_port: 8080
stream_public_host: "192.168.1.22"

subscriptions:
  - topic: "/hdl_graph_slam/map_points"
    msg_type: "sensor_msgs/PointCloud2"
    freq_limit: 0.5
    transport: "http_stream"
    qos: 0
    compression: {}
  - topic: "/tf"
    msg_type: "tf2_msgs/TFMessage"
    freq_limit: 0.0
    transport: "mqtt_binary"
    qos: 0
    compression: {}

fleet_rules: []
```

关键配置说明：

- `robot_id`：每台机器人唯一，必须和地面站配置一致。
- `broker_host`：填地面站 PC 的 IP 或 Broker 主机名。不要在机器人上继续使用 `localhost`，除非 Broker 就跑在机器人本机。
- `stream_public_host`：填地面站 PC 能访问到的机器人 IP。使用 `http_stream` 时建议显式填写。
- `ros_master_uri`：通常是机器人本机 `http://localhost:11311`。
- `subscriptions`：Agent 启动后自动恢复的订阅列表，也会被地面站下发配置更新。

## 八、启动与停止

### 1. 启动地面站

在地面站 PC：

```bash
cd ros-ground-station-pyqt
./qt_frontend/scripts/start.sh
```

该脚本会检查并启动：

- 地面站本地 roscore。
- Mosquitto Broker。
- station launch。
- MQTT-ROS Bridge。
- Qt 前端。

停止地面站本地前端链路：

```bash
./qt_frontend/scripts/stop.sh
```

该停止脚本只处理地面站本地 Qt 前端、Bridge 和 station launch，不停止机器人端 Agent。

### 2. 启动机器人 Agent

在每台机器人上位机，先确认机器人 ROS 已经运行：

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
rostopic list
```

启动 Agent：

```bash
cd ros-ground-station-pyqt
CONFIG_PATH=agent/configs/turtlebot_001.yaml ./agent/scripts/start.sh
```

如果当前机器人只维护 `agent/configs/default.yaml`，可以直接运行：

```bash
./agent/scripts/start.sh
```

停止 Agent：

```bash
./agent/scripts/stop.sh
```

默认一台机器人一个 Agent 时，不需要手动指定 `PID_FILE`。脚本默认使用：

```text
logs/agent.pid
```

## 九、验证命令

### 1. 验证 Broker 可访问

地面站 PC：

```bash
mosquitto_sub -h localhost -t '#' -v
```

机器人上位机：

```bash
mosquitto_pub -h 192.168.1.10 -t deploy/check -m "hello"
```

如果地面站订阅窗口能看到消息，说明机器人到 Broker 的 MQTT 链路可用。

### 2. 验证机器人 ROS 话题

机器人上位机：

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
rostopic list
rostopic info /tf
```

对每个写入 `subscriptions` 的 topic，都用 `rostopic info` 确认真实类型。

### 3. 验证地面站本地 ROS 重发布

地面站 PC：

```bash
source /opt/ros/noetic/setup.bash
rostopic list
rostopic echo /tf
```

正常情况下，Bridge 会把机器人数据重新发布为地面站本地 topic，例如：

```text
/turtlebot_001/odom
/turtlebot_001/scan
/husky_001/hdl_graph_slam/map_points
/tf
/tf_static
```

### 4. 验证 HTTP stream

如果机器人使用 `http_stream`，在地面站 PC 检查机器人端口是否可达：

```bash
curl -I http://192.168.1.22:8080/
```

具体数据 URL 由 Agent 在 MQTT meta 消息中提供，端口不通时 Bridge 会无法拉取点云或大图像。

## 十、日志位置

地面站 PC：

```text
logs/roscore.log
logs/mosquitto-start.log
logs/station.launch.log
logs/bridge.log
logs/pids/
```

机器人上位机：

```text
logs/agent.log
logs/agent.pid
```

排查顺序建议：

1. 先看机器人端 `logs/agent.log`，确认 Agent 是否连上 Broker。
2. 再看地面站 `logs/bridge.log`，确认 Bridge 是否收到机器人消息。
3. 最后看 Qt 前端界面和地面站 `rostopic list`。

## 十一、常见问题

### 1. 机器人一直不上线

检查：

- 机器人 `agent/configs/<robot_id>.yaml` 中 `broker_host` 是否仍是 `localhost`。
- 地面站 PC 的 `1883` 端口是否被防火墙拦截。
- `robot_id` 是否和地面站 `transmit_config.yaml` 中的机器人 key 一致。
- `logs/agent.log` 中是否有 MQTT 连接失败。

### 2. 地面站能看到机器人，但没有某个 topic

检查：

- 机器人本机是否真的存在该 ROS topic。
- `msg_type` 是否和 `rostopic info` 一致。
- 地面站是否已经下发或保存对应订阅。
- Agent 日志中是否有订阅失败或类型导入失败。

### 3. 点云或大图像不显示

检查：

- 该 topic 是否配置为 `http_stream`。
- 机器人 `stream_public_host` 是否填了地面站可访问的 IP。
- 机器人 `8080` 端口是否开放。
- Bridge 日志中是否有 HTTP 拉取失败。

### 4. RViz 切到机器人 fixed frame 后部分数据报 TF 错

这是 RViz fixed frame 和数据 frame 的 TF 连通性问题。全局视角通常使用 `global_map`，单机器人局部视角通常使用 `{robot_id}/base_link`。某些 SLAM 点云只在 `map` 或 `global_map` 下更稳定，切到 `base_link` 时可能因为时间戳或 TF 缓存导致外推错误。优先确认 `/tf`、`/tf_static` 是否完整，以及 `bridge/bridge_config.yaml` 中 fleet frame 是否包含该机器人。

### 5. 停止脚本没有关闭机器人 Agent

这是预期行为。地面站停止脚本只管理地面站本地进程；机器人 Agent 必须在对应机器人上位机执行：

```bash
./agent/scripts/stop.sh
```

## 十二、生产环境建议

- 固定地面站和机器人 IP，或配置稳定 DNS。
- Broker 开启账号密码、ACL 和必要的 TLS。
- 为地面站脚本和机器人 Agent 配置 systemd 服务，确保开机自启动和异常重启。
- 为 `logs/` 配置日志轮转，避免长期运行占满磁盘。
- 每台机器人维护独立 `agent/configs/<robot_id>.yaml`，不要多台机器人共用同一个配置文件。
- 上线前为每个订阅 topic 记录 `rostopic info` 输出，作为配置审查依据。
- 对点云、图像等高带宽 topic 先限频，再逐步调高，避免占满 Wi-Fi 或 Broker 队列。
