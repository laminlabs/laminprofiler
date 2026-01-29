import importlib
import re

import click
import lamindb as ln

assert ln.setup.settings.instance == "laminlabs/lamindata"


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
    task = ln.Record.get(name=task_name)
    record = ln.Record(type=task).save()
    record.features.add_values(
        {
            "package_name": package_name,
            "task_name": task_name,
            "package_version": version,
            "duration_in_sec": duration,
        }
    )
    ln.finish()

    if duration > threshold:
        print(
            f"ERROR: Profiling time {duration:.3f}s exceeds threshold {threshold:.3f}s "
            f"for task {task_name}"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
