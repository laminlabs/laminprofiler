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


@main.command("run")
@click.argument(
    "script",
    type=click.Path(path_type=Path, exists=True),
)
def run(script: Path) -> None:
    """Run script 4 times with pyinstrument; write profile0.txt … profile3.txt."""
    script_str = str(script.resolve())
    is_darwin = platform.system() == "Darwin"
    for i in range(4):
        out = Path(f"profile{i}.txt")
        if is_darwin:
            # macOS: script [-q] file command [args...]; no -c.
            subprocess.run(
                ["script", "-q", str(out), "pyinstrument", script_str],
                check=True,
            )
        else:
            # Linux: script -q -c "command" file.
            cmd = f"pyinstrument {shlex.quote(script_str)}"
            subprocess.run(["script", "-q", "-c", cmd, str(out)], check=True)


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
@ln.flow()
def check(script: Path, threshold: float | None) -> None:
    script = script.resolve()
    assert script.parent.name == "profiling"
    assert script.parent.parent.name == "tests"
    package_name = script.parent.parent.parent.name.replace("-", "_")
    script_basename = script.name

    module = importlib.import_module(package_name, package=".")
    version = module.__version__

    # Parse duration from pyinstrument text output
    with open("profile.txt") as f:
        content = f.read()
        # Extract duration from line like: "Duration: 2.315     CPU time: 2.216"
        match = re.search(r"Duration:\s+([\d.]+)", content)
        duration = float(match.group(1)) if match else 1.0

    print(content)
    print(f"Extracted duration: {duration:.3f}s")
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


if __name__ == "__main__":
    assert ln.setup.settings.instance.slug == "laminlabs/lamindata"
    main()
