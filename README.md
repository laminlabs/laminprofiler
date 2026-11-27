# laminprofiler: Track benchmark and profile runs

Public documentation to come soon. For now, see [this internal Slack thread](https://laminlabs.slack.com/archives/C04A88BKZPX/p1770068673745039).

Records are written to `laminlabs/lamindb-benchmarks` on a local run and on a GitHub `push`. Pull requests still enforce `--threshold`.

## Run

Pass a directory to run every profiling file in it, or a file to run that one:

```bash
laminprofiler profiling_tests
laminprofiler profiling_tests/my_script.py --threshold 1.5
```

A directory runs each Python file placed directly in it, and skips `conftest.py` plus helper files whose names start with `_`. One `--threshold` applies to every task in that run.

## Record types

When a run writes records, laminprofiler:

- creates the `laminprofiler` schema with features:
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
- creates one task type per `profile_*` function

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
laminprofiler tests/profiling/curate.py --threshold 2
```
