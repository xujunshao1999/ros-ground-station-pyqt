from __future__ import annotations

import json
from typing import List, Tuple

import yaml

from agent.base_agent import AgentConfig
from agent.mock_agent import MockAgent
from protocol.messages import Message, MessageType


class RecordingAgent(MockAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self.subscribed: List[Tuple[str, str, dict]] = []
        self.unsubscribed: List[str] = []
        self.applied_fleet_rules = []
        self.fleet_messages = []
        self.saved_count = 0
        self.published = []

    def _on_topic_subscribed(self, topic: str, msg_type: str, options: dict) -> None:
        self.subscribed.append((topic, msg_type, dict(options)))

    def _on_topic_unsubscribed(self, topic: str) -> None:
        self.unsubscribed.append(topic)

    def _apply_fleet_rules(self, fleet_rules: list) -> None:
        self.applied_fleet_rules.append(fleet_rules)

    def _on_fleet_message(self, src_id: str, data) -> None:
        self.fleet_messages.append((src_id, data))

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
            "qos": 2,
            "compression": {"quality": 80},
        },
    )

    agent._handle_topic_request(message)

    assert agent._subscribed_topics["/scan"]["msg_type"] == "sensor_msgs/LaserScan"
    assert agent._subscribed_topics["/scan"]["qos"] == 2
    assert agent.config.subscriptions == [
        {
            "topic": "/scan",
            "msg_type": "sensor_msgs/LaserScan",
            "freq_limit": 5.0,
            "transport": "mqtt_json",
            "qos": 2,
            "compression": {"quality": 80},
        }
    ]
    assert agent.saved_count == 1
    assert agent.published[-1][1]["type"] == "topic_resp"
    assert agent.published[-1][1]["data"]["result"] == "ok"


def test_publish_sensor_data_uses_subscription_qos():
    agent = RecordingAgent(AgentConfig(robot_id="robot_001"))
    agent._subscribed_topics["/scan"] = {
        "msg_type": "sensor_msgs/LaserScan",
        "freq_limit": 0.0,
        "qos": 2,
        "options": {},
    }

    agent.publish_sensor_data(
        "/scan",
        "sensor_msgs/LaserScan",
        {"ranges": [], "angle_min": 0.0, "angle_max": 0.0},
    )

    assert agent.published[-1][2] == 2


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
    agent.applied_fleet_rules.clear()

    fleet_rule = {
        "enabled": True,
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "targets": [
            {
                "robot_id": "robot_002",
                "dst_topic": "/fleet/robot_001/odom",
            }
        ],
        "freq_limit": 10.0,
        "transport": "mqtt_json",
        "frame_policy": "namespace",
    }

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
            "fleet_rules": [fleet_rule],
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
    assert agent.config.fleet_rules == [fleet_rule]
    assert agent.applied_fleet_rules == [[fleet_rule]]
    assert agent.saved_count == 1
    assert agent.published[-1][1]["type"] == "config_response"


def test_normalize_fleet_rules_filters_invalid_entries():
    raw = [
        {
            "enabled": True,
            "src_topic": "/odom",
            "msg_type": "nav_msgs/Odometry",
            "targets": [
                {
                    "robot_id": "robot_002",
                    "dst_topic": "/fleet/robot_001/odom",
                },
                {"robot_id": "", "dst_topic": "/bad"},
            ],
            "freq_limit": 10.0,
            "transport": "mqtt_json",
            "frame_policy": "namespace",
        },
        {"name": "invalid"},
    ]

    rules = MockAgent._normalize_fleet_rules(raw)

    assert rules == [
        {
            "enabled": True,
            "src_topic": "/odom",
            "msg_type": "nav_msgs/Odometry",
            "targets": [
                {
                    "robot_id": "robot_002",
                    "dst_topic": "/fleet/robot_001/odom",
                }
            ],
            "freq_limit": 10.0,
            "transport": "mqtt_json",
            "frame_policy": "namespace",
        }
    ]


def test_handle_fleet_message_preserves_ros_topic_fields():
    agent = RecordingAgent(AgentConfig(robot_id="robot_002"))

    agent._handle_fleet_message(Message(
        src="robot_001",
        dst="robot_002",
        type=MessageType.FLEET_DATA,
        data={
            "data_type": "ros_topic",
            "src_topic": "/odom",
            "dst_topic": "/fleet/robot_001/odom",
            "msg_type": "nav_msgs/Odometry",
            "frame_policy": "namespace",
            "payload": {"header": {"frame_id": "odom"}},
            "stamp": 123.0,
            "ttl": 1.0,
        },
    ))

    src_id, data = agent.fleet_messages[-1]
    assert src_id == "robot_001"
    assert data.data_type == "ros_topic"
    assert data.src_topic == "/odom"
    assert data.dst_topic == "/fleet/robot_001/odom"
    assert data.msg_type == "nav_msgs/Odometry"
    assert data.frame_policy == "namespace"
    assert data.payload == {"header": {"frame_id": "odom"}}
    assert data.stamp == 123.0
    assert data.ttl == 1.0


def test_load_subscriptions_from_config_applies_fleet_rules():
    fleet_rule = {
        "enabled": True,
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "targets": [
            {
                "robot_id": "robot_002",
                "dst_topic": "/fleet/robot_001/odom",
            }
        ],
        "freq_limit": 10.0,
        "transport": "mqtt_json",
        "frame_policy": "namespace",
    }
    agent = RecordingAgent(AgentConfig(
        robot_id="robot_001",
        subscriptions=[],
        fleet_rules=[fleet_rule],
    ))

    agent._load_subscriptions_from_config()

    assert agent.config.fleet_rules == [fleet_rule]
    assert agent.applied_fleet_rules == [[fleet_rule]]


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


def test_agent_config_tracks_missing_source_path_for_first_save(tmp_path):
    config_path = tmp_path / "missing-agent.yaml"

    config = AgentConfig.from_yaml(str(config_path))

    assert config.config_path == str(config_path)


def test_save_config_only_updates_subscriptions(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        "# keep header\n"
        "robot_id: robot_001\n"
        "broker_host: custom-broker\n"
        "broker_port: 1884\n"
        "status_interval: 3.0\n"
        "unknown_runtime_key: keep-me\n"
        "subscriptions:\n"
        "  - topic: /old\n"
        "    msg_type: std_msgs/String\n"
        "fleet_rules:\n"
        "  - name: old-rule\n",
        encoding="utf-8",
    )
    config = AgentConfig.from_yaml(str(config_path))
    agent = MockAgent(config)
    agent.config.subscriptions = [
        {
            "topic": "/scan",
            "msg_type": "sensor_msgs/LaserScan",
            "freq_limit": 5.0,
            "transport": "mqtt_json",
            "compression": {},
        }
    ]
    agent.config.fleet_rules = []

    agent._save_config()

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["robot_id"] == "robot_001"
    assert saved["broker_host"] == "custom-broker"
    assert saved["broker_port"] == 1884
    assert saved["status_interval"] == 3.0
    assert saved["unknown_runtime_key"] == "keep-me"
    assert saved["subscriptions"] == agent.config.subscriptions
    assert saved["fleet_rules"] == [{"name": "old-rule"}]


def test_save_config_preserves_yaml_text_outside_subscriptions(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        "# keep header\n"
        "robot_id: \"robot_001\"\n"
        "\n"
        "# custom comment before broker\n"
        "broker_host: \"custom-broker\"\n"
        "subscriptions:\n"
        "  - topic: /old\n"
        "    msg_type: std_msgs/String\n"
        "\n"
        "# 编队通信规则（应保留）\n"
        "fleet_rules:\n"
        "  - name: old-rule\n",
        encoding="utf-8",
    )
    config = AgentConfig.from_yaml(str(config_path))
    agent = MockAgent(config)
    agent.config.subscriptions = [
        {
            "topic": "/scan",
            "msg_type": "sensor_msgs/LaserScan",
            "freq_limit": 5.0,
            "transport": "mqtt_json",
            "compression": {},
        }
    ]

    agent._save_config()

    text = config_path.read_text(encoding="utf-8")
    assert "# keep header\n" in text
    assert "robot_id: \"robot_001\"\n" in text
    assert "# custom comment before broker\n" in text
    assert "broker_host: \"custom-broker\"\n" in text
    assert "# 编队通信规则（应保留）\n" in text
    assert "  - name: old-rule\n" in text
    assert "topic: /old" not in text
    assert "topic: /scan" in text


def test_config_sync_without_fleet_rules_keeps_existing_fleet_rules():
    agent = RecordingAgent(AgentConfig(
        robot_id="robot_001",
        subscriptions=[
            {
                "topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "compression": {},
            }
        ],
        fleet_rules=[{"name": "keep-rule"}],
    ))

    agent._handle_config_sync(Message(
        src="station",
        dst="robot_001",
        type=MessageType.CONFIG_SYNC,
        data={"subscriptions": []},
    ))

    assert agent.config.subscriptions == []
    assert agent.config.fleet_rules == [{"name": "keep-rule"}]
