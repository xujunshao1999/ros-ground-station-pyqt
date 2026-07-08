from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: str) -> Dict[str, Any]:
    with (ROOT / path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    assert isinstance(data, dict)
    return data


def test_husky_agent_config_defaults_to_heavy_snapshot_topics() -> None:
    config = _load_yaml("agent/configs/husky_001.yaml")

    assert config["robot_id"] == "husky_001"
    assert config["http_stream_port"] == 8080
    assert config["stream_base_url"] == "http://localhost:18080"

    subscriptions = {
        item["topic"]: item for item in config["subscriptions"]
    }
    assert subscriptions["/velodyne_points"]["transport"] == "http_stream"
    assert subscriptions["/realsense/color/image_raw/compressed"] == {
        "topic": "/realsense/color/image_raw/compressed",
        "msg_type": "sensor_msgs/CompressedImage",
        "freq_limit": 5.0,
        "transport": "mqtt_binary",
        "qos": 0,
        "compression": {},
    }
    assert subscriptions["/hdl_graph_slam/map_points"]["transport"] == "http_stream"
    assert subscriptions["/hdl_graph_slam/odom"]["transport"] == "mqtt_binary"
    assert subscriptions["/tf_static"]["qos"] == 1


def test_husky_joint_states_uses_binary_transport() -> None:
    """Husky 关节状态是常规 ROS 话题，默认应使用 ROS1 serialized 二进制传输。"""
    config = _load_yaml("agent/configs/husky_001.yaml")
    subscriptions = {
        item["topic"]: item for item in config["subscriptions"]
    }

    assert subscriptions["/joint_states"]["transport"] == "mqtt_binary"


def test_husky_compose_service_uses_catkin_sim_context_and_publishes_stream_port() -> None:
    compose = _load_yaml("docker-compose.yml")

    service = compose["services"]["robot-husky-001"]
    assert service["build"]["context"] == "/home/lab118/claudeCode_Project/catkin_sim"
    assert service["build"]["dockerfile"].endswith(
        "/ros-ground-station-pyqt/docker/Dockerfile.husky"
    )
    assert service["container_name"] == "husky-001"
    assert "18080:8080" in service["ports"]
    assert (
        "./docker/supervisord-husky.conf:/etc/supervisor/conf.d/ros-agent.conf:ro"
        in service["volumes"]
    )
    assert "DISPLAY=${DISPLAY}" not in service.get("environment", [])
    assert "/tmp/.X11-unix:/tmp/.X11-unix:rw" not in service["volumes"]


def test_husky_dockerfile_builds_catkin_workspace_from_context_src() -> None:
    dockerfile = (ROOT / "docker/Dockerfile.husky").read_text(encoding="utf-8")

    assert "FROM ros:noetic" in dockerfile
    assert "COPY src/ ${CATKIN_WS}/src/" in dockerfile
    assert "PYTHONNOUSERSITE=1 catkin_make -j2 -l2" in dockerfile
    assert "ros-noetic-realsense2-description" in dockerfile
    assert "ros-noetic-compressed-image-transport" in dockerfile
    assert "libsuitesparse-dev" in dockerfile
    assert "xvfb" in dockerfile


def test_husky_supervisor_launches_slam_compressed_image_and_agent() -> None:
    config = (ROOT / "docker/supervisord-husky.conf").read_text(encoding="utf-8")

    assert "[program:roscore]" in config
    assert "[program:husky_slam]" in config
    assert "[program:realsense_color_compressed]" in config
    assert "[program:agent]" in config
    assert "source /opt/catkin_sim/devel/setup.bash" in config
    assert "xvfb-run -a" in config
    assert "husky_hdl_graph_slam.launch gui:=false headless:=true" in config
    assert "rosrun image_transport republish raw" in config
    assert "in:=/realsense/color/image_raw" in config
    assert "compressed out:=/realsense/color/image_raw" in config
    assert "--config /app/agent/configs/%(ENV_ROBOT_ID)s.yaml" in config
