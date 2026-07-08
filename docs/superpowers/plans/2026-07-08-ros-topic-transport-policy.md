# ROS 话题默认传输策略重构实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]` / `- [x]`）语法来跟踪进度。

**目标：** 将常规 ROS topic 默认改为 `mqtt_binary + ros1_serialized_v1`，大 payload 继续使用 `http_stream + ros1_serialized_v1`，只让控制、配置、状态和简单标量数据使用 `mqtt_json`。

**架构：** `protocol/topic_registry.py` 负责按 ROS 消息类型给出默认 transport；ROS1 Agent 在 `mqtt_binary` 下优先直接 serialize 原始 ROS 消息；Bridge 根据 envelope 反序列化并重发布本地 ROS topic。未知 ROS 消息类型默认走 `mqtt_binary`，如果运行时找不到消息类或序列化失败，再记录错误或降级到现有 JSON 路径。

**技术栈：** ROS Noetic、Python 3.8、paho-mqtt、PyQt5、pytest、ROS1 message serialize/deserialize。

---

## 术语与执行约定

本计划应能在新对话中独立执行，不依赖此前聊天上下文。执行者需要先理解以下术语：

- `transport`：本项目中一个 ROS topic 从机器人端 Agent 到地面站 Bridge 的跨机器传输方式。当前重点使用三类值：`mqtt_json`、`mqtt_binary`、`http_stream`。
- `mqtt_json`：通过 MQTT 发送 JSON 格式数据，适合控制、状态、配置、发现结果和简单标量文本消息。
- `mqtt_binary + ros1_serialized_v1`：通过 MQTT 发送二进制 envelope，payload 是 ROS1 原生序列化后的消息字节。它适合大多数普通 ROS topic，因为 Bridge 能按原始消息类型反序列化并重新发布到本地 ROS master。
- `http_stream + ros1_serialized_v1`：MQTT 只发送 meta 信息，真正的大 payload 通过 HTTP snapshot 拉取。它适合点云、octomap、PCL 等大数据，避免把高带宽数据直接压到 MQTT broker 上。
- `transport: auto`：前端或配置中让系统按消息类型自动选择最终传输方式。保存和下发时应能看到或写入解析后的实际传输方式。
- `包级通配符规则`：用 `geometry_msgs/*`、`nav_msgs/*` 这类规则批量匹配同一 ROS 包下的所有消息类型。比如 `geometry_msgs/*` 匹配 `geometry_msgs/PoseStamped`、`geometry_msgs/Twist`、`geometry_msgs/TransformStamped` 等。精确消息类型规则优先于包级通配符规则，例如 `sensor_msgs/PointCloud2` 应先命中精确规则并走 `http_stream`，其它 `sensor_msgs/Image`、`sensor_msgs/JointState` 才落到 `sensor_msgs/*` 的 `mqtt_binary`。
- `未知 ROS 消息类型`：形如 `custom_msgs/Thing` 的合法 ROS 消息类型字符串，但不在内置注册表中。默认策略是走 `mqtt_binary`，运行时由 Agent 和 Bridge 尝试 import 同名消息类并执行 ROS1 serialize/deserialize。

执行时不要把“包级通配符规则”等同于 shell glob 文件匹配；它只是 `TopicRegistry` 内部根据消息类型字符串做的规则匹配。匹配顺序必须是：精确消息类型 > 包级通配符规则 > 未知合法 ROS 消息类型默认 `mqtt_binary`。

## 文件职责

- 修改：`protocol/topic_registry.py`
  - 重新定义内置消息类型默认 transport。
  - 未知消息类型默认返回 `mqtt_binary`。
  - 使用包级通配符规则覆盖常见 ROS 包，避免只靠手工枚举单个消息类型。
  - 保留 `TopicTier` 兼容现有 UI，但不再把 `LIGHT` 简单等同于“所有小 ROS 消息都用 JSON”。

- 修改：`protocol/binary_payloads.py`
  - 将 ROS1 serialized 支持从少量白名单扩展为“普通 ROS 消息默认可走 serialized”。
  - 保留 LaserScan、OccupancyGrid 现有专用 binary 编码兼容逻辑。

- 修改：`agent/ros1_agent.py`
  - `mqtt_binary` 下优先对原始 ROS 消息执行 `_serialize_ros_message()`。
  - `PointCloud2` 在 `http_stream` 下继续走 `publish_heavy_snapshot_data()`。
  - 序列化失败时记录 warning，并按现有 JSON 路径处理。

- 修改：`agent/base_agent.py`
  - `transport: auto` 继续通过 `default_registry.get_transport_type(msg_type)` 解析。
  - 确认 topic request、config sync 和持久化配置写入最终 transport，而不是一直保存 `auto`。

- 修改：`qt_frontend/panels/topic_config_panel.py`
  - 选择机器人发现的话题后，根据消息类型显示“预计传输方式”。
  - 下拉框仍保持 `AUTO`，但用户能看到最终会落到 `mqtt_json`、`mqtt_binary` 或 `http_stream`。

- 修改：`qt_frontend/config/transmit_config.yaml`
  - 仅在确认当前文件中的运行态改动可纳入默认配置后修改。
  - 将常规 ROS topic 默认配置调整为 `mqtt_binary`。

- 修改：`agent/configs/husky_001.yaml`
  - `PointCloud2` 保持 `http_stream`。
  - `Odometry`、`TF`、`CompressedImage`、`JointState` 默认使用 `mqtt_binary`。

- 测试：`tests/test_protocol_registry.py`
  - 覆盖常见 ROS1 消息类型默认 transport。

- 测试：`tests/test_binary_payloads.py`
  - 覆盖未知消息类型默认允许 ROS1 serialized。

- 测试：`tests/test_ros1_agent.py`
  - 覆盖常规 ROS topic 的 serialized fast path。
  - 覆盖 serialize 失败降级。

- 测试：`tests/test_agent_topic_config.py`
  - 覆盖 `transport: auto` 写入最终 transport。

- 测试：`tests/test_mqtt_ros_bridge.py`
  - 覆盖常见 serialized 消息由 Bridge 反序列化并发布。

- 测试：`tests/test_panels.py`
  - 覆盖前端自动传输方式预览。

---

## 默认传输策略覆盖范围

### `mqtt_json`

这些数据不需要在 Bridge 侧重建复杂 ROS 消息，或者更适合作为可读协议数据：

- 项目协议消息：
  - `status`
  - `event`
  - `cmd`
  - `cmd_ack`
  - `discover`
  - `topic_request`
  - `topic_response`
  - `config_sync`
  - `config_query`
  - `config_response`
  - `fleet`

- ROS 简单标量和文本：
  - `std_msgs/Empty`
  - `std_msgs/Bool`
  - `std_msgs/Byte`
  - `std_msgs/Char`
  - `std_msgs/Int8`
  - `std_msgs/UInt8`
  - `std_msgs/Int16`
  - `std_msgs/UInt16`
  - `std_msgs/Int32`
  - `std_msgs/UInt32`
  - `std_msgs/Int64`
  - `std_msgs/UInt64`
  - `std_msgs/Float32`
  - `std_msgs/Float64`
  - `std_msgs/String`
  - `std_msgs/Header`
  - `std_msgs/ColorRGBA`

`std_msgs/*MultiArray`、`std_msgs/MultiArrayLayout` 和 `std_msgs/MultiArrayDimension` 不归入 `mqtt_json` 默认集合，默认走 `mqtt_binary`。数组消息可能很小，也可能很大；用 ROS1 serialized 能避免 JSON 数组膨胀。

### `mqtt_binary + ros1_serialized_v1`

这些是常见 ROS topic，默认应保持 ROS 原始消息结构，通过 ROS1 serialize/deserialize 传输：

- `std_msgs` 数组类
  - `std_msgs/ByteMultiArray`
  - `std_msgs/Float32MultiArray`
  - `std_msgs/Float64MultiArray`
  - `std_msgs/Int8MultiArray`
  - `std_msgs/UInt8MultiArray`
  - `std_msgs/Int16MultiArray`
  - `std_msgs/UInt16MultiArray`
  - `std_msgs/Int32MultiArray`
  - `std_msgs/UInt32MultiArray`
  - `std_msgs/Int64MultiArray`
  - `std_msgs/UInt64MultiArray`
  - `std_msgs/MultiArrayDimension`
  - `std_msgs/MultiArrayLayout`

- `geometry_msgs`
  - `geometry_msgs/Point`
  - `geometry_msgs/Point32`
  - `geometry_msgs/PointStamped`
  - `geometry_msgs/Polygon`
  - `geometry_msgs/PolygonStamped`
  - `geometry_msgs/Pose`
  - `geometry_msgs/PoseStamped`
  - `geometry_msgs/PoseArray`
  - `geometry_msgs/PoseWithCovariance`
  - `geometry_msgs/PoseWithCovarianceStamped`
  - `geometry_msgs/Quaternion`
  - `geometry_msgs/QuaternionStamped`
  - `geometry_msgs/Transform`
  - `geometry_msgs/TransformStamped`
  - `geometry_msgs/Twist`
  - `geometry_msgs/TwistStamped`
  - `geometry_msgs/TwistWithCovariance`
  - `geometry_msgs/TwistWithCovarianceStamped`
  - `geometry_msgs/Vector3`
  - `geometry_msgs/Vector3Stamped`
  - `geometry_msgs/Accel`
  - `geometry_msgs/AccelStamped`
  - `geometry_msgs/AccelWithCovariance`
  - `geometry_msgs/AccelWithCovarianceStamped`
  - `geometry_msgs/Wrench`
  - `geometry_msgs/WrenchStamped`
  - `geometry_msgs/Inertia`
  - `geometry_msgs/InertiaStamped`

- `nav_msgs`
  - `nav_msgs/Odometry`
  - `nav_msgs/Path`
  - `nav_msgs/OccupancyGrid`
  - `nav_msgs/GridCells`
  - `nav_msgs/MapMetaData`

- `sensor_msgs`
  - `sensor_msgs/Imu`
  - `sensor_msgs/JointState`
  - `sensor_msgs/LaserScan`
  - `sensor_msgs/MultiEchoLaserScan`
  - `sensor_msgs/Range`
  - `sensor_msgs/NavSatFix`
  - `sensor_msgs/NavSatStatus`
  - `sensor_msgs/MagneticField`
  - `sensor_msgs/FluidPressure`
  - `sensor_msgs/Temperature`
  - `sensor_msgs/RelativeHumidity`
  - `sensor_msgs/Illuminance`
  - `sensor_msgs/TimeReference`
  - `sensor_msgs/BatteryState`
  - `sensor_msgs/CameraInfo`
  - `sensor_msgs/Image`
  - `sensor_msgs/CompressedImage`
  - `sensor_msgs/RegionOfInterest`
  - `sensor_msgs/Joy`
  - `sensor_msgs/JoyFeedback`
  - `sensor_msgs/JoyFeedbackArray`
  - `sensor_msgs/ChannelFloat32`
  - `sensor_msgs/PointField`

- `tf` / `tf2`
  - `tf2_msgs/TFMessage`
  - `tf/tfMessage`

- `visualization_msgs`
  - `visualization_msgs/Marker`
  - `visualization_msgs/MarkerArray`
  - `visualization_msgs/ImageMarker`
  - `visualization_msgs/InteractiveMarker`
  - `visualization_msgs/InteractiveMarkerControl`
  - `visualization_msgs/InteractiveMarkerFeedback`
  - `visualization_msgs/InteractiveMarkerInit`
  - `visualization_msgs/InteractiveMarkerPose`
  - `visualization_msgs/InteractiveMarkerUpdate`
  - `visualization_msgs/MenuEntry`

- `diagnostic_msgs`
  - `diagnostic_msgs/DiagnosticArray`
  - `diagnostic_msgs/DiagnosticStatus`
  - `diagnostic_msgs/KeyValue`

- `actionlib_msgs`
  - `actionlib_msgs/GoalID`
  - `actionlib_msgs/GoalStatus`
  - `actionlib_msgs/GoalStatusArray`

- `rosgraph_msgs`
  - `rosgraph_msgs/Clock`
  - `rosgraph_msgs/Log`
  - `rosgraph_msgs/TopicStatistics`

- `dynamic_reconfigure`
  - `dynamic_reconfigure/BoolParameter`
  - `dynamic_reconfigure/Config`
  - `dynamic_reconfigure/ConfigDescription`
  - `dynamic_reconfigure/DoubleParameter`
  - `dynamic_reconfigure/Group`
  - `dynamic_reconfigure/GroupState`
  - `dynamic_reconfigure/IntParameter`
  - `dynamic_reconfigure/ParamDescription`
  - `dynamic_reconfigure/SensorLevels`
  - `dynamic_reconfigure/StrParameter`

- `trajectory_msgs`
  - `trajectory_msgs/JointTrajectory`
  - `trajectory_msgs/JointTrajectoryPoint`
  - `trajectory_msgs/MultiDOFJointTrajectory`
  - `trajectory_msgs/MultiDOFJointTrajectoryPoint`

- `control_msgs`
  - `control_msgs/JointControllerState`
  - `control_msgs/JointTrajectoryControllerState`
  - `control_msgs/FollowJointTrajectoryActionGoal`
  - `control_msgs/FollowJointTrajectoryActionFeedback`
  - `control_msgs/FollowJointTrajectoryActionResult`
  - `control_msgs/GripperCommand`
  - `control_msgs/GripperCommandActionGoal`
  - `control_msgs/GripperCommandActionFeedback`
  - `control_msgs/GripperCommandActionResult`

- `ackermann_msgs`
  - `ackermann_msgs/AckermannDrive`
  - `ackermann_msgs/AckermannDriveStamped`

- `map_msgs`
  - `map_msgs/OccupancyGridUpdate`
  - `map_msgs/ProjectedMap`
  - `map_msgs/ProjectedMapInfo`
  - `map_msgs/PointCloud2Update`

- `geographic_msgs`
  - `geographic_msgs/GeoPoint`
  - `geographic_msgs/GeoPointStamped`
  - `geographic_msgs/GeoPose`
  - `geographic_msgs/GeoPoseStamped`
  - `geographic_msgs/GeoPath`
  - `geographic_msgs/WayPoint`
  - `geographic_msgs/RoutePath`
  - `geographic_msgs/RouteNetwork`

- `nmea_msgs`
  - `nmea_msgs/Gpgga`
  - `nmea_msgs/Gpgsa`
  - `nmea_msgs/Gpgsv`
  - `nmea_msgs/Gprmc`
  - `nmea_msgs/Sentence`

- `gazebo_msgs`
  - `gazebo_msgs/ModelState`
  - `gazebo_msgs/ModelStates`
  - `gazebo_msgs/LinkState`
  - `gazebo_msgs/LinkStates`
  - `gazebo_msgs/ContactsState`
  - `gazebo_msgs/PerformanceMetrics`

- `shape_msgs`
  - `shape_msgs/Mesh`
  - `shape_msgs/MeshTriangle`
  - `shape_msgs/Plane`
  - `shape_msgs/SolidPrimitive`

- `stereo_msgs`
  - `stereo_msgs/DisparityImage`

- `move_base_msgs`
  - `move_base_msgs/MoveBaseActionGoal`
  - `move_base_msgs/MoveBaseActionFeedback`
  - `move_base_msgs/MoveBaseActionResult`
  - `move_base_msgs/MoveBaseGoal`
  - `move_base_msgs/MoveBaseFeedback`
  - `move_base_msgs/MoveBaseResult`

- `costmap_2d`
  - `costmap_2d/VoxelGrid`

- 运行时基础设施消息：
  - `bond/Status`
  - `uuid_msgs/UniqueID`

- 常见感知结果消息：
  - `vision_msgs/Detection2D`
  - `vision_msgs/Detection2DArray`
  - `vision_msgs/Detection3D`
  - `vision_msgs/Detection3DArray`
  - `vision_msgs/ObjectHypothesis`
  - `vision_msgs/ObjectHypothesisWithPose`
  - `vision_msgs/VisionInfo`
  - `apriltag_ros/AprilTagDetection`
  - `apriltag_ros/AprilTagDetectionArray`
  - `aruco_msgs/Marker`
  - `aruco_msgs/MarkerArray`
  - `fiducial_msgs/Fiducial`
  - `fiducial_msgs/FiducialArray`
  - `fiducial_msgs/FiducialTransform`
  - `fiducial_msgs/FiducialTransformArray`

- 自定义消息：
  - 未注册且消息类型字符串合法的类型默认 `mqtt_binary`。
  - 运行时如果 ROS1 Agent 能 import 到消息类并 serialize，Bridge 能 import 到同名消息类并 deserialize，则无需额外配置。

实现时不要求把上述每个类型都逐项写进 `_BUILTIN_REGISTRY`。推荐做法是用少量精确规则加包级通配符规则表达默认策略：

- 对 `std_msgs` 的简单标量和文本保留逐项 `mqtt_json` 显式注册。
- 对 `sensor_msgs/PointCloud2`、`sensor_msgs/PointCloud`、`pcl_msgs/*`、`octomap_msgs/*` 显式注册为 `http_stream`。
- 对 `std_msgs/*`、`geometry_msgs/*`、`nav_msgs/*`、`sensor_msgs/*`、`tf/*`、`tf2_msgs/*`、`visualization_msgs/*`、`diagnostic_msgs/*`、`actionlib_msgs/*`、`trajectory_msgs/*`、`control_msgs/*`、`map_msgs/*`、`geographic_msgs/*`、`gazebo_msgs/*`、`shape_msgs/*`、`stereo_msgs/*`、`move_base_msgs/*`、`costmap_2d/*`、`dynamic_reconfigure/*`、`rosgraph_msgs/*`、`ackermann_msgs/*`、`nmea_msgs/*`、`bond/*`、`uuid_msgs/*`、`vision_msgs/*`、`apriltag_ros/*`、`aruco_msgs/*`、`fiducial_msgs/*` 注册为 `mqtt_binary` 包级通配符规则。
- 对所有未注册合法 ROS 消息类型默认返回 `mqtt_binary`。

执行者如果需要在代码中命名变量，可以继续使用 `wildcard` 作为英文变量名；文档语义上它指的就是“包级通配符规则”。不要为覆盖范围清单里的每个消息类型都写一条注册记录，除非该类型需要覆盖包级默认规则。

### `http_stream + ros1_serialized_v1`

这些通常 payload 大，不适合直接压 MQTT broker：

- `sensor_msgs/PointCloud2`
- `sensor_msgs/PointCloud`
- `pcl_msgs/PolygonMesh`
- `pcl_msgs/PointIndices`
- `pcl_msgs/ModelCoefficients`
- `octomap_msgs/Octomap`
- `octomap_msgs/OctomapWithPose`
- 大尺寸自定义数组消息，后续通过配置显式标记为 `http_stream`

---

## 任务 1：调整协议注册表默认策略

**文件：**
- 修改：`protocol/topic_registry.py`
- 测试：`tests/test_protocol_registry.py`

- [x] **步骤 1：编写失败测试**

在 `tests/test_protocol_registry.py` 增加：

```python
def test_regular_ros_topics_default_to_mqtt_binary():
    registry = TopicRegistry()

    assert registry.get_transport_type("nav_msgs/Odometry") == "mqtt_binary"
    assert registry.get_transport_type("sensor_msgs/Imu") == "mqtt_binary"
    assert registry.get_transport_type("sensor_msgs/JointState") == "mqtt_binary"
    assert registry.get_transport_type("geometry_msgs/PoseStamped") == "mqtt_binary"
    assert registry.get_transport_type("tf2_msgs/TFMessage") == "mqtt_binary"
    assert registry.get_transport_type("tf/tfMessage") == "mqtt_binary"
    assert registry.get_transport_type("visualization_msgs/MarkerArray") == "mqtt_binary"
    assert registry.get_transport_type("rosgraph_msgs/Clock") == "mqtt_binary"
    assert registry.get_transport_type("dynamic_reconfigure/Config") == "mqtt_binary"
    assert registry.get_transport_type("ackermann_msgs/AckermannDriveStamped") == "mqtt_binary"
    assert registry.get_transport_type("std_msgs/Float32MultiArray") == "mqtt_binary"
    assert registry.get_transport_type("costmap_2d/VoxelGrid") == "mqtt_binary"


def test_simple_std_msgs_stay_mqtt_json():
    registry = TopicRegistry()

    assert registry.get_transport_type("std_msgs/String") == "mqtt_json"
    assert registry.get_transport_type("std_msgs/Bool") == "mqtt_json"
    assert registry.get_transport_type("std_msgs/Float64") == "mqtt_json"


def test_heavy_payloads_default_to_http_stream():
    registry = TopicRegistry()

    assert registry.get_transport_type("sensor_msgs/PointCloud2") == "http_stream"
    assert registry.get_transport_type("sensor_msgs/PointCloud") == "http_stream"


def test_unknown_ros_message_defaults_to_mqtt_binary():
    registry = TopicRegistry()

    assert registry.get_transport_type("custom_msgs/Thing") == "mqtt_binary"
```

- [x] **步骤 2：运行测试确认失败**

运行：

```bash
python3 -m pytest tests/test_protocol_registry.py -q
```

预期：新增测试失败，当前 `Odometry`、`Imu`、`JointState` 或未知类型仍可能返回 `mqtt_json`。

- [x] **步骤 3：修改 `protocol/topic_registry.py`**

实现要点：

```python
def get(self, msg_type: str) -> TopicInfo:
    if msg_type in self._registry:
        return self._registry[msg_type]

    package = msg_type.rsplit("/", 1)[0] if "/" in msg_type else ""
    wildcard = f"{package}/*"
    if wildcard in self._registry:
        return self._registry[wildcard]

    return TopicInfo(msg_type, TopicTier.MEDIUM, description="未注册类型(默认ROS二进制)")
```

并将常规 ROS 消息类型注册为 `TopicTier.MEDIUM`，将 `sensor_msgs/PointCloud2`、`sensor_msgs/PointCloud`、`octomap_msgs/*`、`pcl_msgs/*` 注册为 `TopicTier.HEAVY`。

注册顺序要保证精确匹配优先于包级通配符规则。例如 `std_msgs/Float64` 应命中显式 `mqtt_json`，`std_msgs/Float32MultiArray` 应命中 `std_msgs/*` 的 `mqtt_binary`。

- [x] **步骤 4：运行测试确认通过**

运行：

```bash
python3 -m pytest tests/test_protocol_registry.py -q
```

预期：全部通过。

- [x] **步骤 5：Commit**

```bash
git add protocol/topic_registry.py tests/test_protocol_registry.py
git commit -m "refactor: 调整ROS话题默认传输策略"
```

---

## 任务 2：让 ROS1 Agent 对普通 `mqtt_binary` 话题直接使用 serialized fast path

**文件：**
- 修改：`protocol/binary_payloads.py`
- 修改：`agent/ros1_agent.py`
- 测试：`tests/test_binary_payloads.py`
- 测试：`tests/test_ros1_agent.py`

- [x] **步骤 1：编写失败测试**

在 `tests/test_binary_payloads.py` 增加：

```python
def test_ros1_serialized_supports_unknown_ros_messages_by_default():
    assert is_ros_message_binary_supported(
        "/custom_topic",
        "custom_msgs/Thing",
    ) is True
```

在 `tests/test_ros1_agent.py` 增加：

```python
def test_joint_state_uses_ros1_serialized_fast_path(monkeypatch):
    mock_rospy = MagicMock()
    captured_callback = {}

    def fake_subscriber(topic, msg_class, callback):
        captured_callback["callback"] = callback
        return MagicMock()

    mock_rospy.Subscriber.side_effect = fake_subscriber
    monkeypatch.setattr("agent.ros1_agent.rospy", mock_rospy)
    monkeypatch.setattr(
        "agent.ros1_agent.ros_msg_to_dict",
        lambda msg: (_ for _ in ()).throw(
            AssertionError("mqtt_binary ROS topic should not use JSON conversion")
        ),
    )

    agent = object.__new__(ROS1Agent)
    agent.config = MagicMock()
    agent.config.default_freq_limit = 100.0
    agent._ros_subscribers = {}
    agent._sensor_data = {}
    agent._sensor_lock = MagicMock()
    agent._get_ros_msg_class = MagicMock(return_value=object)
    agent.publish_sensor_binary_data = MagicMock()

    ROS1Agent._on_topic_subscribed(
        agent,
        "/joint_states",
        "sensor_msgs/JointState",
        {"freq_limit": 100.0, "transport": "mqtt_binary"},
    )
    captured_callback["callback"](_SerializableRosMsg(b"joint-state-raw"))

    agent.publish_sensor_binary_data.assert_called_once()
    assert agent.publish_sensor_binary_data.call_args[0][:3] == (
        "/joint_states",
        "sensor_msgs/JointState",
        b"joint-state-raw",
    )
```

- [x] **步骤 2：运行测试确认失败**

运行：

```bash
python3 -m pytest tests/test_binary_payloads.py::test_ros1_serialized_supports_unknown_ros_messages_by_default tests/test_ros1_agent.py::test_joint_state_uses_ros1_serialized_fast_path -q
```

预期：当前白名单导致失败。

- [x] **步骤 3：修改 `protocol/binary_payloads.py`**

将 `is_ros_message_binary_supported()` 调整为默认允许合法 ROS 消息类型：

```python
def is_ros_message_binary_supported(topic: str, msg_type: str) -> bool:
    if (topic, msg_type) in _ROS1_SERIALIZED_TOPIC_TYPES:
        return True
    if msg_type in _ROS1_SERIALIZED_MESSAGE_TYPES:
        return True
    return "/" in msg_type and len(msg_type) > 3
```

- [x] **步骤 4：确认 `agent/ros1_agent.py` 不再阻断常规类型**

保留现有逻辑：

```python
if tr == "mqtt_binary" and is_ros_message_binary_supported(t, mt):
    raw_payload = self._serialize_ros_message(msg)
    if raw_payload is not None:
        self.publish_sensor_binary_data(...)
        return
```

如果 `_serialize_ros_message()` 返回 `None`，继续落到 JSON dict 路径。

- [x] **步骤 5：运行测试确认通过**

运行：

```bash
python3 -m pytest tests/test_binary_payloads.py tests/test_ros1_agent.py -q
```

预期：全部通过。

- [x] **步骤 6：Commit**

```bash
git add protocol/binary_payloads.py agent/ros1_agent.py tests/test_binary_payloads.py tests/test_ros1_agent.py
git commit -m "feat: 默认支持ROS1序列化二进制话题"
```

---

## 任务 3：前端显示 AUTO 预期传输方式

**文件：**
- 修改：`qt_frontend/panels/topic_config_panel.py`
- 测试：`tests/test_panels.py`

- [x] **步骤 1：编写失败测试**

在 `tests/test_panels.py` 的 `TestTopicConfigPanel` 增加：

```python
def test_available_topic_selection_shows_auto_transport_preview(self, qt_app):
    panel = TopicConfigPanel()
    panel.on_robot_list_changed(["husky_001"])
    panel.on_discover_response(
        "husky_001",
        {"topics": [
            {"topic": "/odom", "msg_type": "nav_msgs/Odometry"},
            {"topic": "/velodyne_points", "msg_type": "sensor_msgs/PointCloud2"},
        ]},
    )

    panel._robot_combo.setCurrentText("husky_001")
    panel._btn_add.click()
    panel._combo_available_topics.setCurrentIndex(1)

    assert panel._combo_msg_type.currentText() == "nav_msgs/Odometry"
    assert "mqtt_binary" in panel._transport_preview.text()

    panel._combo_available_topics.setCurrentIndex(2)

    assert panel._combo_msg_type.currentText() == "sensor_msgs/PointCloud2"
    assert "http_stream" in panel._transport_preview.text()
```

- [x] **步骤 2：运行测试确认失败**

运行：

```bash
python3 -m pytest tests/test_panels.py::TestTopicConfigPanel::test_available_topic_selection_shows_auto_transport_preview -q
```

预期：失败，因为当前没有 `_transport_preview`。

- [x] **步骤 3：修改面板**

在表单传输层级行后增加：

```python
self._transport_preview = QLabel("预计传输方式：-")
self._transport_preview.setWordWrap(True)
form.addWidget(self._transport_preview)
```

新增方法：

```python
@staticmethod
def predicted_transport_for_msg_type(msg_type: str) -> str:
    from protocol.topic_registry import default_registry

    return default_registry.get_transport_type(msg_type)

def _update_transport_preview(self) -> None:
    msg_type = self._combo_msg_type.currentText().strip()
    selected = self._combo_transport.currentText().split()[0].lower()
    if not msg_type:
        self._transport_preview.setText("预计传输方式：-")
        return
    if selected == "auto":
        transport = self.predicted_transport_for_msg_type(msg_type)
        self._transport_preview.setText("预计传输方式：%s" % transport)
        return
    self._transport_preview.setText(
        "已手动选择：%s" % self.transport_from_tier(selected)
    )
```

连接信号：

```python
self._combo_msg_type.currentTextChanged.connect(self._update_transport_preview)
self._combo_transport.currentIndexChanged.connect(self._update_transport_preview)
```

在 `_on_available_topic_selected()`、`_show_add_form()`、`_load_selected_entry_into_form()` 末尾调用 `_update_transport_preview()`。

- [x] **步骤 4：运行测试确认通过**

运行：

```bash
python3 -m pytest tests/test_panels.py::TestTopicConfigPanel -q
```

预期：通过。

- [x] **步骤 5：Commit**

```bash
git add qt_frontend/panels/topic_config_panel.py tests/test_panels.py
git commit -m "feat: 显示话题自动传输方式预览"
```

---

## 任务 4：更新默认配置与文档

**文件：**
- 修改：`agent/configs/husky_001.yaml`
- 修改：`qt_frontend/config/transmit_config.yaml`
- 修改：`docs/protocol.md`
- 测试：`tests/test_husky_docker_config.py`

- [x] **步骤 1：检查当前配置差异**

运行：

```bash
git diff -- qt_frontend/config/transmit_config.yaml agent/configs/husky_001.yaml
```

预期：确认是否有用户运行态配置。不要覆盖用户未确认的配置。

- [x] **步骤 2：编写配置测试**

在 `tests/test_husky_docker_config.py` 中确认：

```python
def test_husky_joint_states_uses_binary_transport():
    config = _load_husky_config()
    subscriptions = {
        item["topic"]: item for item in config["subscriptions"]
    }

    assert subscriptions["/joint_states"]["transport"] == "mqtt_binary"
```

- [x] **步骤 3：运行测试确认失败**

运行：

```bash
python3 -m pytest tests/test_husky_docker_config.py::test_husky_joint_states_uses_binary_transport -q
```

预期：当前如果仍为 `mqtt_json`，测试失败。

- [x] **步骤 4：修改默认配置**

在 `agent/configs/husky_001.yaml` 中将 `/joint_states` 改为：

```yaml
- topic: /joint_states
  msg_type: sensor_msgs/JointState
  freq_limit: 10.0
  transport: mqtt_binary
  qos: 0
  compression: {}
```

如果确认 `qt_frontend/config/transmit_config.yaml` 可纳入默认配置，同步将常规 ROS topic 的 `transport` 调整为 `mqtt_binary`，`PointCloud2` 保持 `http_stream`。

- [x] **步骤 5：更新协议文档**

在 `docs/protocol.md` 增加传输策略说明：

```markdown
### 默认传输策略

- 控制、状态、配置和简单标量：`mqtt_json`
- 常规 ROS topic：`mqtt_binary`，payload 使用 `ros1_serialized_v1`
- 大 payload：`http_stream`，MQTT 仅发送 meta，HTTP payload 使用 `ros1_serialized_v1`
- 未注册 ROS 消息类型：默认 `mqtt_binary`
```

- [x] **步骤 6：运行验证**

运行：

```bash
python3 -m pytest tests/test_husky_docker_config.py tests/test_protocol_registry.py -q
git diff --check -- agent/configs/husky_001.yaml qt_frontend/config/transmit_config.yaml docs/protocol.md tests/test_husky_docker_config.py
```

预期：测试通过，空白检查无输出。

- [x] **步骤 7：Commit**

```bash
git add agent/configs/husky_001.yaml qt_frontend/config/transmit_config.yaml docs/protocol.md tests/test_husky_docker_config.py
git commit -m "docs: 更新ROS话题默认传输策略"
```

---

## 任务 5：运行态验证

**文件：**
- 不修改文件。

- [x] **步骤 1：启动 Husky 容器和前端**

运行：

```bash
docker compose up -d --force-recreate robot-husky-001
./qt_frontend/scripts/start.sh
```

预期：Husky 容器、Bridge 和 Qt 前端启动。

- [x] **步骤 2：验证普通 topic 走 MQTT binary**

运行：

```bash
timeout 10 mosquitto_sub -h localhost -t 'robot/husky_001/sensor/hdl_graph_slam_odom' -C 1
timeout 10 mosquitto_sub -h localhost -t 'robot/husky_001/sensor/joint_states' -C 1
```

预期：payload 为 envelope，包含：

```json
{
  "binary": true,
  "encoding": "ros1_serialized_v1",
  "payload_format": "ros1_serialized"
}
```

- [x] **步骤 3：验证点云继续走 HTTP stream**

运行：

```bash
timeout 10 mosquitto_sub -h localhost -t 'robot/husky_001/sensor/velodyne_points/meta' -C 1
```

预期：payload 包含：

```json
{
  "transport": "http_stream",
  "payload_format": "ros1_serialized"
}
```

- [x] **步骤 4：验证本地 ROS topic**

运行：

```bash
rostopic list | rg 'husky_001/(hdl_graph_slam/odom|joint_states|velodyne_points)'
timeout 8 rostopic echo -n 1 /husky_001/hdl_graph_slam/odom/header
timeout 8 rostopic echo -n 1 /husky_001/joint_states/header
```

预期：Bridge 已重建本地 ROS topic，echo 能拿到消息。

- [x] **步骤 5：关闭运行环境**

运行：

```bash
./qt_frontend/scripts/stop.sh
docker compose stop robot-husky-001
```

预期：前端和容器停止。

- [x] **步骤 6：记录结果**

将运行态结果写入当天工作日志：

```text
docs/work-log-2026-07-08.md
```

- [x] **步骤 7：Commit**

```bash
git add docs/work-log-2026-07-08.md
git commit -m "docs: 记录ROS话题传输策略验证"
```

---

## 自检

- 覆盖了 `std_msgs`、`geometry_msgs`、`nav_msgs`、`sensor_msgs`、`tf/tf2`、`visualization_msgs`、`diagnostic_msgs`、`actionlib_msgs`、`trajectory_msgs`、`control_msgs`、`map_msgs`、`geographic_msgs`、`gazebo_msgs`、`shape_msgs`、`stereo_msgs`、`move_base_msgs`、`costmap_2d`、`dynamic_reconfigure`、`rosgraph_msgs`、`ackermann_msgs`、`nmea_msgs`、`bond`、`uuid_msgs`、`vision_msgs`、`apriltag_ros`、`aruco_msgs`、`fiducial_msgs`、`pcl_msgs`、`octomap_msgs` 和自定义消息。
- 计划已解释“包级通配符规则”的含义、匹配顺序和实现目的，新开对话后不需要依赖此前聊天上下文。
- 计划明确使用包级通配符规则和未知类型默认值兜底，不依赖手工枚举覆盖所有 ROS 消息。
- 未知消息类型默认 `mqtt_binary`。
- `PointCloud2` 等大 payload 保持 `http_stream`。
- 计划包含测试、实现、验证和 commit 步骤。
- 没有要求一次性实现压缩或降采样；带宽优化中的压缩/降采样应作为后续独立计划。
