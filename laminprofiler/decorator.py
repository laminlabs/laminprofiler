"""Optional identity and duration cap for a profiling task."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

F = TypeVar("F", bound=Callable)

# lamindb Record.uid is at most 16 characters.
_MAX_UID_LENGTH = 16


def laminprofiler(
    uid: str | None = None, *, total_seconds: float | None = None
) -> Callable[[F], F]:
    """Pin a task id, a duration cap, or both.

    Pytest identifies a test by its path and name. This decorator is optional.
    Without a uid, laminprofiler keeps using the function name. Without
    `total_seconds`, the run records the duration and does not fail the task.

    Args:
        uid: Stable id, 1 to 16 characters, stored on the task record.
        total_seconds: Maximum allowed duration. The run fails when the task is slower.
    """
    if uid is None and total_seconds is None:
        raise ValueError("pass a uid, total_seconds, or both")
    if uid is not None and (
        not isinstance(uid, str) or not uid or len(uid) > _MAX_UID_LENGTH
    ):
        raise ValueError(f"uid must be a string of 1 to {_MAX_UID_LENGTH} characters")
    if total_seconds is not None and (
        isinstance(total_seconds, bool)
        or not isinstance(total_seconds, int | float)
        or total_seconds <= 0
    ):
        raise ValueError("total_seconds must be a positive number of seconds")

    seconds = None if total_seconds is None else float(total_seconds)

    def decorator(func: F) -> F:
        if uid is not None:
            func.__laminprofiler_uid__ = uid  # type: ignore[attr-defined]
        if seconds is not None:
            func.__laminprofiler_total_seconds__ = seconds  # type: ignore[attr-defined]
        return func

    return decorator
