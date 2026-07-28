"""地面站共享的机器人 ROS 话题目录。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5.QtCore import QObject, pyqtSignal


class RobotTopicCatalog(QObject):
    """缓存 discover 返回的话题，并通知共享目录的使用方。"""

    topics_changed = pyqtSignal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._topics: Dict[str, List[Dict[str, str]]] = {}

    def update_from_discover(
        self, robot_id: str, data: Dict[str, Any]
    ) -> None:
        raw_topics = data.get("topics", [])
        if not isinstance(raw_topics, list):
            raw_topics = []

        normalized = set()
        for item in raw_topics:
            if not isinstance(item, dict):
                continue
            topic = item.get("topic")
            msg_type = item.get("msg_type") or item.get("type")
            if not isinstance(topic, str) or not isinstance(msg_type, str):
                continue
            topic = topic.strip()
            msg_type = msg_type.strip()
            if topic and msg_type:
                normalized.add((topic, msg_type))

        self._topics[robot_id] = [
            {"topic": topic, "msg_type": msg_type}
            for topic, msg_type in sorted(normalized)
        ]
        self.topics_changed.emit(robot_id)

    def topics_for(self, robot_id: str) -> List[Dict[str, str]]:
        return [dict(item) for item in self._topics.get(robot_id, [])]

    def representative_robot(self, robot_ids: List[str]) -> str:
        return sorted(set(robot_ids))[0] if robot_ids else ""
