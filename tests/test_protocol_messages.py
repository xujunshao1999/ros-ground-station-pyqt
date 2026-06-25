from __future__ import annotations

import json
import time

import pytest

from protocol.messages import (
    CmdAckData,
    CmdAction,
    CmdData,
    DiscoverResponseData,
    EventData,
    FleetData,
    Message,
    MessageType,
    RobotMode,
    SensorMetaData,
    StatusData,
    TopicAction,
    TopicRequestData,
    TopicResponseData,
)

# 协议消息层测试 - Message 序列化、反序列化、MessageFactory。


class TestMessage:
    """Message 核心类测试"""

    def test_create_message(self):
        """测试创建 Message 实例"""
        msg = Message(
            ver="1.0",
            src="robot_001",
            dst="station",
            type=MessageType.STATUS,
            seq=1,
            data={"battery": 100.0},
        )
        assert msg.ver == "1.0"
        assert msg.src == "robot_001"
        assert msg.type == MessageType.STATUS
        assert msg.data["battery"] == 100.0

    def test_to_json_and_from_json_roundtrip(self):
        """测试 Message 序列化与反序列化往返"""
        original = Message(
            ver="1.0",
            ts=1234567890.0,
            src="robot_001",
            dst="station",
            type=MessageType.STATUS,
            seq=42,
            data={"battery": 85.5, "mode": "auto"},
        )
        json_str = original.to_json()
        restored = Message.from_json(json_str)

        assert restored.ver == original.ver
        assert restored.ts == original.ts
        assert restored.src == original.src
        assert restored.dst == original.dst
        assert restored.type == original.type
        assert restored.seq == original.seq
        assert restored.data["battery"] == 85.5
        assert restored.data["mode"] == "auto"

    def test_from_json_missing_fields(self):
        """测试反序列化时缺失字段使用默认值"""
        minimal = '{"src": "robot_001", "type": "status"}'
        msg = Message.from_json(minimal)
        # 缺失字段应使用默认值
        assert msg.ver == "1.0"
        assert msg.src == "robot_001"
        assert msg.dst == ""
        assert msg.seq == 0
        assert msg.data == {}

    def test_from_json_invalid(self):
        """测试无效 JSON 应抛异常"""
        with pytest.raises(json.JSONDecodeError):
            Message.from_json("not json")

    def test_to_dict(self):
        """测试 Message 转字典"""
        msg = Message(
            src="robot_001",
            type=MessageType.STATUS,
            data={"battery": 100.0},
        )
        d = msg.to_dict()
        assert d["src"] == "robot_001"
        assert d["type"] == "status"
        assert d["data"]["battery"] == 100.0
        assert "ts" in d
        assert "seq" in d

    def test_from_dict(self):
        """测试从字典构建 Message"""
        d = {
            "ver": "1.0",
            "src": "robot_001",
            "type": "cmd_ack",
            "seq": 5,
            "data": {"result": "ok"},
        }
        msg = Message.from_dict(d)
        assert msg.ver == "1.0"
        assert msg.src == "robot_001"
        assert msg.type == "cmd_ack"
        assert msg.data["result"] == "ok"
        assert msg.dst == ""  # 缺失字段默认值

    def test_timestamp_auto_fill(self):
        """测试创建 Message 时自动填充时间戳"""
        before = time.time()
        msg = Message(src="robot_001", type=MessageType.STATUS)
        after = time.time()
        assert before <= msg.ts <= after

    def test_json_contains_all_fields(self):
        """测试 JSON 输出包含所有必要字段"""
        msg = Message(
            src="robot_001",
            dst="station",
            type=MessageType.STATUS,
            seq=10,
            data={"key": "value"},
        )
        parsed = json.loads(msg.to_json())
        assert "ver" in parsed
        assert "ts" in parsed
        assert "src" in parsed
        assert "dst" in parsed
        assert "type" in parsed
        assert "seq" in parsed
        assert "data" in parsed

    def test_protocol_version_consistency(self):
        """测试协议版本一致性"""
        from protocol.messages import PROTOCOL_VERSION

        msg = Message(src="robot_001", type=MessageType.STATUS)
        assert msg.ver == PROTOCOL_VERSION
        parsed = json.loads(msg.to_json())
        assert parsed["ver"] == PROTOCOL_VERSION


class TestMessageFactory:
    """MessageFactory 测试"""

    def test_status_message(self, factory, sample_status_data):
        """测试创建状态上报消息"""
        msg = factory.status(sample_status_data)
        assert msg.type == MessageType.STATUS
        assert msg.src == "test_robot"
        assert msg.dst == "station"
        assert msg.data["battery"] == 85.5
        assert msg.data["mode"] == "manual"

    def test_cmd_message(self, factory):
        """测试创建控制指令消息"""
        cmd = CmdData(
            action=CmdAction.VELOCITY,
            params={"linear": 0.5, "angular": 0.0},
        )
        msg = factory.cmd(cmd, dst="robot_002")
        assert msg.type == MessageType.CMD
        assert msg.dst == "robot_002"
        assert msg.data["action"] == "velocity"
        assert msg.data["params"]["linear"] == 0.5

    def test_cmd_ack_message(self, factory):
        """测试创建指令确认消息"""
        ack = CmdAckData(exec_id="abc123", result="ok", message="Done")
        msg = factory.cmd_ack(ack)
        assert msg.type == MessageType.CMD_ACK
        assert msg.data["exec_id"] == "abc123"
        assert msg.data["result"] == "ok"

    def test_event_message(self, factory):
        """测试创建事件消息"""
        event = EventData(level="error", code="BATTERY_LOW", message="Battery critically low")
        msg = factory.event(event)
        assert msg.type == MessageType.EVENT
        assert msg.data["level"] == "error"
        assert msg.data["code"] == "BATTERY_LOW"

    def test_discover_message(self, factory):
        """测试创建发现请求消息"""
        msg = factory.discover()
        assert msg.type == MessageType.DISCOVER
        assert msg.dst == "broadcast"
        assert "request_id" in msg.data

    def test_discover_response_message(self, factory):
        """测试创建发现响应消息"""
        resp = DiscoverResponseData(
            request_id="req_001",
            robot_id="robot_001",
            ros_version="1",
            topics=[
                {"topic": "/odom", "msg_type": "nav_msgs/Odometry"},
                {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
            ],
            ip="192.168.1.10",
        )
        msg = factory.discover_response(resp)
        assert msg.type == MessageType.DISCOVER_RESPONSE
        assert msg.data["robot_id"] == "robot_001"
        assert len(msg.data["topics"]) == 2

    def test_topic_request_message(self, factory):
        """测试创建话题请求消息"""
        req = TopicRequestData(
            action=TopicAction.SUBSCRIBE,
            topic="/camera/image_raw",
            msg_type="sensor_msgs/CompressedImage",
            freq_limit=10.0,
        )
        msg = factory.topic_request(req, dst="robot_001")
        assert msg.type == MessageType.TOPIC_REQUEST
        assert msg.dst == "robot_001"
        assert msg.data["action"] == "subscribe"
        assert msg.data["topic"] == "/camera/image_raw"

    def test_topic_response_message(self, factory):
        """测试创建话题响应消息"""
        resp = TopicResponseData(request_id="req_001", result="ok")
        msg = factory.topic_response(resp)
        assert msg.type == MessageType.TOPIC_RESPONSE
        assert msg.data["result"] == "ok"

    def test_sensor_meta_message(self, factory):
        """测试创建重量话题元信息消息"""
        meta = SensorMetaData(
            topic="/lidar/points",
            msg_type="sensor_msgs/PointCloud2",
            stream_url="http://192.168.1.10:8080/stream/lidar/points",
            size_bytes=2048000,
        )
        msg = factory.sensor_meta(meta)
        assert msg.type == MessageType.SENSOR_META
        assert msg.data["stream_url"].startswith("http://")

    def test_sensor_meta_message_includes_heavy_snapshot_fields(self, factory):
        meta = SensorMetaData(
            topic="/velodyne_points",
            msg_type="sensor_msgs/PointCloud2",
            transport="http_stream",
            stream_url="http://192.168.1.10:8080/stream/velodyne_points",
            size_bytes=2048000,
            seq=12,
            stamp={"secs": 1782370000, "nsecs": 120000000},
            frame_id="velodyne",
            encoding="ros1_serialized_v1",
            payload_format="ros1_serialized",
            payload_size=2048000,
        )

        msg = factory.sensor_meta(meta)

        assert msg.type == MessageType.SENSOR_META
        assert msg.data["stream_url"].startswith("http://")
        assert msg.data["seq"] == 12
        assert msg.data["stamp"]["secs"] == 1782370000
        assert msg.data["frame_id"] == "velodyne"
        assert msg.data["encoding"] == "ros1_serialized_v1"
        assert msg.data["payload_format"] == "ros1_serialized"
        assert msg.data["payload_size"] == 2048000

    def test_fleet_data_message(self, factory):
        """测试创建机器人间通信消息"""
        fd = FleetData(
            data_type="position",
            payload={"x": 1.0, "y": 2.0, "theta": 0.5},
            ttl=30.0,
        )
        msg = factory.fleet_data(fd, dst="robot_002")
        assert msg.type == MessageType.FLEET_DATA
        assert msg.dst == "robot_002"
        assert msg.data["data_type"] == "position"
        assert msg.data["payload"]["x"] == 1.0
        assert msg.data["ttl"] == 30.0

    def test_fleet_data_ros_topic_fields(self, factory):
        """测试创建 ROS topic 转发类型的机器人间通信消息"""
        fd = FleetData(
            data_type="ros_topic",
            src_topic="/odom",
            dst_topic="/fleet/turtlebot_001/odom",
            msg_type="nav_msgs/Odometry",
            frame_policy="namespace",
            payload={"header": {"frame_id": "odom"}},
            stamp=123.0,
            ttl=1.0,
        )

        msg = factory.fleet_data(fd, dst="turtlebot_002")

        assert msg.type == MessageType.FLEET_DATA
        assert msg.dst == "turtlebot_002"
        assert msg.data["data_type"] == "ros_topic"
        assert msg.data["src_topic"] == "/odom"
        assert msg.data["dst_topic"] == "/fleet/turtlebot_001/odom"
        assert msg.data["msg_type"] == "nav_msgs/Odometry"
        assert msg.data["frame_policy"] == "namespace"
        assert msg.data["payload"] == {"header": {"frame_id": "odom"}}
        assert msg.data["stamp"] == 123.0
        assert msg.data["ttl"] == 1.0

    def test_sequence_number_increment(self, factory):
        """测试序列号递增"""
        msg1 = factory.status(StatusData())
        msg2 = factory.status(StatusData())
        assert msg2.seq == msg1.seq + 1

    def test_factory_src_consistency(self, factory):
        """测试工厂 src 一致性"""
        msg1 = factory.status(StatusData())
        msg2 = factory.cmd(CmdData())
        msg3 = factory.event(EventData())
        assert msg1.src == "test_robot"
        assert msg2.src == "test_robot"
        assert msg3.src == "test_robot"


class TestMessageTypes:
    """消息类型枚举测试"""

    def test_all_types_have_unique_values(self):
        """测试所有消息类型有唯一值"""
        values = [t.value for t in MessageType]
        assert len(values) == len(set(values))

    def test_cmd_action_values(self):
        """测试指令动作枚举值"""
        assert CmdAction.VELOCITY == "velocity"
        assert CmdAction.MODE == "mode"
        assert CmdAction.NAV_GOAL == "nav_goal"
        assert CmdAction.CUSTOM == "custom"

    def test_robot_mode_values(self):
        """测试机器人模式枚举值"""
        assert RobotMode.AUTO == "auto"
        assert RobotMode.MANUAL == "manual"
        assert RobotMode.STOP == "stop"
        assert RobotMode.ERROR == "error"

    def test_topic_action_values(self):
        """测试话题动作枚举值"""
        assert TopicAction.SUBSCRIBE == "subscribe"
        assert TopicAction.UNSUBSCRIBE == "unsubscribe"
