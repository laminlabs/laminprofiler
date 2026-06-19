# laminprofiler: Track pyinstrument calls

Public documentation to come soon. For now, see [this internal Slack thread](https://laminlabs.slack.com/archives/C04A88BKZPX/p1770068673745039).

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
