"""Discover profiling tasks and run pytest-benchmark function tasks."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
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
    path: str
    uid: str | None = None
    fail_seconds: float | None = None


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


def function_uid(script: Path, name: str) -> str | None:
    """Uid from an optional `@laminprofiler("...")` decorator."""
    return _mark(script, name)[0]


def function_fail_seconds(script: Path, name: str) -> float | None:
    """Duration cap from an optional `@laminprofiler(..., fail_seconds=...)` decorator."""
    return _mark(script, name)[1]


def _mark(script: Path, name: str) -> tuple[str | None, float | None]:
    tree = ast.parse(script.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return _mark_from_decorators(node.decorator_list)
    return None, None


def _mark_from_decorators(
    decorators: list[ast.expr],
) -> tuple[str | None, float | None]:
    for decorator in decorators:
        if not isinstance(decorator, ast.Call):
            continue
        func = decorator.func
        called = func.id if isinstance(func, ast.Name) else None
        if called is None and isinstance(func, ast.Attribute):
            called = func.attr
        if called != "laminprofiler":
            continue
        uid = None
        if decorator.args:
            arg = decorator.args[0]
            if (
                isinstance(arg, ast.Constant)
                and isinstance(arg.value, str)
                and arg.value
            ):
                uid = arg.value
        fail_seconds = None
        for keyword in decorator.keywords:
            if keyword.arg != "fail_seconds" or not isinstance(
                keyword.value, ast.Constant
            ):
                continue
            value = keyword.value.value
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            if value > 0:
                fail_seconds = float(value)
        return uid, fail_seconds
    return None, None


def tasks_over_budget(
    results: list[TaskResult], override: float | None
) -> list[tuple[TaskResult, float]]:
    """Tasks slower than `fail_seconds`, or slower than one command-wide override."""
    over: list[tuple[TaskResult, float]] = []
    for result in results:
        limit = override if override is not None else result.fail_seconds
        if limit is not None and result.duration > limit:
            over.append((result, limit))
    return over


def task_name(function_name: str) -> str:
    """Registry name for a collected `profile_*` function."""
    return function_name.removeprefix("profile_")


def registry_names(script: Path) -> list[str]:
    """Task names a profiling file contributes to the registry."""
    return [task_name(name) for name in profile_function_names(script)]


def profiling_scripts(path: Path) -> list[Path]:
    """One Python script, or each script placed directly in a directory.

    Directory runs skip `conftest.py` and helper modules whose names start with `_`.
    """
    path = Path(path)
    if path.is_file():
        if path.suffix != ".py":
            raise ValueError(f"{path} is not a Python file")
        return [path.resolve()]
    if not path.is_dir():
        raise ValueError(f"{path} is not a file or directory")
    return [
        script.resolve()
        for script in sorted(path.glob("*.py"))
        if script.is_file()
        and not script.name.startswith("_")
        and script.name != "conftest.py"
    ]


def package_name_from_path(path: Path, *, cwd: Path | None = None) -> str:
    """Import name of the package that owns a profiling script or directory."""
    path = path.resolve()
    anchor = path.parent if path.is_file() else path
    if anchor.name == "profiling" and anchor.parent.name == "tests":
        return anchor.parent.parent.name.replace("-", "_")
    for parent in (anchor, *anchor.parents):
        if (parent / "pyproject.toml").is_file() or (parent / "setup.py").is_file():
            return parent.name.replace("-", "_")
    root = Path.cwd() if cwd is None else cwd
    return root.name.replace("-", "_")


IMPORT_WARMUP_ROUNDS = 1
IMPORT_ROUNDS = 5


def _is_import_benchmark(name: str) -> bool:
    return name.startswith("profile_import_")


def _parameter_names(script: Path, name: str) -> list[str]:
    tree = ast.parse(script.read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return [arg.arg for arg in node.args.args]
    raise LookupError(f"Function {name} not found in {script}")


def run_benchmarks(targets: Path | list[Path]) -> list[TaskResult]:
    """Time `profile_*` functions with pytest, then profile each once.

    pytest-benchmark owns the rounds. The pyinstrument pass runs after those
    rounds, so it is not part of `duration`.

    `profile_import_*` functions are the exception: each round is a new
    Python process, so a repeated import is measured again.
    """
    scripts = [targets] if isinstance(targets, Path) else list(targets)
    scripts = [script.resolve() for script in scripts]
    if not scripts:
        raise RuntimeError("No profiling scripts were given")
    import_tasks = [
        (script, name)
        for script in scripts
        for name in profile_function_names(script)
        if _is_import_benchmark(name)
    ]
    pytest_scripts = [
        script
        for script in scripts
        if any(
            not _is_import_benchmark(name) for name in profile_function_names(script)
        )
    ]
    results: list[TaskResult] = []
    if pytest_scripts:
        keyword = "not profile_import_" if import_tasks else None
        results.extend(_run_pytest(pytest_scripts, keyword=keyword))
    results.extend(_run_import_benchmark(script, name) for script, name in import_tasks)
    if not results:
        joined = ", ".join(str(script) for script in scripts)
        raise RuntimeError(f"No profile_* benchmarks ran in {joined}")
    return results


def _run_pytest(scripts: list[Path], *, keyword: str | None) -> list[TaskResult]:
    """Run in-process `profile_*` benchmarks in one pytest session."""
    rootdir = Path(os.path.commonpath([script.parent for script in scripts]))
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
            *[str(script) for script in scripts],
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
            str(rootdir),
            "--tb=short",
            "-v",
            "-rP",
        ]
        if keyword is not None:
            command.extend(["-k", keyword])
        # Inherit the terminal. Capturing and replaying stdout, then stderr,
        # splits pytest's report from the benchmark table.
        completed = subprocess.run(
            command,
            env=env,
            check=False,
        )
        # 5 is pytest's "no tests collected".
        if completed.returncode not in (0, 5):
            raise subprocess.CalledProcessError(completed.returncode, command)
        if not benchmark_json.exists():
            joined = ", ".join(str(script) for script in scripts)
            raise RuntimeError(f"No profile_* benchmarks ran in {joined}")
        payload = json.loads(benchmark_json.read_text())
        python_version = (
            payload.get("machine_info", {}).get("python_version")
            or f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )
        results: list[TaskResult] = []
        for benchmark in payload.get("benchmarks", []):
            name = benchmark["name"]
            fullname = benchmark["fullname"]
            script = _script_for_node(fullname, scripts, rootdir)
            stats = benchmark["stats"]
            duration = float(stats.get("median", stats["mean"]))
            profile_path = out / f"{_safe_name(fullname)}.txt"
            profile_text = (
                profile_path.read_text()
                if profile_path.exists()
                else "No pyinstrument profile was captured.\n"
            )
            func_name = name.split("[", 1)[0]
            source = function_source(script, func_name)
            uid, fail_seconds = _mark(script, func_name)
            results.append(
                TaskResult(
                    name=task_name(name),
                    source=source,
                    duration=duration,
                    profile_text=profile_text,
                    benchmark_json=json.dumps(benchmark, indent=2),
                    source_hash=source_hash(source),
                    python_version=python_version,
                    path=str(script),
                    uid=uid,
                    fail_seconds=fail_seconds,
                )
            )
        if not results:
            joined = ", ".join(str(script) for script in scripts)
            raise RuntimeError(f"No profile_* benchmarks ran in {joined}")
        return results


def _run_import_benchmark(script: Path, name: str) -> TaskResult:
    """Time one import benchmark. Every round is a new Python process."""
    if _parameter_names(script, name):
        raise RuntimeError(
            f"{name} runs in a fresh Python process per round and takes no arguments"
        )
    call = _import_call_source(script, name)
    durations: list[float] = []
    for _ in range(IMPORT_WARMUP_ROUNDS + IMPORT_ROUNDS):
        started = time.perf_counter()
        completed = _run_python(call)
        durations.append(time.perf_counter() - started)
        sys.stdout.write(completed.stdout)
        sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise subprocess.CalledProcessError(completed.returncode, completed.args)
    measured = durations[IMPORT_WARMUP_ROUNDS:]
    median = statistics.median(measured)
    profile = _run_python(_import_profile_source(script, name))
    if profile.returncode != 0:
        sys.stdout.write(profile.stdout)
        sys.stderr.write(profile.stderr)
        raise subprocess.CalledProcessError(profile.returncode, profile.args)
    source = function_source(script, name)
    uid, fail_seconds = _mark(script, name)
    rounds = {
        "warmup_rounds": IMPORT_WARMUP_ROUNDS,
        "rounds": measured,
        "median": median,
    }
    return TaskResult(
        name=task_name(name),
        source=source,
        duration=median,
        profile_text=profile.stdout,
        benchmark_json=json.dumps(rounds, indent=2),
        source_hash=source_hash(source),
        python_version=_python_version(),
        path=str(script),
        uid=uid,
        fail_seconds=fail_seconds,
    )


def _python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def _import_call_source(script: Path, name: str) -> str:
    return (
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('_laminprofiler_import', {str(script)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        f"getattr(module, {name!r})()\n"
    )


def _import_profile_source(script: Path, name: str) -> str:
    return (
        "from pyinstrument import Profiler\n"
        "import importlib.util\n"
        f"spec = importlib.util.spec_from_file_location('_laminprofiler_import', {str(script)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "profiler = Profiler()\n"
        "profiler.start()\n"
        "try:\n"
        "    spec.loader.exec_module(module)\n"
        f"    getattr(module, {name!r})()\n"
        "finally:\n"
        "    profiler.stop()\n"
        "print(profiler.output_text(unicode=True, color=False), end='')\n"
    )


def _run_python(source: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "run.py"
        path.write_text(source)
        return subprocess.run(
            [sys.executable, str(path)],
            check=False,
            capture_output=True,
            text=True,
        )


def _script_for_node(fullname: str, scripts: list[Path], rootdir: Path) -> Path:
    """Map a pytest node id back to one of the files that were run."""
    node_file = Path(fullname.split("::", 1)[0])
    by_resolved = {script.resolve(): script for script in scripts}
    candidates = [node_file]
    if not node_file.is_absolute():
        candidates = [rootdir / node_file, node_file]
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in by_resolved:
            return by_resolved[resolved]
    raise LookupError(f"No profiling file for {fullname}")


def _safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
