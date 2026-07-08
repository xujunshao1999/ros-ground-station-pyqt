from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

# 话题类型注册表 - 根据消息类型自动分类传输策略。
# 传输策略分层：
# - light: 控制、状态、简单标量 -> MQTT + JSON
# - medium: 常规 ROS 话题 -> MQTT + ROS1 序列化二进制
# - heavy: 重量话题 (>1MB) -> HTTP 流 + MQTT 信令


# ---------------------------------------------------------------------------
# 传输层级定义
# ---------------------------------------------------------------------------
class TopicTier(str, Enum):
    """话题传输层级"""
    LIGHT = "light"       # MQTT + JSON
    MEDIUM = "medium"     # MQTT + 二进制
    HEAVY = "heavy"       # HTTP 流 + MQTT 信令


@dataclass
class TopicInfo:
    """话题信息"""
    msg_type: str                # ROS 消息类型，如 "sensor_msgs/Image"
    tier: TopicTier              # 传输层级
    description: str = ""        # 说明
    default_freq_limit: Optional[float] = None  # 默认频率限制 (Hz)
    compression_defaults: Dict[str, Any] = field(default_factory=dict)  # 默认压缩选项


# ---------------------------------------------------------------------------
# 内置注册表 - 常见 ROS 消息类型的默认分类
# ---------------------------------------------------------------------------
_BUILTIN_REGISTRY: Dict[str, TopicInfo] = {
    # ================================================================
    # 轻量话题 → MQTT + JSON
    # ================================================================

    # -- std_msgs 简单标量和文本 --
    "std_msgs/Empty":     TopicInfo("std_msgs/Empty",     TopicTier.LIGHT, "空消息"),
    "std_msgs/Bool":      TopicInfo("std_msgs/Bool",      TopicTier.LIGHT, "布尔值"),
    "std_msgs/Byte":      TopicInfo("std_msgs/Byte",      TopicTier.LIGHT, "字节"),
    "std_msgs/Char":      TopicInfo("std_msgs/Char",      TopicTier.LIGHT, "字符"),
    "std_msgs/Int8":      TopicInfo("std_msgs/Int8",      TopicTier.LIGHT, "8位整数"),
    "std_msgs/UInt8":     TopicInfo("std_msgs/UInt8",     TopicTier.LIGHT, "8位无符号整数"),
    "std_msgs/Int16":     TopicInfo("std_msgs/Int16",     TopicTier.LIGHT, "16位整数"),
    "std_msgs/UInt16":    TopicInfo("std_msgs/UInt16",    TopicTier.LIGHT, "16位无符号整数"),
    "std_msgs/Int32":     TopicInfo("std_msgs/Int32",     TopicTier.LIGHT, "整数"),
    "std_msgs/UInt32":    TopicInfo("std_msgs/UInt32",    TopicTier.LIGHT, "32位无符号整数"),
    "std_msgs/Int64":     TopicInfo("std_msgs/Int64",     TopicTier.LIGHT, "64位整数"),
    "std_msgs/UInt64":    TopicInfo("std_msgs/UInt64",    TopicTier.LIGHT, "64位无符号整数"),
    "std_msgs/Float32":   TopicInfo("std_msgs/Float32",   TopicTier.LIGHT, "浮点数"),
    "std_msgs/Float64":   TopicInfo("std_msgs/Float64",   TopicTier.LIGHT, "双精度浮点"),
    "std_msgs/String":    TopicInfo("std_msgs/String",    TopicTier.LIGHT, "字符串"),
    "std_msgs/Header":    TopicInfo("std_msgs/Header",    TopicTier.LIGHT, "消息头"),
    "std_msgs/ColorRGBA": TopicInfo("std_msgs/ColorRGBA", TopicTier.LIGHT, "RGBA颜色"),

    # ================================================================
    # 中等话题 → MQTT + ROS1 序列化二进制
    # ================================================================

    # -- 常见精确类型保留默认频率或压缩参数 --
    "sensor_msgs/Imu": TopicInfo(
        "sensor_msgs/Imu", TopicTier.MEDIUM, "IMU数据", default_freq_limit=50
    ),
    "sensor_msgs/NavSatFix": TopicInfo(
        "sensor_msgs/NavSatFix", TopicTier.MEDIUM, "GPS数据", default_freq_limit=10
    ),
    "sensor_msgs/JointState": TopicInfo(
        "sensor_msgs/JointState", TopicTier.MEDIUM, "关节状态", default_freq_limit=50
    ),
    "sensor_msgs/Range": TopicInfo(
        "sensor_msgs/Range", TopicTier.MEDIUM, "超声波/红外测距", default_freq_limit=10
    ),
    "sensor_msgs/MagneticField": TopicInfo(
        "sensor_msgs/MagneticField", TopicTier.MEDIUM, "磁力计", default_freq_limit=10
    ),
    "sensor_msgs/FluidPressure": TopicInfo(
        "sensor_msgs/FluidPressure", TopicTier.MEDIUM, "气压计", default_freq_limit=10
    ),
    "sensor_msgs/CompressedImage": TopicInfo(
        "sensor_msgs/CompressedImage", TopicTier.MEDIUM, "压缩图像",
        default_freq_limit=10,
        compression_defaults={"quality": 60},
    ),
    "sensor_msgs/Image": TopicInfo(
        "sensor_msgs/Image", TopicTier.MEDIUM, "原始图像",
        default_freq_limit=5,
        compression_defaults={"quality": 60, "resize": [640, 480]},
    ),
    "sensor_msgs/LaserScan": TopicInfo(
        "sensor_msgs/LaserScan", TopicTier.MEDIUM, "激光扫描",
        default_freq_limit=10,
    ),
    "nav_msgs/Odometry": TopicInfo(
        "nav_msgs/Odometry", TopicTier.MEDIUM, "里程计", default_freq_limit=50
    ),
    "nav_msgs/OccupancyGrid": TopicInfo(
        "nav_msgs/OccupancyGrid", TopicTier.MEDIUM, "占据栅格地图",
        default_freq_limit=2,
    ),
    "tf2_msgs/TFMessage": TopicInfo(
        "tf2_msgs/TFMessage", TopicTier.MEDIUM, "TF变换", default_freq_limit=50
    ),

    # 包级通配符用于覆盖同包下常规 ROS 消息，精确类型仍优先覆盖。
    "std_msgs/*": TopicInfo("std_msgs/*", TopicTier.MEDIUM, "std_msgs数组或复合消息"),
    "geometry_msgs/*": TopicInfo("geometry_msgs/*", TopicTier.MEDIUM, "geometry_msgs常规消息"),
    "nav_msgs/*": TopicInfo("nav_msgs/*", TopicTier.MEDIUM, "nav_msgs常规消息"),
    "sensor_msgs/*": TopicInfo("sensor_msgs/*", TopicTier.MEDIUM, "sensor_msgs常规消息"),
    "tf/*": TopicInfo("tf/*", TopicTier.MEDIUM, "tf常规消息"),
    "tf2_msgs/*": TopicInfo("tf2_msgs/*", TopicTier.MEDIUM, "tf2_msgs常规消息"),
    "visualization_msgs/*": TopicInfo(
        "visualization_msgs/*", TopicTier.MEDIUM, "visualization_msgs常规消息"
    ),
    "diagnostic_msgs/*": TopicInfo(
        "diagnostic_msgs/*", TopicTier.MEDIUM, "diagnostic_msgs常规消息"
    ),
    "actionlib_msgs/*": TopicInfo(
        "actionlib_msgs/*", TopicTier.MEDIUM, "actionlib_msgs常规消息"
    ),
    "trajectory_msgs/*": TopicInfo(
        "trajectory_msgs/*", TopicTier.MEDIUM, "trajectory_msgs常规消息"
    ),
    "control_msgs/*": TopicInfo("control_msgs/*", TopicTier.MEDIUM, "control_msgs常规消息"),
    "map_msgs/*": TopicInfo("map_msgs/*", TopicTier.MEDIUM, "map_msgs常规消息"),
    "geographic_msgs/*": TopicInfo(
        "geographic_msgs/*", TopicTier.MEDIUM, "geographic_msgs常规消息"
    ),
    "gazebo_msgs/*": TopicInfo("gazebo_msgs/*", TopicTier.MEDIUM, "gazebo_msgs常规消息"),
    "shape_msgs/*": TopicInfo("shape_msgs/*", TopicTier.MEDIUM, "shape_msgs常规消息"),
    "stereo_msgs/*": TopicInfo("stereo_msgs/*", TopicTier.MEDIUM, "stereo_msgs常规消息"),
    "move_base_msgs/*": TopicInfo(
        "move_base_msgs/*", TopicTier.MEDIUM, "move_base_msgs常规消息"
    ),
    "costmap_2d/*": TopicInfo("costmap_2d/*", TopicTier.MEDIUM, "costmap_2d常规消息"),
    "dynamic_reconfigure/*": TopicInfo(
        "dynamic_reconfigure/*", TopicTier.MEDIUM, "dynamic_reconfigure常规消息"
    ),
    "rosgraph_msgs/*": TopicInfo("rosgraph_msgs/*", TopicTier.MEDIUM, "rosgraph_msgs常规消息"),
    "ackermann_msgs/*": TopicInfo(
        "ackermann_msgs/*", TopicTier.MEDIUM, "ackermann_msgs常规消息"
    ),
    "nmea_msgs/*": TopicInfo("nmea_msgs/*", TopicTier.MEDIUM, "nmea_msgs常规消息"),
    "bond/*": TopicInfo("bond/*", TopicTier.MEDIUM, "bond常规消息"),
    "uuid_msgs/*": TopicInfo("uuid_msgs/*", TopicTier.MEDIUM, "uuid_msgs常规消息"),
    "vision_msgs/*": TopicInfo("vision_msgs/*", TopicTier.MEDIUM, "vision_msgs常规消息"),
    "apriltag_ros/*": TopicInfo(
        "apriltag_ros/*", TopicTier.MEDIUM, "apriltag_ros常规消息"
    ),
    "aruco_msgs/*": TopicInfo("aruco_msgs/*", TopicTier.MEDIUM, "aruco_msgs常规消息"),
    "fiducial_msgs/*": TopicInfo(
        "fiducial_msgs/*", TopicTier.MEDIUM, "fiducial_msgs常规消息"
    ),

    # ================================================================
    # 重量话题 → HTTP snapshot + MQTT meta
    # ================================================================
    "sensor_msgs/PointCloud2": TopicInfo(
        "sensor_msgs/PointCloud2", TopicTier.HEAVY, "3D点云",
        default_freq_limit=2,
    ),

    "sensor_msgs/PointCloud": TopicInfo(
        "sensor_msgs/PointCloud", TopicTier.HEAVY, "3D点云(遗留)",
        default_freq_limit=2,
    ),
    "pcl_msgs/*": TopicInfo("pcl_msgs/*", TopicTier.HEAVY, "PCL大数据消息"),
    "octomap_msgs/*": TopicInfo("octomap_msgs/*", TopicTier.HEAVY, "OctoMap大数据消息"),
}


# ---------------------------------------------------------------------------
# 注册表类
# ---------------------------------------------------------------------------
class TopicRegistry:
    """
    话题类型注册表

    - 根据消息类型查询传输策略
    - 支持注册自定义消息类型
    - 未注册的合法 ROS 消息类型默认为 MEDIUM
    """

    def __init__(self, custom_entries: Optional[Dict[str, TopicInfo]] = None):
        self._registry: Dict[str, TopicInfo] = dict(_BUILTIN_REGISTRY)
        if custom_entries:
            self._registry.update(custom_entries)

    def get(self, msg_type: str) -> TopicInfo:
        """
        查询消息类型信息

        未注册的合法 ROS 消息类型默认为 MEDIUM 层级
        """
        if msg_type in self._registry:
            return self._registry[msg_type]

        # 包级通配符只匹配 ROS 消息类型字符串，不使用 shell glob 语义。
        package = msg_type.rsplit("/", 1)[0] if "/" in msg_type else ""
        wildcard = f"{package}/*"
        if wildcard in self._registry:
            return self._registry[wildcard]

        # 未知 ROS 消息默认走二进制，运行时再由 Agent/Bridge 尝试导入消息类。
        return TopicInfo(msg_type, TopicTier.MEDIUM, description="未注册类型(默认ROS二进制)")

    def register(self, msg_type: str, info: TopicInfo) -> None:
        """注册自定义消息类型"""
        self._registry[msg_type] = info

    def unregister(self, msg_type: str) -> None:
        """取消注册消息类型"""
        self._registry.pop(msg_type, None)

    def get_tier(self, msg_type: str) -> TopicTier:
        """快捷查询传输层级"""
        return self.get(msg_type).tier

    def get_transport_type(self, msg_type: str) -> str:
        """
        根据层级返回传输方式字符串

        Returns:
            "mqtt_json" | "mqtt_binary" | "http_stream"
        """
        tier = self.get_tier(msg_type)
        mapping = {
            TopicTier.LIGHT: "mqtt_json",
            TopicTier.MEDIUM: "mqtt_binary",
            TopicTier.HEAVY: "http_stream",
        }
        return mapping[tier]

    def list_all(self) -> Dict[str, TopicInfo]:
        """列出所有已注册的消息类型"""
        return dict(self._registry)

    def list_by_tier(self, tier: TopicTier) -> Dict[str, TopicInfo]:
        """列出指定层级的所有消息类型"""
        return {k: v for k, v in self._registry.items() if v.tier == tier}


# ---------------------------------------------------------------------------
# 全局默认实例
# ---------------------------------------------------------------------------
default_registry = TopicRegistry()
