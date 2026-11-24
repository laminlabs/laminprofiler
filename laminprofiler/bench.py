"""Discover profiling tasks and run pytest-benchmark function tasks."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TaskResult:
    """One measured task."""

    name: str
    source: str
    duration: float
    profile_text: str
    benchmark_json: str | None
    source_hash: str
    python_version: str


def source_hash(source: str) -> str:
    """Short hash of the measured source, so a benchmark edit is visible."""
    return hashlib.sha256(source.encode()).hexdigest()[:16]


def profile_function_names(script: Path) -> list[str]:
    """Module-level `profile_*` functions. Helpers and scripts are ignored."""
    tree = ast.parse(script.read_text())
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("profile_")
    ]


def function_source(script: Path, name: str) -> str:
    """Source of one module-level function."""
    text = script.read_text()
    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            segment = ast.get_source_segment(text, node)
            if segment is not None:
                return segment
    raise LookupError(f"Function {name} not found in {script}")


def registry_names(script: Path) -> list[str]:
    """Task names a profiling file contributes to the LaminProfiler registry."""
    names = profile_function_names(script)
    if names:
        return names
    return [script.stem]


def run_function_benchmarks(script: Path) -> list[TaskResult]:
    """Time `profile_*` functions with pytest-benchmark, then profile each once.

    The pyinstrument pass runs after the timed rounds, so it is not part of
    `duration`.
    """
    with tempfile.TemporaryDirectory() as directory:
        out = Path(directory)
        env = os.environ.copy()
        env.pop("PYTEST_ADDOPTS", None)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["LAMIN_SETTINGS_DIR"] = str(out / "lamin-home")
        env["LAMINPROFILER_PROFILE_DIR"] = str(out)
        benchmark_json = out / "benchmark.json"
        command = [
            sys.executable,
            "-m",
            "pytest",
            str(script.resolve()),
            "-p",
            "pytest_benchmark.plugin",
            "-p",
            "laminprofiler.plugin",
            "--benchmark-json",
            str(benchmark_json),
            "-o",
            "python_files=*.py",
            "-o",
            "python_functions=profile_*",
            "-o",
            "addopts=",
            "--noconftest",
            "--rootdir",
            str(script.parent),
            "-s",
            "--tb=short",
            "-q",
        ]
        completed = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(completed.returncode, command)
        payload = json.loads(benchmark_json.read_text())
        python_version = (
            payload.get("machine_info", {}).get("python_version")
            or f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
        results: list[TaskResult] = []
        for benchmark in payload.get("benchmarks", []):
            name = benchmark["name"]
            stats = benchmark["stats"]
            duration = float(stats.get("median", stats["mean"]))
            profile_path = out / f"{_safe_name(name)}.txt"
            profile_text = (
                profile_path.read_text()
                if profile_path.exists()
                else "No pyinstrument profile was captured.\n"
            )
            source = function_source(script, name)
            results.append(
                TaskResult(
                    name=name,
                    source=source,
                    duration=duration,
                    profile_text=profile_text,
                    benchmark_json=json.dumps(benchmark, indent=2),
                    source_hash=source_hash(source),
                    python_version=python_version,
                )
            )
        if not results:
            raise RuntimeError(f"No profile_* benchmarks ran in {script}")
        return results


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
