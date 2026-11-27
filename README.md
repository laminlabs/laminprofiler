# laminprofiler: Track benchmark and profile runs

Public documentation to come soon. For now, see [this internal Slack thread](https://laminlabs.slack.com/archives/C04A88BKZPX/p1770068673745039).

Runs are written to `laminlabs/lamindb-dev` on a local run and on a GitHub `push`. Pull requests still enforce `--threshold` and do not write.

## Benchmark

Pass a directory to run every profiling file in it, or a file to run that one:

```bash
laminprofiler benchmark profiling_tests
laminprofiler benchmark profiling_tests/my_script.py --threshold 1.5
```

A directory runs each Python file placed directly in it, and skips `conftest.py` plus helper files whose names start with `_`. One `--threshold` applies to every task in that run.

The default `--output-format parquet` saves one unkeyed artifact for the run (`description="benchmarks"`, `kind="laminprofiler"`). On GitHub Actions the artifact's `extra_data` includes `gh_run_id`. The artifact uses the `laminprofiler-benchmarks-artifact` schema, with one row per task:

- `product` (a Products record)
- `task_name`
- `task_uid`
- `package_version`
- `duration_in_sec`
- `commit_hash16` (a GitCommits record)
- `runner_env`
- `task_source_hash`
- `python_version`
- `created_at`
- `run`
- `benchmark`

`--output-format records` writes one record per task instead of the parquet file.

## Record types

When a benchmark run writes records, laminprofiler:

- creates the `laminprofiler-benchmarks-record` schema with features:
  - `package_version`
  - `duration_in_sec`
  - `commit_hash16`
  - `runner_env`
  - `task_source_hash`
  - `python_version`
  - `created_at`
  - `run`
- registers those features under the `LaminProfiler` feature type
- creates (or reuses) the top-level `LaminProfiler` record type
- creates (or reuses) the package type (`<repo_name>`, normalized with `_`)
- creates one task type per `profile_*` function, without the `profile_` prefix

## Coverage

`laminprofiler coverage` writes a GitCommits record and a coverage artifact. It is not a tracked run.

```bash
laminprofiler coverage coverage.xml --product lamindb
```

The artifact has no key, `description="coverage"`, and `kind="laminprofiler"`. It is annotated with `commit_hash16`, the GitCommits record for this commit, and `product`, the Products record named with `--product`. That GitCommits record stores `hash16`, `repo`, `coverage`, and `coverage_report`.

## Benchmarks

Every task is a `profile_*` function run with pytest. Import and fixtures stay outside the median. `benchmark.pedantic` owns the rounds, and its `teardown` runs between rounds. After the timed rounds, laminprofiler profiles that same callable once with pyinstrument. That profile is not part of `duration_in_sec`.

Name the file something other than `test_*.py`, so the package's normal pytest run does not collect it.

An import benchmark is a `profile_import_*` function with no arguments. Each round starts a new Python process, so the import runs again instead of hitting `sys.modules`. The first round is dropped and the median of the remaining rounds is `duration_in_sec`.

```python
def profile_import_lamindb():
    import lamindb
```

```python
def profile_curate_simple_dataframe(benchmark, mini_immuno):
    df, schema = mini_immuno

    def save():
        ln.Artifact.from_dataframe(df, key="profile/mini_immuno.parquet", schema=schema).save()

    def teardown():
        ln.Artifact.get(key="profile/mini_immuno.parquet").delete(permanent=True)

    benchmark.pedantic(save, teardown=teardown, rounds=5, iterations=1, warmup_rounds=1)
```

```bash
laminprofiler benchmark tests/profiling
laminprofiler benchmark tests/profiling/curate.py --threshold 2
```

Pytest identifies a test by its file and function name, so renaming a function starts a new task. `@laminprofiler` is optional. Pass a uid to keep the same task record when the function is renamed. Pass `fail_seconds` to fail the run when that task is slower. `--threshold` overrides every `fail_seconds` for that one run.

```python
from laminprofiler import laminprofiler

@laminprofiler("k5F8p2Q1nX9a", fail_seconds=2)
def profile_curate_simple_dataframe(benchmark, mini_immuno):
    ...
```
