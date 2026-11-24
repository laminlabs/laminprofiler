from pathlib import Path

from laminprofiler.bench import (
    profile_function_names,
    registry_names,
    run_function_benchmarks,
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


def test_registry_names_use_the_script_stem_without_profile_functions(tmp_path: Path):
    script = tmp_path / "import_lamindb.py"
    script.write_text("import lamindb as ln\n")
    assert registry_names(script) == ["import_lamindb"]


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
    results = run_function_benchmarks(script)
    assert len(results) == 1
    result = results[0]
    assert result.name == "profile_fast"
    assert result.source.startswith("def profile_fast")
    assert result.duration < 0.2
    assert "Duration:" in result.profile_text
    assert result.benchmark_json is not None
    assert '"median"' in result.benchmark_json
