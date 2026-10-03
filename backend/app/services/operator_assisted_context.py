"""Explicit runtime context for retained operator-assisted final actions."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_OPERATOR_FINAL_ACTION_ACTIVE: ContextVar[bool] = ContextVar(
    "jobtomatik_operator_final_action_active",
    default=False,
)


def operator_final_action_active() -> bool:
    """Return whether execution is inside the explicit retained final-action scope."""
    return bool(_OPERATOR_FINAL_ACTION_ACTIVE.get())


@contextmanager
def operator_final_action_scope() -> Iterator[None]:
    """Temporarily identify the exact retained final-action gate evaluation."""
    token = _OPERATOR_FINAL_ACTION_ACTIVE.set(True)
    try:
        yield
    finally:
        _OPERATOR_FINAL_ACTION_ACTIVE.reset(token)


__all__ = ["operator_final_action_active", "operator_final_action_scope"]
