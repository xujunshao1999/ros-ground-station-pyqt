"""批量命令确认状态机测试。"""

from __future__ import annotations

from qt_frontend.command_batch import CommandBatchTracker


def test_batch_accepts_each_robot_first_terminal_ack() -> None:
    tracker = CommandBatchTracker()
    tracker.start("exec-1", ["r2", "r1", "r1"], now=10.0)

    assert tracker.ack("exec-1", "r1", "ok", "done") is True
    assert tracker.ack("exec-1", "r1", "error", "late error") is False
    assert tracker.ack("exec-1", "r2", "error", "rejected") is True

    result = tracker.result("exec-1")
    assert result is not None
    assert result.counts() == {"success": 1, "failed": 1, "timeout": 0}
    assert result.details["r1"].status == "success"
    assert result.details["r1"].message == "done"
    assert result.details["r2"].status == "failed"
    assert result.details["r2"].message == "rejected"


def test_batch_rejects_unknown_exec_and_robot() -> None:
    tracker = CommandBatchTracker()
    tracker.start("exec-1", ["r1"], now=10.0)

    assert tracker.ack("missing", "r1", "ok", "") is False
    assert tracker.ack("exec-1", "missing", "ok", "") is False
    assert tracker.result("missing") is None
    assert tracker.result("exec-1").counts() == {
        "success": 0,
        "failed": 0,
        "timeout": 0,
    }


def test_batch_summarizes_partial_failure_and_timeout() -> None:
    tracker = CommandBatchTracker(timeout_seconds=5.0)
    tracker.start("exec-1", ["r1", "r2", "r3"], now=10.0)
    tracker.ack("exec-1", "r1", "ok", "done")
    tracker.ack("exec-1", "r2", "error", "missing message package")

    assert tracker.expire(now=14.9) == []
    assert tracker.expire(now=15.1) == ["exec-1"]
    assert tracker.expire(now=20.0) == []

    result = tracker.result("exec-1")
    assert result.counts() == {"success": 1, "failed": 1, "timeout": 1}
    assert result.details["r2"].message == "missing message package"
    assert result.details["r3"].status == "timeout"


def test_completed_history_limit_never_evicts_active_batches() -> None:
    tracker = CommandBatchTracker(max_completed=20)
    tracker.start("active", ["waiting"], now=0.0)

    for index in range(21):
        exec_id = "done-{}".format(index)
        tracker.start(exec_id, ["r1"], now=float(index))
        assert tracker.ack(exec_id, "r1", "ok", "") is True

    assert tracker.result("active") is not None
    assert tracker.result("done-0") is None
    assert tracker.result("done-1") is not None
    assert tracker.result("done-20") is not None
