from __future__ import annotations

import json
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock

import paho.mqtt.client as mqtt
import pytest
import yaml

from agent.base_agent import AgentConfig, AgentState, BaseAgent
from agent.mock_agent import MockAgent
from agent.mock_pointcloud2_data import FakePointCloud2Message, build_pointcloud2_dict
from protocol.binary_payloads import encode_fleet_binary_payload
from protocol.messages import (
    FleetBinaryEnvelopeData,
    FleetData,
    Message,
    MessageFactory,
    MessageType,
)


def test_turtlebot_fleet_examples_use_expected_binary_qos():
    """从完整 YAML 读取禁用示例，避免只检查字符串而遗漏层级错误。"""
    root = Path(__file__).resolve().parents[1]
    turtlebot_001 = yaml.safe_load(
        (root / "agent/configs/turtlebot_001.yaml").read_text(encoding="utf-8")
    )
    turtlebot_002 = yaml.safe_load(
        (root / "agent/configs/turtlebot_002.yaml").read_text(encoding="utf-8")
    )

    odom_rule = turtlebot_001["fleet_rules"][0]
    goal_rule = turtlebot_002["fleet_rules"][0]
    assert odom_rule["enabled"] is False
    assert odom_rule["transport"] == "mqtt_binary"
    assert odom_rule["qos"] == 0
    assert goal_rule["enabled"] is False
    assert goal_rule["transport"] == "mqtt_binary"
    assert goal_rule["qos"] == 1

# Agent 订阅配置与重型 snapshot 发布测试。


class RecordingAgent(MockAgent):
    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        self.subscribed: List[Tuple[str, str, dict]] = []
        self.unsubscribed: List[str] = []
        self.applied_fleet_rules = []
        self.fleet_messages = []
        self.fleet_binary_messages = []
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

    def _on_fleet_binary_message(self, src_id, envelope, body) -> None:
        self.fleet_binary_messages.append((src_id, envelope, body))

    def _save_config(self) -> None:
        self.saved_count += 1

    def _mqtt_publish(
        self,
        topic: str,
        payload: bytes,
        qos: int = 1,
        retain: bool = False,
    ) -> bool:
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            decoded = payload
        self.published.append((
            topic,
            decoded,
            qos,
            retain,
        ))
        return True

    def _start_stream_server(self) -> None:
        self._stream_server = object()


class FakeMqttMessage:
    """提供 BaseAgent MQTT 回调所需的最小消息接口。"""

    def __init__(self, topic: str, payload: bytes):
        self.topic = topic
        self.payload = payload


def build_recording_agent_and_envelope(
    robot_id: str,
    src_id: str,
    transfer_id: int,
    body_size: int,
):
    """构造可直接进入 BaseAgent 配对流程的测试 envelope。"""
    agent = RecordingAgent(AgentConfig(robot_id=robot_id))
    message = MessageFactory(src_id).fleet_binary_envelope(
        FleetBinaryEnvelopeData(
            transfer_id=transfer_id,
            payload_size=body_size,
            md5sum="md5",
            src_topic="/odom",
            dst_topic="/fleet/%s/odom" % src_id,
            msg_type="nav_msgs/Odometry",
            ttl=0.0,
        ),
        dst=robot_id,
    )
    return agent, message


def test_fleet_binary_pairs_when_body_arrives_before_envelope():
    """body 先到时应缓存，并在 envelope 到达后完成配对。"""
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    body = encode_fleet_binary_payload(7, b"body")
    envelope_message = MessageFactory("r1").fleet_binary_envelope(
        FleetBinaryEnvelopeData(
            transfer_id=7,
            payload_size=4,
            md5sum="md5",
            src_topic="/odom",
            dst_topic="/fleet/r1/odom",
            msg_type="nav_msgs/Odometry",
            ttl=1.0,
        ),
        dst="r2",
    )

    agent._on_message(
        None,
        None,
        FakeMqttMessage("robot/r1/to/r2/bin", body),
    )
    agent._on_message(
        None,
        None,
        FakeMqttMessage(
            "robot/r1/to/r2",
            envelope_message.to_json().encode("utf-8"),
        ),
    )

    assert agent.fleet_binary_messages[0][0] == "r1"
    assert agent.fleet_binary_messages[0][2] == b"body"


def test_fleet_binary_pairs_when_envelope_arrives_before_body():
    """envelope 先到时应缓存，并在 body 到达后完成配对。"""
    agent, message = build_recording_agent_and_envelope(
        robot_id="r2",
        src_id="r1",
        transfer_id=12,
        body_size=4,
    )
    agent._on_message(
        None,
        None,
        FakeMqttMessage(
            "robot/r1/to/r2",
            message.to_json().encode("utf-8"),
        ),
    )
    agent._on_message(
        None,
        None,
        FakeMqttMessage(
            "robot/r1/to/r2/bin",
            encode_fleet_binary_payload(12, b"body"),
        ),
    )

    assert agent.fleet_binary_messages[0][2] == b"body"


def test_fleet_binary_topic_bypasses_utf8_decode():
    """任意 ROS bytes 不得经过 UTF-8 解码。"""
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    payload = encode_fleet_binary_payload(13, b"\xff\xfe")

    agent._on_message(
        None,
        None,
        FakeMqttMessage("robot/r1/to/r2/bin", payload),
    )

    assert agent._fleet_body_cache[("r1", 13)][0] == b"\xff\xfe"


def test_fleet_main_topic_rejects_source_mismatch():
    """主 topic 的源 ID 与 Message.src 不一致时拒绝 envelope。"""
    agent, message = build_recording_agent_and_envelope(
        robot_id="r2",
        src_id="forged",
        transfer_id=14,
        body_size=4,
    )

    agent._on_message(
        None,
        None,
        FakeMqttMessage(
            "robot/r1/to/r2",
            message.to_json().encode("utf-8"),
        ),
    )

    assert agent._fleet_envelope_cache == {}


def test_fleet_main_topic_rejects_destination_mismatch():
    """Message.dst 必须同时匹配 topic 目标和本机 ID。"""
    agent, message = build_recording_agent_and_envelope(
        robot_id="other",
        src_id="r1",
        transfer_id=15,
        body_size=4,
    )

    agent._on_message(
        None,
        None,
        FakeMqttMessage(
            "robot/r1/to/r2",
            message.to_json().encode("utf-8"),
        ),
    )

    assert agent._fleet_envelope_cache == {}


def test_fleet_binary_rechecks_ttl_after_pairing(monkeypatch):
    """配对完成时已过期的 envelope 不得调用子类 hook。"""
    clock = {"wall": 100.5, "mono": 10.0}
    monkeypatch.setattr("agent.base_agent.time.time", lambda: clock["wall"])
    monkeypatch.setattr("agent.base_agent.time.monotonic", lambda: clock["mono"])
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    message = MessageFactory("r1").fleet_binary_envelope(
        FleetBinaryEnvelopeData(
            transfer_id=7,
            payload_size=4,
            md5sum="md5",
            src_topic="/odom",
            dst_topic="/fleet/r1/odom",
            msg_type="nav_msgs/Odometry",
            ttl=1.0,
        ),
        dst="r2",
    )
    message.ts = 100.0

    agent._handle_fleet_binary_envelope("r1", message)
    clock.update(wall=101.1, mono=10.6)
    agent._handle_fleet_binary_body(
        "r1",
        encode_fleet_binary_payload(7, b"body"),
    )

    assert agent.fleet_binary_messages == []
    assert agent._fleet_envelope_cache == {}
    assert agent._fleet_body_cache == {}


def test_fleet_message_ttl_rejects_expired_json(monkeypatch):
    """完整 JSON fleet 消息也必须在子类回调前检查 TTL。"""
    monkeypatch.setattr("agent.base_agent.time.time", lambda: 101.1)
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    message = Message(
        ts=100.0,
        src="r1",
        dst="r2",
        type=MessageType.FLEET_DATA,
        data={"data_type": "custom", "payload": {}, "ttl": 1.0},
    )

    agent._handle_fleet_message(message)

    assert agent.fleet_messages == []


def test_fleet_message_ttl_defaults_ros_topic_to_one_second(monkeypatch):
    """缺少 TTL 的 ROS topic 使用固定 1 秒，而不是旧 custom 默认值。"""
    monkeypatch.setattr("agent.base_agent.time.time", lambda: 101.1)
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    message = Message(
        ts=100.0,
        src="r1",
        dst="r2",
        type=MessageType.FLEET_DATA,
        data={"data_type": "ros_topic", "payload": {}},
    )

    agent._handle_fleet_message(message)

    assert agent.fleet_messages == []


def test_fleet_message_ttl_passes_resolved_default_to_json_hook(monkeypatch):
    """TTL 校验值与传给子类的 FleetData.ttl 必须保持一致。"""
    monkeypatch.setattr("agent.base_agent.time.time", lambda: 100.5)
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    message = Message(
        ts=100.0,
        src="r1",
        dst="r2",
        type=MessageType.FLEET_DATA,
        data={"data_type": "ros_topic", "payload": {}},
    )

    agent._handle_fleet_message(message)

    assert agent.fleet_messages[0][1].ttl == 1.0


@pytest.mark.parametrize("message_ts,ttl", [
    (True, 1.0),
    (100.0, True),
    (float("nan"), 1.0),
    (100.0, float("inf")),
])
def test_fleet_message_ttl_rejects_non_finite_or_bool_values(message_ts, ttl):
    """TTL 判断拒绝 bool、NaN 和无穷值。"""
    assert BaseAgent._is_fleet_message_fresh(
        message_ts,
        ttl,
        now=100.0,
    ) is False


def test_fleet_message_ttl_rejects_clock_too_far_in_future():
    """超过容忍范围的未来时间戳视为时钟异常。"""
    assert BaseAgent._is_fleet_message_fresh(105.1, 0.0, now=100.0) is False
    assert BaseAgent._is_fleet_message_fresh(105.0, 0.0, now=100.0) is True


def test_fleet_binary_hook_runs_without_cache_lock():
    """子类 hook 必须在缓存锁外执行，避免慢 ROS 操作阻塞接收。"""
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    lock_states = []

    def record_lock_state(src_id, envelope, body):
        acquired = agent._fleet_cache_lock.acquire(blocking=False)
        lock_states.append(acquired)
        if acquired:
            agent._fleet_cache_lock.release()

    agent._on_fleet_binary_message = record_lock_state
    message = MessageFactory("r1").fleet_binary_envelope(
        FleetBinaryEnvelopeData(
            transfer_id=8,
            payload_size=4,
            md5sum="md5",
            src_topic="/odom",
            dst_topic="/fleet/r1/odom",
            msg_type="nav_msgs/Odometry",
            ttl=0.0,
        ),
        dst="r2",
    )

    agent._handle_fleet_binary_envelope("r1", message)
    agent._handle_fleet_binary_body(
        "r1",
        encode_fleet_binary_payload(8, b"body"),
    )

    assert lock_states == [True]


def test_fleet_binary_rejects_body_over_limit(monkeypatch):
    """单个 body 超过上限时不得占用缓存。"""
    monkeypatch.setattr("agent.base_agent.FLEET_BODY_MAX_BYTES", 8)
    agent = RecordingAgent(AgentConfig(robot_id="r2"))

    agent._handle_fleet_binary_body(
        "r1",
        encode_fleet_binary_payload(9, b"123456789"),
    )

    assert agent._fleet_body_cache == {}
    assert agent._fleet_body_cache_bytes == 0


def test_fleet_binary_rejects_envelope_body_size_over_limit(monkeypatch):
    """声明 body 超限的 envelope 不得进入缓存。"""
    monkeypatch.setattr("agent.base_agent.FLEET_BODY_MAX_BYTES", 8)
    agent, message = build_recording_agent_and_envelope(
        robot_id="r2",
        src_id="r1",
        transfer_id=9,
        body_size=9,
    )

    agent._handle_fleet_binary_envelope("r1", message)

    assert agent._fleet_envelope_cache == {}


def test_fleet_binary_envelope_cache_does_not_retain_unknown_fields():
    """缓存仅保留净化字段，避免额外 JSON 数据在配对窗口内驻留。"""
    agent, message = build_recording_agent_and_envelope(
        robot_id="r2",
        src_id="r1",
        transfer_id=12,
        body_size=4,
    )
    message.data["padding"] = "x" * 4096

    agent._handle_fleet_binary_envelope("r1", message)

    cached_ts, cached_envelope, _ = agent._fleet_envelope_cache[("r1", 12)]
    assert cached_ts == message.ts
    assert isinstance(cached_envelope, FleetBinaryEnvelopeData)


def test_fleet_binary_rejects_oversized_envelope_payload(monkeypatch):
    """超出 envelope 上限的原始 MQTT JSON 不得进入配对缓存。"""
    agent, message = build_recording_agent_and_envelope(
        robot_id="r2",
        src_id="r1",
        transfer_id=13,
        body_size=4,
    )
    message.data["padding"] = "x" * 256
    payload = message.to_json().encode("utf-8")
    monkeypatch.setattr(
        "agent.base_agent.FLEET_ENVELOPE_MAX_BYTES",
        len(payload) - 1,
    )

    agent._on_message(
        None,
        None,
        FakeMqttMessage("robot/r1/to/r2", payload),
    )

    assert agent._fleet_envelope_cache == {}


def test_fleet_robot_json_rejects_oversized_payload_before_decode(monkeypatch):
    """机器人间 JSON 超限时必须在 UTF-8 和协议解析前拒绝。"""
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    parse_json = MagicMock(side_effect=AssertionError("不应解析超限 JSON"))
    monkeypatch.setattr("agent.base_agent.FLEET_ROBOT_JSON_MAX_BYTES", 8)
    monkeypatch.setattr("agent.base_agent.Message.from_json", parse_json)

    agent._on_message(
        None,
        None,
        FakeMqttMessage("robot/r1/to/r2", b"x" * 9),
    )

    parse_json.assert_not_called()


def test_fleet_binary_evicts_oldest_body_to_keep_budget(monkeypatch):
    """body 总字节数超限时移除最早写入项。"""
    monkeypatch.setattr("agent.base_agent.FLEET_BODY_MAX_BYTES", 8)
    monkeypatch.setattr("agent.base_agent.FLEET_BODY_CACHE_MAX_BYTES", 8)
    agent = RecordingAgent(AgentConfig(robot_id="r2"))

    agent._handle_fleet_binary_body(
        "r1",
        encode_fleet_binary_payload(10, b"123456"),
    )
    agent._handle_fleet_binary_body(
        "r1",
        encode_fleet_binary_payload(11, b"abcdef"),
    )

    assert ("r1", 10) not in agent._fleet_body_cache
    assert agent._fleet_body_cache[("r1", 11)][0] == b"abcdef"
    assert agent._fleet_body_cache_bytes == 6


def test_fleet_binary_evicts_oldest_body_to_keep_entry_limit(monkeypatch):
    """body 条目数超限时移除最早写入项。"""
    clock = {"mono": 1.0}
    monkeypatch.setattr("agent.base_agent.FLEET_CACHE_MAX_ENTRIES", 1)
    monkeypatch.setattr("agent.base_agent.time.monotonic", lambda: clock["mono"])
    agent = RecordingAgent(AgentConfig(robot_id="r2"))

    agent._handle_fleet_binary_body(
        "r1",
        encode_fleet_binary_payload(20, b"a"),
    )
    clock["mono"] = 1.1
    agent._handle_fleet_binary_body(
        "r1",
        encode_fleet_binary_payload(21, b"b"),
    )

    assert ("r1", 20) not in agent._fleet_body_cache
    assert agent._fleet_body_cache[("r1", 21)][0] == b"b"
    assert agent._fleet_body_cache_bytes == 1


def test_fleet_binary_cleanup_expires_unpaired_entries(monkeypatch):
    """公开清理入口按 monotonic 时间移除缺少另一侧的条目。"""
    clock = {"mono": 10.0}
    monkeypatch.setattr("agent.base_agent.time.monotonic", lambda: clock["mono"])
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    agent._handle_fleet_binary_body(
        "r1",
        encode_fleet_binary_payload(30, b"body"),
    )

    clock["mono"] = 12.1
    agent._cleanup_fleet_cache()

    assert agent._fleet_body_cache == {}
    assert agent._fleet_body_cache_bytes == 0


def test_fleet_binary_rejects_payload_size_mismatch():
    """声明大小与实际 body 不符时弹出配对但不调用 hook。"""
    agent, message = build_recording_agent_and_envelope(
        robot_id="r2",
        src_id="r1",
        transfer_id=40,
        body_size=5,
    )

    agent._handle_fleet_binary_envelope("r1", message)
    agent._handle_fleet_binary_body(
        "r1",
        encode_fleet_binary_payload(40, b"body"),
    )

    assert agent.fleet_binary_messages == []
    assert agent._fleet_envelope_cache == {}
    assert agent._fleet_body_cache == {}


def test_on_connect_subscribes_fleet_binary_topic():
    """MQTT 单层通配符不会覆盖 /bin，因此必须显式订阅。"""
    agent = RecordingAgent(AgentConfig(robot_id="r2"))
    agent._load_subscriptions_from_config = MagicMock()
    agent._start_status_loop = MagicMock()
    client = MagicMock()

    agent._on_connect(client, None, None, 0, None)

    client.subscribe.assert_any_call("robot/+/to/r2/bin", qos=1)


def test_normalize_fleet_rules_preserves_qos_and_deduplicates_targets():
    """相同目标只保留一次，并保留 binary route 的传输参数。"""
    rules = MockAgent._normalize_fleet_rules([{
        "enabled": True,
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "targets": [
            {"robot_id": "r2", "dst_topic": "/fleet/r1/odom"},
            {"robot_id": "r2", "dst_topic": "/fleet/r1/odom"},
        ],
        "freq_limit": 10.0,
        "transport": "mqtt_binary",
        "qos": 0,
        "frame_policy": "namespace",
    }])

    assert rules[0]["transport"] == "mqtt_binary"
    assert rules[0]["qos"] == 0
    assert rules[0]["targets"] == [
        {"robot_id": "r2", "dst_topic": "/fleet/r1/odom"}
    ]


@pytest.mark.parametrize("transport", ["auto", "unknown", None])
def test_normalize_fleet_rules_falls_back_invalid_transport(transport):
    """非法 transport 回落 JSON，但不覆盖合法 route QoS。"""
    rules = MockAgent._normalize_fleet_rules([{
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "targets": [{"robot_id": "r2", "dst_topic": "/fleet/r1/odom"}],
        "transport": transport,
        "qos": 0,
    }])

    assert rules[0]["transport"] == "mqtt_json"
    assert rules[0]["qos"] == 0


@pytest.mark.parametrize("qos", [2, "0", True])
def test_normalize_fleet_rules_falls_back_invalid_qos(qos):
    """非法 QoS 回落到 1，但不覆盖合法 binary transport。"""
    rules = MockAgent._normalize_fleet_rules([{
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "targets": [{"robot_id": "r2", "dst_topic": "/fleet/r1/odom"}],
        "transport": "mqtt_binary",
        "qos": qos,
    }])

    assert rules[0]["transport"] == "mqtt_binary"
    assert rules[0]["qos"] == 1


@pytest.mark.parametrize("targets", [None, {}, "invalid", 1])
def test_normalize_fleet_rules_filters_invalid_targets_container(targets):
    """非法 targets 容器只丢弃当前规则，不能中断配置恢复。"""
    rules = MockAgent._normalize_fleet_rules([{
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "targets": targets,
    }])

    assert rules == []


@pytest.mark.parametrize(
    "src_topic,dst_topic",
    [
        ("odom", "/fleet/r1/odom"),
        ("/odom", "fleet/r1/odom"),
        (1, "/fleet/r1/odom"),
        ("/odom", 1),
    ],
)
def test_normalize_fleet_rules_requires_absolute_string_topics(
    src_topic,
    dst_topic,
):
    """源和目标 topic 必须是绝对 ROS topic 字符串。"""
    rules = MockAgent._normalize_fleet_rules([{
        "src_topic": src_topic,
        "msg_type": "nav_msgs/Odometry",
        "targets": [{"robot_id": "r2", "dst_topic": dst_topic}],
    }])

    assert rules == []


@pytest.mark.parametrize(
    "freq_limit",
    ["invalid", True, float("nan"), float("inf")],
)
def test_normalize_fleet_rules_filters_invalid_frequency(freq_limit):
    """非法限频值不能变成无限速 route，也不能中断配置恢复。"""
    rules = MockAgent._normalize_fleet_rules([{
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "targets": [{"robot_id": "r2", "dst_topic": "/fleet/r1/odom"}],
        "freq_limit": freq_limit,
    }])

    assert rules == []


def test_normalize_fleet_rules_preserves_negative_unlimited_frequency():
    """按既有协议保留有限负数，ROS 回调将其视为不限频。"""
    rules = MockAgent._normalize_fleet_rules([{
        "src_topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "targets": [{"robot_id": "r2", "dst_topic": "/fleet/r1/odom"}],
        "freq_limit": -1.0,
    }])

    assert rules[0]["freq_limit"] == -1.0


def test_fleet_transfer_ids_are_unique_and_roll_session_nonce(monkeypatch):
    """计数回绕时更换 session nonce，避免 Agent 生命周期内 ID 重复。"""
    nonces = iter([0x11111111, 0x22222222])
    monkeypatch.setattr(
        "agent.base_agent.secrets.randbits",
        lambda bits: next(nonces),
    )
    agent = RecordingAgent(AgentConfig(robot_id="r1"))
    first = agent._next_fleet_transfer_id()
    agent._fleet_transfer_counter = 0xFFFFFFFF
    wrapped = agent._next_fleet_transfer_id()

    assert first == 0x1111111100000001
    assert wrapped == 0x2222222200000001


def test_send_to_robot_returns_publish_status_and_uses_route_qos():
    """既有 JSON fleet 发送入口保留兼容默认值并暴露发布状态。"""
    agent = RecordingAgent(AgentConfig(robot_id="r1"))

    result = agent.send_to_robot(
        "r2",
        FleetData(data_type="custom", payload={"value": 1}),
        qos=0,
    )

    assert result is True
    assert agent.published[0][0] == "robot/r1/to/r2"
    assert agent.published[0][2] == 0


def test_send_fleet_binary_publishes_envelope_and_body_with_route_qos():
    """同一路由的 envelope 与 body 应使用一致的目标和 QoS。"""
    agent = RecordingAgent(AgentConfig(robot_id="r1"))
    envelope = FleetBinaryEnvelopeData(
        transfer_id=7,
        payload_size=4,
        md5sum="md5",
        src_topic="/odom",
        dst_topic="/fleet/r1/odom",
        msg_type="nav_msgs/Odometry",
        ttl=1.0,
    )
    body = encode_fleet_binary_payload(7, b"body")

    result = agent.send_fleet_binary_to_robot("r2", envelope, body, qos=0)

    assert result == (True, True)
    assert agent.published[0][0] == "robot/r1/to/r2"
    assert agent.published[0][2] == 0
    assert agent.published[1] == ("robot/r1/to/r2/bin", body, 0, False)


def test_mock_agent_binary_hook_logs_summary_without_ros(caplog):
    """MockAgent 的目标 hook 只记录摘要，不依赖 rospy 或 ROS 消息类。"""
    agent = MockAgent(AgentConfig(robot_id="r2"))
    envelope = FleetBinaryEnvelopeData(
        transfer_id=8,
        payload_size=4,
        md5sum="md5",
        src_topic="/odom",
        dst_topic="/fleet/r1/odom",
        msg_type="nav_msgs/Odometry",
    )
    caplog.set_level("INFO", logger="agent.mock_agent")

    agent._on_fleet_binary_message("r1", envelope, b"body")

    assert "Fleet binary from r1" in caplog.text
    assert "type=nav_msgs/Odometry" in caplog.text
    assert "dst=/fleet/r1/odom" in caplog.text
    assert "size=4" in caplog.text


def test_init_mqtt_sets_bounded_client_queues(monkeypatch):
    """Paho 离线队列和在途消息数必须有界。"""
    client = MagicMock()
    monkeypatch.setattr(
        "agent.base_agent.mqtt.Client",
        MagicMock(return_value=client),
    )
    agent = RecordingAgent(AgentConfig(robot_id="r1"))

    agent._init_mqtt()

    client.max_queued_messages_set.assert_called_once_with(1000)
    client.max_inflight_messages_set.assert_called_once_with(20)


@pytest.mark.parametrize("rc,expected", [
    (mqtt.MQTT_ERR_SUCCESS, True),
    (mqtt.MQTT_ERR_NO_CONN, False),
    (mqtt.MQTT_ERR_QUEUE_SIZE, False),
])
def test_mqtt_publish_returns_paho_rc_status(rc, expected):
    """返回值仅表示 Paho 是否接受发布请求，不代表 Broker 已投递。"""
    agent = RecordingAgent(AgentConfig(robot_id="r1"))
    agent._mqtt_client = MagicMock()
    agent._mqtt_client.publish.return_value.rc = rc
    agent.state = AgentState.CONNECTED

    assert BaseAgent._mqtt_publish(
        agent,
        "robot/r1/test",
        b"payload",
    ) is expected


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
    assert agent.subscribed[-1] == (
        "/scan",
        "sensor_msgs/LaserScan",
        {
            "quality": 80,
            "freq_limit": 5.0,
            "qos": 2,
            "transport": "mqtt_json",
        },
    )


def test_topic_request_auto_transport_uses_registry_default_for_pointcloud2():
    agent = RecordingAgent(AgentConfig(robot_id="robot_001"))
    message = Message(
        src="station",
        dst="robot_001",
        type=MessageType.TOPIC_REQUEST,
        data={
            "action": "subscribe",
            "topic": "/velodyne_points",
            "msg_type": "sensor_msgs/PointCloud2",
            "freq_limit": 2.0,
            "transport": "auto",
            "qos": 0,
            "compression": {},
        },
    )

    agent._handle_topic_request(message)

    assert agent._subscribed_topics["/velodyne_points"]["transport"] == "http_stream"
    assert agent.config.subscriptions[-1]["transport"] == "http_stream"
    assert agent.subscribed[-1] == (
        "/velodyne_points",
        "sensor_msgs/PointCloud2",
        {
            "freq_limit": 2.0,
            "qos": 0,
            "transport": "http_stream",
        },
    )
    assert agent.published[-1][1]["data"]["transport"] == "http_stream"


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


def test_publish_sensor_data_uses_mqtt_binary_transport_for_scan():
    agent = RecordingAgent(AgentConfig(robot_id="robot_001"))
    agent._subscribed_topics["/scan"] = {
        "msg_type": "sensor_msgs/LaserScan",
        "freq_limit": 0.0,
        "transport": "mqtt_binary",
        "qos": 2,
        "options": {},
    }

    agent.publish_sensor_data(
        "/scan",
        "sensor_msgs/LaserScan",
        {
            "header": {
                "seq": 1,
                "stamp": {"secs": 2, "nsecs": 3},
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
        },
    )

    assert len(agent.published) == 2
    envelope_topic, envelope, envelope_qos, _ = agent.published[0]
    binary_topic, binary_payload, binary_qos, _ = agent.published[1]
    assert envelope_topic == "robot/robot_001/sensor/scan"
    assert envelope["binary"] is True
    assert envelope["encoding"] == "laser_scan_v1"
    assert envelope["msg_type"] == "sensor_msgs/LaserScan"
    assert binary_topic == "robot/robot_001/sensor/scan/bin"
    assert isinstance(binary_payload, bytes)
    assert binary_payload[:1] != b"{"
    assert envelope_qos == 2
    assert binary_qos == 2


def test_publish_sensor_binary_data_marks_transport_mqtt_binary():
    agent = RecordingAgent(AgentConfig(robot_id="robot_001"))
    agent._subscribed_topics["/hdl_graph_slam/odom"] = {
        "msg_type": "nav_msgs/Odometry",
        "freq_limit": 0.0,
        "transport": "mqtt_binary",
        "qos": 0,
        "options": {},
    }

    agent.publish_sensor_binary_data(
        "/hdl_graph_slam/odom",
        "nav_msgs/Odometry",
        b"serialized-odom",
        seq=7,
    )

    envelope = agent.published[0][1]
    assert envelope["topic"] == "/hdl_graph_slam/odom"
    assert envelope["transport"] == "mqtt_binary"
    assert envelope["encoding"] == "ros1_serialized_v1"


def test_publish_sensor_data_keeps_json_transport_single_payload():
    agent = RecordingAgent(AgentConfig(robot_id="robot_001"))
    agent._subscribed_topics["/scan"] = {
        "msg_type": "sensor_msgs/LaserScan",
        "freq_limit": 0.0,
        "transport": "mqtt_json",
        "qos": 1,
        "options": {},
    }

    agent.publish_sensor_data(
        "/scan",
        "sensor_msgs/LaserScan",
        {"ranges": [1.0], "intensities": [], "angle_min": 0.0, "angle_max": 0.0},
    )

    assert len(agent.published) == 1
    assert agent.published[0][0] == "robot/robot_001/sensor/scan"
    assert agent.published[0][1]["_msg_type"] == "sensor_msgs/LaserScan"
    assert "binary" not in agent.published[0][1]


def test_publish_sensor_data_can_retain_message():
    agent = RecordingAgent(AgentConfig(robot_id="robot_001"))
    agent._subscribed_topics["/tf_static"] = {
        "msg_type": "tf2_msgs/TFMessage",
        "freq_limit": 0.0,
        "qos": 1,
        "options": {},
    }

    agent.publish_sensor_data(
        "/tf_static",
        "tf2_msgs/TFMessage",
        {"transforms": []},
        bypass_rate_limit=True,
        retain=True,
    )

    assert agent.published[-1][0] == "robot/robot_001/sensor/tf_static"
    assert agent.published[-1][3] is True


def test_publish_heavy_snapshot_data_stores_stream_and_publishes_meta():
    agent = RecordingAgent(AgentConfig(robot_id="robot_001", http_stream_port=18080))
    agent.config.stream_public_host = "10.0.0.2"
    agent._subscribed_topics["/velodyne_points"] = {
        "msg_type": "sensor_msgs/PointCloud2",
        "freq_limit": 2.0,
        "transport": "http_stream",
        "qos": 0,
        "options": {},
    }
    agent._stream_data = {}

    data = build_pointcloud2_dict(
        frame_id="velodyne",
        seq=7,
        stamp={"secs": 1, "nsecs": 2},
    )
    msg = FakePointCloud2Message.from_dict(data)
    raw_payload = bytes(msg.data)

    agent.publish_heavy_snapshot_data(
        "/velodyne_points",
        "sensor_msgs/PointCloud2",
        raw_payload,
        seq=msg.header.seq,
        stamp={"secs": msg.header.stamp.secs, "nsecs": msg.header.stamp.nsecs},
        frame_id=msg.header.frame_id,
    )

    assert agent._stream_data["/velodyne_points"] == raw_payload
    topic, meta_payload, qos, retain = agent.published[-1]
    assert topic == "robot/robot_001/sensor/velodyne_points/meta"
    assert qos == 0
    assert retain is False
    assert meta_payload["type"] == "sensor_meta"
    assert meta_payload["data"]["topic"] == "/velodyne_points"
    assert meta_payload["data"]["msg_type"] == "sensor_msgs/PointCloud2"
    assert meta_payload["data"]["transport"] == "http_stream"
    assert meta_payload["data"]["stream_url"] == "http://10.0.0.2:18080/stream/velodyne_points"
    assert meta_payload["data"]["encoding"] == "ros1_serialized_v1"
    assert meta_payload["data"]["payload_format"] == "ros1_serialized"
    assert meta_payload["data"]["payload_size"] == len(raw_payload)
    assert meta_payload["data"]["seq"] == 7
    assert meta_payload["data"]["stamp"] == {"secs": 1, "nsecs": 2}
    assert meta_payload["data"]["frame_id"] == "velodyne"


def test_publish_heavy_snapshot_data_does_not_publish_meta_when_stream_server_fails():
    class FailingStreamAgent(RecordingAgent):
        def _start_stream_server(self) -> None:
            self._stream_server = None

    agent = FailingStreamAgent(
        AgentConfig(robot_id="robot_001", http_stream_port=18080)
    )
    agent.config.stream_public_host = "10.0.0.2"
    agent._subscribed_topics["/velodyne_points"] = {
        "msg_type": "sensor_msgs/PointCloud2",
        "freq_limit": 2.0,
        "transport": "http_stream",
        "qos": 0,
        "options": {},
    }

    agent.publish_heavy_snapshot_data(
        "/velodyne_points",
        "sensor_msgs/PointCloud2",
        b"raw-pointcloud",
        seq=1,
        stamp={"secs": 1, "nsecs": 2},
        frame_id="velodyne",
    )

    assert agent.published == []


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
        "qos": 1,
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
        (
            "/scan",
            "sensor_msgs/LaserScan",
            {
                "quality": 70,
                "freq_limit": 2.0,
                "transport": "mqtt_json",
                "qos": 1,
            },
        ),
        (
            "/map",
            "nav_msgs/OccupancyGrid",
            {
                "freq_limit": 1.0,
                "transport": "mqtt_json",
                "qos": 1,
            },
        ),
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
            "qos": 1,
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
            "qos": 1,
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
        "qos": 1,
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


def test_agent_config_loads_stream_public_url_fields(tmp_path):
    config_path = tmp_path / "agent.yaml"
    config_path.write_text(
        "robot_id: robot_001\n"
        "http_stream_port: 18080\n"
        "stream_public_host: 10.0.0.2\n"
        "stream_base_url: http://station-reachable:18080/base\n",
        encoding="utf-8",
    )

    config = AgentConfig.from_yaml(str(config_path))

    assert config.http_stream_port == 18080
    assert config.stream_public_host == "10.0.0.2"
    assert config.stream_base_url == "http://station-reachable:18080/base"


def test_save_config_updates_subscriptions_and_fleet_rules(tmp_path):
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
    agent.config.fleet_rules = [
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

    agent._save_config()

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["robot_id"] == "robot_001"
    assert saved["broker_host"] == "custom-broker"
    assert saved["broker_port"] == 1884
    assert saved["status_interval"] == 3.0
    assert saved["unknown_runtime_key"] == "keep-me"
    assert saved["subscriptions"] == agent.config.subscriptions
    assert saved["fleet_rules"] == agent.config.fleet_rules


def test_save_config_preserves_yaml_text_outside_runtime_sections(tmp_path):
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
    agent.config.fleet_rules = [
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

    agent._save_config()

    text = config_path.read_text(encoding="utf-8")
    assert "# keep header\n" in text
    assert "robot_id: \"robot_001\"\n" in text
    assert "# custom comment before broker\n" in text
    assert "broker_host: \"custom-broker\"\n" in text
    assert "# 编队通信规则（应保留）\n" in text
    assert "topic: /old" not in text
    assert "topic: /scan" in text
    assert "src_topic: /odom" in text
    assert "name: old-rule" not in text


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


def test_config_sync_with_only_fleet_rules_keeps_existing_subscriptions():
    existing_subscription = {
        "topic": "/odom",
        "msg_type": "nav_msgs/Odometry",
        "freq_limit": 10.0,
        "transport": "mqtt_json",
        "compression": {},
    }
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
        "qos": 1,
        "frame_policy": "namespace",
    }
    agent = RecordingAgent(AgentConfig(
        robot_id="robot_001",
        subscriptions=[existing_subscription],
    ))
    agent._load_subscriptions_from_config()
    agent.subscribed.clear()

    agent._handle_config_sync(Message(
        src="station",
        dst="robot_001",
        type=MessageType.CONFIG_SYNC,
        data={"fleet_rules": [fleet_rule]},
    ))

    assert agent.config.subscriptions == [
        {
            "topic": "/odom",
            "msg_type": "nav_msgs/Odometry",
            "freq_limit": 10.0,
            "transport": "mqtt_json",
            "qos": 1,
            "compression": {},
        }
    ]
    assert set(agent._subscribed_topics.keys()) == {"/odom"}
    assert agent.unsubscribed == []
    assert agent.subscribed == []
    assert agent.config.fleet_rules == [fleet_rule]
