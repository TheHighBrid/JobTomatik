"""Per-attempt supervised target context.

The context is process-local, task-scoped, and automatically reset. It contains
only the already-safe target identity snapshot, never applicant answers or browser
secrets.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Mapping, Optional


_CURRENT_TARGET: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "jobtomatik_supervised_target",
    default=None,
)


def current_supervised_target() -> Optional[Dict[str, Any]]:
    value = _CURRENT_TARGET.get()
    return dict(value) if value else None


@contextmanager
def supervised_target_scope(
    metadata: Optional[Mapping[str, Any]],
) -> Iterator[None]:
    token = _CURRENT_TARGET.set(dict(metadata) if metadata else None)
    try:
        yield
    finally:
        _CURRENT_TARGET.reset(token)


__all__ = ["current_supervised_target", "supervised_target_scope"]
