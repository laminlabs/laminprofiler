from pathlib import Path

import pytest
from laminprofiler import laminprofiler
from laminprofiler.bench import (
    IMPORT_ROUNDS,
    IMPORT_WARMUP_ROUNDS,
    TaskResult,
    function_fail_seconds,
    function_uid,
    package_name_from_path,
    profile_function_names,
    profiling_scripts,
    registry_names,
    run_benchmarks,
    tasks_over_budget,
)


def test_registry_names_follow_profile_functions(tmp_path: Path):
    script = tmp_path / "curate.py"
    script.write_text(
        "def helper():\n"
        "    return 1\n"
        "\n"
        "def profile_curate_simple_dataframe():\n"
        "    return helper()\n"
    )
    assert profile_function_names(script) == ["profile_curate_simple_dataframe"]
    assert registry_names(script) == ["curate_simple_dataframe"]


def test_laminprofiler_mark_is_optional(tmp_path: Path):
    script = tmp_path / "curate.py"
    script.write_text(
        "from laminprofiler import laminprofiler\n"
        "\n"
        "@laminprofiler('k5F8p2Q1nX9a', fail_seconds=2)\n"
        "def profile_curate_simple_dataframe():\n"
        "    return 1\n"
        "\n"
        "@laminprofiler(fail_seconds=1.5)\n"
        "def profile_import_lamindb():\n"
        "    return 2\n"
        "\n"
        "def profile_other():\n"
        "    return 3\n"
    )
    assert function_uid(script, "profile_curate_simple_dataframe") == "k5F8p2Q1nX9a"
    assert function_fail_seconds(script, "profile_curate_simple_dataframe") == 2
    assert function_uid(script, "profile_import_lamindb") is None
    assert function_fail_seconds(script, "profile_import_lamindb") == 1.5
    assert function_uid(script, "profile_other") is None
    assert function_fail_seconds(script, "profile_other") is None

    @laminprofiler("k5F8p2Q1nX9a", fail_seconds=2)
    def profile_curate_simple_dataframe():
        return 1

    assert profile_curate_simple_dataframe() == 1
    marked = profile_curate_simple_dataframe
    assert marked.__laminprofiler_uid__ == "k5F8p2Q1nX9a"  # type: ignore[attr-defined]
    assert marked.__laminprofiler_fail_seconds__ == 2  # type: ignore[attr-defined]


def test_laminprofiler_mark_requires_a_uid_or_fail_seconds():
    with pytest.raises(ValueError, match="uid"):
        laminprofiler()
    with pytest.raises(ValueError, match="uid"):
        laminprofiler("")
    with pytest.raises(ValueError, match="fail_seconds"):
        laminprofiler("k5F8p2Q1nX9a", fail_seconds=0)


def test_tasks_over_budget_uses_fail_seconds_unless_overridden():
    capped = TaskResult(
        name="import_lamindb",
        source="",
        duration=2,
        profile_text="",
        benchmark_json=None,
        source_hash="",
        python_version="3.12.0",
        path="import_lamindb.py",
        fail_seconds=1.5,
    )
    open_ended = TaskResult(
        name="describe_a_record",
        source="",
        duration=30,
        profile_text="",
        benchmark_json=None,
        source_hash="",
        python_version="3.12.0",
        path="describe_a_record.py",
    )
    assert [
        result.name for result, _ in tasks_over_budget([capped, open_ended], None)
    ] == ["import_lamindb"]
    assert tasks_over_budget([capped], 3) == []
    assert [result.name for result, _ in tasks_over_budget([open_ended], 20)] == [
        "describe_a_record"
    ]


def test_registry_names_are_empty_without_profile_functions(tmp_path: Path):
    script = tmp_path / "import_lamindb.py"
    script.write_text("import lamindb as ln\n")
    assert registry_names(script) == []


def test_function_benchmark_median_excludes_import_and_saves_a_profile(tmp_path: Path):
    script = tmp_path / "sample.py"
    script.write_text(
        "import time\n"
        "time.sleep(0.25)\n"
        "\n"
        "def profile_fast(benchmark):\n"
        "    def work():\n"
        "        time.sleep(0.02)\n"
        "    benchmark.pedantic(work, rounds=2, iterations=1, warmup_rounds=0)\n"
    )
    results = run_benchmarks(script)
    assert len(results) == 1
    result = results[0]
    assert result.name == "fast"
    assert result.source.startswith("def profile_fast")
    assert result.duration < 0.2
    assert "Duration:" in result.profile_text
    assert result.benchmark_json is not None
    assert '"median"' in result.benchmark_json


def test_import_benchmark_uses_a_fresh_process_per_round(tmp_path: Path):
    marker = tmp_path / "pids.txt"
    script = tmp_path / "import_sample.py"
    script.write_text(
        "import os\n"
        "from pathlib import Path\n"
        "\n"
        "def profile_import_marker():\n"
        f"    path = Path({str(marker)!r})\n"
        "    with path.open('a') as handle:\n"
        "        handle.write(f'{os.getpid()}\\n')\n"
    )
    results = run_benchmarks(script)
    assert len(results) == 1
    result = results[0]
    assert result.name == "import_marker"
    assert result.duration > 0
    assert "Duration:" in result.profile_text
    pids = [line for line in marker.read_text().splitlines() if line]
    assert len(set(pids)) == IMPORT_WARMUP_ROUNDS + IMPORT_ROUNDS + 1


def test_profiling_scripts_from_file_or_directory(tmp_path: Path):
    (tmp_path / "my_script.py").write_text("x = 1\n")
    (tmp_path / "_helper.py").write_text("x = 1\n")
    (tmp_path / "conftest.py").write_text("x = 1\n")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "other.py").write_text("x = 1\n")

    assert [path.name for path in profiling_scripts(tmp_path / "my_script.py")] == [
        "my_script.py"
    ]
    assert [path.name for path in profiling_scripts(tmp_path)] == ["my_script.py"]
    assert [path.name for path in profiling_scripts(nested)] == ["other.py"]


def test_profiling_scripts_rejects_non_python_file(tmp_path: Path):
    target = tmp_path / "notes.txt"
    target.write_text("hi\n")
    with pytest.raises(ValueError, match="not a Python file"):
        profiling_scripts(target)


def test_package_name_from_tests_profiling_layout(tmp_path: Path):
    script = tmp_path / "lamindb" / "tests" / "profiling" / "import_lamindb.py"
    script.parent.mkdir(parents=True)
    script.write_text("x = 1\n")
    assert package_name_from_path(script) == "lamindb"
    assert package_name_from_path(script.parent) == "lamindb"


def test_package_name_from_nearest_project_root(tmp_path: Path):
    root = tmp_path / "my-package"
    script_dir = root / "profiling_tests"
    script_dir.mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'my-package'\n")
    script = script_dir / "my_script.py"
    script.write_text("x = 1\n")
    assert package_name_from_path(script, cwd=tmp_path) == "my_package"
    assert package_name_from_path(script_dir, cwd=tmp_path) == "my_package"


def test_measurement_row_carries_task_product_and_benchmark():
    from datetime import datetime, timezone

    from laminprofiler.output import measurement_row

    created_at = datetime(2026, 11, 27, tzinfo=timezone.utc)
    fast = TaskResult(
        name="curate_simple_dataframe",
        source="def profile_curate_simple_dataframe():\n    pass\n",
        duration=0.08,
        profile_text="",
        benchmark_json='{"median": 0.08}',
        source_hash="abc",
        python_version="3.12.0",
        path="curate.py",
        uid="k5F8p2Q1nX9a",
    )
    plain = TaskResult(
        name="import_lamindb",
        source="",
        duration=1.2,
        profile_text="",
        benchmark_json=None,
        source_hash="def",
        python_version="3.12.0",
        path="import_lamindb.py",
    )
    curated = measurement_row(
        fast,
        product="lamindb",
        package_version="2.13a1",
        commit_hash16="487b32cddcc4f0ef",
        runner_env="github_hosted",
        created_at=created_at,
        run="iqwdAC2ZPpljcgj",
    )
    imported = measurement_row(
        plain,
        product="lamindb",
        package_version="2.13a1",
        commit_hash16=None,
        runner_env=None,
        created_at=created_at,
        run="iqwdAC2ZPpljcgj",
    )
    assert curated["product"] == "lamindb"
    assert curated["task_name"] == "curate_simple_dataframe"
    assert curated["task_uid"] == "k5F8p2Q1nX9a"
    assert curated["created_at"] is created_at
    assert curated["run"] == "iqwdAC2ZPpljcgj"
    assert curated["benchmark"] == {"median": 0.08}
    assert curated["commit_hash16"] == "487b32cddcc4f0ef"
    assert imported["task_uid"] is None
    assert imported["benchmark"] is None
    assert imported["commit_hash16"] is None


def test_benchmark_payload_omits_empty_dicts_so_parquet_can_store_it(tmp_path: Path):
    import json

    import pandas as pd
    from laminprofiler.output import benchmark_payload

    raw = {
        "median": 0.08,
        "extra_info": {},
        "stats": {"data": [0.08], "nested": {}},
        "kept": {"note": "warm"},
    }
    result = TaskResult(
        name="curate_simple_dataframe",
        source="",
        duration=0.08,
        profile_text="",
        benchmark_json=json.dumps(raw),
        source_hash="abc",
        python_version="3.12.0",
        path="curate.py",
    )
    payload = benchmark_payload(result)
    assert payload == {
        "median": 0.08,
        "stats": {"data": [0.08]},
        "kept": {"note": "warm"},
    }
    frame = pd.DataFrame(
        {
            "benchmark": [
                payload,
                {"warmup_rounds": 1, "rounds": [0.9], "median": 0.9},
                None,
            ]
        }
    )
    frame.to_parquet(tmp_path / "benchmark.parquet")


def test_record_registry_is_requested_only_for_records_output():
    from laminprofiler.output import record_registry_requested

    assert record_registry_requested("records") is True
    assert record_registry_requested("parquet") is False


def test_github_run_id_is_stored_only_when_actions_sets_it(monkeypatch):
    from laminprofiler.output import github_run_extra_data

    monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    assert github_run_extra_data() is None
    monkeypatch.setenv("GITHUB_RUN_ID", "4242")
    assert github_run_extra_data() == {"gh_run_id": "4242"}


def test_coverage_ratio_reads_line_counts(tmp_path: Path):
    from laminprofiler.output import coverage_ratio

    report = tmp_path / "coverage.xml"
    report.write_text(
        '<coverage lines-covered="80" lines-valid="100" line-rate="0.8"></coverage>\n'
    )
    assert coverage_ratio(report) == 0.8
