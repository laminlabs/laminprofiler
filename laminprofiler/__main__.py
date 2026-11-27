import importlib
import os
from pathlib import Path

import click
import lamindb as ln

from laminprofiler.bench import (
    package_name_from_path,
    profiling_scripts,
    run_benchmarks,
    tasks_over_budget,
)
from laminprofiler.output import (
    ARTIFACT_KIND,
    BENCHMARK_DESCRIPTION,
    COVERAGE_DESCRIPTION,
    INSTANCE,
    MEASUREMENT_COLUMNS,
    benchmark_payload,
    cast_categorical_columns,
    categorical_column_names,
    coverage_ratio,
    current_commit_hash16,
    current_runner_env,
    github_run_extra_data,
    measurement_row,
    record_registry_requested,
)
from laminprofiler.setup import (
    COMMIT_HASH16_UID,
    ensure_git_commit,
    get_or_create_artifact_schema,
    require_product,
    setup,
)

SHOULD_WRITE = (
    os.getenv("GITHUB_EVENT_NAME") is None or os.getenv("GITHUB_EVENT_NAME") == "push"
)


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


def _report_result(result, override: float | None) -> None:
    print(f"\n# {result.name}\n{result.source}\n")
    print("pyinstrument profile (not included in the median)")
    print(result.profile_text)
    limit = override if override is not None else result.total_seconds
    if limit is None:
        print(f"{result.name}: {result.duration:.3f}s")
    else:
        print(f"{result.name}: {result.duration:.3f}s (total_seconds {limit:g})")


def _scripts_by_package(results) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for result in results:
        package_name = package_name_from_path(Path(result.path))
        grouped.setdefault(package_name, []).append(result)
    return grouped


def _active_run():
    run = ln.context.run
    if run is None:
        raise click.ClickException("Benchmarking requires an active LaminDB run.")
    return run


def _flow_created_at(run):
    import pandas as pd

    stamp = pd.Timestamp(run.created_at)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def _product(name: str):
    try:
        return require_product(name)
    except LookupError as error:
        raise click.ClickException(str(error)) from error


def record_benchmark(result, package_name: str, version: str, commit, runner) -> None:
    """Save one measurement on the current flow run."""
    package = ln.Record.get(name=package_name, type__name="LaminProfiler", is_type=True)
    task_type = ln.Record.get(name=result.name, type=package, is_type=True)
    features = {
        "package_version": version,
        "duration_in_sec": result.duration,
        "runner_env": runner,
        "task_source_hash": result.source_hash,
        "python_version": result.python_version,
    }
    if commit is not None:
        features["commit_hash16"] = commit
    payload = benchmark_payload(result)
    ln.Record(
        name=result.name,
        features=features,
        type=task_type,
        extra_data=None if payload is None else {"benchmark": payload},
    ).save()


def _write_parquet(
    measured: list[dict], commit_hash: str | None, runner: str | None
) -> None:
    run = _active_run()
    created_at = _flow_created_at(run)
    products = {}
    for item in measured:
        name = item["product"]
        if name not in products:
            products[name] = _product(name)
    if commit_hash is not None and products:
        ensure_git_commit(commit_hash, next(iter(products.values())))
    rows = [
        measurement_row(
            item["result"],
            product=item["product"],
            package_version=item["version"],
            commit_hash16=commit_hash,
            runner_env=runner,
            created_at=created_at,
            run=run.uid,
        )
        for item in measured
    ]
    import pandas as pd

    frame = pd.DataFrame(rows, columns=MEASUREMENT_COLUMNS)
    schema = get_or_create_artifact_schema()
    # Record features validate as pandas categories. A DataFrame of Python
    # strings stores them as object, and parquet keeps that dtype.
    cast_categorical_columns(frame, categorical_column_names(schema.members))
    extra = github_run_extra_data()
    kwargs = {
        "description": BENCHMARK_DESCRIPTION,
        "schema": schema,
    }
    if extra is not None:
        kwargs["extra_data"] = extra
    artifact = ln.Artifact.from_dataframe(frame, **kwargs)
    artifact.kind = ARTIFACT_KIND
    artifact.save()


def _save_coverage_record(coverage_xml: Path, product_name: str) -> None:
    ratio = coverage_ratio(coverage_xml)
    hash16 = current_commit_hash16()
    if hash16 is None:
        raise click.ClickException("Could not resolve the git commit.")
    product = _product(product_name)
    extra = github_run_extra_data()
    record = ensure_git_commit(hash16, product)
    schema = get_or_create_artifact_schema()
    commit_hash16 = next(
        feature for feature in schema.features.all() if feature.uid == COMMIT_HASH16_UID
    )
    artifact = ln.Artifact(
        coverage_xml,
        description=COVERAGE_DESCRIPTION,
        kind=ARTIFACT_KIND,
        extra_data=extra,
        features={commit_hash16: record},
    ).save()
    record.features.set_values(
        {
            "hash16": hash16,
            "repo": product,
            "coverage": ratio,
            "coverage_report": artifact,
        }
    )


@click.group(no_args_is_help=True)
def main():
    """Track benchmark and coverage runs."""


@main.command("benchmark", no_args_is_help=True)
@click.argument(
    "paths",
    nargs=-1,
    required=True,
    metavar="PATH...",
    type=click.Path(exists=True),
)
@click.option(
    "--output-format",
    type=click.Choice(["parquet", "records"]),
    default="parquet",
    show_default=True,
    help="parquet writes one artifact for the run. records writes one record per task.",
)
@click.option(
    "--threshold",
    default=None,
    type=float,
    help="Max allowed duration in seconds for every task in this run. "
    "Overrides total_seconds on @laminprofiler. "
    "Omit it to use each task's total_seconds.",
)
def benchmark_command(
    paths: tuple[str, ...], threshold: float | None, output_format: str
) -> None:
    """Run profile_* functions with pytest.

    laminprofiler benchmark profiling_tests

    laminprofiler benchmark profiling_tests/my_script.py

    A directory runs each profile_* function in the Python files placed
    directly in it, and skips conftest.py plus names that start with an
    underscore. A file runs the profile_* functions in that file.
    """
    ln.connect(INSTANCE)
    benchmark(paths, threshold, output_format)


@ln.flow("BVQ42qdoymVS")
def benchmark(
    paths: tuple[str, ...], threshold: float | None, output_format: str
) -> None:
    """Measure profiling tasks and store one run."""
    scripts = collect_scripts(tuple(Path(path) for path in paths))
    if len(scripts) > 1:
        print(f"Running {len(scripts)} profiling files")
        for script in scripts:
            print(f"# {_display_path(script)}")
    try:
        results = run_benchmarks(scripts)
    except RuntimeError as error:
        raise click.ClickException(str(error)) from error

    commit_hash = current_commit_hash16()
    runner = current_runner_env()
    measured: list[dict] = []
    commit_record = None
    for package_name, package_results in _scripts_by_package(results).items():
        module = importlib.import_module(package_name, package=".")
        version = module.__version__
        if SHOULD_WRITE and record_registry_requested(output_format):
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
            if commit_hash is not None and commit_record is None:
                commit_record = ensure_git_commit(commit_hash, _product(package_name))
        for result in package_results:
            _report_result(result, threshold)
            measured.append(
                {"result": result, "product": package_name, "version": version}
            )
            if SHOULD_WRITE and record_registry_requested(output_format):
                record_benchmark(result, package_name, version, commit_record, runner)

    if SHOULD_WRITE and output_format == "parquet":
        _write_parquet(measured, commit_hash, runner)

    too_slow = tasks_over_budget(results, threshold)
    if too_slow:
        details = "\n".join(
            f"{result.name}: {result.duration:.3f}s > {limit:.3f}s"
            for result, limit in too_slow
        )
        raise click.ClickException(f"Profiling time exceeds total_seconds\n{details}")


@main.command("coverage")
@click.argument(
    "coverage_xml",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--product",
    required=True,
    help="Name of the Products record, for example lamindb.",
)
def coverage(coverage_xml: Path, product: str) -> None:
    """Log line coverage on a GitCommits record.

    The coverage artifact is annotated with `commit_hash16`.
    This command is not a tracked LaminDB run.
    """
    ln.connect(INSTANCE)
    _save_coverage_record(coverage_xml, product)


if __name__ == "__main__":
    main()
