from __future__ import annotations

"""面板纯逻辑测试 — 不涉及 Qt Widget 渲染"""

import os
import time

import pytest
import yaml
from PyQt5.QtWidgets import QApplication, QHeaderView, QLabel

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

    def test_selected_robot_detail_refreshes_when_status_updates(self, qt_app):
        panel = RobotListPanel()
        panel.on_status_received(
            "turtlebot_001",
            {
                "battery": 50.0,
                "position": {"x": 1.0, "y": 2.0, "theta": 0.3},
                "velocity": {"linear": 0.1, "angular": 0.2},
            },
        )
        item = panel._tree.topLevelItem(0)
        item.setSelected(True)
        panel._on_selection_changed()

        panel.on_status_received(
            "turtlebot_001",
            {
                "battery": 75.0,
                "position": {"x": 3.0, "y": 4.0, "theta": 0.6},
                "velocity": {"linear": 0.5, "angular": 0.7},
            },
        )

        assert panel._lb_position.text() == "位姿: x=3.00, y=4.00, θ=0.60"
        assert panel._lb_velocity.text() == "速度: linear=0.50, angular=0.70"
        assert panel._battery_bar.value() == 75

    def test_detail_battery_uses_progress_bar_without_duplicate_label(self, qt_app):
        panel = RobotListPanel()

        assert all(label.text() != "电量:" for label in panel.findChildren(QLabel))


# ------------------------------------------------------------------
# CommandPanel slider value mapping
# ------------------------------------------------------------------
class TestCommandPanel:
    def test_velocity_step_defaults_to_medium(self):
        assert CommandPanel.velocity_step("medium") == (0.30, 0.75)

    def test_velocity_step_falls_back_to_medium_for_unknown_level(self):
        assert CommandPanel.velocity_step("bad") == (0.30, 0.75)

    def test_direction_velocity_forward_left(self):
        assert CommandPanel.direction_velocity("forward_left", "medium") == (0.30, 0.75)

    def test_direction_velocity_backward_right(self):
        assert CommandPanel.direction_velocity("backward_right", "high") == (-0.50, -1.20)

    def test_direction_velocity_turn_left(self):
        assert CommandPanel.direction_velocity("left", "low") == (0.0, 0.40)

    def test_direction_velocity_stop_and_unknown_direction(self):
        assert CommandPanel.direction_velocity("stop", "medium") == (0.0, 0.0)
        assert CommandPanel.direction_velocity("bad", "medium") == (0.0, 0.0)

    def test_direction_button_emits_velocity(self, qt_app):
        panel = CommandPanel()
        panel.on_robot_selected("turtlebot_001")

        sent = []
        panel.command_sent.connect(lambda *args: sent.append(args))

        panel._send_direction_velocity("forward_right")

        assert sent == [
            (
                "turtlebot_001",
                "velocity",
                {"linear": 0.30, "angular": -0.75},
            )
        ]

    def test_direction_buttons_disabled_without_selected_robot(self, qt_app):
        panel = CommandPanel()

        assert all(not btn.isEnabled() for btn in panel._direction_buttons)

    def test_release_direction_button_emits_stop(self, qt_app):
        panel = CommandPanel()
        panel.on_robot_selected("turtlebot_001")

        sent = []
        panel.command_sent.connect(lambda *args: sent.append(args))

        panel._stop_direction_velocity()

        assert sent == [
            (
                "turtlebot_001",
                "velocity",
                {"linear": 0.0, "angular": 0.0},
            )
        ]


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
        assert FleetCommPanel.validate_fleet_rule(
            "r1", "/odom", "nav_msgs/Odometry", "r2", "/fleet/r1/odom", 10.0
        ) is True
        assert FleetCommPanel.validate_fleet_rule(
            "r1", "/odom", "nav_msgs/Odometry", "r1", "/fleet/r1/odom", 10.0
        ) is False

    def test_validate_rule_topic_must_start_with_slash(self):
        assert FleetCommPanel.validate_fleet_rule(
            "r1", "/odom", "nav_msgs/Odometry", "r2", "/fleet/r1/odom", 10.0
        ) is True
        assert FleetCommPanel.validate_fleet_rule(
            "r1", "odom", "nav_msgs/Odometry", "r2", "/fleet/r1/odom", 10.0
        ) is False
        assert FleetCommPanel.validate_fleet_rule(
            "r1", "/odom", "nav_msgs/Odometry", "r2", "fleet/r1/odom", 10.0
        ) is False

    def test_validate_rule_empty_fields(self):
        assert FleetCommPanel.validate_fleet_rule(
            "", "/odom", "nav_msgs/Odometry", "r2", "/fleet/r1/odom", 10.0
        ) is False
        assert FleetCommPanel.validate_fleet_rule(
            "r1", "/odom", "nav_msgs/Odometry", "", "/fleet/r1/odom", 10.0
        ) is False
        assert FleetCommPanel.validate_fleet_rule(
            "r1", "/odom", "", "r2", "/fleet/r1/odom", 10.0
        ) is False

    def test_validate_rule_rejects_negative_frequency(self):
        assert FleetCommPanel.validate_fleet_rule(
            "r1", "/odom", "nav_msgs/Odometry", "r2", "/fleet/r1/odom", -1.0
        ) is False

    def test_table_headers_match_fleet_rule_fields(self, qt_app):
        panel = FleetCommPanel()

        headers = [
            panel._table.horizontalHeaderItem(index).text()
            for index in range(panel._table.columnCount())
        ]

        assert headers == [
            "启用",
            "源机器人",
            "源话题",
            "消息类型",
            "目标机器人",
            "目标话题",
            "频率",
            "Frame 策略",
            "操作",
        ]

        for index in range(panel._table.columnCount()):
            assert panel._table.horizontalHeader().sectionResizeMode(index) == (
                QHeaderView.ResizeToContents
            )

    def test_discover_response_populates_source_topic_options(self, qt_app):
        panel = FleetCommPanel()
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])

        panel.on_discover_response(
            "turtlebot_001",
            {
                "topics": [
                    {"topic": "/odom", "msg_type": "nav_msgs/Odometry"},
                    {"topic": "/scan", "type": "sensor_msgs/LaserScan"},
                ]
            },
        )

        assert [
            panel._combo_src_topic.itemText(index)
            for index in range(panel._combo_src_topic.count())
        ] == ["/odom", "/scan"]

    def test_source_topic_selection_autofills_type_and_destination(self, qt_app):
        panel = FleetCommPanel()
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])
        panel.on_discover_response(
            "turtlebot_001",
            {"topics": [{"topic": "/odom", "msg_type": "nav_msgs/Odometry"}]},
        )

        panel._combo_src.setCurrentText("turtlebot_001")
        panel._combo_src_topic.setCurrentText("/odom")

        assert panel._combo_msg_type.currentText() == "nav_msgs/Odometry"
        assert panel._edit_dst_topic.text() == "/fleet/turtlebot_001/odom"

    def test_show_add_form_requests_discover_when_source_topics_missing(self, qt_app):
        panel = FleetCommPanel()
        requested = []
        panel.discover_requested.connect(lambda: requested.append(True))
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])

        panel._btn_add.click()

        assert requested == [True]

    def test_form_layout_groups_destination_and_frequency_policy_rows(self, qt_app):
        panel = FleetCommPanel()

        assert panel._source_topic_row.objectName() == "sourceTopicRow"
        assert panel._destination_topic_row.objectName() == "destinationTopicRow"
        assert panel._frequency_policy_row.objectName() == "frequencyPolicyRow"
        assert panel._source_topic_row.indexOf(panel._combo_src_topic) >= 0
        assert panel._destination_topic_row.indexOf(panel._edit_dst_topic) >= 0
        assert panel._frequency_policy_row.indexOf(panel._spin_freq) >= 0
        assert panel._frequency_policy_row.indexOf(panel._combo_frame_policy) >= 0

    def test_add_rule_button_opens_form(self, qt_app):
        panel = FleetCommPanel()

        assert panel._form_group.isChecked() is False

        panel._btn_add.click()

        assert panel._form_group.isChecked() is True

    def test_confirm_adds_rule_from_form(self, qt_app):
        panel = FleetCommPanel()
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])
        panel._btn_add.click()
        panel._combo_src.setCurrentText("turtlebot_001")
        panel._combo_dst.setCurrentText("turtlebot_002")
        panel._combo_src_topic.setCurrentText("/odom")
        panel._edit_dst_topic.setText("/fleet/turtlebot_001/odom")
        panel._combo_msg_type.setCurrentText("nav_msgs/Odometry")
        panel._spin_freq.setValue(10.0)
        panel._combo_frame_policy.setCurrentText("namespace")

        panel._btn_confirm.click()

        assert len(panel._rules) == 1
        assert panel._rules[0] == {
            "enabled": True,
            "src_robot": "turtlebot_001",
            "src_topic": "/odom",
            "msg_type": "nav_msgs/Odometry",
            "dst_robot": "turtlebot_002",
            "dst_topic": "/fleet/turtlebot_001/odom",
            "freq_limit": 10.0,
            "transport": "mqtt_json",
            "frame_policy": "namespace",
        }
        assert panel._table.rowCount() == 1
        assert panel._table.item(0, 1).text() == "turtlebot_001"
        assert panel._table.item(0, 2).text() == "/odom"
        assert panel._table.item(0, 4).text() == "turtlebot_002"
        assert panel._form_group.isChecked() is False

    def test_deploy_rules_groups_config_sync_by_source_robot(self, qt_app, tmp_path):
        panel = FleetCommPanel()
        panel._transmit_config_path = tmp_path / "transmit_config.yaml"
        emitted = []
        panel.config_sync_requested.connect(
            lambda robot_id, payload: emitted.append((robot_id, payload))
        )
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])
        panel._rules = [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            }
        ]

        panel._btn_deploy.click()

        assert emitted == [
            (
                "turtlebot_001",
                {
                    "fleet_rules": [
                        {
                            "enabled": True,
                            "src_topic": "/odom",
                            "msg_type": "nav_msgs/Odometry",
                            "targets": [
                                {
                                    "robot_id": "turtlebot_002",
                                    "dst_topic": "/fleet/turtlebot_001/odom",
                                }
                            ],
                            "freq_limit": 10.0,
                            "transport": "mqtt_json",
                            "frame_policy": "namespace",
                        }
                    ]
                },
            )
        ]

    def test_deploy_rules_sends_each_source_robot_own_rules(self, qt_app, tmp_path):
        panel = FleetCommPanel()
        panel._transmit_config_path = tmp_path / "transmit_config.yaml"
        emitted = []
        panel.config_sync_requested.connect(
            lambda robot_id, payload: emitted.append((robot_id, payload))
        )
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])
        panel._rules = [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            },
            {
                "enabled": True,
                "src_robot": "turtlebot_002",
                "src_topic": "/scan",
                "msg_type": "sensor_msgs/LaserScan",
                "dst_robot": "turtlebot_001",
                "dst_topic": "/fleet/turtlebot_002/scan",
                "freq_limit": 5.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            },
        ]

        panel._btn_deploy.click()

        assert [robot_id for robot_id, _payload in emitted] == [
            "turtlebot_001",
            "turtlebot_002",
        ]
        assert emitted[0][1]["fleet_rules"][0]["src_topic"] == "/odom"
        assert emitted[1][1]["fleet_rules"][0]["src_topic"] == "/scan"

    def test_pull_rules_queries_all_known_robots(self, qt_app):
        panel = FleetCommPanel()
        emitted = []
        panel.config_query_requested.connect(lambda robot_id: emitted.append(robot_id))
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])

        panel._btn_pull.click()

        assert emitted == ["turtlebot_001", "turtlebot_002"]

    def test_config_response_loads_fleet_rules_into_table(self, qt_app, tmp_path):
        panel = FleetCommPanel()
        panel._transmit_config_path = tmp_path / "transmit_config.yaml"
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])

        panel.on_config_response(
            "turtlebot_001",
            {
                "fleet_rules": [
                    {
                        "enabled": True,
                        "src_topic": "/odom",
                        "msg_type": "nav_msgs/Odometry",
                        "targets": [
                            {
                                "robot_id": "turtlebot_002",
                                "dst_topic": "/fleet/turtlebot_001/odom",
                            }
                        ],
                        "freq_limit": 10.0,
                        "transport": "mqtt_json",
                        "frame_policy": "namespace",
                    }
                ]
            },
        )

        assert panel._rules == [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            }
        ]
        assert panel._table.rowCount() == 1
        assert panel._table.item(0, 1).text() == "turtlebot_001"
        assert panel._table.item(0, 4).text() == "turtlebot_002"

    def test_config_response_replaces_only_matching_source_robot_rules(
        self, qt_app, tmp_path
    ):
        panel = FleetCommPanel()
        panel._transmit_config_path = tmp_path / "transmit_config.yaml"
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])
        panel._rules = [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/old",
                "msg_type": "std_msgs/String",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/old",
                "freq_limit": 1.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            },
            {
                "enabled": True,
                "src_robot": "turtlebot_002",
                "src_topic": "/scan",
                "msg_type": "sensor_msgs/LaserScan",
                "dst_robot": "turtlebot_001",
                "dst_topic": "/fleet/turtlebot_002/scan",
                "freq_limit": 5.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            },
        ]

        panel.on_config_response(
            "turtlebot_001",
            {
                "fleet_rules": [
                    {
                        "enabled": True,
                        "src_topic": "/odom",
                        "msg_type": "nav_msgs/Odometry",
                        "targets": [
                            {
                                "robot_id": "turtlebot_002",
                                "dst_topic": "/fleet/turtlebot_001/odom",
                            }
                        ],
                        "freq_limit": 10.0,
                        "transport": "mqtt_json",
                        "frame_policy": "namespace",
                    }
                ]
            },
        )

        assert [(rule["src_robot"], rule["src_topic"]) for rule in panel._rules] == [
            ("turtlebot_002", "/scan"),
            ("turtlebot_001", "/odom"),
        ]

    def test_config_response_without_fleet_rules_keeps_existing_rules(
        self, qt_app, tmp_path
    ):
        panel = FleetCommPanel()
        panel._transmit_config_path = tmp_path / "transmit_config.yaml"
        panel._rules = [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            }
        ]

        panel.on_config_response("turtlebot_001", {"subscriptions": []})

        assert panel._rules == [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            }
        ]

    def test_build_transmit_config_preserves_subscriptions(self):
        rules = [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            }
        ]

        config = FleetCommPanel.build_transmit_config(
            {
                "subscriptions": {
                    "turtlebot_001": [
                        {
                            "topic": "/scan",
                            "msg_type": "sensor_msgs/LaserScan",
                        }
                    ]
                },
                "robots": {"legacy": {}},
            },
            rules,
        )

        assert config["subscriptions"]["turtlebot_001"][0]["topic"] == "/scan"
        assert config["robots"] == {"legacy": {}}
        assert config["fleet_rules"] == rules

    def test_save_and_load_fleet_rules_from_transmit_config(self, tmp_path):
        path = tmp_path / "transmit_config.yaml"
        path.write_text(
            "subscriptions:\n"
            "  turtlebot_001:\n"
            "    - topic: /scan\n"
            "      msg_type: sensor_msgs/LaserScan\n",
            encoding="utf-8",
        )
        rules = [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            }
        ]

        FleetCommPanel.save_transmit_config_file(path, rules)

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert loaded["subscriptions"]["turtlebot_001"][0]["topic"] == "/scan"
        assert loaded["fleet_rules"] == rules
        assert FleetCommPanel.rules_from_transmit_config(loaded) == rules

    def test_load_saved_rules_refreshes_table(self, qt_app, tmp_path):
        path = tmp_path / "transmit_config.yaml"
        rules = [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            }
        ]
        FleetCommPanel.save_transmit_config_file(path, rules)
        panel = FleetCommPanel()
        panel._transmit_config_path = path

        panel._load_saved_rules()

        assert panel._rules == rules
        assert panel._table.rowCount() == 1
        assert panel._table.item(0, 1).text() == "turtlebot_001"

    def test_deploy_rules_saves_ground_station_config_before_emit(
        self, qt_app, tmp_path
    ):
        path = tmp_path / "transmit_config.yaml"
        panel = FleetCommPanel()
        panel._transmit_config_path = path
        panel.on_robot_list_changed(["turtlebot_001", "turtlebot_002"])
        panel._rules = [
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "transport": "mqtt_json",
                "frame_policy": "namespace",
            }
        ]

        panel._btn_deploy.click()

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert loaded["fleet_rules"] == panel._rules

    def test_build_config_sync_payload_generates_fleet_rules(self):
        payload = FleetCommPanel.build_config_sync_payload([
            {
                "enabled": True,
                "src_robot": "turtlebot_001",
                "src_topic": "/odom",
                "msg_type": "nav_msgs/Odometry",
                "dst_robot": "turtlebot_002",
                "dst_topic": "/fleet/turtlebot_001/odom",
                "freq_limit": 10.0,
                "frame_policy": "namespace",
            }
        ])

        assert payload == {
            "fleet_rules": [
                {
                    "enabled": True,
                    "src_topic": "/odom",
                    "msg_type": "nav_msgs/Odometry",
                    "targets": [
                        {
                            "robot_id": "turtlebot_002",
                            "dst_topic": "/fleet/turtlebot_001/odom",
                        }
                    ],
                    "freq_limit": 10.0,
                    "transport": "mqtt_json",
                    "frame_policy": "namespace",
                }
            ]
        }


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

    def test_estimate_payload_bytes_uses_large_payload_summary(self):
        assert TrafficMonitor.estimate_payload_bytes({"_payload_bytes": 123456}) == 123456

    def test_subscription_config_updates_transport(self, qt_app):
        panel = TrafficMonitor()

        panel.on_subscriptions_changed(
            "r1",
            [
                {
                    "topic": "/camera/image_raw/compressed",
                    "transport": "mqtt_binary",
                }
            ],
        )
        panel.on_sensor_data_received(
            "r1",
            "camera/image_raw/compressed",
            {"format": "jpeg", "data": [1, 2, 3]},
            now=100.0,
        )

        entry = panel._entries[("camera/image_raw/compressed", "r1")]
        assert entry.transport == "mqtt_binary"

    def test_frequency_uses_message_intervals_not_refresh_interval(self, qt_app):
        panel = TrafficMonitor()

        panel.on_sensor_data_received("r1", "scan", {"ranges": [1.0]}, now=100.0)
        panel.on_sensor_data_received("r1", "scan", {"ranges": [1.0]}, now=100.1)
        panel.on_sensor_data_received("r1", "scan", {"ranges": [1.0]}, now=100.2)
        panel._update_stats(now=101.2)

        entry = panel._entries[("scan", "r1")]
        assert entry.current_hz == pytest.approx(10.0)
        assert panel._table.item(0, 4).text() == "10.0 Hz"

    def test_frequency_expires_when_topic_stops(self, qt_app):
        panel = TrafficMonitor()

        panel.on_sensor_data_received("r1", "scan", {"ranges": [1.0]}, now=100.0)
        panel.on_sensor_data_received("r1", "scan", {"ranges": [1.0]}, now=100.1)
        panel._update_stats(now=106.0)

        entry = panel._entries[("scan", "r1")]
        assert entry.current_hz == 0.0
        assert panel._table.item(0, 4).text() == "0.0 Hz"


# ------------------------------------------------------------------
# SensorSummaryPanel
# ------------------------------------------------------------------
class TestSensorSummary:
    def test_topic_snapshot_tracks_hz_summary_and_age(self):
        snapshot = SensorSummaryPanel.build_topic_snapshot(
            robot_id="r1",
            sensor_name="scan",
            data={"ranges": [1.0, 2.0]},
            now=100.0,
            previous=None,
        )
        snapshot = SensorSummaryPanel.build_topic_snapshot(
            robot_id="r1",
            sensor_name="scan",
            data={"ranges": [1.0, 2.0, 3.0]},
            now=100.5,
            previous=snapshot,
        )
        snapshot = SensorSummaryPanel.build_topic_snapshot(
            robot_id="r1",
            sensor_name="scan",
            data={"ranges": [1.0]},
            now=101.0,
            previous=snapshot,
        )

        assert snapshot.frame_count == 3
        assert snapshot.hz == pytest.approx(2.0)
        assert snapshot.age(101.25) == pytest.approx(0.25)
        assert any("LaserScan" in line for line in snapshot.summary_lines)
        assert snapshot.is_stale(101.25) is False
        assert snapshot.is_stale(104.5) is True

    def test_topic_snapshot_prunes_old_samples_from_hz_window(self):
        snapshot = None
        for now in [100.0, 101.0, 106.0, 107.0]:
            snapshot = SensorSummaryPanel.build_topic_snapshot(
                robot_id="r1",
                sensor_name="odom",
                data={"pose": {}, "twist": {}},
                now=now,
                previous=snapshot,
            )

        assert snapshot is not None
        assert snapshot.hz == pytest.approx(1.0)
        assert snapshot.frame_count == 4

    def test_generic_summary_handles_unknown_dict(self):
        lines = SensorSummaryPanel.summarize_data(
            {
                "header": {"frame_id": "map", "stamp": {"secs": 10, "nsecs": 5}},
                "custom": {"value": 42},
                "enabled": True,
            },
            msg_type_hint="custom_msgs/Widget",
        )

        assert any("custom_msgs/Widget" in line for line in lines)
        assert any("frame_id: map" in line for line in lines)
        assert any("字段: 3" in line for line in lines)

    def test_panel_keeps_selected_topic_when_other_data_arrives(self, qt_app):
        panel = SensorSummaryPanel()
        panel.show()
        panel.on_sensor_data_received("r1", "scan", {"ranges": [1.0]})
        panel._refresh_current_view(force=True)
        panel.on_sensor_data_received("r1", "odom", {"pose": {}, "twist": {}})
        panel._refresh_current_view(force=True)

        panel._topic_combo.setCurrentIndex(
            panel._topic_combo.findData("r1\x1fscan")
        )
        panel.on_sensor_data_received("r1", "odom", {"pose": {}, "twist": {}})
        panel._refresh_current_view(force=True)

        assert panel._selected_key == ("r1", "scan")
        assert "话题: scan" in panel._browser.toPlainText()
        assert "Odometry" not in panel._browser.toPlainText()

    def test_panel_does_not_duplicate_combo_items_for_same_topic(self, qt_app):
        panel = SensorSummaryPanel()
        panel.show()

        for _ in range(5):
            panel.on_sensor_data_received(
                "r1",
                "scan",
                {"_msg_type": "sensor_msgs/LaserScan", "ranges": [1.0]},
            )
        panel._refresh_current_view(force=True)

        assert panel._topic_combo.count() == 1
        assert panel._topic_combo.itemData(0) == "r1\x1fscan"

    def test_panel_batches_inbound_data_until_refresh(self, qt_app, monkeypatch):
        panel = SensorSummaryPanel()
        panel.show()
        calls = []
        original_summarize_data = SensorSummaryPanel.summarize_data

        def fake_summarize_data(data, msg_type_hint=""):
            calls.append((data, msg_type_hint))
            return original_summarize_data(data, msg_type_hint)

        monkeypatch.setattr(
            SensorSummaryPanel,
            "summarize_data",
            staticmethod(fake_summarize_data),
        )

        panel.on_sensor_data_received(
            "r1",
            "scan",
            {"_msg_type": "sensor_msgs/LaserScan", "ranges": [1.0]},
        )
        panel.on_sensor_data_received(
            "r1",
            "scan",
            {"_msg_type": "sensor_msgs/LaserScan", "ranges": [2.0]},
        )

        assert calls == []

        panel._refresh_current_view(force=True)

        assert len(calls) == 1
        assert calls[0][0]["ranges"] == [2.0]
        assert panel._snapshots[("r1", "scan")].frame_count == 2

    def test_panel_uses_msg_type_field_without_raw_json_panel(self, qt_app):
        panel = SensorSummaryPanel()
        panel.show()

        panel.on_sensor_data_received(
            "r1",
            "joint_states",
            {
                "_msg_type": "sensor_msgs/JointState",
                "header": {"frame_id": "base_link"},
                "name": ["left_wheel", "right_wheel"],
                "position": [0.1, 0.2],
            },
        )
        panel._refresh_current_view(force=True)

        summary = panel._browser.toPlainText()
        assert "类型: sensor_msgs/JointState" in summary
        assert "JointState: 2 个关节" in summary
        assert not hasattr(panel, "_raw_browser")

    def test_summarize_joint_state_and_occupancy_grid(self):
        joint_lines = SensorSummaryPanel.summarize_data({
            "_msg_type": "sensor_msgs/JointState",
            "name": ["left", "right"],
            "position": [1.0, 2.0],
            "velocity": [0.1, 0.2],
            "effort": [],
        })
        grid_lines = SensorSummaryPanel.summarize_data({
            "_msg_type": "nav_msgs/OccupancyGrid",
            "info": {"width": 100, "height": 50, "resolution": 0.05},
            "data": [0, 100, -1],
        })

        assert any("JointState: 2 个关节" in line for line in joint_lines)
        assert any("position: 2" in line for line in joint_lines)
        assert any("OccupancyGrid: 100×50" in line for line in grid_lines)
        assert any("resolution: 0.050 m" in line for line in grid_lines)

    def test_binary_laserscan_envelope_uses_msg_type_not_encoding(self):
        envelope = {
            "binary": True,
            "topic": "/scan",
            "msg_type": "sensor_msgs/LaserScan",
            "encoding": "laser_scan_v1",
            "payload_format": "float32_le",
            "payload_size": 2880,
            "ranges_len": 360,
            "intensities_len": 360,
        }

        snapshot = SensorSummaryPanel.build_topic_snapshot(
            robot_id="r1",
            sensor_name="scan",
            data=envelope,
            now=100.0,
            previous=None,
        )

        assert snapshot.msg_type == "sensor_msgs/LaserScan"
        assert not any("Image" in line for line in snapshot.summary_lines)

    def test_binary_occupancy_grid_envelope_uses_msg_type_not_encoding(self):
        envelope = {
            "binary": True,
            "topic": "/map",
            "msg_type": "nav_msgs/OccupancyGrid",
            "encoding": "occupancy_grid_v1",
            "payload_format": "int8",
            "payload_size": 714,
            "raw_payload_size": 147456,
            "compression": "zlib",
            "info": {"width": 384, "height": 384, "resolution": 0.05},
            "data_len": 147456,
        }

        snapshot = SensorSummaryPanel.build_topic_snapshot(
            robot_id="r1",
            sensor_name="map",
            data=envelope,
            now=100.0,
            previous=None,
        )

        assert snapshot.msg_type == "nav_msgs/OccupancyGrid"
        assert any("OccupancyGrid: 384×384" in line for line in snapshot.summary_lines)
        assert not any("Image" in line for line in snapshot.summary_lines)

    def test_panel_observation_list_comes_from_subscriptions(self, qt_app):
        panel = SensorSummaryPanel()
        panel.show()

        panel.on_subscriptions_changed(
            "r1",
            [
                {
                    "topic": "/imu/data",
                    "msg_type": "sensor_msgs/Imu",
                    "status": "active",
                },
                {
                    "topic": "/camera/image_raw/compressed",
                    "msg_type": "sensor_msgs/CompressedImage",
                    "status": "active",
                },
            ],
        )

        assert panel._topic_combo.count() == 2
        combo_keys = {
            panel._topic_combo.itemData(index)
            for index in range(panel._topic_combo.count())
        }
        assert combo_keys == {
            "r1\x1fimu/data",
            "r1\x1fcamera/image_raw/compressed",
        }
        assert "等待数据" in panel._browser.toPlainText()

        panel.on_sensor_data_received(
            "r1",
            "imu/data",
            {
                "_msg_type": "sensor_msgs/Imu",
                "angular_velocity": {"x": 0.1, "y": 0.0, "z": 0.0},
                "linear_acceleration": {"x": 0.0, "y": 0.0, "z": 9.8},
            },
        )
        panel._refresh_current_view(force=True)

        assert panel._topic_combo.count() == 2
        assert "类型: sensor_msgs/Imu" in panel._browser.toPlainText()

    def test_snapshot_does_not_store_large_payload(self):
        data = {
            "_msg_type": "nav_msgs/OccupancyGrid",
            "info": {"width": 100, "height": 100, "resolution": 0.05},
            "data": list(range(10000)),
        }
        snapshot = SensorSummaryPanel.build_topic_snapshot(
            robot_id="r1",
            sensor_name="map",
            data=data,
            now=100.0,
            previous=None,
        )

        assert not hasattr(snapshot, "last_data")
        assert any("OccupancyGrid: 100×100" in line for line in snapshot.summary_lines)
        assert any("数据长度: 10000" in line for line in snapshot.summary_lines)

    def test_status_table_shows_subscribed_topic_summary(self, qt_app):
        panel = SensorSummaryPanel()
        panel.show()

        panel.on_subscriptions_changed(
            "r1",
            [
                {
                    "topic": "/map",
                    "msg_type": "nav_msgs/OccupancyGrid",
                    "status": "active",
                }
            ],
        )
        panel.on_sensor_data_received(
            "r1",
            "map",
            {
                "_msg_type": "nav_msgs/OccupancyGrid",
                "info": {"width": 20, "height": 10, "resolution": 0.1},
                "data": list(range(200)),
            },
        )
        panel._refresh_current_view(force=True)

        assert panel._topic_table.columnCount() == 6
        assert panel._topic_table.item(0, 2).text() == "正常"
        assert "OccupancyGrid: 20×10" in panel._topic_table.item(0, 5).text()

    def test_retain_robots_removes_offline_robot_observations(self, qt_app):
        panel = SensorSummaryPanel()
        panel.show()

        panel.on_subscriptions_changed(
            "turtlebot_001",
            [{"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"}],
        )
        panel.on_subscriptions_changed(
            "turtlebot_002",
            [{"topic": "/odom", "msg_type": "nav_msgs/Odometry"}],
        )

        panel.retain_robots(["turtlebot_001"])

        combo_keys = {
            panel._topic_combo.itemData(index)
            for index in range(panel._topic_combo.count())
        }
        assert combo_keys == {"turtlebot_001\x1fscan"}
        assert panel._topic_table.rowCount() == 1
        assert panel._topic_table.item(0, 1).text() == "turtlebot_001"

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
        lines = SensorSummaryPanel.summarize_image(
            {"width": 640, "height": 480, "encoding": "rgb8"}
        )
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
