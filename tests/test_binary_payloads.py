from __future__ import annotations

import pytest

from protocol.binary_payloads import (
    ENCODING_TF_MESSAGE,
    decode_sensor_binary,
    encode_ros_message_binary,
    encode_sensor_binary,
    is_binary_supported,
    is_ros_message_binary_encoding,
    is_ros_message_binary_supported,
)


def test_laser_scan_binary_roundtrip():
    source = {
        "header": {
            "seq": 7,
            "stamp": {"secs": 1, "nsecs": 2},
            "frame_id": "base_scan",
        },
        "angle_min": 0.0,
        "angle_max": 1.0,
        "angle_increment": 0.5,
        "time_increment": 0.0,
        "scan_time": 0.1,
        "range_min": 0.12,
        "range_max": 3.5,
        "ranges": [1.0, 2.0],
        "intensities": [0.5, 0.25],
        "_msg_type": "sensor_msgs/LaserScan",
    }

    envelope, payload = encode_sensor_binary(
        "/scan",
        "sensor_msgs/LaserScan",
        source,
        seq=3,
    )

    assert envelope["encoding"] == "laser_scan_v1"
    assert envelope["payload_size"] == len(payload)
    assert envelope["payload_format"] == "float32_le"
    assert envelope["compression"] == "none"

    restored = decode_sensor_binary(envelope, payload)

    assert restored["header"] == source["header"]
    assert restored["angle_min"] == pytest.approx(0.0)
    assert restored["angle_max"] == pytest.approx(1.0)
    assert restored["ranges"] == pytest.approx([1.0, 2.0])
    assert restored["intensities"] == pytest.approx([0.5, 0.25])
    assert restored["_msg_type"] == "sensor_msgs/LaserScan"


def test_occupancy_grid_binary_roundtrip_uses_zlib_int8_payload():
    source = {
        "header": {
            "seq": 4,
            "stamp": {"secs": 5, "nsecs": 6},
            "frame_id": "map",
        },
        "info": {
            "map_load_time": {"secs": 0, "nsecs": 0},
            "resolution": 0.05,
            "width": 4,
            "height": 2,
            "origin": {
                "position": {"x": -1.0, "y": -2.0, "z": 0.0},
                "orientation": {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0},
            },
        },
        "data": [-1, 0, 100, 42, -1, -1, 0, 100],
        "_msg_type": "nav_msgs/OccupancyGrid",
    }

    envelope, payload = encode_sensor_binary(
        "/map",
        "nav_msgs/OccupancyGrid",
        source,
        seq=8,
    )

    assert envelope["encoding"] == "occupancy_grid_v1"
    assert envelope["payload_format"] == "int8"
    assert envelope["compression"] == "zlib"
    assert envelope["meta"]["data_len"] == 8

    restored = decode_sensor_binary(envelope, payload)

    assert restored["header"] == source["header"]
    assert restored["info"] == source["info"]
    assert restored["data"] == source["data"]
    assert restored["_msg_type"] == "nav_msgs/OccupancyGrid"


def test_is_binary_supported_only_for_first_phase_types():
    assert is_binary_supported("sensor_msgs/LaserScan") is True
    assert is_binary_supported("nav_msgs/OccupancyGrid") is True
    assert is_binary_supported("tf2_msgs/TFMessage") is False
    assert is_binary_supported("nav_msgs/Odometry") is False


def test_tf_message_binary_envelope_keeps_ros_payload_opaque():
    envelope, payload = encode_ros_message_binary(
        "/tf",
        "tf2_msgs/TFMessage",
        b"\x01\x02tf-bytes",
        seq=42,
    )

    assert envelope == {
        "binary": True,
        "topic": "/tf",
        "msg_type": "tf2_msgs/TFMessage",
        "encoding": ENCODING_TF_MESSAGE,
        "seq": 42,
        "payload_format": "ros1_serialized",
        "payload_size": len(payload),
        "compression": "none",
    }
    assert payload == b"\x01\x02tf-bytes"
    assert is_ros_message_binary_encoding(envelope) is True


def test_ros1_serialized_envelope_is_not_tf_specific():
    envelope, payload = encode_ros_message_binary(
        "/odom",
        "nav_msgs/Odometry",
        b"serialized-odom",
        seq=12,
    )

    assert envelope["encoding"] == "ros1_serialized_v1"
    assert envelope["payload_format"] == "ros1_serialized"
    assert envelope["msg_type"] == "nav_msgs/Odometry"
    assert envelope["topic"] == "/odom"
    assert envelope["payload_size"] == len(payload)
    assert payload == b"serialized-odom"
    assert is_ros_message_binary_encoding(envelope) is True


def test_ros1_serialized_supports_regular_ros_message_types_by_default():
    """专用二进制编码仍存在，但 ROS1 serialized 默认覆盖普通 ROS 类型。"""
    assert is_ros_message_binary_supported("/tf", "tf2_msgs/TFMessage") is True
    assert is_ros_message_binary_supported("/tf_static", "tf2_msgs/TFMessage") is True
    assert is_ros_message_binary_supported("/odom", "nav_msgs/Odometry") is True
    assert is_ros_message_binary_supported("/imu", "sensor_msgs/Imu") is True
    assert is_ros_message_binary_supported(
        "/realsense/color/image_raw/compressed",
        "sensor_msgs/CompressedImage",
    ) is True
    assert is_binary_supported("sensor_msgs/LaserScan") is True
    assert is_binary_supported("nav_msgs/OccupancyGrid") is True
    assert is_ros_message_binary_supported("/scan", "sensor_msgs/LaserScan") is True
    assert is_ros_message_binary_supported("/map", "nav_msgs/OccupancyGrid") is True


def test_ros1_serialized_supports_unknown_ros_messages_by_default():
    """未知 ROS 消息类型默认允许走 ROS1 serialized，由运行时导入消息类。"""
    assert is_ros_message_binary_supported(
        "/custom_topic",
        "custom_msgs/Thing",
    ) is True
