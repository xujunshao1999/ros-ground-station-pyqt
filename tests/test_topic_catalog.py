"""共享机器人话题目录测试。"""

from __future__ import annotations

import os

import pytest
from PyQt5.QtWidgets import QApplication

from qt_frontend.topic_catalog import RobotTopicCatalog

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qt_app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_catalog_normalizes_discovers_and_returns_defensive_copy(qt_app):
    catalog = RobotTopicCatalog()
    changed = []
    catalog.topics_changed.connect(changed.append)

    catalog.update_from_discover(
        "r1",
        {
            "topics": [
                {"topic": " /scan ", "msg_type": " sensor_msgs/LaserScan "},
                {"topic": "/cmd", "type": "custom_msgs/Command"},
                {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
                {"topic": "", "msg_type": "ignored/Empty"},
                {"topic": "/empty_type", "msg_type": "  "},
            ]
        },
    )

    topics = catalog.topics_for("r1")
    assert topics == [
        {"topic": "/cmd", "msg_type": "custom_msgs/Command"},
        {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
    ]
    assert changed == ["r1"]

    topics[0]["topic"] = "/modified"
    topics.append({"topic": "/added", "msg_type": "std_msgs/String"})
    assert catalog.topics_for("r1") == [
        {"topic": "/cmd", "msg_type": "custom_msgs/Command"},
        {"topic": "/scan", "msg_type": "sensor_msgs/LaserScan"},
    ]


@pytest.mark.parametrize(
    "raw_topics",
    [
        None,
        "not-a-list",
        [None, 1, "topic"],
        [
            {"topic": None, "msg_type": "std_msgs/String"},
            {"topic": 123, "msg_type": "std_msgs/String"},
            {"topic": "/none", "msg_type": None},
            {"topic": "/number", "msg_type": 123},
            {"topic": "/fallback", "msg_type": 0, "type": 1},
        ],
    ],
)
def test_catalog_ignores_invalid_discover_topics(qt_app, raw_topics):
    catalog = RobotTopicCatalog()
    changed = []
    catalog.topics_changed.connect(changed.append)

    catalog.update_from_discover("r1", {"topics": raw_topics})

    assert catalog.topics_for("r1") == []
    assert changed == ["r1"]


def test_catalog_unknown_robot_and_representative_robot(qt_app):
    catalog = RobotTopicCatalog()

    assert catalog.topics_for("unknown") == []
    assert catalog.representative_robot(["r2", "r1", "r2"]) == "r1"
    assert catalog.representative_robot([]) == ""
