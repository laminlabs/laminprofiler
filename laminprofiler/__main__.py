import importlib
import json
import os
import subprocess
from pathlib import Path

import click
import lamindb as ln

from laminprofiler.bench import (
    TaskResult,
    package_name_from_path,
    profiling_scripts,
    run_benchmarks,
    tasks_over_budget,
)
from laminprofiler.setup import setup

GITHUB_EVENT_NAME = os.getenv("GITHUB_EVENT_NAME")
SHOULD_WRITE_RECORDS = GITHUB_EVENT_NAME is None or GITHUB_EVENT_NAME == "push"
ln.connect("laminlabs/lamindb-benchmarks")


def current_commit_hash16() -> str | None:
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    # 1 in a million collision probability (0.0001%) for 6.07 million commits
    return commit_hash[:16] if commit_hash else None


def current_runner_env() -> str | None:
    if (
        os.getenv("GITHUB_ACTIONS") == "true"
        and os.getenv("RUNNER_ENVIRONMENT") == "github-hosted"
    ):
        return "github_hosted"
    return None


def collect_scripts(paths: tuple[Path, ...]) -> list[Path]:
    """Expand file and directory targets into profiling scripts."""
    if not paths:
        raise click.ClickException(
            "Pass a profiling script or a directory of profiling scripts."
        )
    scripts: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        try:
            found = profiling_scripts(path)
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        if not found:
            raise click.ClickException(f"No profiling scripts found in {path}")
        for script in found:
            if script in seen:
                continue
            seen.add(script)
            scripts.append(script)
    return scripts


def _display_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        return resolved.relative_to(Path.cwd())
    except ValueError:
        return resolved


# Filled by main() for the duration of record_benchmark().
_RESULTS: dict[str, tuple[TaskResult, str, str, str | None, str | None]] = {}


@ln.step()
def record_benchmark(task: str, source: str) -> None:
    """Save one measurement. `source` is the code that ran."""
    result, package_name, version, commit, runner = _RESULTS[task]
    if source != result.source:
        raise click.ClickException(f"Source for {task} does not match the measurement")
    package = ln.Record.get(name=package_name, type__name="LaminProfiler", is_type=True)
    task_type = ln.Record.get(name=task, type=package, is_type=True)
    extra_data = None
    if result.benchmark_json is not None:
        extra_data = {"benchmark": json.loads(result.benchmark_json)}
    ln.Record(
        name=result.name,
        features={
            "package_version": version,
            "duration_in_sec": result.duration,
            "commit_hash16": commit,
            "runner_env": runner,
            "task_source_hash": result.source_hash,
            "python_version": result.python_version,
        },
        type=task_type,
        extra_data=extra_data,
    ).save()


def _report_result(result: TaskResult, override: float | None) -> None:
    print(f"\n# {result.name}\n{result.source}\n")
    print("pyinstrument profile (not included in the median)")
    print(result.profile_text)
    limit = override if override is not None else result.total_seconds
    if limit is None:
        print(f"{result.name}: {result.duration:.3f}s")
    else:
        print(f"{result.name}: {result.duration:.3f}s (total_seconds {limit:g})")


def _scripts_by_package(results: list[TaskResult]) -> dict[str, list[TaskResult]]:
    grouped: dict[str, list[TaskResult]] = {}
    for result in results:
        package_name = package_name_from_path(Path(result.path))
        grouped.setdefault(package_name, []).append(result)
    return grouped


@click.command(no_args_is_help=True)
@click.argument(
    "paths",
    nargs=-1,
    required=True,
    metavar="PATH...",
    type=click.Path(exists=True),
)
@click.option(
    "--threshold",
    default=None,
    type=float,
    help="Max allowed duration in seconds for every task in this run. "
    "Overrides total_seconds on @laminprofiler. "
    "Omit it to use each task's total_seconds.",
)
@ln.flow("BVQ42qdoymVS")
def main(paths: tuple[str, ...], threshold: float | None) -> None:
    """Run profile_* functions with pytest.

    laminprofiler profiling_tests

    laminprofiler profiling_tests/my_script.py

    A directory runs each profile_* function in the Python files placed
    directly in it, and skips conftest.py plus names that start with an
    underscore. A file runs the profile_* functions in that file. The run
    creates any missing LaminProfiler features and task types.
    """
    scripts = collect_scripts(tuple(Path(path) for path in paths))
    if len(scripts) > 1:
        print(f"Running {len(scripts)} profiling files")
        for script in scripts:
            print(f"# {_display_path(script)}")
    try:
        results = run_benchmarks(scripts)
    except RuntimeError as error:
        raise click.ClickException(str(error)) from error

    for package_name, package_results in _scripts_by_package(results).items():
        module = importlib.import_module(package_name, package=".")
        version = module.__version__
        commit = current_commit_hash16()
        runner = current_runner_env()
        if SHOULD_WRITE_RECORDS:
            setup(
                package_name=package_name,
                task_names=[result.name for result in package_results],
                task_uids={
                    result.name: result.uid
                    for result in package_results
                    if result.uid is not None
                },
                verbose=False,
            )
        for result in package_results:
            _report_result(result, threshold)
            if SHOULD_WRITE_RECORDS:
                _RESULTS[result.name] = (
                    result,
                    package_name,
                    version,
                    commit,
                    runner,
                )
                record_benchmark(
                    task=result.name,
                    source=result.source,
                )

    too_slow = tasks_over_budget(results, threshold)
    if too_slow:
        details = "\n".join(
            f"{result.name}: {result.duration:.3f}s > {limit:.3f}s"
            for result, limit in too_slow
        )
        raise click.ClickException(f"Profiling time exceeds total_seconds\n{details}")


if __name__ == "__main__":
    main()
