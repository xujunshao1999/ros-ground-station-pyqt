from __future__ import annotations

import pytest

from protocol.binary_payloads import (
    decode_sensor_binary,
    encode_sensor_binary,
    is_binary_supported,
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
    assert is_binary_supported("nav_msgs/Odometry") is False
