from pathlib import Path

import pytest
from laminprofiler.bench import (
    IMPORT_ROUNDS,
    IMPORT_WARMUP_ROUNDS,
    package_name_from_path,
    profile_function_names,
    profiling_scripts,
    registry_names,
    run_benchmarks,
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
    assert registry_names(script) == ["profile_curate_simple_dataframe"]


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
    assert result.name == "profile_fast"
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
    assert result.name == "profile_import_marker"
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
