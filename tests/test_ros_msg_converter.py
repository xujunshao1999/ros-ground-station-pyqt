from __future__ import annotations
"""ROS 消息通用序列化器测试"""

import pytest
from agent.ros_msg_converter import ros_msg_to_dict


class FakeSlots:
    """模拟 ROS 消息对象（有 __slots__ 属性）"""
    __slots__ = ["x", "y", "z"]

    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x = x
        self.y = y
        self.z = z


class FakeNested:
    """模拟嵌套 ROS 消息"""
    __slots__ = ["header", "data"]

    def __init__(self, header=None, data=None):
        self.header = header or FakeSlots()
        self.data = data or []


class FakeTime:
    """模拟 ROS time"""
    __slots__ = ["secs", "nsecs"]

    def __init__(self, secs=0, nsecs=0):
        self.secs = secs
        self.nsecs = nsecs


class TestRosMsgConverter:
    """通用序列化器测试"""

    def test_flat_message(self):
        msg = FakeSlots(x=1.0, y=2.0, z=3.0)
        result = ros_msg_to_dict(msg)
        assert result == {"x": 1.0, "y": 2.0, "z": 3.0}

    def test_nested_message(self):
        header = FakeSlots(x=1, y=2, z=3)
        msg = FakeNested(header=header, data=[1, 2, 3])
        result = ros_msg_to_dict(msg)
        assert result["header"] == {"x": 1, "y": 2, "z": 3}
        assert result["data"] == [1, 2, 3]

    def test_bytes_conversion(self):
        class FakeBytes:
            __slots__ = ["raw"]
            def __init__(self):
                self.raw = b"\x00\x01\xff"

        result = ros_msg_to_dict(FakeBytes())
        assert result["raw"] == [0, 1, 255]

    def test_ros_time(self):
        t = FakeTime(secs=100, nsecs=500000000)
        result = ros_msg_to_dict(t)
        assert result == {"secs": 100, "nsecs": 500000000}

    def test_empty_list(self):
        msg = FakeNested(data=[])
        result = ros_msg_to_dict(msg)
        assert result["data"] == []

    def test_str_and_bool(self):
        class FakeFlags:
            __slots__ = ["name", "active"]
            def __init__(self):
                self.name = "test"
                self.active = True
        result = ros_msg_to_dict(FakeFlags())
        assert result == {"name": "test", "active": True}

    def test_none_value(self):
        class FakeWithNone:
            __slots__ = ["value"]
            def __init__(self):
                self.value = None
        result = ros_msg_to_dict(FakeWithNone())
        assert result == {"value": None}

    def test_no_slots_fallback(self):
        class NoSlotsObj:
            pass

        obj = NoSlotsObj()
        obj.foo = "bar"
        result = ros_msg_to_dict(obj)
        # Fallback: should return a dict or string representation
        assert isinstance(result, dict)
