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
- creates one task type per script, or per `profile_*` function when a file defines any

## Function benchmarks

A file that defines `profile_*` functions is run with pytest-benchmark. Import and fixtures are outside the median. `benchmark.pedantic` owns the rounds, and its `teardown` runs between rounds. After the timed rounds, laminprofiler profiles that same callable once with pyinstrument. That profile is not part of `duration_in_sec`.

Name the file something other than `test_*.py`, so the package's normal pytest run does not collect it.

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

## Script profiles

A `tests/profiling/*.py` file with no `profile_*` function is timed as a whole process with pyinstrument. Use this for import and cold-start tasks. `--repeats` greater than 1 drops the first run as warmup.

```bash
laminprofiler tests/profiling
laminprofiler tests/profiling/import_lamindb.py --threshold 1.5
```

## Optional `cleanup()` hook for profiling scripts

If a profiling script defines a top-level `cleanup()` function, `laminprofiler` calls it after each script run. This is useful for deleting benchmark artifacts between repeats.

Use the script pattern below so importing the script does not run the benchmark body:

```python
def main():
    ...


def cleanup():
    ...


if __name__ == "__main__":
    main()
```
