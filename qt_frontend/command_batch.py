"""批量命令确认状态机。"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Set


@dataclass
class RobotCommandResult:
    """一台目标机器人的命令终态。"""

    status: str = "pending"
    message: str = ""


@dataclass
class CommandBatchResult:
    """同一 exec ID 下全部目标机器人的确认结果。"""

    exec_id: str
    deadline: float
    details: Dict[str, RobotCommandResult] = field(default_factory=dict)

    def counts(self) -> Dict[str, int]:
        counts = {"success": 0, "failed": 0, "timeout": 0}
        for detail in self.details.values():
            if detail.status in counts:
                counts[detail.status] += 1
        return counts


class CommandBatchTracker:
    """跟踪并限制批量命令的确认历史。"""

    def __init__(
        self,
        timeout_seconds: float = 5.0,
        max_completed: int = 20,
    ) -> None:
        self._timeout_seconds = float(timeout_seconds)
        self._max_completed = max(1, int(max_completed))
        self._batches: Dict[str, CommandBatchResult] = {}
        self._completed_order: Deque[str] = deque()
        self._completed_ids: Set[str] = set()

    def start(self, exec_id: str, robot_ids: List[str], now: float) -> None:
        if exec_id in self._batches:
            raise ValueError("exec_id 已存在")
        details = {
            robot_id: RobotCommandResult()
            for robot_id in sorted(set(robot_ids))
        }
        self._batches[exec_id] = CommandBatchResult(
            exec_id=exec_id,
            deadline=float(now) + self._timeout_seconds,
            details=details,
        )
        self._record_completed_if_ready(exec_id)

    def ack(
        self,
        exec_id: str,
        robot_id: str,
        result: str,
        message: str,
    ) -> bool:
        batch = self._batches.get(exec_id)
        if batch is None:
            return False
        detail = batch.details.get(robot_id)
        if detail is None or detail.status != "pending":
            return False

        detail.status = "success" if result == "ok" else "failed"
        detail.message = message
        self._record_completed_if_ready(exec_id)
        return True

    def expire(self, now: float) -> List[str]:
        completed = []
        for exec_id, batch in list(self._batches.items()):
            if exec_id in self._completed_ids or float(now) < batch.deadline:
                continue
            for detail in batch.details.values():
                if detail.status == "pending":
                    detail.status = "timeout"
                    detail.message = "等待确认超时"
            if self._record_completed_if_ready(exec_id):
                completed.append(exec_id)
        return completed

    def result(self, exec_id: str) -> Optional[CommandBatchResult]:
        return self._batches.get(exec_id)

    def _record_completed_if_ready(self, exec_id: str) -> bool:
        batch = self._batches.get(exec_id)
        if batch is None or exec_id in self._completed_ids:
            return False
        if any(detail.status == "pending" for detail in batch.details.values()):
            return False

        self._completed_ids.add(exec_id)
        self._completed_order.append(exec_id)
        # 只淘汰已经完成的历史，仍等待确认的活动批次不计入上限。
        while len(self._completed_order) > self._max_completed:
            oldest = self._completed_order.popleft()
            self._completed_ids.discard(oldest)
            self._batches.pop(oldest, None)
        return True


__all__ = [
    "CommandBatchResult",
    "CommandBatchTracker",
    "RobotCommandResult",
]
