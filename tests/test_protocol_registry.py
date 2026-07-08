from __future__ import annotations

from protocol.topic_registry import (
    TopicInfo,
    TopicRegistry,
    TopicTier,
    default_registry,
)

# 话题类型注册表测试 - Tier 分类、查询、自定义注册。


def test_pointcloud2_is_heavy_http_stream():
    info = default_registry.get("sensor_msgs/PointCloud2")

    assert info.tier == TopicTier.HEAVY
    assert default_registry.get_transport_type("sensor_msgs/PointCloud2") == "http_stream"
    assert info.default_freq_limit == 2


def test_regular_ros_topics_default_to_mqtt_binary():
    """常规 ROS 话题默认使用二进制传输，避免 JSON 放大结构化消息。"""
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
    """简单标量和文本消息保持 JSON，便于协议可读和轻量处理。"""
    registry = TopicRegistry()

    assert registry.get_transport_type("std_msgs/String") == "mqtt_json"
    assert registry.get_transport_type("std_msgs/Bool") == "mqtt_json"
    assert registry.get_transport_type("std_msgs/Float64") == "mqtt_json"


def test_heavy_payloads_default_to_http_stream():
    """点云等大 payload 默认走 HTTP stream，避免压垮 MQTT broker。"""
    registry = TopicRegistry()

    assert registry.get_transport_type("sensor_msgs/PointCloud2") == "http_stream"
    assert registry.get_transport_type("sensor_msgs/PointCloud") == "http_stream"


def test_unknown_ros_message_defaults_to_mqtt_binary():
    """未知但合法的 ROS 消息类型默认按 ROS1 serialized 二进制传输。"""
    registry = TopicRegistry()

    assert registry.get_transport_type("custom_msgs/Thing") == "mqtt_binary"


class TestTopicRegistry:
    """TopicRegistry 基本功能测试"""

    def setup_method(self):
        self.registry = TopicRegistry()

    def test_get_light_tier(self):
        """轻量话题返回 LIGHT"""
        info = self.registry.get("std_msgs/Bool")
        assert info.tier == TopicTier.LIGHT

    def test_get_medium_tier(self):
        """中等话题返回 MEDIUM"""
        info = self.registry.get("sensor_msgs/CompressedImage")
        assert info.tier == TopicTier.MEDIUM

    def test_get_heavy_tier(self):
        """重量话题返回 HEAVY"""
        info = self.registry.get("sensor_msgs/PointCloud2")
        assert info.tier == TopicTier.HEAVY

    def test_get_unknown_type_default_medium(self):
        """未知 ROS 消息类型默认返回 MEDIUM，后续按二进制传输处理。"""
        info = self.registry.get("unknown_pkg/UnknownType")
        assert info.tier == TopicTier.MEDIUM
        assert "未注册" in info.description

    def test_get_tier_shortcut(self):
        """get_tier 快捷方法"""
        assert self.registry.get_tier("std_msgs/String") == TopicTier.LIGHT
        assert self.registry.get_tier("sensor_msgs/LaserScan") == TopicTier.MEDIUM
        assert self.registry.get_tier("sensor_msgs/PointCloud2") == TopicTier.HEAVY

    def test_register_custom_type(self):
        """注册自定义消息类型"""
        info = TopicInfo("my_pkg/MyData", TopicTier.MEDIUM)
        self.registry.register("my_pkg/MyData", info)
        assert self.registry.get("my_pkg/MyData").tier == TopicTier.MEDIUM

    def test_register_overrides_builtin(self):
        """注册覆盖内置类型"""
        self.registry.register("std_msgs/Bool", TopicInfo("std_msgs/Bool", TopicTier.HEAVY))
        assert self.registry.get("std_msgs/Bool").tier == TopicTier.HEAVY

    def test_unregister(self):
        """取消注册后恢复默认行为"""
        self.registry.register("test/Foo", TopicInfo("test/Foo", TopicTier.HEAVY))
        self.registry.unregister("test/Foo")
        info = self.registry.get("test/Foo")
        assert info.tier == TopicTier.MEDIUM  # 回退到未知 ROS 类型默认二进制

    def test_unregister_builtin(self):
        """取消注册内置类型后恢复到默认"""
        # 先注册覆盖
        self.registry.register("std_msgs/Bool", TopicInfo("std_msgs/Bool", TopicTier.MEDIUM))
        assert self.registry.get("std_msgs/Bool").tier == TopicTier.MEDIUM
        # 取消
        self.registry.unregister("std_msgs/Bool")
        # 移除精确规则后命中 std_msgs/*，用于避免复合消息回落到 JSON。
        info = self.registry.get("std_msgs/Bool")
        assert info.tier == TopicTier.MEDIUM

    def test_get_transport_type(self):
        """get_transport_type 返回正确传输方式"""
        assert self.registry.get_transport_type("std_msgs/String") == "mqtt_json"
        assert self.registry.get_transport_type("sensor_msgs/CompressedImage") == "mqtt_binary"
        assert self.registry.get_transport_type("sensor_msgs/PointCloud2") == "http_stream"
        assert self.registry.get_transport_type("unknown/Type") == "mqtt_binary"

    def test_list_all(self):
        """list_all 返回所有注册类型"""
        all_types = self.registry.list_all()
        assert "std_msgs/Bool" in all_types
        assert "sensor_msgs/Imu" in all_types
        assert "sensor_msgs/PointCloud2" in all_types

    def test_list_by_tier(self):
        """list_by_tier 过滤指定层级"""
        light_types = self.registry.list_by_tier(TopicTier.LIGHT)
        assert all(v.tier == TopicTier.LIGHT for v in light_types.values())
        assert "std_msgs/Bool" in light_types

        medium_types = self.registry.list_by_tier(TopicTier.MEDIUM)
        assert all(v.tier == TopicTier.MEDIUM for v in medium_types.values())
        assert "sensor_msgs/LaserScan" in medium_types

        heavy_types = self.registry.list_by_tier(TopicTier.HEAVY)
        assert all(v.tier == TopicTier.HEAVY for v in heavy_types.values())
        assert "sensor_msgs/PointCloud2" in heavy_types

    def test_custom_registry_init(self):
        """使用自定义条目初始化"""
        custom = {"my/Type": TopicInfo("my/Type", TopicTier.HEAVY)}
        registry = TopicRegistry(custom_entries=custom)
        assert registry.get("my/Type").tier == TopicTier.HEAVY
        # 内置类型仍可用
        assert registry.get("std_msgs/Bool").tier == TopicTier.LIGHT


class TestTopicInfo:
    """TopicInfo 数据类测试"""

    def test_default_freq_limit(self):
        """部分内置类型有默认频率限制"""
        registry = TopicRegistry()
        imu = registry.get("sensor_msgs/Imu")
        assert imu.default_freq_limit == 50

        pointcloud = registry.get("sensor_msgs/PointCloud2")
        assert pointcloud.default_freq_limit == 2

    def test_compression_defaults(self):
        """部分类型有压缩默认选项"""
        registry = TopicRegistry()
        image = registry.get("sensor_msgs/Image")
        assert "quality" in image.compression_defaults
        assert image.compression_defaults["quality"] == 60


class TestDefaultRegistry:
    """全局默认注册表实例测试"""

    def test_default_registry_is_singleton(self):
        """默认实例可用"""
        assert isinstance(default_registry, TopicRegistry)
        assert default_registry.get("std_msgs/String").tier == TopicTier.LIGHT

    def test_default_registry_mutations_isolated(self):
        """修改默认实例不影响新实例"""
        default_registry.register("test/Isolated", TopicInfo("test/Isolated", TopicTier.MEDIUM))

        fresh = TopicRegistry()
        # 新实例不应包含自定义注册的类型
        info = fresh.get("test/Isolated")
        assert info.tier == TopicTier.MEDIUM
        assert "未注册" in info.description
