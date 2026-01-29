import importlib
import platform
import re
import shlex
import subprocess
from pathlib import Path

import click
import lamindb as ln


@click.group()
def main():
    """LaminProfiler."""


def parse_duration(path: Path) -> float:
    """Extract duration from pyinstrument output; line like 'Duration: 2.315     CPU time: 2.216'."""
    text = path.read_text()
    print(text)
    match = re.search(r"Duration:\s+([\d.]+)", text)
    return float(match.group(1)) if match else 0.0


def run_profiler(script: Path) -> None:
    """Run script 4 times with pyinstrument; profile0 warmup, profile1–3 for averaging."""
    script_str = str(script.resolve())
    is_darwin = platform.system() == "Darwin"
    for i in range(4):
        print(f"Running script {i}...")
        out = Path(f"profile{i}.txt")
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


@main.command("run")
@click.argument(
    "script",
    type=click.Path(path_type=Path, exists=True),
)
def run(script: Path) -> None:
    """Run script 4 times with pyinstrument; profile0 warmup, profile1–3 for averaging."""
    run_profiler(script)


@main.command("check")
@click.argument(
    "script",
    type=click.Path(path_type=Path, exists=True),
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
    help="Skip running the profiler; use existing profile1–3.txt.",
)
def check(script: Path, threshold: float | None, no_run: bool) -> None:
    ln.track("BVQ42qdoymVS")

    script = script.resolve()
    assert script.parent.name == "profiling"
    assert script.parent.parent.name == "tests"
    package_name = script.parent.parent.parent.name.replace("-", "_")
    script_basename = script.name

    if not no_run:
        run_profiler(script)

    # Last 3 runs (profile1–3); profile0 warms the cache.
    durations = [parse_duration(Path(f"profile{i}.txt")) for i in range(1, 4)]
    duration = sum(durations) / 3

    module = importlib.import_module(package_name, package=".")
    version = module.__version__

    print(f"Durations: {[f'{d:.3f}s' for d in durations]} → avg {duration:.3f}s")
    laminprofiler = ln.Record.get(name="LaminProfiler")
    package = ln.Record.get(name=package_name, type=laminprofiler, is_type=True).save()
    task = ln.Record.get(name=script_basename, type=package, is_type=True).save()
    measurement = ln.Record(type=task).save()
    measurement.features.add_values(
        {
            "package_version": version,
            "duration_in_sec": duration,
        }
    )

    if threshold is not None and duration > threshold:
        print(
            f"ERROR: Profiling time {duration:.3f}s exceeds threshold {threshold:.3f}s "
            f"for script {script_basename}"
        )
        raise SystemExit(1)

    ln.finish()


if __name__ == "__main__":
    assert ln.setup.settings.instance.slug == "laminlabs/lamindata"
    main()
