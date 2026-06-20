# laminprofiler: Track pyinstrument calls

Public documentation to come soon. For now, see [this internal Slack thread](https://laminlabs.slack.com/archives/C04A88BKZPX/p1770068673745039).

## Set up record types

Use `laminprofiler setup` to create the record types that `laminprofiler check` writes to.

```bash
laminprofiler setup
```

When run from a package repository root, this command:

- creates the `laminprofiler` schema with features:
  - `package_version`
  - `duration_in_sec`
  - `commit_hash16`
  - `runner_env`
- creates (or reuses) the top-level `LaminProfiler` type
- creates (or reuses) the package type (`<repo_name>`, normalized with `_`)
- creates (or reuses) task/script types for `tests/profiling/*.py`

You can also set up a single profiling script:

```bash
laminprofiler setup tests/profiling/my_benchmark.py
```

If profiling record types are missing, `laminprofiler check` raises an error telling you to run `laminprofiler setup`.

## Optional `cleanup()` hook for profiling scripts

If a profiling script defines a top-level `cleanup()` function, `laminprofiler` calls it after each profiling run (`run` and `check` commands). This is useful for deleting benchmark artifacts between repeats.

Use the script pattern below so importing the script does not run the benchmark body:

```python
def main():
    ...


def cleanup():
    ...


if __name__ == "__main__":
    main()
```
