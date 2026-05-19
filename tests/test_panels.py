from __future__ import annotations

"""面板纯逻辑测试 — 不涉及 Qt Widget 渲染"""

import os
import time

import pytest
import yaml
from PyQt5.QtWidgets import QApplication

from qt_frontend.panels.command_panel import CommandPanel
from qt_frontend.panels.event_panel import EventPanel
from qt_frontend.panels.fleet_comm_panel import FleetCommPanel
from qt_frontend.panels.robot_list_panel import RobotInfo, RobotListPanel
from qt_frontend.panels.sensor_summary_panel import SensorSummaryPanel
from qt_frontend.panels.topic_config_panel import (
    SubscriptionEntry,
    TopicConfigPanel,
)
from qt_frontend.panels.traffic_monitor import BandwidthEntry, TrafficMonitor


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ------------------------------------------------------------------
# RobotInfo
# ------------------------------------------------------------------
class TestRobotInfo:
    def test_default_fields(self):
        info = RobotInfo()
        assert info.robot_id == ""
        assert info.online is False
        assert info.battery == 0.0
        assert info.mode == "stop"

    def test_custom_robot(self):
        info = RobotInfo(robot_id="robot_001", online=True, battery=90.0, mode="auto")
        assert info.robot_id == "robot_001"
        assert info.online is True
        assert info.battery == 90.0
        assert info.mode == "auto"

    def test_online_offline_detection(self):
        info = RobotInfo(robot_id="r1", online=True, last_seen=time.monotonic())
        assert info.online is True

        info.online = False
        assert info.online is False


# ------------------------------------------------------------------
# RobotListPanel heartbeat timeout
# ------------------------------------------------------------------
class TestRobotListHeartbeat:
    def test_heartbeat_timeout_detection(self):
        assert RobotListPanel._HEARTBEAT_TIMEOUT == 30.0

    def test_robot_marked_offline_after_timeout(self):
        now = time.monotonic()
        info = RobotInfo(robot_id="r1", online=True, last_seen=now - 35.0)
        assert (now - info.last_seen) > RobotListPanel._HEARTBEAT_TIMEOUT

    def test_robot_remains_online_within_timeout(self):
        now = time.monotonic()
        info = RobotInfo(robot_id="r1", online=True, last_seen=now - 10.0)
        assert (now - info.last_seen) <= RobotListPanel._HEARTBEAT_TIMEOUT


class TestRobotListSubscriptions:
    def test_discover_response_does_not_change_subscription_count(self):
        info = RobotInfo(robot_id="robot_001", subscriptions_count=7)

        updated = RobotListPanel.info_after_discover_response(
            info,
            {
                "topics": [
                    {"topic": f"/topic_{i}", "msg_type": "std_msgs/String"}
                    for i in range(22)
                ]
            },
            now=100.0,
        )

        assert updated.subscriptions_count == 7
        assert updated.online is True
        assert updated.last_seen == 100.0

    def test_subscription_counts_from_transmit_config(self):
        config = {
            "subscriptions": {
                "turtlebot_001": [
                    {"topic": "/odom"},
                    {"topic": "/scan"},
                ],
                "robot_002": {"topic": {"msg_type": "std_msgs/String"}},
            }
        }

        assert RobotListPanel.subscription_counts_from_transmit_config(config) == {
            "turtlebot_001": 2,
            "robot_002": 1,
        }

    def test_discover_response_keeps_displayed_subscription_count(self, qt_app):
        panel = RobotListPanel()
        panel.on_status_received("turtlebot_001", {"battery": 90.0})
        panel.update_subscription_counts({"turtlebot_001": 7})

        panel.on_discover_response(
            "turtlebot_001",
            {
                "topics": [
                    {"topic": f"/topic_{i}", "msg_type": "std_msgs/String"}
                    for i in range(22)
                ]
            },
        )

        item = panel._tree.topLevelItem(0)
        assert item.text(4) == "7"

    def test_status_received_applies_cached_subscription_count(self, qt_app):
        panel = RobotListPanel()
        panel.update_subscription_counts({"turtlebot_001": 7})

        panel.on_status_received("turtlebot_001", {"battery": 90.0})

        item = panel._tree.topLevelItem(0)
        assert item.text(4) == "7"


# ------------------------------------------------------------------
# CommandPanel slider value mapping
# ------------------------------------------------------------------
class TestCommandPanel:
    def test_slider_to_value_positive(self):
        assert CommandPanel.slider_to_value(100) == 1.0
        assert CommandPanel.slider_to_value(50) == 0.5
        assert CommandPanel.slider_to_value(0) == 0.0

    def test_slider_to_value_negative(self):
        assert CommandPanel.slider_to_value(-100) == -1.0
        assert CommandPanel.slider_to_value(-50) == -0.5

    def test_value_to_slider(self):
        assert CommandPanel.value_to_slider(1.0) == 100
        assert CommandPanel.value_to_slider(0.0) == 0
        assert CommandPanel.value_to_slider(-1.0) == -100
        assert CommandPanel.value_to_slider(0.75) == 75

    def test_value_to_slider_clamping(self):
        assert CommandPanel.value_to_slider(2.0) == 100
        assert CommandPanel.value_to_slider(-2.0) == -100


# ------------------------------------------------------------------
# TopicConfigPanel validators
# ------------------------------------------------------------------
class TestTopicConfigPanel:
    def test_validate_topic_must_start_with_slash(self):
        assert TopicConfigPanel.validate_topic("/odom") is True
        assert TopicConfigPanel.validate_topic("/camera/image_raw") is True
        assert TopicConfigPanel.validate_topic("odom") is False
        assert TopicConfigPanel.validate_topic("/") is False
        assert TopicConfigPanel.validate_topic("") is False

    def test_validate_msg_type_must_contain_slash(self):
        assert TopicConfigPanel.validate_msg_type("nav_msgs/Odometry") is True
        assert TopicConfigPanel.validate_msg_type("sensor_msgs/LaserScan") is True
        assert TopicConfigPanel.validate_msg_type("Odometry") is False
        assert TopicConfigPanel.validate_msg_type("") is False

    def test_transport_from_tier(self):
        assert TopicConfigPanel.transport_from_tier("LIGHT") == "mqtt_json"
        assert TopicConfigPanel.transport_from_tier("MEDIUM") == "mqtt_binary"
        assert TopicConfigPanel.transport_from_tier("HEAVY") == "http_stream"
        assert TopicConfigPanel.transport_from_tier("UNKNOWN") == "mqtt_json"

    def test_qos_options_describe_all_mqtt_levels(self):
        assert TopicConfigPanel.qos_options() == [
            ("QoS 0 - 最多一次：低延迟，允许丢包，适合高频传感器数据", 0),
            ("QoS 1 - 至少一次：保证到达，可能重复，适合指令和配置", 1),
            ("QoS 2 - 恰好一次：避免重复，开销最大，通常不建议高频使用", 2),
        ]

    def test_subscription_entry_defaults(self):
        entry = SubscriptionEntry()
        assert entry.topic == ""
        assert entry.msg_type == ""
        assert entry.status == "pending"
        assert entry.transport == "auto"

    def test_subscription_entry_custom(self):
        entry = SubscriptionEntry(
            topic="/odom", msg_type="nav_msgs/Odometry",
            freq_limit=10.0, transport="mqtt_json", status="active",
        )
        assert entry.topic == "/odom"
        assert entry.status == "active"

    def test_subscription_entry_round_trip(self):
        entry = SubscriptionEntry(
            topic="/scan",
            msg_type="sensor_msgs/LaserScan",
            freq_limit=5.0,
            transport="mqtt_json",
            status="active",
            compression={"quality": 80},
        )

        restored = SubscriptionEntry.from_dict(entry.to_dict())

        assert restored == entry

    def test_build_topic_request_uses_entry_fields(self):
        entry = SubscriptionEntry(
            topic="/odom",
            msg_type="nav_msgs/Odometry",
            freq_limit=10.0,
            transport="mqtt_json",
            qos=2,
            compression={"resize": [320, 240]},
        )

        req = TopicConfigPanel.build_topic_request("subscribe", entry)

        assert req["action"] == "subscribe"
        assert req["topic"] == "/odom"
        assert req["msg_type"] == "nav_msgs/Odometry"
        assert req["freq_limit"] == 10.0
        assert req["transport"] == "mqtt_json"
        assert req["qos"] == 2
        assert req["compression"] == {"resize": [320, 240]}

    def test_replace_entry_for_edit_keeps_single_topic(self):
        entries = [
            SubscriptionEntry(topic="/scan", msg_type="sensor_msgs/LaserScan"),
            SubscriptionEntry(topic="/odom", msg_type="nav_msgs/Odometry"),
        ]
        updated = SubscriptionEntry(
            topic="/odom",
            msg_type="nav_msgs/Odometry",
            freq_limit=5.0,
            transport="mqtt_binary",
        )

        replaced = TopicConfigPanel.replace_entry_for_edit(
            entries, "/scan", updated
        )

        assert [(entry.topic, entry.freq_limit) for entry in replaced] == [
            ("/odom", 5.0)
        ]

    def test_build_edit_topic_requests_renamed_topic(self):
        updated = SubscriptionEntry(
            topic="/map",
            msg_type="nav_msgs/OccupancyGrid",
            freq_limit=1.0,
            transport="mqtt_json",
        )

        requests = TopicConfigPanel.build_edit_topic_requests("/scan", updated)

        assert [request["action"] for request in requests] == [
            "unsubscribe",
            "subscribe",
        ]
        assert requests[0]["topic"] == "/scan"
        assert requests[1]["topic"] == "/map"
        assert requests[1]["msg_type"] == "nav_msgs/OccupancyGrid"

    def test_apply_local_edit_marks_entry_pending(self):
        entries = [
            SubscriptionEntry(
                topic="/scan",
                msg_type="sensor_msgs/LaserScan",
                status="saved",
            )
        ]
        updated = SubscriptionEntry(
            topic="/scan",
            msg_type="sensor_msgs/LaserScan",
            freq_limit=3.0,
            status="saved",
        )

        result = TopicConfigPanel.apply_local_entry_change(entries, "/scan", updated)

        assert len(result) == 1
        assert result[0].freq_limit == 3.0
        assert result[0].status == "pending"

    def test_topic_response_message_uses_pending_edit_operation(self):
        pending = {"/scan": "edit"}

        result = TopicConfigPanel.topic_response_result(
            pending,
            {"action": "subscribe", "topic": "/scan", "result": "ok"},
        )

        assert result == {
            "level": "success",
            "message": "更新话题成功：/scan",
        }
        assert pending == {}

    def test_topic_response_message_suppresses_rename_unsubscribe_success(self):
        pending = {"/scan": "rename_remove"}

        result = TopicConfigPanel.topic_response_result(
            pending,
            {"action": "unsubscribe", "topic": "/scan", "result": "ok"},
        )

        assert result == {}
        assert pending == {}

    def test_apply_config_response_loads_subscriptions(self):
        entries = TopicConfigPanel.entries_from_config_response({
            "subscriptions": [
                {
                    "topic": "/map",
                    "msg_type": "nav_msgs/OccupancyGrid",
                    "freq_limit": 1.0,
                    "transport": "mqtt_json",
                }
            ]
        })

        assert len(entries) == 1
        assert entries[0].topic == "/map"
        assert entries[0].status == "active"

    def test_apply_topic_response_marks_failed(self):
        entry = SubscriptionEntry(topic="/scan", msg_type="sensor_msgs/LaserScan")

        TopicConfigPanel.apply_topic_response_to_entries(
            [entry],
            {"topic": "/scan", "result": "failed", "message": "not found"},
        )

        assert entry.status == "failed"

    def test_build_transmit_config_preserves_existing_fields(self):
        entry = SubscriptionEntry(
            topic="/scan",
            msg_type="sensor_msgs/LaserScan",
            freq_limit=5.0,
            transport="mqtt_json",
            status="active",
        )

        config = TopicConfigPanel.build_transmit_config(
            {"robots": {"legacy": {}}, "subscriptions": {"old": {}}},
            "robot_001",
            [entry],
        )

        assert config["robots"] == {"legacy": {}}
        assert config["subscriptions"] == {
            "old": [],
            "robot_001": [
                {
                    "topic": "/scan",
                    "msg_type": "sensor_msgs/LaserScan",
                    "freq_limit": 5.0,
                    "transport": "mqtt_json",
                    "qos": 1,
                    "compression": {},
                }
            ],
        }

    def test_entries_from_transmit_config_for_robot_list_format(self):
        entries = TopicConfigPanel.entries_from_transmit_config(
            {
                "subscriptions": {
                    "robot_001": [
                        {
                            "topic": "/odom",
                            "msg_type": "nav_msgs/Odometry",
                            "freq_limit": 10.0,
                            "transport": "mqtt_json",
                        }
                    ]
                }
            },
            "robot_001",
        )

        assert len(entries) == 1
        assert entries[0].topic == "/odom"
        assert entries[0].status == "saved"

    def test_entries_from_transmit_config_accepts_legacy_mapping_format(self):
        entries = TopicConfigPanel.entries_from_transmit_config(
            {
                "subscriptions": {
                    "robot_001": {
                        "/odom": {
                            "msg_type": "nav_msgs/Odometry",
                            "freq_limit": 10.0,
                            "transport": "mqtt_json",
                        }
                    }
                }
            },
            "robot_001",
        )

        assert len(entries) == 1
        assert entries[0].topic == "/odom"

    def test_save_and_load_transmit_config_file(self, tmp_path):
        path = tmp_path / "transmit_config.yaml"
        panel_entries = [
            SubscriptionEntry(
                topic="/map",
                msg_type="nav_msgs/OccupancyGrid",
                freq_limit=1.0,
                transport="mqtt_json",
            )
        ]

        TopicConfigPanel.save_transmit_config_file(path, "robot_001", panel_entries)
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))

        assert loaded["subscriptions"]["robot_001"][0]["topic"] == "/map"
        assert loaded["subscriptions"]["robot_001"][0]["msg_type"] == (
            "nav_msgs/OccupancyGrid"
        )
        assert TopicConfigPanel.load_transmit_config_file(path) == loaded

    def test_save_transmit_config_keeps_subscription_field_order(self, tmp_path):
        path = tmp_path / "transmit_config.yaml"

        TopicConfigPanel.save_transmit_config_file(
            path,
            "robot_001",
            [
                SubscriptionEntry(
                    topic="/scan",
                    msg_type="sensor_msgs/LaserScan",
                    freq_limit=5.0,
                    transport="mqtt_binary",
                    compression={},
                )
            ],
        )

        text = path.read_text(encoding="utf-8")
        assert text.index("  - topic: /scan") < text.index(
            "    msg_type: sensor_msgs/LaserScan"
        )
        assert text.index("    msg_type: sensor_msgs/LaserScan") < text.index(
            "    freq_limit: 5.0"
        )
        assert text.index("    freq_limit: 5.0") < text.index(
            "    transport: mqtt_binary"
        )
        assert text.index("    transport: mqtt_binary") < text.index(
            "    compression: {}"
        )

    def test_build_config_sync_payload_omits_ui_status(self):
        entry = SubscriptionEntry(
            topic="/scan",
            msg_type="sensor_msgs/LaserScan",
            freq_limit=5.0,
            transport="mqtt_json",
            status="active",
        )

        payload = TopicConfigPanel.build_config_sync_payload([entry])

        assert payload == {
            "subscriptions": [
                {
                    "topic": "/scan",
                    "msg_type": "sensor_msgs/LaserScan",
                    "freq_limit": 5.0,
                    "transport": "mqtt_json",
                    "qos": 1,
                    "compression": {},
                }
            ]
        }

    def test_build_available_topic_entries(self):
        entries = TopicConfigPanel.entries_from_available_topics([
            {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
            {"topic": "/odom", "msg_type": "nav_msgs/Odometry"},
            {"topic": "", "msg_type": ""},
        ])

        assert [(entry.topic, entry.msg_type, entry.status) for entry in entries] == [
            ("/scan", "sensor_msgs/LaserScan", "available"),
            ("/odom", "nav_msgs/Odometry", "available"),
        ]

    def test_available_topics_cache_is_keyed_by_robot(self):
        cache = {}

        TopicConfigPanel.update_available_topics_cache(
            cache,
            "robot_001",
            {
                "topics": [
                    {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
                    {"topic": "/odom", "type": "nav_msgs/Odometry"},
                ]
            },
        )

        assert cache == {
            "robot_001": [
                {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
                {"topic": "/odom", "msg_type": "nav_msgs/Odometry"},
            ]
        }

    def test_should_request_discover_when_available_topics_missing(self):
        assert TopicConfigPanel.should_request_available_topics({}, "robot_001") is True
        assert TopicConfigPanel.should_request_available_topics(
            {"robot_001": []}, "robot_001"
        ) is True
        assert TopicConfigPanel.should_request_available_topics(
            {"robot_001": [{"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"}]},
            "robot_001",
        ) is False
        assert TopicConfigPanel.should_request_available_topics({}, "") is False

    def test_robot_list_refresh_only_reloads_when_selected_robot_changes(self):
        assert TopicConfigPanel.should_reload_saved_config("robot_001", "robot_001") is False
        assert TopicConfigPanel.should_reload_saved_config("robot_001", "robot_002") is True
        assert TopicConfigPanel.should_reload_saved_config("robot_001", "") is True

    def test_target_robot_after_refresh_auto_selects_single_robot(self):
        assert TopicConfigPanel.target_robot_after_refresh("", "-- 选择 --", ["robot_001"]) == (
            "robot_001"
        )
        assert TopicConfigPanel.target_robot_after_refresh("", "-- 选择 --", ["r1", "r2"]) == ""
        assert TopicConfigPanel.target_robot_after_refresh("robot_001", "-- 选择 --", ["robot_001"]) == (
            "robot_001"
        )

    def test_should_load_selected_entry_by_valid_row(self):
        assert TopicConfigPanel.should_load_selected_entry(row=-1, count=1) is False
        assert TopicConfigPanel.should_load_selected_entry(row=1, count=1) is False
        assert TopicConfigPanel.should_load_selected_entry(row=0, count=1) is True

    def test_mark_entries_saved_after_local_save(self):
        entries = [
            SubscriptionEntry(topic="/scan", msg_type="sensor_msgs/LaserScan", status="active"),
            SubscriptionEntry(topic="/map", msg_type="nav_msgs/OccupancyGrid", status="pending"),
            SubscriptionEntry(topic="/odom", msg_type="nav_msgs/Odometry", status="failed"),
        ]

        TopicConfigPanel.mark_entries_saved(entries)

        assert [entry.status for entry in entries] == ["saved", "saved", "failed"]

    def test_operation_result_success_message(self):
        result = TopicConfigPanel.build_operation_result(
            "success", "保存草稿成功：robot_001，2 个话题"
        )

        assert result == {
            "level": "success",
            "message": "保存草稿成功：robot_001，2 个话题",
        }

    def test_operation_result_rejects_unknown_level(self):
        result = TopicConfigPanel.build_operation_result("unknown", "ignored")

        assert result == {
            "level": "error",
            "message": "未知操作结果：ignored",
        }

    def test_config_response_result_failed(self):
        assert TopicConfigPanel.config_response_failed(
            {"result": "failed", "message": "write failed"}
        ) == "write failed"
        assert TopicConfigPanel.config_response_failed({"result": "error"}) == (
            "机器人返回配置失败"
        )
        assert TopicConfigPanel.config_response_failed({"subscriptions": []}) == ""


# ------------------------------------------------------------------
# EventPanel formatters
# ------------------------------------------------------------------
class TestEventPanel:
    def test_level_to_color(self):
        from PyQt5.QtGui import QColor
        assert EventPanel.level_to_color("critical").name().lower() == "#8b0000"
        assert EventPanel.level_to_color("error") == QColor("#ffcccc")
        assert EventPanel.level_to_color("warning") == QColor("#fff3cd")
        assert EventPanel.level_to_color("info") == QColor("#ffffff")

    def test_level_to_text_color(self):
        assert EventPanel.level_to_text_color("critical").name() == "#ffffff"
        assert EventPanel.level_to_text_color("info").name() == "#000000"

    def test_format_event(self):
        result = EventPanel.format_event(
            "robot_001", "ERROR", "E001", "battery low", timestamp=3600.0
        )
        assert "[robot_001]" in result
        assert "[ERROR]" in result
        assert "E001" in result
        assert "battery low" in result

    def test_trim_events_none_removed(self):
        events = list(range(100))
        assert len(EventPanel.trim_events(events, 1000)) == 100

    def test_trim_events_trims_oldest(self):
        events = list(range(2000))
        trimmed = EventPanel.trim_events(events, 1000)
        assert len(trimmed) == 1000
        assert trimmed[0] == 1000  # oldest 1000 removed
        assert trimmed[-1] == 1999


# ------------------------------------------------------------------
# FleetCommPanel validator
# ------------------------------------------------------------------
class TestFleetCommPanel:
    def test_validate_rule_src_neq_dst(self):
        assert FleetCommPanel.validate_fleet_rule("r1", "r2", "/odom") is True
        assert FleetCommPanel.validate_fleet_rule("r1", "r1", "/odom") is False

    def test_validate_rule_topic_must_start_with_slash(self):
        assert FleetCommPanel.validate_fleet_rule("r1", "r2", "/odom") is True
        assert FleetCommPanel.validate_fleet_rule("r1", "r2", "odom") is False

    def test_validate_rule_empty_fields(self):
        assert FleetCommPanel.validate_fleet_rule("", "r2", "/odom") is False
        assert FleetCommPanel.validate_fleet_rule("r1", "", "/odom") is False
        assert FleetCommPanel.validate_fleet_rule("", "", "") is False


# ------------------------------------------------------------------
# TrafficMonitor bandwidth calculation
# ------------------------------------------------------------------
class TestTrafficMonitor:
    def test_calculate_bandwidth(self):
        assert TrafficMonitor.calculate_bandwidth(1000, 1.0) == 1000.0
        assert TrafficMonitor.calculate_bandwidth(500, 2.0) == 250.0
        assert TrafficMonitor.calculate_bandwidth(0, 1.0) == 0.0
        assert TrafficMonitor.calculate_bandwidth(100, 0) == 0.0
        assert TrafficMonitor.calculate_bandwidth(100, -1) == 0.0

    def test_ema_smooth(self):
        # alpha=0.3: new = old*0.7 + new*0.3
        assert TrafficMonitor.ema_smooth(0.0, 100.0, 0.3) == pytest.approx(30.0)
        assert TrafficMonitor.ema_smooth(100.0, 0.0, 0.3) == pytest.approx(70.0)
        assert TrafficMonitor.ema_smooth(50.0, 50.0, 0.3) == pytest.approx(50.0)

    def test_bandwidth_entry_defaults(self):
        entry = BandwidthEntry()
        assert entry.topic == ""
        assert entry.bytes_received == 0
        assert entry.current_bps == 0.0

    def test_bandwidth_entry_custom(self):
        entry = BandwidthEntry(
            topic="/scan", robot_id="r1", transport="mqtt_binary",
            bytes_received=10000, current_bps=500.0,
        )
        assert entry.topic == "/scan"
        assert entry.robot_id == "r1"
        assert entry.bytes_received == 10000


# ------------------------------------------------------------------
# SensorSummaryPanel
# ------------------------------------------------------------------
class TestSensorSummary:
    def test_summarize_laserscan(self):
        lines = SensorSummaryPanel.summarize_laserscan({
            "ranges": [1.0, 2.0, 5.0, float("inf")],
            "angle_min": -1.57, "angle_max": 1.57,
        })
        assert any("3 个有效" in line for line in lines)
        assert any("最近: 1.00m" in line for line in lines)

    def test_summarize_laserscan_empty(self):
        lines = SensorSummaryPanel.summarize_laserscan({"ranges": []})
        assert any("无数据" in line for line in lines)

    def test_summarize_image(self):
        lines = SensorSummaryPanel.summarize_image({"width": 640, "height": 480, "encoding": "rgb8"})
        assert any("640×480" in line for line in lines)

    def test_summarize_imu(self):
        lines = SensorSummaryPanel.summarize_imu({
            "angular_velocity": {"x": 0.1, "y": 0.2, "z": 0.3},
            "linear_acceleration": {"x": 9.8, "y": 0.0, "z": 0.0},
        })
        assert any("0.100" in line for line in lines)
        assert any("9.800" in line for line in lines)

    def test_summarize_data_dispatch(self):
        lines = SensorSummaryPanel.summarize_data({"ranges": [1.0, 2.0]})
        assert any("LaserScan" in line for line in lines)
