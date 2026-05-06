from __future__ import annotations

"""pytest 共享 fixtures"""

import pytest

from protocol.messages import Message, MessageFactory, StatusData, Position, Velocity


@pytest.fixture
def factory() -> MessageFactory:
    """创建一个 MessageFactory 实例"""
    return MessageFactory(src="test_robot")


@pytest.fixture
def sample_status_data() -> StatusData:
    """创建示例状态数据"""
    return StatusData(
        battery=85.5,
        position=Position(x=1.0, y=2.0, theta=0.5),
        velocity=Velocity(linear=0.5, angular=0.1),
        mode="manual",
        ros_version="mock",
        uptime=120,
        ip="192.168.1.100",
    )
