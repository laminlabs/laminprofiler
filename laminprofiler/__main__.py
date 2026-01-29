import importlib
import re
from pathlib import Path

import click
import lamindb as ln


@click.group()
def main():
    """LaminProfiler."""


@main.command("check")
@click.option(
    "--script",
    "script_path",
    required=True,
    type=click.Path(path_type=Path, exists=True),
    help="Path to the profiled script (package_name inferred from parent of script dir).",
)
@click.option(
    "--threshold",
    default=0.62,
    type=float,
    show_default=True,
    help="Max allowed duration in seconds; exit 1 if exceeded.",
)
def check(script_path: Path, threshold: float) -> None:
    script = script_path.resolve()
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

    if duration > threshold:
        print(
            f"ERROR: Profiling time {duration:.3f}s exceeds threshold {threshold:.3f}s "
            f"for script {script_basename}"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    assert ln.setup.settings.instance.slug == "laminlabs/lamindata"
    main()
