# Husky 重型数据仿真机器人镜像设计

## 一、目标

新增一个可复现构建的 Husky 仿真机器人 Docker 镜像，用于生成真实 Gazebo/SLAM 链路中的重型 ROS 数据。该镜像应类似现有 TurtleBot 仿真镜像：容器启动后自动运行 `roscore`、Gazebo 仿真、SLAM 和 `ROS1 Agent`，地面站可通过 MQTT 与 HTTP stream 验证点云、图像、地图点云等大数据传输能力。

## 二、默认运行内容

容器默认启动 `husky_velodyne_gazebo husky_hdl_graph_slam.launch`，并使用无 GUI/headless 模式运行。该 launch 会启动：

- Husky Gazebo 仿真；
- Velodyne VLP-16 点云；
- Intel RealSense D435 图像、深度图和深度点云；
- `hdl_graph_slam` 三维激光 SLAM；
- SLAM 里程计、地图点云和 `map -> hdl_odom` TF 发布。

默认不提供“只启动 Gazebo、不启动 SLAM”的容器服务，因为本次目标就是稳定生成重型数据。

## 三、Docker 架构

新增 `docker/Dockerfile.husky`，镜像基于 ROS Noetic 环境构建。构建期将 `catkin_sim/src` 复制到镜像内的 catkin 工作空间并执行 `PYTHONNOUSERSITE=1 catkin_make -j2 -l2`，确保 Husky、Velodyne、RealSense 和 `hdl_graph_slam` 相关包在镜像内完成编译。镜像内安装 `xvfb`，用于在无宿主 X11 授权的 headless 容器中为 Gazebo depth camera 提供稳定渲染上下文。

由于 `catkin_sim` 位于当前仓库外部，Compose 中 Husky 服务的 build context 指向 `/home/lab118/claudeCode_Project/catkin_sim`。Dockerfile 从该 context 复制 `src/`；运行期仍挂载当前地面站仓库的 `agent/` 与 `protocol/`，保持与现有 TurtleBot 服务一致的开发方式。

## 四、运行编排

新增 `docker/supervisord-husky.conf` 管理容器内进程：

- `roscore`：提供容器内 ROS master；
- `husky_slam`：等待 roscore 可用后通过 `xvfb-run` 启动 headless Husky + Velodyne + RealSense + `hdl_graph_slam`；
- `agent`：等待 roscore 可用后启动 `python3 -m agent.main --agent-type ros1`，使用 Husky 专用配置连接宿主机 MQTT broker。

新增 `docker-compose.yml` 服务 `robot-husky-001`，环境变量使用 `ROBOT_ID=husky_001`、`BROKER_HOST=host-gateway`，并挂载 `agent/`、`protocol/` 和 `docker/supervisord-husky.conf`。

## 五、默认订阅与传输策略

新增 `agent/configs/husky_001.yaml`。默认订阅面向重型数据验证：

- `/velodyne_points`：`sensor_msgs/PointCloud2`，使用 `http_stream`；
- `/realsense/depth/color/points`：`sensor_msgs/PointCloud2`，使用 `http_stream`；
- `/hdl_graph_slam/map_points`：`sensor_msgs/PointCloud2`，使用 `http_stream`；
- `/hdl_graph_slam/odom`：`nav_msgs/Odometry`，使用 `mqtt_binary`；
- `/tf`、`/tf_static`：`tf2_msgs/TFMessage`，使用 `mqtt_binary`；
- `/joint_states`：`sensor_msgs/JointState`，使用 `mqtt_json`。

重型 payload 默认不走 MQTT JSON，避免大点云导致 broker 压力和序列化开销过高。当前 ROS1 Agent 的 HTTP serialized snapshot 优先覆盖 `sensor_msgs/PointCloud2`，所以 RealSense RGB 原始图像不作为默认订阅；如需测试图像链路，可在后续扩展图像 HTTP snapshot 后启用。

## 六、验证标准

实现完成后至少验证：

- `docker compose config` 能解析新增服务；
- Husky Dockerfile 能进入构建流程，若因网络或 apt 源受限失败，需要明确记录失败位置；
- `agent/configs/husky_001.yaml` 能被 YAML 解析；
- 运行态环境可用时，`robot-husky-001` 启动后应能看到 `/velodyne_points`、`/realsense/depth/color/points`、`/hdl_graph_slam/map_points` 等话题。

ROS/Gazebo 完整运行验证依赖本机 Docker、显卡/软件渲染和 ROS 包构建环境；如受网络或环境限制，应在最终结果中说明未验证范围。
