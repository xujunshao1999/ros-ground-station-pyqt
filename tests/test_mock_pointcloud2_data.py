from __future__ import annotations

import struct

from agent.mock_pointcloud2_data import (
    FakePointCloud2Message,
    build_pointcloud2_dict,
    generate_xyz_points,
    serialize_fake_pointcloud2,
)


def test_generate_xyz_points_is_deterministic():
    points = generate_xyz_points()

    assert len(points) > 100
    assert points[0] == (-2.5, -2.5, 0.0)
    assert all(len(point) == 3 for point in points)


def test_build_pointcloud2_dict_contains_standard_fields():
    data = build_pointcloud2_dict(frame_id="velodyne", seq=7)

    assert data["_msg_type"] == "sensor_msgs/PointCloud2"
    assert data["header"]["seq"] == 7
    assert data["header"]["frame_id"] == "velodyne"
    assert data["height"] == 1
    assert data["width"] == len(generate_xyz_points())
    assert data["point_step"] == 12
    assert data["row_step"] == data["width"] * data["point_step"]
    assert [field["name"] for field in data["fields"]] == ["x", "y", "z"]
    assert len(data["data"]) == data["row_step"]


def test_fake_pointcloud2_message_serializes_payload():
    data = build_pointcloud2_dict(frame_id="velodyne", seq=3)
    msg = FakePointCloud2Message.from_dict(data)
    payload = serialize_fake_pointcloud2(msg)

    assert msg.header.frame_id == "velodyne"
    assert msg.header.seq == 3
    assert payload == bytes(data["data"])
    first_x, first_y, first_z = struct.unpack("<fff", payload[:12])
    assert first_x == -2.5
    assert first_y == -2.5
    assert first_z == 0.0
