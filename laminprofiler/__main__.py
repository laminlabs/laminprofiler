import importlib
import importlib.util
import os
import platform
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

import click
import lamindb as ln

from laminprofiler.bench import (
    TaskResult,
    package_name_from_path,
    profile_function_names,
    profiling_scripts,
    run_function_benchmarks,
    source_hash,
)
from laminprofiler.cli import LaminProfilerGroup
from laminprofiler.setup import setup

GITHUB_EVENT_NAME = os.getenv("GITHUB_EVENT_NAME")
SHOULD_WRITE_RECORDS = GITHUB_EVENT_NAME is None or GITHUB_EVENT_NAME == "push"
ln.connect("laminlabs/lamindb-benchmarks")


@click.group(cls=LaminProfilerGroup, no_args_is_help=True)
def main():
    """Run profiling scripts."""


def load_cleanup_hook(script: Path):
    """Load an optional cleanup() from a profiling script."""
    module_name = f"_laminprofiler_{script.stem}"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cleanup = getattr(module, "cleanup", None)
    return cleanup if callable(cleanup) else None


def run_profiler(
    script: Path, repeats: int, *, profile_prefix: str = "profile"
) -> None:
    """Run script with pyinstrument; profile0 warmup, remaining runs for averaging."""
    script_str = str(script.resolve())
    is_darwin = platform.system() == "Darwin"
    cleanup_hook = load_cleanup_hook(script)
    if repeats == 1:
        print("WARNING: --repeats=1 disables cache warming; timing may be noisier.")
    for i in range(repeats):
        print(f"running script {i}...")
        out = Path(f"{profile_prefix}{i}.txt")
        try:
            if is_darwin:
                subprocess.run(
                    ["script", "-q", str(out), "pyinstrument", script_str],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                cmd = f"pyinstrument {shlex.quote(script_str)}"
                subprocess.run(
                    ["script", "-q", "-c", cmd, str(out)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        finally:
            if cleanup_hook is not None:
                cleanup_hook()


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


def current_python_version() -> str:
    return platform.python_version()


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


def _profile_prefix(script: Path, scripts: list[Path]) -> str:
    """Keep `profile0.txt` for one script. Give each file its own prefix."""
    if len(scripts) == 1:
        return "profile"
    return f"{script.stem}-profile"


@main.command("run")
@click.argument(
    "paths",
    nargs=-1,
    required=True,
    metavar="PATH...",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--repeats",
    default=4,
    type=click.IntRange(min=1),
    show_default=True,
    help="Number of profiling runs for a script. With repeats > 1, first run is warmup.",
)
def run(paths: tuple[Path, ...], repeats: int) -> None:
    """Profile scripts with pyinstrument.

    PATH is a script or a directory. A directory profiles each Python file
    placed directly in it. One script writes profile0.txt. Each script in a
    directory writes <name>-profile0.txt. With repeats > 1, the first run of
    each script is warmup.
    """
    scripts = collect_scripts(paths)
    for script in scripts:
        if len(scripts) > 1:
            print(f"# {_display_path(script)}")
        run_profiler(script, repeats, profile_prefix=_profile_prefix(script, scripts))


def _duration_from_profile(text: str) -> float:
    match = re.search(r"Duration:\s+([\d.]+)", text)
    return float(match.group(1)) if match else 0.0


def _run_script_task(
    script: Path, task_name: str, no_run: bool, repeats: int
) -> TaskResult:
    """Time a whole script. The duration is the mean pyinstrument Duration."""
    if not no_run:
        run_profiler(script, repeats)
    try:
        if repeats == 1 and no_run:
            print("WARNING: --repeats=1 disables cache warming; timing may be noisier.")
        measured = [0] if repeats == 1 else list(range(1, repeats))
        chunks: list[str] = []
        durations: list[float] = []
        for i in range(repeats):
            text = Path(f"profile{i}.txt").read_text()
            chunks.append(f"# profile{i}.txt\n{text}")
            if i in measured:
                durations.append(_duration_from_profile(text))
        source = script.read_text()
        return TaskResult(
            name=task_name,
            source=source,
            duration=sum(durations) / len(durations),
            profile_text="\n".join(chunks),
            benchmark_json=None,
            source_hash=source_hash(source),
            python_version=current_python_version(),
        )
    finally:
        for i in range(repeats):
            profile = Path(f"profile{i}.txt")
            if profile.exists():
                profile.unlink()


# Filled by check() for the duration of record_benchmark().
_RESULTS: dict[str, tuple[TaskResult, str, str, str | None, str | None]] = {}


@ln.step()
def record_benchmark(task: str, source: str, script: str) -> None:
    """Save one measurement. `source` is the code that ran."""
    result, package_name, version, commit, runner = _RESULTS[task]
    if source != result.source:
        raise click.ClickException(f"Source for {task} does not match the measurement")
    package = ln.Record.get(name=package_name, type__name="LaminProfiler", is_type=True)
    task_type = ln.Record.get(name=task, type=package, is_type=True)
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
    ).save()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        profile_path = root / "pyinstrument.txt"
        profile_path.write_text(result.profile_text)
        ln.Artifact(
            profile_path,
            key=f"laminprofiler/{package_name}/{task}/pyinstrument.txt",
            description=f"pyinstrument profile of {task} in {script}",
        ).save()
        if result.benchmark_json is not None:
            stats_path = root / "benchmark.json"
            stats_path.write_text(result.benchmark_json)
            ln.Artifact(
                stats_path,
                key=f"laminprofiler/{package_name}/{task}/benchmark.json",
                description=f"pytest-benchmark stats for {task}",
            ).save()


def _measure(script: Path, *, no_run: bool, repeats: int) -> list[TaskResult]:
    if profile_function_names(script):
        if no_run:
            raise click.ClickException(
                "--no-run applies to script profiles. "
                "Function benchmarks always run pytest-benchmark."
            )
        return run_function_benchmarks(script)
    return [_run_script_task(script, script.stem, no_run, repeats)]


def _report_result(result: TaskResult) -> None:
    print(f"\n# {result.name}\n{result.source}\n")
    if result.benchmark_json is not None:
        print("pyinstrument profile (not included in the median)")
    print(result.profile_text)
    print(f"{result.name}: {result.duration:.3f}s")


@main.command("profile", hidden=True)
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
    help="Max allowed duration in seconds. Exit 1 when a task exceeds it. "
    "Omit it to record the duration with no limit.",
)
@click.option(
    "--no-run",
    "no_run",
    is_flag=True,
    help="Skip running a script profiler; use existing profile files.",
)
@click.option(
    "--repeats",
    default=4,
    type=click.IntRange(min=1),
    show_default=True,
    help="Script runs. With repeats > 1, the first run is warmup. "
    "Function benchmarks take their rounds from benchmark.pedantic.",
)
@ln.flow("BVQ42qdoymVS")
def profile(
    paths: tuple[str, ...], threshold: float | None, no_run: bool, repeats: int
) -> None:
    """Run profiling scripts.

    laminprofiler profiling_tests

    laminprofiler profiling_tests/my_script.py

    A directory runs each Python file placed directly in it, and skips
    conftest.py plus names that start with an underscore. A file runs that
    script. The run creates any missing LaminProfiler features and task types.

    laminprofiler run PATH writes pyinstrument files in the working directory.
    """
    scripts = collect_scripts(tuple(Path(path) for path in paths))
    if no_run and len(scripts) > 1:
        raise click.ClickException("Pass one script to --no-run.")
    if any(profile_function_names(script) for script in scripts):
        print(
            "Function benchmarks use benchmark.pedantic for the median. "
            "--repeats applies to scripts."
        )
    if len(scripts) > 1:
        print(f"Running {len(scripts)} profiling scripts")

    results: list[TaskResult] = []
    for package_name, package_scripts in _scripts_by_package(scripts).items():
        module = importlib.import_module(package_name, package=".")
        version = module.__version__
        commit = current_commit_hash16()
        runner = current_runner_env()
        for script in package_scripts:
            if len(scripts) > 1:
                print(f"\n# {_display_path(script)}")
            script_results = _measure(script, no_run=no_run, repeats=repeats)
            if SHOULD_WRITE_RECORDS:
                setup(
                    package_name=package_name,
                    task_names=[result.name for result in script_results],
                    verbose=False,
                )
            for result in script_results:
                _report_result(result)
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
                        script=str(script),
                    )
                results.append(result)

    if threshold is None:
        return
    too_slow = [result for result in results if result.duration > threshold]
    if too_slow:
        details = "\n".join(
            f"{result.name}: {result.duration:.3f}s > {threshold:.3f}s"
            for result in too_slow
        )
        raise click.ClickException(f"Profiling time exceeds threshold\n{details}")


def _scripts_by_package(scripts: list[Path]) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = {}
    for script in scripts:
        grouped.setdefault(package_name_from_path(script), []).append(script)
    return grouped


if __name__ == "__main__":
    main()
