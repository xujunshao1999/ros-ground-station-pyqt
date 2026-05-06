from __future__ import annotations
"""
Agent 限频器

按话题独立限频，每个话题有自己的发送频率上限。
地面站通过 topic/request 消息指定 freq_limit，Agent 按此频率转发数据。
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RateLimitEntry:
    """单个话题的限频记录"""

    freq_limit: float  # Hz，0 表示不限频
    last_sent: float = 0.0  # 上次发送时间戳
    interval: float = 0.0  # 发送间隔（秒）

    def __post_init__(self):
        if self.freq_limit > 0:
            self.interval = 1.0 / self.freq_limit


class RateLimiter:
    """
    话题限频管理器

    用法：
        limiter = RateLimiter()
        limiter.set_limit("/camera/image", freq_limit=10.0)

        if limiter.can_send("/camera/image"):
            # 发送数据
            limiter.mark_sent("/camera/image")
    """

    def __init__(self, default_freq_limit: float = 0.0):
        """
        Args:
            default_freq_limit: 默认频率上限（Hz），0 表示不限频
        """
        self._entries: dict[str, RateLimitEntry] = {}
        self._default_freq_limit = default_freq_limit

    def set_limit(self, topic: str, freq_limit: float) -> None:
        """设置话题的频率限制

        Args:
            topic: 话题名称
            freq_limit: 频率上限（Hz），0 表示不限频
        """
        if topic in self._entries:
            self._entries[topic].freq_limit = freq_limit
            if freq_limit > 0:
                self._entries[topic].interval = 1.0 / freq_limit
            else:
                self._entries[topic].interval = 0.0
        else:
            self._entries[topic] = RateLimitEntry(freq_limit=freq_limit)

    def remove_limit(self, topic: str) -> None:
        """移除话题的频率限制（取消订阅时调用）"""
        self._entries.pop(topic, None)

    def can_send(self, topic: str) -> bool:
        """检查话题是否可以发送数据

        Args:
            topic: 话题名称

        Returns:
            True 表示可以发送，False 表示需要等待
        """
        entry = self._entries.get(topic)

        # 没有记录，使用默认限制
        if entry is None:
            if self._default_freq_limit <= 0:
                return True
            entry = RateLimitEntry(freq_limit=self._default_freq_limit)
            self._entries[topic] = entry

        # 不限频
        if entry.freq_limit <= 0:
            return True

        # 检查是否超过间隔
        now = time.monotonic()
        elapsed = now - entry.last_sent
        return elapsed >= entry.interval

    def mark_sent(self, topic: str) -> None:
        """标记话题已发送，更新时间戳

        Args:
            topic: 话题名称
        """
        entry = self._entries.get(topic)
        if entry is None:
            entry = RateLimitEntry(freq_limit=self._default_freq_limit)
            self._entries[topic] = entry
        entry.last_sent = time.monotonic()

    def get_wait_time(self, topic: str) -> float:
        """获取话题需要等待的时间（秒）

        Args:
            topic: 话题名称

        Returns:
            需要等待的秒数，0 表示可以立即发送
        """
        entry = self._entries.get(topic)
        if entry is None or entry.freq_limit <= 0:
            return 0.0

        now = time.monotonic()
        elapsed = now - entry.last_sent
        remaining = entry.interval - elapsed
        return max(0.0, remaining)

    def get_limit(self, topic: str) -> Optional[float]:
        """获取话题的频率限制

        Args:
            topic: 话题名称

        Returns:
            频率上限（Hz），None 表示未设置
        """
        entry = self._entries.get(topic)
        if entry is None:
            return None
        return entry.freq_limit

    def list_limits(self) -> dict[str, float]:
        """列出所有话题的频率限制

        Returns:
            {topic: freq_limit} 字典
        """
        return {topic: entry.freq_limit for topic, entry in self._entries.items()}

    def clear(self) -> None:
        """清除所有限频记录"""
        self._entries.clear()
