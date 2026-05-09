from __future__ import annotations

"""
话题类型注册表 - 根据消息类型自动分类传输策略

传输策略分层:
  - light:   轻量话题 (<10KB)   → MQTT + JSON
  - medium:  中等话题 (10KB-1MB) → MQTT + 二进制
  - heavy:   重量话题 (>1MB)     → HTTP 流 + MQTT 信令
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


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
    compression_defaults: dict[str, Any] = field(default_factory=dict)  # 默认压缩选项


# ---------------------------------------------------------------------------
# 内置注册表 - 常见 ROS 消息类型的默认分类
# ---------------------------------------------------------------------------
_BUILTIN_REGISTRY: dict[str, TopicInfo] = {
    # ================================================================
    # 轻量话题 → MQTT + JSON  (<10 KB per message)
    # ================================================================

    # -- std_msgs --
    "std_msgs/Bool":      TopicInfo("std_msgs/Bool",      TopicTier.LIGHT, "布尔值"),
    "std_msgs/Int32":     TopicInfo("std_msgs/Int32",     TopicTier.LIGHT, "整数"),
    "std_msgs/Float32":   TopicInfo("std_msgs/Float32",   TopicTier.LIGHT, "浮点数"),
    "std_msgs/Float64":   TopicInfo("std_msgs/Float64",   TopicTier.LIGHT, "双精度浮点"),
    "std_msgs/String":    TopicInfo("std_msgs/String",    TopicTier.LIGHT, "字符串"),
    "std_msgs/ColorRGBA": TopicInfo("std_msgs/ColorRGBA", TopicTier.LIGHT, "RGBA颜色"),

    # -- geometry_msgs --
    "geometry_msgs/Twist":                      TopicInfo("geometry_msgs/Twist",                      TopicTier.LIGHT, "速度指令"),
    "geometry_msgs/TwistStamped":               TopicInfo("geometry_msgs/TwistStamped",               TopicTier.LIGHT, "带时间戳速度"),
    "geometry_msgs/Pose2D":                     TopicInfo("geometry_msgs/Pose2D",                     TopicTier.LIGHT, "2D位姿"),
    "geometry_msgs/Pose":                       TopicInfo("geometry_msgs/Pose",                       TopicTier.LIGHT, "3D位姿"),
    "geometry_msgs/PoseStamped":                TopicInfo("geometry_msgs/PoseStamped",                TopicTier.LIGHT, "带时间戳3D位姿"),
    "geometry_msgs/PoseArray":                  TopicInfo("geometry_msgs/PoseArray",                  TopicTier.LIGHT, "位姿数组"),
    "geometry_msgs/PoseWithCovarianceStamped":  TopicInfo("geometry_msgs/PoseWithCovarianceStamped",  TopicTier.LIGHT, "带协方差位姿"),
    "geometry_msgs/PointStamped":               TopicInfo("geometry_msgs/PointStamped",               TopicTier.LIGHT, "带时间戳3D点"),
    "geometry_msgs/PolygonStamped":             TopicInfo("geometry_msgs/PolygonStamped",             TopicTier.LIGHT, "多边形"),
    "geometry_msgs/AccelStamped":               TopicInfo("geometry_msgs/AccelStamped",               TopicTier.LIGHT, "加速度"),
    "geometry_msgs/WrenchStamped":              TopicInfo("geometry_msgs/WrenchStamped",              TopicTier.LIGHT, "力/力矩"),

    # -- sensor_msgs (light) --
    "sensor_msgs/Imu":              TopicInfo("sensor_msgs/Imu",              TopicTier.LIGHT, "IMU数据",         default_freq_limit=50),
    "sensor_msgs/NavSatFix":        TopicInfo("sensor_msgs/NavSatFix",        TopicTier.LIGHT, "GPS数据",         default_freq_limit=10),
    "sensor_msgs/BatteryState":     TopicInfo("sensor_msgs/BatteryState",     TopicTier.LIGHT, "电池状态"),
    "sensor_msgs/JointState":       TopicInfo("sensor_msgs/JointState",       TopicTier.LIGHT, "关节状态",        default_freq_limit=50),
    "sensor_msgs/Range":            TopicInfo("sensor_msgs/Range",            TopicTier.LIGHT, "超声波/红外测距",  default_freq_limit=10),
    "sensor_msgs/MagneticField":    TopicInfo("sensor_msgs/MagneticField",    TopicTier.LIGHT, "磁力计",          default_freq_limit=10),
    "sensor_msgs/FluidPressure":    TopicInfo("sensor_msgs/FluidPressure",    TopicTier.LIGHT, "气压计",          default_freq_limit=10),
    "sensor_msgs/Temperature":      TopicInfo("sensor_msgs/Temperature",      TopicTier.LIGHT, "温度"),
    "sensor_msgs/Illuminance":      TopicInfo("sensor_msgs/Illuminance",      TopicTier.LIGHT, "光照"),
    "sensor_msgs/RelativeHumidity": TopicInfo("sensor_msgs/RelativeHumidity", TopicTier.LIGHT, "湿度"),
    "sensor_msgs/TimeReference":    TopicInfo("sensor_msgs/TimeReference",    TopicTier.LIGHT, "时间基准"),
    "sensor_msgs/CameraInfo":       TopicInfo("sensor_msgs/CameraInfo",       TopicTier.LIGHT, "相机标定信息"),

    # -- nav_msgs (light) --
    "nav_msgs/Odometry":  TopicInfo("nav_msgs/Odometry",  TopicTier.LIGHT, "里程计", default_freq_limit=50),
    "nav_msgs/Path":      TopicInfo("nav_msgs/Path",      TopicTier.LIGHT, "路径"),
    "nav_msgs/GridCells": TopicInfo("nav_msgs/GridCells", TopicTier.LIGHT, "网格单元"),

    # -- tf2_msgs --
    "tf2_msgs/TFMessage": TopicInfo("tf2_msgs/TFMessage", TopicTier.LIGHT, "TF变换", default_freq_limit=50),

    # -- visualization_msgs (light) --
    "visualization_msgs/Marker":      TopicInfo("visualization_msgs/Marker",      TopicTier.LIGHT, "可视化标记"),
    "visualization_msgs/MarkerArray": TopicInfo("visualization_msgs/MarkerArray", TopicTier.LIGHT, "标记数组"),

    # ================================================================
    # 中等话题 → MQTT + 二进制  (10 KB ~ 1 MB)
    # ================================================================
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
    "nav_msgs/OccupancyGrid": TopicInfo(
        "nav_msgs/OccupancyGrid", TopicTier.MEDIUM, "占据栅格地图",
        default_freq_limit=2,
    ),

    # ================================================================
    # HEAVY 层保留骨架暂不使用（HTTP 流需要 Web 前端拉取，当前不用）
    # 以下类型降为 MEDIUM → MQTT JSON 直传
    # ================================================================
    "sensor_msgs/PointCloud2": TopicInfo(
        "sensor_msgs/PointCloud2", TopicTier.MEDIUM, "3D点云",
        default_freq_limit=5,
    ),
    "sensor_msgs/PointCloud": TopicInfo(
        "sensor_msgs/PointCloud", TopicTier.MEDIUM, "3D点云(遗留)",
        default_freq_limit=2,
    ),
}


# ---------------------------------------------------------------------------
# 注册表类
# ---------------------------------------------------------------------------
class TopicRegistry:
    """
    话题类型注册表

    - 根据消息类型查询传输策略
    - 支持注册自定义消息类型
    - 未注册的消息类型默认为 LIGHT
    """

    def __init__(self, custom_entries: Optional[Dict[str, TopicInfo]] = None):
        self._registry: dict[str, TopicInfo] = dict(_BUILTIN_REGISTRY)
        if custom_entries:
            self._registry.update(custom_entries)

    def get(self, msg_type: str) -> TopicInfo:
        """
        查询消息类型信息

        未注册的类型默认为 LIGHT 层级
        """
        if msg_type in self._registry:
            return self._registry[msg_type]

        # 通配符匹配: "std_msgs/*" 匹配所有 std_msgs 类型
        package = msg_type.rsplit("/", 1)[0] if "/" in msg_type else ""
        wildcard = f"{package}/*"
        if wildcard in self._registry:
            return self._registry[wildcard]

        # 未知类型默认为 LIGHT
        return TopicInfo(msg_type, TopicTier.LIGHT, description="未注册类型(默认轻量)")

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

    def list_all(self) -> dict[str, TopicInfo]:
        """列出所有已注册的消息类型"""
        return dict(self._registry)

    def list_by_tier(self, tier: TopicTier) -> dict[str, TopicInfo]:
        """列出指定层级的所有消息类型"""
        return {k: v for k, v in self._registry.items() if v.tier == tier}


# ---------------------------------------------------------------------------
# 全局默认实例
# ---------------------------------------------------------------------------
default_registry = TopicRegistry()
