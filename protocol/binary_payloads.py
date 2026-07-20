"""Binary payload helpers for MQTT sensor transport."""

from __future__ import annotations

import struct
import zlib
from typing import Any, Dict, List, Tuple

ENCODING_LASER_SCAN = "laser_scan_v1"
ENCODING_OCCUPANCY_GRID = "occupancy_grid_v1"
ENCODING_ROS1_SERIALIZED = "ros1_serialized_v1"
ENCODING_TF_MESSAGE = ENCODING_ROS1_SERIALIZED

_LASER_SCAN_TYPE = "sensor_msgs/LaserScan"
_OCCUPANCY_GRID_TYPE = "nav_msgs/OccupancyGrid"
_ROS1_SERIALIZED_TOPIC_TYPES = {
    ("/tf", "tf2_msgs/TFMessage"),
    ("/tf_static", "tf2_msgs/TFMessage"),
    ("/odom", "nav_msgs/Odometry"),
    ("/imu", "sensor_msgs/Imu"),
}
_ROS1_SERIALIZED_MESSAGE_TYPES = {
    "sensor_msgs/CompressedImage",
}
_ROS_MESSAGE_BINARY_ENCODINGS = frozenset({ENCODING_ROS1_SERIALIZED})

# Agent 间二进制主体使用固定 13 字节头，跨平台按网络字节序解析。
_FLEET_BINARY_MAGIC = b"FRB1"
_FLEET_BINARY_VERSION = 1
_FLEET_BINARY_HEADER = struct.Struct(">4sBQ")


def encode_fleet_binary_payload(transfer_id: int, body: bytes) -> bytes:
    """为 ROS1 serialized body 添加可乱序配对的固定关联头。"""
    # bool 是 int 的子类，但不允许作为协议中的 uint64 标识。
    if isinstance(transfer_id, bool) or not isinstance(transfer_id, int):
        raise ValueError("transfer_id must be an integer")
    if not 0 <= transfer_id < (1 << 64):
        raise ValueError("transfer_id out of uint64 range")
    if not isinstance(body, bytes):
        raise TypeError("fleet binary body must be bytes")
    return _FLEET_BINARY_HEADER.pack(
        _FLEET_BINARY_MAGIC,
        _FLEET_BINARY_VERSION,
        transfer_id,
    ) + body


def decode_fleet_binary_payload(payload: bytes) -> Tuple[int, bytes]:
    """校验关联头并返回 transfer ID 与未改动的 ROS1 body。"""
    if len(payload) < _FLEET_BINARY_HEADER.size:
        raise ValueError("fleet binary payload is truncated")
    magic, version, transfer_id = _FLEET_BINARY_HEADER.unpack_from(payload)
    if magic != _FLEET_BINARY_MAGIC:
        raise ValueError("invalid fleet binary magic")
    if version != _FLEET_BINARY_VERSION:
        raise ValueError("unsupported fleet binary version")
    return transfer_id, payload[_FLEET_BINARY_HEADER.size:]


def is_binary_supported(msg_type: str) -> bool:
    return msg_type in {_LASER_SCAN_TYPE, _OCCUPANCY_GRID_TYPE}


def is_ros_message_binary_supported(topic: str, msg_type: str) -> bool:
    if (topic, msg_type) in _ROS1_SERIALIZED_TOPIC_TYPES:
        return True
    if msg_type in _ROS1_SERIALIZED_MESSAGE_TYPES:
        return True
    # 合法 ROS 消息类型默认允许 serialized，实际导入和序列化由运行时验证。
    return "/" in msg_type and len(msg_type) > 3


def is_ros_message_binary_encoding(envelope: Dict[str, Any]) -> bool:
    return envelope.get("encoding") in _ROS_MESSAGE_BINARY_ENCODINGS


def encode_ros_message_binary(
    topic: str,
    msg_type: str,
    payload: bytes,
    seq: int,
) -> Tuple[Dict[str, Any], bytes]:
    envelope = {
        "binary": True,
        "topic": topic,
        "msg_type": msg_type,
        "encoding": ENCODING_ROS1_SERIALIZED,
        "seq": int(seq),
        "payload_format": "ros1_serialized",
        "payload_size": len(payload),
        "compression": "none",
    }
    return envelope, payload


def encode_sensor_binary(
    topic: str,
    msg_type: str,
    data: Dict[str, Any],
    seq: int,
) -> Tuple[Dict[str, Any], bytes]:
    if msg_type == _LASER_SCAN_TYPE:
        return _encode_laser_scan(topic, msg_type, data, seq)
    if msg_type == _OCCUPANCY_GRID_TYPE:
        return _encode_occupancy_grid(topic, msg_type, data, seq)
    raise ValueError("Unsupported binary sensor type: %s" % msg_type)


def decode_sensor_binary(
    envelope: Dict[str, Any],
    payload: bytes,
) -> Dict[str, Any]:
    encoding = envelope.get("encoding")
    if encoding == ENCODING_LASER_SCAN:
        return _decode_laser_scan(envelope, payload)
    if encoding == ENCODING_OCCUPANCY_GRID:
        return _decode_occupancy_grid(envelope, payload)
    raise ValueError("Unsupported binary sensor encoding: %s" % encoding)


def _encode_laser_scan(
    topic: str,
    msg_type: str,
    data: Dict[str, Any],
    seq: int,
) -> Tuple[Dict[str, Any], bytes]:
    ranges = _float_list(data.get("ranges", []))
    intensities = _float_list(data.get("intensities", []))
    values = ranges + intensities
    payload = struct.pack("<%sf" % len(values), *values) if values else b""
    envelope = {
        "binary": True,
        "topic": topic,
        "msg_type": msg_type,
        "encoding": ENCODING_LASER_SCAN,
        "seq": int(seq),
        "payload_format": "float32_le",
        "payload_size": len(payload),
        "compression": "none",
        "meta": {
            "header": data.get("header", {}),
            "angle_min": data.get("angle_min", 0.0),
            "angle_max": data.get("angle_max", 0.0),
            "angle_increment": data.get("angle_increment", 0.0),
            "time_increment": data.get("time_increment", 0.0),
            "scan_time": data.get("scan_time", 0.0),
            "range_min": data.get("range_min", 0.0),
            "range_max": data.get("range_max", 0.0),
            "ranges_len": len(ranges),
            "intensities_len": len(intensities),
        },
    }
    return envelope, payload


def _decode_laser_scan(
    envelope: Dict[str, Any],
    payload: bytes,
) -> Dict[str, Any]:
    meta = dict(envelope.get("meta") or {})
    ranges_len = int(meta.get("ranges_len", 0))
    intensities_len = int(meta.get("intensities_len", 0))
    count = ranges_len + intensities_len
    expected_size = count * 4
    if len(payload) != expected_size:
        raise ValueError(
            "LaserScan payload size mismatch: expected %d, got %d"
            % (expected_size, len(payload))
        )
    values = list(struct.unpack("<%sf" % count, payload)) if count else []
    return {
        "header": meta.get("header", {}),
        "angle_min": meta.get("angle_min", 0.0),
        "angle_max": meta.get("angle_max", 0.0),
        "angle_increment": meta.get("angle_increment", 0.0),
        "time_increment": meta.get("time_increment", 0.0),
        "scan_time": meta.get("scan_time", 0.0),
        "range_min": meta.get("range_min", 0.0),
        "range_max": meta.get("range_max", 0.0),
        "ranges": values[:ranges_len],
        "intensities": values[ranges_len:],
        "_msg_type": envelope.get("msg_type", _LASER_SCAN_TYPE),
    }


def _encode_occupancy_grid(
    topic: str,
    msg_type: str,
    data: Dict[str, Any],
    seq: int,
) -> Tuple[Dict[str, Any], bytes]:
    cells = [int(value) for value in data.get("data", [])]
    raw_payload = struct.pack("<%sb" % len(cells), *cells) if cells else b""
    payload = zlib.compress(raw_payload)
    envelope = {
        "binary": True,
        "topic": topic,
        "msg_type": msg_type,
        "encoding": ENCODING_OCCUPANCY_GRID,
        "seq": int(seq),
        "payload_format": "int8",
        "payload_size": len(payload),
        "raw_payload_size": len(raw_payload),
        "compression": "zlib",
        "meta": {
            "header": data.get("header", {}),
            "info": data.get("info", {}),
            "data_len": len(cells),
        },
    }
    return envelope, payload


def _decode_occupancy_grid(
    envelope: Dict[str, Any],
    payload: bytes,
) -> Dict[str, Any]:
    meta = dict(envelope.get("meta") or {})
    data_len = int(meta.get("data_len", 0))
    if envelope.get("compression") == "zlib":
        raw_payload = zlib.decompress(payload)
    else:
        raw_payload = payload
    expected_size = data_len
    if len(raw_payload) != expected_size:
        raise ValueError(
            "OccupancyGrid payload size mismatch: expected %d, got %d"
            % (expected_size, len(raw_payload))
        )
    cells = list(struct.unpack("<%sb" % data_len, raw_payload)) if data_len else []
    return {
        "header": meta.get("header", {}),
        "info": meta.get("info", {}),
        "data": cells,
        "_msg_type": envelope.get("msg_type", _OCCUPANCY_GRID_TYPE),
    }


def _float_list(values: Any) -> List[float]:
    if not isinstance(values, list):
        return []
    return [float(value) for value in values]
