"""Canonical recommendation task transition rules."""

from __future__ import annotations

from .enums import TaskStatus


TERMINAL_STATES = {
    TaskStatus.COMPLETED,
    TaskStatus.DEGRADED_COMPLETED,
    TaskStatus.FAILED,
}

_NORMAL_TRANSITIONS: dict[
    TaskStatus, set[TaskStatus]
] = {
    TaskStatus.CREATED: {TaskStatus.UNDERSTANDING},
    TaskStatus.UNDERSTANDING: {TaskStatus.PROBING},
    TaskStatus.PROBING: {TaskStatus.DECIDING},
    TaskStatus.DECIDING: {
        TaskStatus.WAITING_CLARIFICATION,
        TaskStatus.RECALLING,
    },
    TaskStatus.WAITING_CLARIFICATION: {TaskStatus.UNDERSTANDING},
    TaskStatus.RECALLING: {TaskStatus.RANKING},
    TaskStatus.RANKING: {
        TaskStatus.REPLANNING,
        TaskStatus.EXPLAINING,
    },
    TaskStatus.REPLANNING: {TaskStatus.RECALLING},
    TaskStatus.EXPLAINING: {TaskStatus.PERSISTING},
    TaskStatus.PERSISTING: {
        TaskStatus.COMPLETED,
        TaskStatus.DEGRADED_COMPLETED,
    },
}


def can_transition(
    current: TaskStatus,
    target: TaskStatus,
) -> bool:
    if current in TERMINAL_STATES:
        return False
    if target is TaskStatus.FAILED:
        return True
    return target in _NORMAL_TRANSITIONS.get(current, set())
