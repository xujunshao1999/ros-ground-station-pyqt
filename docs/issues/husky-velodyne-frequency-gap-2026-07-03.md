# Husky Velodyne 点云跨链路频率不一致记录

## 一、问题背景

2026 年 7 月 3 日，在测试 Husky 重型数据仿真镜像时，手动将 `agent/configs/husky_001.yaml` 中 `/velodyne_points` 的 `freq_limit` 调整为 `0.0`，也就是不在 Agent 配置层主动限频，期望观察容器内原始点云频率与地面站侧重发布频率是否一致。

Husky 容器内的 `/velodyne_points` 是 Gazebo 仿真发布的 Velodyne 点云数据。地面站侧看到的 `/husky_001/velodyne_points` 不是直接连接机器人 ROS master 得到的原始话题，而是经过本项目链路重新发布的本地 ROS 话题：Agent 订阅机器人 ROS 话题，将最新点云缓存到 HTTP snapshot；同时通过 MQTT 发布 meta；Bridge 收到 meta 后通过 HTTP 拉取 serialized payload，再反序列化并发布到地面站本地 ROS。

本记录用于保留当前现象和排查证据，后续再决定是否需要优化或修正。

## 二、当前现象

测试结果显示两侧频率不一致：

- Husky 容器内原始 `/velodyne_points` 约为 `10.0 Hz`。
- 地面站本地 `/husky_001/velodyne_points` 约为 `3.9 Hz`。
- MQTT meta 话题 `robot/husky_001/sensor/velodyne_points/meta` 的到达频率也约为 `3.9 Hz`。

这说明 Gazebo 原始点云发布频率是正常的，地面站侧较低频率不是单纯由 RViz 或本地 ROS 发布造成，而更可能发生在 Agent 处理重型点云、发布 MQTT meta、HTTP snapshot 缓存更新这一段链路。

## 三、已确认配置

容器内实际加载的 Agent 配置已确认 `/velodyne_points` 为无限频率：

```yaml
- topic: /velodyne_points
  msg_type: sensor_msgs/PointCloud2
  freq_limit: 0.0
  transport: http_stream
  qos: 0
  compression: {}
```

当前每帧 `/velodyne_points` 的 HTTP snapshot payload 大小约为 `512 KB`。在这个数据量下，虽然 Agent 不再按配置限频，但完整的 serialize、HTTP snapshot 缓存更新和 MQTT meta 发布链路实际只达到约 `4 Hz`。

## 四、验证记录

### 1. 容器内原始点云频率

执行命令：

```bash
docker exec husky-001 bash -lc 'source /opt/ros/noetic/setup.bash && source /opt/catkin_sim/devel/setup.bash && timeout 15 rostopic hz /velodyne_points'
```

观察结果：

```text
average rate: 10.000
min: 0.084s max: 0.112s std dev: 0.00634s window: 57
```

结论：Husky 容器内 Gazebo 发布的 Velodyne 原始点云约为 `10 Hz`。

### 2. 地面站侧重发布点云频率

执行命令：

```bash
timeout 15 rostopic hz /husky_001/velodyne_points
```

观察结果：

```text
average rate: 3.942
min: 0.181s max: 0.321s std dev: 0.02898s window: 57
```

结论：地面站本地 ROS 上由 Bridge 发布的 `/husky_001/velodyne_points` 约为 `3.9 Hz`。

### 3. 地面站侧话题发布者

执行命令：

```bash
rostopic info /husky_001/velodyne_points
```

观察结果：

```text
Type: sensor_msgs/PointCloud2

Publishers:
 * /mqtt_ros_bridge

Subscribers:
 * /qt_frontend
```

结论：地面站侧点云确实由 `/mqtt_ros_bridge` 发布，Qt 前端作为订阅者消费该话题。

### 4. MQTT meta 到达情况

执行命令：

```bash
timeout 10 mosquitto_sub -h localhost -t robot/husky_001/sensor/velodyne_points/meta -C 80
```

观察结果：

```json
{
  "type": "sensor_meta",
  "data": {
    "topic": "/velodyne_points",
    "msg_type": "sensor_msgs/PointCloud2",
    "transport": "http_stream",
    "stream_url": "http://localhost:18080/stream/velodyne_points",
    "size_bytes": 512374,
    "freq_hz": 0.0,
    "payload_format": "ros1_serialized",
    "payload_size": 512374
  }
}
```

采样窗口内 meta 到达间隔约为 `0.2s` 到 `0.3s`，对应约 `3.9 Hz`。meta 中的 `freq_hz: 0.0` 进一步确认配置层没有主动限频。

## 五、初步判断

当前现象更像是重型数据链路的实际吞吐上限，而不是配置未生效：

- ROS 原始话题为 `10 Hz`，说明仿真端数据源频率正常。
- Agent 配置为 `freq_limit: 0.0`，说明配置层没有主动限频。
- MQTT meta 约 `3.9 Hz`，说明进入 Bridge 之前已经降到约 `4 Hz`。
- Bridge 发布频率与 MQTT meta 基本一致，说明 Bridge 侧没有进一步明显降频。

初步怀疑点包括：

- Agent 对 `PointCloud2` 进行 ROS1 serialized payload 处理和 HTTP snapshot 缓存更新的 CPU 开销。
- 单帧约 `512 KB` 的点云在 Python Agent 中高频处理时产生的内存拷贝成本。
- MQTT meta 发布、HTTP snapshot 最新帧更新和 ROS 回调线程之间的串行处理影响。
- 当前 HTTP snapshot 方案本身更偏向「最新帧可视化」而不是严格保持原始传感器满频转发。

## 六、后续待确认

后续如果需要修正或优化，可以从以下方向继续排查：

- 在 Agent 内增加轻量统计日志，分别记录 ROS 回调进入频率、HTTP snapshot 缓存更新频率和 MQTT meta 发布频率。
- 对比不同点云大小下的吞吐，例如减少 Velodyne 点数或启用体素降采样后再测频率。
- 验证 `mqtt_binary` 或其它传输方式是否能提高小规模点云吞吐，但需要注意 MQTT 大包对 broker 和队列的压力。
- 评估是否需要为 `http_stream` 增加更明确的性能目标，例如「尽力最新帧」或「目标频率上限」。
- 如果业务确实需要接近 `10 Hz` 的完整点云，考虑后续设计专门的长连接、共享内存、压缩或分块传输方案。

## 七、当前处理结论

本次只记录问题，不修改代码。当前 Husky 重型数据链路可以用于 RViz 查看 Velodyne 点云和测试 HTTP snapshot 通道，但在 `512 KB` 单帧点云、无限频率配置下，地面站侧实际频率约为 `4 Hz`，与容器内原始 `10 Hz` 不一致。
