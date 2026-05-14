from __future__ import annotations

import json
from typing import List, Tuple

from agent.base_agent import AgentConfig
from agent.mock_agent import MockAgent
from protocol.messages import Message, MessageType


class RecordingAgent(MockAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self.subscribed: List[Tuple[str, str, dict]] = []
        self.unsubscribed: List[str] = []
        self.saved_count = 0
        self.published = []

    def _on_topic_subscribed(self, topic: str, msg_type: str, options: dict) -> None:
        self.subscribed.append((topic, msg_type, dict(options)))

    def _on_topic_unsubscribed(self, topic: str) -> None:
        self.unsubscribed.append(topic)

    def _save_config(self) -> None:
        self.saved_count += 1

    def _mqtt_publish(self, topic: str, payload: bytes, qos: int = 1) -> None:
        self.published.append((topic, json.loads(payload.decode("utf-8")), qos))


def test_topic_request_subscribe_updates_runtime_and_persistent_config():
    agent = RecordingAgent(AgentConfig(robot_id="robot_001"))
    message = Message(
        src="station",
        dst="robot_001",
        type=MessageType.TOPIC_REQUEST,
        data={
            "action": "subscribe",
            "topic": "/scan",
            "msg_type": "sensor_msgs/LaserScan",
            "freq_limit": 5.0,
            "transport": "mqtt_json",
            "compression": {"quality": 80},
        },
    )

    agent._handle_topic_request(message)

    assert agent._subscribed_topics["/scan"]["msg_type"] == "sensor_msgs/LaserScan"
    assert agent.config.subscriptions == [
        {
            "topic": "/scan",
            "msg_type": "sensor_msgs/LaserScan",
            "freq_limit": 5.0,
            "transport": "mqtt_json",
            "compression": {"quality": 80},
        }
    ]
    assert agent.saved_count == 1
    assert agent.published[-1][1]["type"] == "topic_resp"
    assert agent.published[-1][1]["data"]["result"] == "ok"


def test_topic_request_unsubscribe_removes_runtime_and_persistent_config():
    agent = RecordingAgent(AgentConfig(
        robot_id="robot_001",
        subscriptions=[
            {
                "topic": "/scan",
                "msg_type": "sensor_msgs/LaserScan",
                "freq_limit": 5.0,
                "transport": "mqtt_json",
                "compression": {},
            }
        ],
    ))
    agent._subscribed_topics["/scan"] = {
        "msg_type": "sensor_msgs/LaserScan",
        "freq_limit": 5.0,
        "options": {},
    }

    agent._handle_topic_request(Message(
        src="station",
        dst="robot_001",
        type=MessageType.TOPIC_REQUEST,
        data={"action": "unsubscribe", "topic": "/scan"},
    ))

    assert "/scan" not in agent._subscribed_topics
    assert agent.config.subscriptions == []
    assert agent.unsubscribed == ["/scan"]
    assert agent.saved_count == 1


def test_config_sync_converges_added_updated_and_removed_subscriptions():
    agent = RecordingAgent(AgentConfig(
        robot_id="robot_001",
        subscriptions=[
            {
                "topic": "/scan",
                "msg_type": "sensor_msgs/LaserScan",
                "freq_limit": 5.0,
                "transport": "mqtt_json",
                "compression": {},
            },
            {
                "topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "compression": {},
            },
        ],
    ))
    agent._load_subscriptions_from_config()
    agent.subscribed.clear()

    agent._handle_config_sync(Message(
        src="station",
        dst="robot_001",
        type=MessageType.CONFIG_SYNC,
        data={
            "subscriptions": [
                {
                    "topic": "/scan",
                    "msg_type": "sensor_msgs/LaserScan",
                    "freq_limit": 2.0,
                    "transport": "mqtt_json",
                    "compression": {"quality": 70},
                },
                {
                    "topic": "/map",
                    "msg_type": "nav_msgs/OccupancyGrid",
                    "freq_limit": 1.0,
                    "transport": "mqtt_json",
                    "compression": {},
                },
            ],
            "fleet_rules": [{"name": "reserved"}],
        },
    ))

    assert set(agent._subscribed_topics.keys()) == {"/scan", "/map"}
    assert agent._subscribed_topics["/scan"]["freq_limit"] == 2.0
    assert agent._subscribed_topics["/scan"]["options"] == {"quality": 70}
    assert agent.unsubscribed == ["/odom", "/scan"]
    assert agent.subscribed == [
        ("/scan", "sensor_msgs/LaserScan", {"quality": 70}),
        ("/map", "nav_msgs/OccupancyGrid", {}),
    ]
    assert agent.config.fleet_rules == [{"name": "reserved"}]
    assert agent.saved_count == 1
    assert agent.published[-1][1]["type"] == "config_response"


def test_agent_config_tracks_source_path_for_save(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        "robot_id: robot_001\n"
        "subscriptions:\n"
        "  - topic: /scan\n"
        "    msg_type: sensor_msgs/LaserScan\n",
        encoding="utf-8",
    )

    config = AgentConfig.from_yaml(str(config_path))

    assert config.config_path == str(config_path)
