from __future__ import annotations

"""
MQTT Topic 规范 - 定义所有 MQTT topic 的命名规则和生成函数

Topic 层级结构:
  robot/{id}/status              - 心跳 + 状态上报
  robot/{id}/sensor/{name}       - 传感器数据（按需订阅）
  robot/{id}/sensor/{name}/meta  - 重量话题元信息
  robot/{id}/cmd                 - 控制指令
  robot/{id}/cmd/ack             - 指令确认
  robot/{id}/event               - 告警/异常事件
  station/discover               - 发现请求
  station/topic/request          - 请求订阅/取消 topic
  station/topic/response         - 订阅请求确认
"""

from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Topic 前缀常量
# ---------------------------------------------------------------------------
ROBOT_PREFIX = "robot"
STATION_PREFIX = "station"

# Topic 后缀
_STATUS = "status"
_SENSOR = "sensor"
_META = "meta"
_CMD = "cmd"
_CMD_ACK = "cmd/ack"
_EVENT = "event"
_DISCOVER = "discover"
_TOPIC_REQUEST = "topic/request"
_TOPIC_RESPONSE = "topic/response"
_TO = "to"


# ---------------------------------------------------------------------------
# QoS 策略
# ---------------------------------------------------------------------------
class QoS:
    """MQTT QoS 等级定义"""
    AT_MOST_ONCE = 0    # 最多一次（适合高频传感器数据）
    AT_LEAST_ONCE = 1   # 至少一次（适合状态、指令）
    EXACTLY_ONCE = 2    # 恰好一次（一般不用，开销大）


# 各 topic 的默认 QoS
TOPIC_QOS = {
    "status": QoS.AT_LEAST_ONCE,
    "sensor": QoS.AT_MOST_ONCE,
    "sensor_meta": QoS.AT_LEAST_ONCE,
    "cmd": QoS.AT_LEAST_ONCE,
    "cmd_ack": QoS.AT_LEAST_ONCE,
    "event": QoS.AT_LEAST_ONCE,
    "discover": QoS.AT_LEAST_ONCE,
    "topic_request": QoS.AT_LEAST_ONCE,
    "topic_response": QoS.AT_LEAST_ONCE,
    "to_robot": QoS.AT_LEAST_ONCE,
    "to_robot_meta": QoS.AT_LEAST_ONCE,
    "config_sync": QoS.AT_LEAST_ONCE,
    "config_query": QoS.AT_LEAST_ONCE,
    "config_response": QoS.AT_LEAST_ONCE,
}


# ---------------------------------------------------------------------------
# Topic 生成函数
# ---------------------------------------------------------------------------
def robot_status(robot_id: str) -> str:
    """robot/{id}/status"""
    return f"{ROBOT_PREFIX}/{robot_id}/{_STATUS}"


def robot_sensor(robot_id: str, sensor_name: str) -> str:
    """robot/{id}/sensor/{name}"""
    return f"{ROBOT_PREFIX}/{robot_id}/{_SENSOR}/{sensor_name}"


def robot_sensor_meta(robot_id: str, sensor_name: str) -> str:
    """robot/{id}/sensor/{name}/meta"""
    return f"{ROBOT_PREFIX}/{robot_id}/{_SENSOR}/{sensor_name}/{_META}"


def robot_cmd(robot_id: str) -> str:
    """robot/{id}/cmd"""
    return f"{ROBOT_PREFIX}/{robot_id}/{_CMD}"


def robot_cmd_ack(robot_id: str) -> str:
    """robot/{id}/cmd/ack"""
    return f"{ROBOT_PREFIX}/{robot_id}/{_CMD_ACK}"


def robot_event(robot_id: str) -> str:
    """robot/{id}/event"""
    return f"{ROBOT_PREFIX}/{robot_id}/{_EVENT}"


def station_discover() -> str:
    """station/discover"""
    return f"{STATION_PREFIX}/{_DISCOVER}"


def station_topic_request() -> str:
    """station/topic/request"""
    return f"{STATION_PREFIX}/{_TOPIC_REQUEST}"


def station_topic_response(robot_id: str = "") -> str:
    """station/topic/response/{robot_id}"""
    if robot_id:
        return f"{STATION_PREFIX}/{_TOPIC_RESPONSE}/{robot_id}"
    return f"{STATION_PREFIX}/{_TOPIC_RESPONSE}"


def station_config_sync(robot_id: str) -> str:
    """station/{robot_id}/config/sync — 地面站下发配置到指定机器人"""
    return f"{STATION_PREFIX}/{robot_id}/config/sync"


def station_config_query(robot_id: str) -> str:
    """station/{robot_id}/config/query — 查询机器人当前配置"""
    return f"{STATION_PREFIX}/{robot_id}/config/query"


def station_config_response(robot_id: str) -> str:
    """station/{robot_id}/config/response — 机器人返回当前配置"""
    return f"{STATION_PREFIX}/{robot_id}/config/response"


# ---------------------------------------------------------------------------
# 机器人间通信 topic
# ---------------------------------------------------------------------------
def robot_to_robot(src_id: str, dst_id: str) -> str:
    """robot/{src}/to/{dst} — 机器人间数据传递"""
    return f"{ROBOT_PREFIX}/{src_id}/{_TO}/{dst_id}"


def robot_to_robot_meta(src_id: str, dst_id: str) -> str:
    """robot/{src}/to/{dst}/meta — 机器人间重量话题元信息"""
    return f"{ROBOT_PREFIX}/{src_id}/{_TO}/{dst_id}/{_META}"


# ---------------------------------------------------------------------------
# 订阅通配符 - 地面站用于订阅所有机器人
# ---------------------------------------------------------------------------
def all_robot_status() -> str:
    """robot/+/status - 订阅所有机器人的状态"""
    return f"{ROBOT_PREFIX}/+/{_STATUS}"


def all_robot_cmd_ack() -> str:
    """robot/+/cmd/ack - 订阅所有机器人的指令确认"""
    return f"{ROBOT_PREFIX}/+/{_CMD_ACK}"


def all_robot_event() -> str:
    """robot/+/event - 订阅所有机器人的事件"""
    return f"{ROBOT_PREFIX}/+/{_EVENT}"


def all_robot_sensor_meta() -> str:
    """robot/+/sensor/+/meta - 订阅所有机器人的传感器元信息"""
    return f"{ROBOT_PREFIX}/+/{_SENSOR}/+/{_META}"


def all_robot_to_robot(dst_id: str) -> str:
    """robot/+/to/{dst_id} - 订阅所有发往本机的机器人间数据"""
    return f"{ROBOT_PREFIX}/+/{_TO}/{dst_id}"


def all_robot_to_robot_meta(dst_id: str) -> str:
    """robot/+/to/{dst_id}/meta - 订阅所有发往本机的元信息"""
    return f"{ROBOT_PREFIX}/+/{_TO}/{dst_id}/{_META}"


# ---------------------------------------------------------------------------
# Topic 解析 - 从 MQTT topic 字符串中提取信息
# ---------------------------------------------------------------------------
def parse_robot_topic(topic: str) -> Optional[Dict[str, str]]:
    """
    解析 robot/ 开头的 topic，返回结构化信息

    示例:
      "robot/robot_001/status" → {"robot_id": "robot_001", "type": "status"}
      "robot/robot_001/sensor/camera" → {"robot_id": "robot_001", "type": "sensor", "name": "camera"}
      "robot/robot_001/cmd/ack" → {"robot_id": "robot_001", "type": "cmd_ack"}

    Returns:
        解析失败的返回 None
    """
    parts = topic.split("/")
    if len(parts) < 3 or parts[0] != ROBOT_PREFIX:
        return None

    result = {"robot_id": parts[1]}

    if parts[2] == _STATUS:
        result["type"] = "status"
    elif parts[2] == _CMD:
        if len(parts) > 3 and parts[3] == "ack":
            result["type"] = "cmd_ack"
        else:
            result["type"] = "cmd"
    elif parts[2] == _EVENT:
        result["type"] = "event"
    elif parts[2] == _SENSOR:
        if len(parts) > 3:
            result["type"] = "sensor"
            result["name"] = parts[3]
            if len(parts) > 4 and parts[4] == _META:
                result["type"] = "sensor_meta"
        else:
            return None
    elif parts[2] == _TO:
        # robot/{src}/to/{dst} 或 robot/{src}/to/{dst}/meta
        if len(parts) > 3:
            result["type"] = "to_robot"
            result["dst_id"] = parts[3]
            if len(parts) > 4 and parts[4] == _META:
                result["type"] = "to_robot_meta"
        else:
            return None
    else:
        return None

    return result


def parse_station_topic(topic: str) -> Optional[Dict[str, str]]:
    """
    解析 station/ 开头的 topic

    示例:
      "station/discover" → {"type": "discover"}
      "station/topic/request" → {"type": "topic_request"}
      "station/topic/response" → {"type": "topic_response"}
    """
    parts = topic.split("/")
    if len(parts) < 2 or parts[0] != STATION_PREFIX:
        return None

    if parts[1] == _DISCOVER:
        return {"type": "discover"}
    elif parts[1] == "topic":
        if len(parts) > 2 and parts[2] == "request":
            return {"type": "topic_request"}
        elif len(parts) > 2 and parts[2] == "response":
            return {"type": "topic_response"}
    elif len(parts) >= 4 and parts[2] == "config":
        if parts[3] == "sync":
            return {"type": "config_sync", "robot_id": parts[1]}
        elif parts[3] == "query":
            return {"type": "config_query", "robot_id": parts[1]}
        elif parts[3] == "response":
            return {"type": "config_response", "robot_id": parts[1]}

    return None
