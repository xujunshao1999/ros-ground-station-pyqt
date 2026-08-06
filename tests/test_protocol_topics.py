"""MQTT Topic 规范测试 - 生成函数与解析器"""

from __future__ import annotations

from protocol.topics import (
    TOPIC_QOS,
    QoS,
    all_message_schema_responses,
    all_robot_cmd_ack,
    all_robot_event,
    all_robot_sensor_meta,
    all_robot_status,
    all_robot_to_robot,
    all_robot_to_robot_binary,
    all_robot_to_robot_meta,
    parse_robot_topic,
    parse_station_topic,
    robot_cmd,
    robot_cmd_ack,
    robot_event,
    robot_sensor,
    robot_sensor_meta,
    robot_status,
    robot_to_robot,
    robot_to_robot_binary,
    robot_to_robot_meta,
    station_discover,
    station_message_schema_query,
    station_message_schema_response,
    station_topic_request,
    station_topic_response,
)


def test_robot_to_robot_binary_topics():
    """二进制主体使用独立的 Agent 间 MQTT topic。"""
    assert robot_to_robot_binary("r1", "r2") == "robot/r1/to/r2/bin"
    assert all_robot_to_robot_binary("r2") == "robot/+/to/r2/bin"


def test_parse_robot_to_robot_binary_requires_exact_segments():
    """Agent 间后缀 topic 必须精确匹配，拒绝多余层级。"""
    parsed = parse_robot_topic("robot/r1/to/r2/bin")
    assert parsed == {
        "robot_id": "r1",
        "type": "to_robot_binary",
        "dst_id": "r2",
    }
    assert parse_robot_topic("robot/r1/to/r2/bin/extra") is None
    assert parse_robot_topic("robot/r1/to/r2/meta/extra") is None


def test_message_schema_topics_and_parser_are_targeted():
    """消息结构查询必须定向到单台机器人并严格匹配层级。"""
    assert station_message_schema_query("r1") == "station/r1/message_schema/query"
    assert station_message_schema_response("r1") == "station/r1/message_schema/response"
    assert all_message_schema_responses() == "station/+/message_schema/response"
    assert parse_station_topic("station/r1/message_schema/query") == {
        "type": "message_schema_query",
        "robot_id": "r1",
    }
    assert parse_station_topic("station/r1/message_schema/response") == {
        "type": "message_schema_response",
        "robot_id": "r1",
    }
    assert parse_station_topic("station/r1/message_schema/query/extra") is None
    assert parse_station_topic("station/r1/config/query/extra") is None


def test_message_schema_topics_use_qos_one():
    """查询与响应属于控制面消息，必须使用 QoS 1。"""
    assert TOPIC_QOS["message_schema_query"] == QoS.AT_LEAST_ONCE
    assert TOPIC_QOS["message_schema_response"] == QoS.AT_LEAST_ONCE


class TestTopicGeneration:
    """Topic 生成函数测试"""

    def test_robot_status(self):
        assert robot_status("robot_001") == "robot/robot_001/status"

    def test_robot_sensor(self):
        assert robot_sensor("robot_001", "imu") == "robot/robot_001/sensor/imu"

    def test_robot_sensor_with_slash_name(self):
        """传感器名包含 / 时保持原样"""
        assert robot_sensor("r1", "camera/image") == "robot/r1/sensor/camera/image"

    def test_robot_sensor_meta(self):
        assert robot_sensor_meta("robot_001", "lidar") == "robot/robot_001/sensor/lidar/meta"

    def test_robot_cmd(self):
        assert robot_cmd("robot_001") == "robot/robot_001/cmd"

    def test_robot_cmd_ack(self):
        assert robot_cmd_ack("robot_001") == "robot/robot_001/cmd/ack"

    def test_robot_event(self):
        assert robot_event("robot_001") == "robot/robot_001/event"

    def test_station_discover(self):
        assert station_discover() == "station/discover"

    def test_station_topic_request(self):
        assert station_topic_request() == "station/topic/request"

    def test_station_topic_response(self):
        assert station_topic_response() == "station/topic/response"

    def test_station_topic_response_with_id(self):
        assert station_topic_response("robot_001") == "station/topic/response/robot_001"

    def test_all_robot_status(self):
        assert all_robot_status() == "robot/+/status"

    def test_all_robot_cmd_ack(self):
        assert all_robot_cmd_ack() == "robot/+/cmd/ack"

    def test_all_robot_event(self):
        assert all_robot_event() == "robot/+/event"

    def test_all_robot_sensor_meta(self):
        assert all_robot_sensor_meta() == "robot/+/sensor/+/meta"

    # ---- 机器人间通信 topic ----

    def test_robot_to_robot(self):
        assert robot_to_robot("robot_001", "robot_002") == "robot/robot_001/to/robot_002"

    def test_robot_to_robot_meta(self):
        assert robot_to_robot_meta("robot_001", "robot_002") == "robot/robot_001/to/robot_002/meta"

    def test_all_robot_to_robot(self):
        assert all_robot_to_robot("robot_002") == "robot/+/to/robot_002"

    def test_all_robot_to_robot_meta(self):
        assert all_robot_to_robot_meta("robot_002") == "robot/+/to/robot_002/meta"

    def test_topic_prefixes_consistency(self):
        """验证所有 robot topic 使用 robot/ 前缀"""
        for robot_id in ["r1", "robot_001", "test-robot"]:
            assert robot_status(robot_id).startswith("robot/")
            assert robot_cmd(robot_id).startswith("robot/")
            assert robot_sensor(robot_id, "scan").startswith("robot/")
            assert robot_event(robot_id).startswith("robot/")

    def test_station_prefixes_consistency(self):
        """验证所有 station topic 使用 station/ 前缀"""
        assert station_discover().startswith("station/")
        assert station_topic_request().startswith("station/")
        assert station_topic_response().startswith("station/")


class TestTopicParser:
    """Topic 解析器测试"""

    # --- robot topic 解析 ---

    def test_parse_robot_status(self):
        result = parse_robot_topic("robot/robot_001/status")
        assert result is not None
        assert result["robot_id"] == "robot_001"
        assert result["type"] == "status"

    def test_parse_robot_cmd(self):
        result = parse_robot_topic("robot/robot_001/cmd")
        assert result is not None
        assert result["robot_id"] == "robot_001"
        assert result["type"] == "cmd"

    def test_parse_robot_cmd_ack(self):
        result = parse_robot_topic("robot/robot_001/cmd/ack")
        assert result is not None
        assert result["robot_id"] == "robot_001"
        assert result["type"] == "cmd_ack"

    def test_parse_robot_event(self):
        result = parse_robot_topic("robot/robot_001/event")
        assert result is not None
        assert result["type"] == "event"

    def test_parse_robot_sensor(self):
        result = parse_robot_topic("robot/robot_001/sensor/camera")
        assert result is not None
        assert result["type"] == "sensor"
        assert result["name"] == "camera"

    def test_parse_robot_sensor_with_path(self):
        """嵌套传感器路径"""
        result = parse_robot_topic("robot/r1/sensor/camera/image/compressed")
        assert result is not None
        assert result["type"] == "sensor"
        assert result["name"] == "camera/image/compressed"

    def test_parse_robot_sensor_meta_with_path(self):
        """嵌套传感器路径的 meta 后缀"""
        result = parse_robot_topic("robot/r1/sensor/camera/image/compressed/meta")
        assert result is not None
        assert result["type"] == "sensor_meta"
        assert result["name"] == "camera/image/compressed"

    def test_parse_robot_sensor_meta(self):
        result = parse_robot_topic("robot/robot_001/sensor/lidar/meta")
        assert result is not None
        assert result["type"] == "sensor_meta"
        assert result["name"] == "lidar"

    def test_parse_robot_invalid_short(self):
        """过短的 topic 应返回 None"""
        assert parse_robot_topic("robot") is None
        assert parse_robot_topic("robot/") is None
        assert parse_robot_topic("robot/robot_001") is None

    def test_parse_robot_wrong_prefix(self):
        """非 robot 前缀应返回 None"""
        assert parse_robot_topic("station/discover") is None

    def test_parse_robot_unknown_type(self):
        """未知类型应返回 None"""
        assert parse_robot_topic("robot/r1/unknown") is None
        assert parse_robot_topic("robot/r1/unknown/stuff") is None

    def test_parse_robot_sensor_no_name(self):
        """sensor 后无名称应返回 None"""
        assert parse_robot_topic("robot/r1/sensor") is None

    def test_parse_robot_sensor_meta_no_name(self):
        """确保 sensor/{name}/meta 结构正确"""
        # sensor/meta 缺少 name 应该返回 None（len(parts)==4, parts[3]=meta, 不满足 _META 匹配）
        result = parse_robot_topic("robot/r1/sensor/meta")
        assert result is not None
        # 这里 "meta" 被当作 sensor name，而不是 _META 后缀
        assert result["type"] == "sensor"
        assert result["name"] == "meta"

    # ---- 机器人间通信 parse ----

    def test_parse_robot_to_robot(self):
        """解析 robot/{src}/to/{dst}"""
        result = parse_robot_topic("robot/robot_001/to/robot_002")
        assert result is not None
        assert result["type"] == "to_robot"
        assert result["dst_id"] == "robot_002"

    def test_parse_robot_to_robot_meta(self):
        """解析 robot/{src}/to/{dst}/meta"""
        result = parse_robot_topic("robot/robot_001/to/robot_002/meta")
        assert result is not None
        assert result["type"] == "to_robot_meta"
        assert result["dst_id"] == "robot_002"

    def test_parse_robot_to_robot_no_dst(self):
        """robot/+/to 缺少 dst_id 应返回 None"""
        assert parse_robot_topic("robot/r1/to") is None

    # --- station topic 解析 ---

    def test_parse_station_discover(self):
        result = parse_station_topic("station/discover")
        assert result is not None
        assert result["type"] == "discover"

    def test_parse_station_topic_request(self):
        result = parse_station_topic("station/topic/request")
        assert result is not None
        assert result["type"] == "topic_request"

    def test_parse_station_topic_response(self):
        result = parse_station_topic("station/topic/response")
        assert result is not None
        assert result["type"] == "topic_response"

    def test_parse_station_topic_response_with_robot_id(self):
        result = parse_station_topic("station/topic/response/robot_001")
        assert result is not None
        assert result["type"] == "topic_response"
        assert result["robot_id"] == "robot_001"

    def test_parse_station_wrong_prefix(self):
        assert parse_station_topic("robot/robot_001/status") is None

    def test_parse_station_unknown(self):
        assert parse_station_topic("station/unknown") is None
        assert parse_station_topic("station/topic/unknown") is None

    def test_parse_station_short(self):
        assert parse_station_topic("station") is None

    # --- 通配符解析 ---

    def test_parse_wildcard_status(self):
        """通配符 topic 解析，+ 被当作普通 robot_id（解析器不校验 ID 格式）"""
        result = parse_robot_topic("robot/+/status")
        assert result is not None
        assert result["robot_id"] == "+"
        assert result["type"] == "status"


class TestQoS:
    """QoS 策略测试"""

    def test_qos_values(self):
        assert QoS.AT_MOST_ONCE == 0
        assert QoS.AT_LEAST_ONCE == 1
        assert QoS.EXACTLY_ONCE == 2

    def test_topic_qos_has_all_keys(self):
        """确保所有 topic 类型都有 QoS 配置"""
        expected_keys = {
            "status", "sensor", "sensor_meta", "cmd",
            "cmd_ack", "event", "discover", "topic_request",
            "topic_response", "to_robot", "to_robot_meta",
            "config_sync", "config_query", "config_response",
            "message_schema_query", "message_schema_response",
        }
        assert set(TOPIC_QOS.keys()) == expected_keys

    def test_sensor_qos_at_most_once(self):
        """传感器数据使用 QoS 0"""
        assert TOPIC_QOS["sensor"] == QoS.AT_MOST_ONCE

    def test_command_qos_at_least_once(self):
        """控制指令使用 QoS 1"""
        assert TOPIC_QOS["cmd"] == QoS.AT_LEAST_ONCE
        assert TOPIC_QOS["cmd_ack"] == QoS.AT_LEAST_ONCE
