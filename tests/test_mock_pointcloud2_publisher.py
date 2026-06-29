from __future__ import annotations

from agent import mock_pointcloud2_publisher


class FakeHeader:
    def __init__(self) -> None:
        self.stamp = None
        self.frame_id = ""


class FakeRate:
    def __init__(self, hz: float) -> None:
        self.hz = hz
        self.sleep_count = 0

    def sleep(self) -> None:
        self.sleep_count += 1


class FakePublisher:
    def __init__(self) -> None:
        self.messages = []

    def publish(self, msg) -> None:
        self.messages.append(msg)


class FakeRospy:
    def __init__(self) -> None:
        self.node_name = ""
        self.publisher = FakePublisher()
        self.rate = None
        self.shutdown_checks = 0

    def init_node(self, name: str) -> None:
        self.node_name = name

    def Publisher(self, topic, msg_type, queue_size=1):
        self.topic = topic
        self.msg_type = msg_type
        self.queue_size = queue_size
        return self.publisher

    def Rate(self, hz):
        self.rate = FakeRate(hz)
        return self.rate

    def is_shutdown(self):
        self.shutdown_checks += 1
        return self.shutdown_checks > 1

    class Time:
        @staticmethod
        def now():
            return "now"


class FakePointCloud2:
    pass


class FakePointCloud2Module:
    def __init__(self) -> None:
        self.calls = []

    def create_cloud_xyz32(self, header, points):
        self.calls.append((header, points))
        return {"header": header, "points": points}


def test_parse_args_defaults_to_velodyne_points():
    args = mock_pointcloud2_publisher.parse_args([])

    assert args.topic == "/velodyne_points"
    assert args.frame_id == "velodyne"
    assert args.rate == 2.0


def test_build_points_reuses_mock_pointcloud2_data():
    points = mock_pointcloud2_publisher.build_points()

    assert len(points) > 100
    assert points[0] == (-2.5, -2.5, 0.0)
    assert all(len(point) == 3 for point in points)


def test_publish_mock_pointcloud2_publishes_ros_message_once():
    rospy = FakeRospy()
    point_cloud2 = FakePointCloud2Module()

    mock_pointcloud2_publisher.publish_mock_pointcloud2(
        rospy_module=rospy,
        point_cloud2_module=point_cloud2,
        pointcloud2_type=FakePointCloud2,
        header_type=FakeHeader,
        topic="/mock_points",
        frame_id="mock_frame",
        rate_hz=5.0,
    )

    assert rospy.node_name == "mock_pointcloud2_publisher"
    assert rospy.topic == "/mock_points"
    assert rospy.msg_type is FakePointCloud2
    assert rospy.queue_size == 1
    assert rospy.rate.hz == 5.0
    assert len(rospy.publisher.messages) == 1
    published = rospy.publisher.messages[0]
    assert published["header"].stamp == "now"
    assert published["header"].frame_id == "mock_frame"
    assert point_cloud2.calls[0][1] == mock_pointcloud2_publisher.build_points()
