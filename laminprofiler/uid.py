"""Optional stable id for a profiling task."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F", bound=Callable)

# lamindb Record.uid is at most 16 characters.
_MAX_UID_LENGTH = 16


def uid(value: str) -> Callable[[F], F]:
    """Pin a task id that stays put when the function is renamed.

    Pytest identifies a test by its path and name. This decorator is optional.
    Without it, laminprofiler keeps using the function name.

    Args:
        value: Stable id, 1 to 16 characters, stored on the task record.
    """
    if not isinstance(value, str) or not value or len(value) > _MAX_UID_LENGTH:
        raise ValueError(f"uid must be a string of 1 to {_MAX_UID_LENGTH} characters")

    def decorator(func: F) -> F:
        func.__laminprofiler_uid__ = value  # type: ignore[attr-defined]
        return func

    return decorator
