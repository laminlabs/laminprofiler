"""Pytest plugin: profile one warm call after pytest-benchmark's timed rounds."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from pyinstrument import Profiler


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _wrap_benchmark(item: pytest.Item) -> dict:
    """Remember the callable passed to `benchmark.pedantic`."""
    state: dict = {}
    funcargs = getattr(item, "funcargs", {})
    benchmark = funcargs.get("benchmark")
    if benchmark is None or not hasattr(benchmark, "pedantic"):
        return state
    original = benchmark.pedantic

    def pedantic(target, *args, **kwargs):
        state["target"] = target
        state["teardown"] = kwargs.get("teardown")
        state["setup"] = kwargs.get("setup")
        state["args"] = kwargs.get("args", ())
        state["kwargs"] = kwargs.get("kwargs") or {}
        return original(target, *args, **kwargs)

    benchmark.pedantic = pedantic
    return state


def _prepare_call(state: dict) -> tuple[tuple, dict]:
    args = state["args"]
    kwargs = dict(state["kwargs"])
    setup = state.get("setup")
    if setup is not None:
        prepared = setup()
        if prepared is not None:
            args, kwargs = prepared
    return args, kwargs


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item):
    """Profile the pedantic target once, outside the measured rounds."""
    state = _wrap_benchmark(item)
    outcome = yield
    if outcome.excinfo is not None or "target" not in state:
        return
    args, kwargs = _prepare_call(state)
    profiler = Profiler()
    try:
        profiler.start()
        try:
            state["target"](*args, **kwargs)
        finally:
            profiler.stop()
        profile_text = profiler.output_text(unicode=True, color=False)
        profile_dir = os.environ.get("LAMINPROFILER_PROFILE_DIR")
        if profile_dir:
            path = Path(profile_dir) / f"{_safe_name(item.name)}.txt"
            path.write_text(profile_text)
    finally:
        teardown = state.get("teardown")
        if teardown is not None:
            teardown(*args, **kwargs)
