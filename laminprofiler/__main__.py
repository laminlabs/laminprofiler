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
    profile_function_names,
    registry_names,
    run_function_benchmarks,
    source_hash,
)
from laminprofiler.setup import setup

GITHUB_EVENT_NAME = os.getenv("GITHUB_EVENT_NAME")
SHOULD_WRITE_RECORDS = GITHUB_EVENT_NAME is None or GITHUB_EVENT_NAME == "push"
ln.connect("laminlabs/lamindb-benchmarks")


@click.group()
def main():
    """LaminProfiler."""


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


def run_profiler(script: Path, repeats: int) -> None:
    """Run script with pyinstrument; profile0 warmup, remaining runs for averaging."""
    script_str = str(script.resolve())
    is_darwin = platform.system() == "Darwin"
    cleanup_hook = load_cleanup_hook(script)
    if repeats == 1:
        print("WARNING: --repeats=1 disables cache warming; timing may be noisier.")
    for i in range(repeats):
        print(f"running script {i}...")
        out = Path(f"profile{i}.txt")
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


def parse_registry_names_from_script(script: Path) -> tuple[str, str]:
    script = script.resolve()
    assert script.parent.name == "profiling"
    assert script.parent.parent.name == "tests"
    package_name = script.parent.parent.parent.name.replace("-", "_")
    script_basename = script.stem
    return package_name, script_basename


@main.command("setup")
@click.argument(
    "script",
    required=False,
    type=click.Path(path_type=Path, exists=True),
)
def setup_command(script: Path | None) -> None:
    """Set up lamindb registry and schema for laminprofiler."""
    if script is not None:
        package_name, _script_basename = parse_registry_names_from_script(script)
        setup(package_name=package_name, task_names=registry_names(script))
        return

    package_name = Path.cwd().name.replace("-", "_")
    profiling_dir = Path.cwd() / "tests" / "profiling"
    task_names: list[str] = []
    for path in sorted(profiling_dir.glob("*.py")):
        if path.is_file() and not path.name.startswith("_"):
            task_names.extend(registry_names(path))
    setup(package_name=package_name, task_names=task_names)


@main.command("run")
@click.argument(
    "script",
    type=click.Path(path_type=Path, exists=True),
)
@click.option(
    "--repeats",
    default=4,
    type=click.IntRange(min=1),
    show_default=True,
    help="Number of profiling runs for a script. With repeats > 1, first run is warmup.",
)
def run(script: Path, repeats: int) -> None:
    """Run script with pyinstrument; profile0 warmup if repeats > 1."""
    run_profiler(script, repeats)


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


@main.command("check")
@click.argument(
    "script",
    type=click.Path(exists=True),
)
@click.option(
    "--threshold",
    default=None,
    type=float,
    help="Max allowed duration in seconds; exit 1 if exceeded. Omit to skip check.",
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
def check(script: str, threshold: float | None, no_run: bool, repeats: int) -> None:
    script_path = Path(script)
    package_name, script_basename = parse_registry_names_from_script(script_path)
    is_function_mode = bool(profile_function_names(script_path))

    if is_function_mode:
        if no_run:
            raise click.ClickException(
                "--no-run applies to script profiles. "
                "Function benchmarks always run pytest-benchmark."
            )
        print(
            "Function benchmarks use benchmark.pedantic for the median. "
            "--repeats applies to scripts."
        )
        results = run_function_benchmarks(script_path)
    else:
        results = [_run_script_task(script_path, script_basename, no_run, repeats)]

    module = importlib.import_module(package_name, package=".")
    version = module.__version__
    commit = current_commit_hash16()
    runner = current_runner_env()
    if SHOULD_WRITE_RECORDS:
        setup(
            package_name=package_name,
            task_names=[result.name for result in results],
            verbose=False,
        )
    for result in results:
        print(f"\n# {result.name}\n{result.source}\n")
        if result.benchmark_json is not None:
            print("pyinstrument profile (not included in the median)")
        print(result.profile_text)
        print(f"{result.name}: {result.duration:.3f}s")
        if SHOULD_WRITE_RECORDS:
            _RESULTS[result.name] = (result, package_name, version, commit, runner)
            record_benchmark(
                task=result.name, source=result.source, script=str(script_path)
            )

    if threshold is None:
        return
    too_slow = [result for result in results if result.duration > threshold]
    if too_slow:
        details = "\n".join(
            f"{result.name}: {result.duration:.3f}s > {threshold:.3f}s"
            for result in too_slow
        )
        raise click.ClickException(f"Profiling time exceeds threshold\n{details}")


if __name__ == "__main__":
    main()
