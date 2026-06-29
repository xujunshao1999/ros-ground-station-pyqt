from __future__ import annotations

import argparse
from typing import List, Sequence

from agent.mock_pointcloud2_data import PointXYZ, generate_xyz_points


def build_points() -> List[PointXYZ]:
    return generate_xyz_points()


def parse_args(argv: Sequence[str] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish deterministic mock sensor_msgs/PointCloud2 data.",
    )
    parser.add_argument(
        "--topic",
        default="/velodyne_points",
        help="ROS topic to publish. Defaults to /velodyne_points.",
    )
    parser.add_argument(
        "--frame-id",
        default="velodyne",
        help="PointCloud2 header frame_id. Defaults to velodyne.",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=2.0,
        help="Publish rate in Hz. Defaults to 2.0.",
    )
    return parser.parse_args(argv)


def publish_mock_pointcloud2(
    rospy_module,
    point_cloud2_module,
    pointcloud2_type,
    header_type,
    topic: str,
    frame_id: str,
    rate_hz: float,
) -> None:
    rospy_module.init_node("mock_pointcloud2_publisher")
    pub = rospy_module.Publisher(topic, pointcloud2_type, queue_size=1)
    rate = rospy_module.Rate(rate_hz)
    points = build_points()

    while not rospy_module.is_shutdown():
        header = header_type()
        header.stamp = rospy_module.Time.now()
        header.frame_id = frame_id
        pub.publish(point_cloud2_module.create_cloud_xyz32(header, points))
        rate.sleep()


def main(argv: Sequence[str] = None) -> None:
    args = parse_args(argv)

    import rospy
    from sensor_msgs import point_cloud2
    from sensor_msgs.msg import PointCloud2
    from std_msgs.msg import Header

    publish_mock_pointcloud2(
        rospy_module=rospy,
        point_cloud2_module=point_cloud2,
        pointcloud2_type=PointCloud2,
        header_type=Header,
        topic=args.topic,
        frame_id=args.frame_id,
        rate_hz=args.rate,
    )


if __name__ == "__main__":
    main()
