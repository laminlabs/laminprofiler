import importlib
import re

import click
import lamindb as ln


@click.group()
def main():
    """Laminprofiler CLI."""


@main.command("check")
def check():
    package_name = "lamindb_setup"
    module = importlib.import_module(package_name, package=".")
    version = module.__version__
    task_name = "import_lamindb_setup.py"
    threshold = 0.62

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
    task = ln.Record.get(name=task_name, type=package, is_type=True).save()
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
            f"for task {task_name}"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    assert ln.setup.settings.instance.slug == "laminlabs/lamindata"
    main()
