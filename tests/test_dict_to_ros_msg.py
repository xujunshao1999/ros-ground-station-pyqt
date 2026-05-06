from __future__ import annotations

"""dict_to_ros_msg 测试 - 使用 mock/fake ROS 消息类"""

import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock rospy before importing bridge module
# ---------------------------------------------------------------------------
mock_rospy = MagicMock()
mock_rospy.msg = MagicMock()


class MockTime:
    """Mock rospy.Time"""
    def __init__(self, secs=0, nsecs=0):
        self.secs = secs
        self.nsecs = nsecs

    def __eq__(self, other):
        if isinstance(other, MockTime):
            return self.secs == other.secs and self.nsecs == other.nsecs
        return NotImplemented

    def __repr__(self):
        return f"MockTime(secs={self.secs}, nsecs={self.nsecs})"


class MockDuration:
    """Mock rospy.Duration"""
    def __init__(self, secs=0, nsecs=0):
        self.secs = secs
        self.nsecs = nsecs

    def __eq__(self, other):
        if isinstance(other, MockDuration):
            return self.secs == other.secs and self.nsecs == other.nsecs
        return NotImplemented

    def __repr__(self):
        return f"MockDuration(secs={self.secs}, nsecs={self.nsecs})"

    @classmethod
    def from_sec(cls, seconds):
        secs = int(seconds)
        nsecs = int(round((seconds - secs) * 1e9))
        return cls(secs=secs, nsecs=nsecs)

    def to_sec(self):
        return self.secs + self.nsecs * 1e-9


mock_rospy.Time = MockTime
mock_rospy.Duration = MockDuration

sys.modules["rospy"] = mock_rospy
sys.modules["rospy.msg"] = mock_rospy.msg

# Now import the module under test
from agent.ros_msg_converter import ros_msg_to_dict  # noqa: E402
from bridge.dict_to_ros_msg import _parse_type_str, dict_to_ros_msg  # noqa: E402


# Reset warning counters for each test
@pytest.fixture(autouse=True)
def _reset_warning_counters():
    from bridge.dict_to_ros_msg import _WARNING_COUNTS
    _WARNING_COUNTS.clear()


# ---------------------------------------------------------------------------
# Mock ROS message classes
# ---------------------------------------------------------------------------

class MockSimpleMsg:
    """原始类型字段的消息"""
    __slots__ = ["x", "y", "z", "name", "active"]
    _slot_types = ["float64", "float64", "float64", "string", "bool"]

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.name = ""
        self.active = False


class MockNestedMsg:
    """包含嵌套消息的消息"""
    __slots__ = ["header", "data"]
    _slot_types = ["test_msgs/Header", "float64[]"]

    def __init__(self):
        self.header = MockHeaderMsg()
        self.data = []


class MockHeaderMsg:
    """模拟 Header 消息"""
    __slots__ = ["seq", "stamp", "frame_id"]
    _slot_types = ["uint32", "time", "string"]

    def __init__(self):
        self.seq = 0
        self.stamp = MockTime()
        self.frame_id = ""


class MockArrayMsg:
    """包含数组的消息"""
    __slots__ = ["points", "covariance", "byte_data", "poses"]
    _slot_types = ["float64[]", "float64[9]", "uint8[]", "test_msgs/Pose[]"]

    def __init__(self):
        self.points = []
        self.covariance = (0.0,) * 9
        self.byte_data = b""
        self.poses = []


class MockPoseMsg:
    """模拟 Pose 消息"""
    __slots__ = ["x", "y", "theta"]
    _slot_types = ["float64", "float64", "float64"]

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0


class MockRoundtripMsg:
    """综合消息：用于 roundtrip 测试"""
    __slots__ = ["x", "name", "active", "stamp", "period", "data", "nested"]
    _slot_types = ["float64", "string", "bool", "time", "duration", "float64[]", "test_msgs/Pose"]

    def __init__(self):
        self.x = 0.0
        self.name = ""
        self.active = False
        self.stamp = MockTime()
        self.period = MockDuration()
        self.data = []
        self.nested = MockPoseMsg()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_get_message_class(msg_type: str):
    """根据类型名返回对应的 mock 消息类"""
    registry = {
        "test_msgs/Simple": MockSimpleMsg,
        "test_msgs/Nested": MockNestedMsg,
        "test_msgs/Header": MockHeaderMsg,
        "test_msgs/Array": MockArrayMsg,
        "test_msgs/Pose": MockPoseMsg,
        "test_msgs/Roundtrip": MockRoundtripMsg,
    }
    return registry.get(msg_type)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseTypeStr:
    """_parse_type_str 单元测试"""

    def test_primitive_type(self):
        assert _parse_type_str("float64") == ("float64", False, None)
        assert _parse_type_str("int32") == ("int32", False, None)
        assert _parse_type_str("string") == ("string", False, None)

    def test_variable_array(self):
        assert _parse_type_str("float64[]") == ("float64", True, None)

    def test_fixed_array(self):
        assert _parse_type_str("float64[36]") == ("float64", True, 36)
        assert _parse_type_str("uint8[3]") == ("uint8", True, 3)

    def test_nested_type_array(self):
        assert _parse_type_str("test_msgs/Pose[]") == ("test_msgs/Pose", True, None)

    def test_empty_bracket(self):
        assert _parse_type_str("") == ("", False, None)


class TestDictToRosMsg:
    """dict_to_ros_msg 主功能测试"""

    def test_primitive_fields(self):
        """基本类型字段"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg(
                {
                    "x": 1.0,
                    "y": 2.0,
                    "z": 3.0,
                    "name": "test_robot",
                    "active": True,
                },
                "test_msgs/Simple",
            )

        assert isinstance(result, MockSimpleMsg)
        assert result.x == 1.0
        assert result.y == 2.0
        assert result.z == 3.0
        assert result.name == "test_robot"
        assert result.active is True

    def test_missing_fields(self):
        """缺少字段时不报错，保留默认值"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg({"x": 99.0}, "test_msgs/Simple")

        assert result.x == 99.0
        assert result.y == 0.0  # 默认值
        assert result.z == 0.0  # 默认值
        assert result.name == ""  # 默认值

    def test_nested_message(self):
        """嵌套消息递归转换"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg(
                {
                    "header": {"seq": 1, "stamp": {"secs": 100, "nsecs": 500}, "frame_id": "odom"},
                    "data": [1.0, 2.0, 3.0],
                },
                "test_msgs/Nested",
            )

        assert isinstance(result, MockNestedMsg)
        assert isinstance(result.header, MockHeaderMsg)
        assert result.header.seq == 1
        assert isinstance(result.header.stamp, MockTime)
        assert result.header.stamp.secs == 100
        assert result.header.stamp.nsecs == 500
        assert result.header.frame_id == "odom"
        assert result.data == [1.0, 2.0, 3.0]

    def test_ros_time_from_dict(self):
        """dict 中的 secs/nsecs → rospy.Time"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg(
                {"seq": 5, "stamp": {"secs": 42, "nsecs": 123456789}, "frame_id": "map"},
                "test_msgs/Header",
            )

        assert isinstance(result.stamp, MockTime)
        assert result.stamp.secs == 42
        assert result.stamp.nsecs == 123456789

    def test_ros_duration_from_dict(self):
        """测试 duration 类型反序列化"""

        class MockDurationMsg:
            __slots__ = ["period", "name"]
            _slot_types = ["duration", "string"]

            def __init__(self):
                self.period = MockDuration()
                self.name = ""

        registry = {"test_msgs/Duration": MockDurationMsg}

        with patch.object(
            mock_rospy.msg, "get_message_class",
            side_effect=lambda t: registry.get(t),
        ):
            result = dict_to_ros_msg(
                {"period": {"secs": 5, "nsecs": 100}, "name": "loop"},
                "test_msgs/Duration",
            )

        assert isinstance(result.period, MockDuration)
        assert result.period.secs == 5
        assert result.period.nsecs == 100
        assert result.name == "loop"

    def test_bytes_from_list(self):
        """uint8[] 列表 → bytes 转换"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg(
                {
                    "points": [1.0, 2.0, 3.0],
                    "covariance": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0],
                    "byte_data": [0, 1, 255, 128],
                    "poses": [],
                },
                "test_msgs/Array",
            )

        assert result.points == [1.0, 2.0, 3.0]
        # 定长数组存储为 tuple
        assert isinstance(result.covariance, tuple)
        assert result.covariance == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
        # uint8[] → bytes
        assert isinstance(result.byte_data, bytes)
        assert result.byte_data == bytes([0, 1, 255, 128])

    def test_list_of_nested_messages(self):
        """嵌套消息数组"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg(
                {
                    "points": [],
                    "covariance": [0.0] * 9,
                    "byte_data": [],
                    "poses": [
                        {"x": 1.0, "y": 2.0, "theta": 0.5},
                        {"x": 3.0, "y": 4.0, "theta": 1.0},
                    ],
                },
                "test_msgs/Array",
            )

        assert len(result.poses) == 2
        assert isinstance(result.poses[0], MockPoseMsg)
        assert result.poses[0].x == 1.0
        assert result.poses[0].y == 2.0
        assert result.poses[0].theta == 0.5
        assert result.poses[1].x == 3.0
        assert result.poses[1].y == 4.0
        assert result.poses[1].theta == 1.0

    def test_unknown_field_skipped(self):
        """data 中的未知字段跳过并触发警告"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg(
                {
                    "x": 1.0,
                    "unknown_field": "should_be_skipped",
                    "y": 2.0,
                },
                "test_msgs/Simple",
            )

        assert result.x == 1.0
        assert result.y == 2.0
        # unknown_field 不存在于 __slots__ 中，应被跳过
        assert not hasattr(result, "unknown_field")

    def test_unknown_type(self):
        """未知类型字符串处理"""

        class MockUnknownTypeMsg:
            __slots__ = ["data", "name"]
            _slot_types = ["some_unknown_type", "string"]

            def __init__(self):
                self.data = None
                self.name = ""

        registry = {"test_msgs/Unknown": MockUnknownTypeMsg}

        with patch.object(
            mock_rospy.msg, "get_message_class",
            side_effect=lambda t: registry.get(t),
        ):
            result = dict_to_ros_msg(
                {"data": [1, 2, 3], "name": "test"},
                "test_msgs/Unknown",
            )

        # 未知类型透传
        assert result.data == [1, 2, 3]
        assert result.name == "test"

    def test_none_value(self):
        """None 值处理"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg(
                {"x": None, "y": 5.0, "z": None, "name": "test", "active": None},
                "test_msgs/Simple",
            )

        assert result.x is None
        assert result.y == 5.0
        assert result.z is None
        assert result.name == "test"
        assert result.active is None

    def test_unknown_message_type(self):
        """未知消息类型抛出 ValueError"""
        with patch.object(
            mock_rospy.msg, "get_message_class",
            side_effect=lambda t: None,
        ):
            with pytest.raises(ValueError, match="Unknown ROS message type"):
                dict_to_ros_msg({}, "nonexistent/Type")

    def test_empty_dict(self):
        """空 dict 创建默认消息"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg({}, "test_msgs/Simple")

        assert isinstance(result, MockSimpleMsg)
        assert result.x == 0.0
        assert result.name == ""

    def test_string_to_float_conversion(self):
        """字符串值可转换为数字时正确处理"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg(
                {"x": "3.14", "y": 2, "z": 1.0, "name": "test", "active": 1},
                "test_msgs/Simple",
            )

        # string → float
        assert result.x == 3.14
        # int → float
        assert isinstance(result.y, float)
        assert result.y == 2.0
        # int → bool
        assert result.active is True

    def test_invalid_type_returns_val_as_is(self):
        """列表值给到非数组类型时，透传"""
        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            result = dict_to_ros_msg(
                {"x": [1, 2, 3], "y": 2.0, "z": 3.0, "name": "", "active": False},
                "test_msgs/Simple",
            )

        # float64 字段得到 list，透传
        assert result.x == [1, 2, 3]

    def test_throttled_warning_for_unknown_fields(self):
        """未知字段触发限频警告"""
        from bridge.dict_to_ros_msg import _WARNING_COUNTS

        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            # 多次触发相同的未知字段警告
            for _ in range(5):
                dict_to_ros_msg(
                    {"x": 1.0, "bogus": "field"},
                    "test_msgs/Simple",
                )

        # 只记录 _MAX_WARNINGS + 1 条
        assert _WARNING_COUNTS.get(
            "Unknown field 'bogus' in data for message type 'test_msgs/Simple'", 0
        ) == 5

    def test_ros_duration_from_numeric(self):
        """测试 duration 数字值（float/int）反序列化"""
        class MockDurationMsg:
            __slots__ = ["period", "name"]
            _slot_types = ["duration", "string"]

            def __init__(self):
                self.period = MockDuration()
                self.name = ""

        registry = {"test_msgs/Duration": MockDurationMsg}

        with patch.object(
            mock_rospy.msg, "get_message_class",
            side_effect=lambda t: registry.get(t),
        ):
            # float value (e.g. from ros_msg_to_dict's to_sec())
            result = dict_to_ros_msg(
                {"period": 5.5, "name": "float_dur"},
                "test_msgs/Duration",
            )

        assert isinstance(result.period, MockDuration)
        assert result.period.secs == 5
        assert result.period.nsecs == 500000000
        assert result.name == "float_dur"

        with patch.object(
            mock_rospy.msg, "get_message_class",
            side_effect=lambda t: registry.get(t),
        ):
            # int value
            result2 = dict_to_ros_msg(
                {"period": 3, "name": "int_dur"},
                "test_msgs/Duration",
            )

        assert isinstance(result2.period, MockDuration)
        assert result2.period.secs == 3
        assert result2.period.nsecs == 0
        assert result2.name == "int_dur"

    def test_roundtrip(self):
        """完整 roundtrip：消息 → dict → 消息 → dict"""
        msg = MockRoundtripMsg()
        msg.x = 1.5
        msg.name = "test_robot"
        msg.active = True
        msg.stamp = MockTime(secs=100, nsecs=500)
        msg.period = MockDuration(secs=5, nsecs=100)
        msg.data = [1.0, 2.0, 3.0]
        msg.nested = MockPoseMsg()
        msg.nested.x = 10.0
        msg.nested.y = 20.0
        msg.nested.theta = 0.5

        d1 = ros_msg_to_dict(msg)

        with patch.object(
            mock_rospy.msg, "get_message_class", side_effect=_mock_get_message_class
        ):
            restored = dict_to_ros_msg(d1, "test_msgs/Roundtrip")

        assert isinstance(restored, MockRoundtripMsg)
        assert isinstance(restored.nested, MockPoseMsg)
        assert isinstance(restored.stamp, MockTime)
        assert isinstance(restored.period, MockDuration)

        d2 = ros_msg_to_dict(restored)

        assert d1 == d2
