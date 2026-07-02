# Husky 重型数据仿真镜像实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 新增一个可复现构建的 Husky 仿真机器人 Docker 服务，默认启动 Gazebo、Velodyne、RealSense、`hdl_graph_slam` 和 ROS1 Agent，用于测试点云和地图点云等重型数据链路。

**架构：** 新增 Husky 专用 Dockerfile，在镜像构建期复制并编译 `/home/lab118/claudeCode_Project/catkin_sim/src`。运行期通过 supervisord 管理 `roscore`、headless SLAM launch 和 ROS1 Agent，并在 `docker-compose.yml` 中新增 `robot-husky-001` 服务。Agent 使用 `agent/configs/husky_001.yaml` 默认订阅重型话题，点云和图像优先走 `http_stream`。

**技术栈：** Docker Compose、ROS Noetic、catkin、Gazebo 11、supervisord、PyYAML、ROS1 Agent、MQTT、HTTP stream。

---

## 文件结构

- 创建 `docker/Dockerfile.husky`：定义 Husky 仿真镜像的系统依赖、catkin 工作空间复制和构建流程。
- 创建 `docker/supervisord-husky.conf`：管理 `roscore`、`husky_slam` 和 `agent` 三个进程。
- 创建 `agent/configs/husky_001.yaml`：定义 Husky 机器人 ID、MQTT broker、HTTP stream、宿主机可访问的 stream URL 和默认 ROS 话题订阅。
- 修改 `docker-compose.yml`：新增 `robot-husky-001` 服务，使用外部 `catkin_sim` 作为 build context。
- 创建或更新验证命令记录：使用 `docker compose config`、YAML 解析和可行的 Docker build 检查。

### 任务 1：添加 Husky Agent 配置

**文件：**
- 创建：`agent/configs/husky_001.yaml`

- [ ] **步骤 1：创建配置文件**

写入 Husky 专用配置，重型话题使用 `http_stream`：

```yaml
robot_id: "husky_001"
broker_host: "localhost"
broker_port: 1883
status_interval: 2.0
default_freq_limit: 10.0
http_stream_port: 8080
stream_base_url: "http://localhost:18080"
auto_reconnect: true
reconnect_delay: 5.0
subscriptions:
- topic: /velodyne_points
  msg_type: sensor_msgs/PointCloud2
  freq_limit: 2.0
  transport: http_stream
  qos: 0
  compression: {}
- topic: /realsense/depth/color/points
  msg_type: sensor_msgs/PointCloud2
  freq_limit: 1.0
  transport: http_stream
  qos: 0
  compression: {}
- topic: /hdl_graph_slam/map_points
  msg_type: sensor_msgs/PointCloud2
  freq_limit: 0.5
  transport: http_stream
  qos: 0
  compression: {}
- topic: /hdl_graph_slam/odom
  msg_type: nav_msgs/Odometry
  freq_limit: 10.0
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
- topic: /joint_states
  msg_type: sensor_msgs/JointState
  freq_limit: 10.0
  transport: mqtt_json
  qos: 1
  compression: {}
fleet_rules: []
```

- [ ] **步骤 2：运行 YAML 解析检查**

运行：`python3 -c "import yaml; yaml.safe_load(open('agent/configs/husky_001.yaml')); print('ok')"`
预期：输出 `ok`。

### 任务 2：添加 Husky 镜像 Dockerfile

**文件：**
- 创建：`docker/Dockerfile.husky`

- [ ] **步骤 1：创建 Dockerfile**

Dockerfile 使用 `catkin_sim` 作为 build context，因此复制 context 内的 `src/`：

```dockerfile
FROM ros:noetic-ros-base

ENV DEBIAN_FRONTEND=noninteractive
ENV CATKIN_WS=/opt/catkin_sim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    python3-pip \
    python3-catkin-tools \
    python3-rosdep \
    supervisor \
    ros-noetic-gazebo-ros \
    ros-noetic-gazebo-plugins \
    ros-noetic-gazebo-ros-control \
    ros-noetic-controller-manager \
    ros-noetic-interactive-marker-twist-server \
    ros-noetic-joint-state-controller \
    ros-noetic-robot-localization \
    ros-noetic-robot-state-publisher \
    ros-noetic-twist-mux \
    ros-noetic-xacro \
    ros-noetic-nodelet \
    ros-noetic-pcl-ros \
    ros-noetic-tf \
    ros-noetic-tf2-ros \
    ros-noetic-cv-bridge \
    ros-noetic-image-transport \
    ros-noetic-realsense2-description \
    libomp-dev \
    libsuitesparse-dev \
    libg2o-dev \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    libgazebo11-dev \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir paho-mqtt pyyaml numpy

RUN mkdir -p ${CATKIN_WS}/src
COPY src/ ${CATKIN_WS}/src/
WORKDIR ${CATKIN_WS}
RUN /bin/bash -c "source /opt/ros/noetic/setup.bash && PYTHONNOUSERSITE=1 catkin_make -j2 -l2"

WORKDIR /app
ENV PYTHONPATH=/app
ENV LIBGL_ALWAYS_SOFTWARE=1

CMD ["/usr/bin/supervisord", "-n", "-c", "/etc/supervisor/supervisord.conf"]
```

- [ ] **步骤 2：检查 Dockerfile 语法入口**

运行：`docker build -f docker/Dockerfile.husky /home/lab118/claudeCode_Project/catkin_sim --target does-not-exist`
预期：Docker 能读取 Dockerfile；若失败，应是 `target stage "does-not-exist" could not be found`，而不是 Dockerfile 路径或 build context 错误。

### 任务 3：添加 supervisord 编排

**文件：**
- 创建：`docker/supervisord-husky.conf`

- [ ] **步骤 1：创建 supervisord 配置**

```ini
[supervisord]
nodaemon=true
loglevel=info
user=root

[program:roscore]
command=/bin/bash -c "source /opt/ros/noetic/setup.bash && roscore"
autorestart=true
startsecs=3
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:husky_slam]
command=/bin/bash -c "source /opt/ros/noetic/setup.bash && source /opt/catkin_sim/devel/setup.bash && export LIBGL_ALWAYS_SOFTWARE=1 && until rostopic list &>/dev/null; do echo 'waiting for roscore...'; sleep 1; done && xvfb-run -a -s '-screen 0 1280x1024x24' roslaunch husky_velodyne_gazebo husky_hdl_graph_slam.launch gui:=false headless:=true"
autorestart=true
startsecs=8
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0

[program:agent]
command=/bin/bash -c "source /opt/ros/noetic/setup.bash && source /opt/catkin_sim/devel/setup.bash && until rostopic list &>/dev/null; do echo 'waiting for roscore...'; sleep 1; done && python3 -m agent.main --agent-type ros1 --config /app/agent/configs/%(ENV_ROBOT_ID)s.yaml --broker-host %(ENV_BROKER_HOST)s --robot-id %(ENV_ROBOT_ID)s"
autorestart=true
startsecs=5
stdout_logfile=/dev/stdout
stdout_logfile_maxbytes=0
stderr_logfile=/dev/stderr
stderr_logfile_maxbytes=0
environment=BROKER_HOST="%(ENV_BROKER_HOST)s",ROBOT_ID="%(ENV_ROBOT_ID)s"
```

- [ ] **步骤 2：检查配置包含三个 program**

运行：`rg -n "program:(roscore|husky_slam|agent)" docker/supervisord-husky.conf`
预期：输出三个 program 行。

### 任务 4：接入 Docker Compose

**文件：**
- 修改：`docker-compose.yml`

- [ ] **步骤 1：新增 `robot-husky-001` 服务**

在 TurtleBot 服务之后加入：

```yaml
  robot-husky-001:
    build:
      context: /home/lab118/claudeCode_Project/catkin_sim
      dockerfile: /home/lab118/claudeCode_Project/ros-ground-station-pyqt/docker/Dockerfile.husky
    container_name: husky-001
    environment:
      - ROBOT_ID=husky_001
      - BROKER_HOST=host-gateway
    extra_hosts:
      - "host-gateway:host-gateway"
    restart: unless-stopped
    ports:
      - "18080:8080"
    volumes:
      - ./protocol:/app/protocol:ro
      - ./agent:/app/agent:rw
      - ./docker/supervisord-husky.conf:/etc/supervisor/conf.d/ros-agent.conf:ro
    stdin_open: true
    tty: true
```

- [ ] **步骤 2：验证 Compose 解析**

运行：`docker compose config --services`
预期：输出包含 `robot-husky-001`。

### 任务 5：最终验证与记录

**文件：**
- 检查：`docker/Dockerfile.husky`
- 检查：`docker/supervisord-husky.conf`
- 检查：`agent/configs/husky_001.yaml`
- 检查：`docker-compose.yml`

- [ ] **步骤 1：运行配置验证**

运行：

```bash
python3 -c "import yaml; yaml.safe_load(open('agent/configs/husky_001.yaml')); print('yaml ok')"
docker compose config --services
```

预期：第一条输出 `yaml ok`，第二条包含 `robot-husky-001`。

- [ ] **步骤 2：尝试构建 Husky 镜像**

运行：`docker compose build robot-husky-001`
预期：在网络和 apt 源可用时完成构建；如果因网络、包名或外部源问题失败，记录首个失败命令和错误，不隐瞒未完成的运行态验证。

- [ ] **步骤 3：运行态冒烟验证**

运行：

```bash
docker compose up -d robot-husky-001
docker compose logs --tail=120 robot-husky-001
```

预期：日志显示 `roscore`、`husky_slam` 和 `agent` 均启动。环境允许时，在容器内检查：

```bash
docker exec husky-001 bash -lc "source /opt/ros/noetic/setup.bash && source /opt/catkin_sim/devel/setup.bash && rostopic info /velodyne_points && rostopic info /hdl_graph_slam/map_points"
```

预期：两个话题存在；完整频率验证可继续使用 `rostopic hz`。

## 自检

- 规格中的镜像职责、默认启动 SLAM、默认重型话题、Compose 服务和验证标准均有对应任务。
- 计划没有依赖未定义函数或类型；所有新增文件路径均为精确路径。
- 运行态验证依赖 Docker、apt 网络和 Gazebo 环境，计划中明确要求记录无法验证的范围。
