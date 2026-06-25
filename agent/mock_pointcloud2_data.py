from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

PointXYZ = Tuple[float, float, float]


@dataclass
class FakeStamp:
    secs: int = 0
    nsecs: int = 0


@dataclass
class FakeHeader:
    seq: int = 0
    stamp: FakeStamp = field(default_factory=FakeStamp)
    frame_id: str = "velodyne"


class FakePointCloud2Message:
    """Small ROS-like PointCloud2 fake used by non-ROS unit tests."""

    def __init__(self) -> None:
        self.header = FakeHeader()
        self.height = 1
        self.width = 0
        self.fields: List[Dict[str, object]] = []
        self.is_bigendian = False
        self.point_step = 12
        self.row_step = 0
        self.data = b""
        self.is_dense = True

    @classmethod
    def from_dict(cls, data: dict) -> "FakePointCloud2Message":
        msg = cls()
        header = data.get("header", {})
        stamp = header.get("stamp", {})
        msg.header = FakeHeader(
            seq=int(header.get("seq", 0)),
            stamp=FakeStamp(
                secs=int(stamp.get("secs", 0)),
                nsecs=int(stamp.get("nsecs", 0)),
            ),
            frame_id=str(header.get("frame_id", "velodyne")),
        )
        msg.height = int(data.get("height", 1))
        msg.width = int(data.get("width", 0))
        msg.fields = list(data.get("fields", []))
        msg.is_bigendian = bool(data.get("is_bigendian", False))
        msg.point_step = int(data.get("point_step", 12))
        msg.row_step = int(data.get("row_step", msg.width * msg.point_step))
        msg.data = bytes(data.get("data", b""))
        msg.is_dense = bool(data.get("is_dense", True))
        return msg

    def serialize(self, buff) -> None:
        buff.write(self.data)

    def deserialize(self, payload: bytes) -> None:
        self.data = payload


def generate_xyz_points() -> List[PointXYZ]:
    points: List[PointXYZ] = []
    for xi in range(20):
        x = -2.5 + xi * (5.0 / 19.0)
        for yi in range(20):
            y = -2.5 + yi * (5.0 / 19.0)
            points.append((round(x, 4), round(y, 4), 0.0))

    for zi in range(20):
        z = zi * (1.5 / 19.0)
        points.append((1.0, 0.5, round(z, 4)))

    return points


def pack_xyz_points(points: List[PointXYZ]) -> bytes:
    payload = bytearray()
    for x, y, z in points:
        payload.extend(struct.pack("<fff", x, y, z))
    return bytes(payload)


def build_pointcloud2_dict(
    frame_id: str = "velodyne",
    seq: int = 0,
    stamp: Optional[Dict[str, int]] = None,
) -> dict:
    points = generate_xyz_points()
    data = pack_xyz_points(points)
    stamp_data = stamp or {"secs": 0, "nsecs": 0}
    return {
        "_msg_type": "sensor_msgs/PointCloud2",
        "header": {
            "seq": int(seq),
            "stamp": stamp_data,
            "frame_id": frame_id,
        },
        "height": 1,
        "width": len(points),
        "fields": [
            {"name": "x", "offset": 0, "datatype": 7, "count": 1},
            {"name": "y", "offset": 4, "datatype": 7, "count": 1},
            {"name": "z", "offset": 8, "datatype": 7, "count": 1},
        ],
        "is_bigendian": False,
        "point_step": 12,
        "row_step": len(data),
        "data": data,
        "is_dense": True,
    }


def serialize_fake_pointcloud2(msg: FakePointCloud2Message) -> bytes:
    return bytes(msg.data)
