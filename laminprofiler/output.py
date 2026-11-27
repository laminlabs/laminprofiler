"""Pure helpers for benchmark rows and coverage summaries."""

from __future__ import annotations

import json
import os
import subprocess
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from laminprofiler.bench import TaskResult

INSTANCE = "laminlabs/lamindb-dev"
ARTIFACT_KIND = "laminprofiler"
BENCHMARK_DESCRIPTION = "benchmarks"
COVERAGE_DESCRIPTION = "coverage"

MEASUREMENT_COLUMNS = [
    "product",
    "task_name",
    "task_uid",
    "package_version",
    "duration_in_sec",
    "commit_hash16",
    "runner_env",
    "task_source_hash",
    "python_version",
    "created_at",
    "run",
    "benchmark",
]


def record_registry_requested(output_format: str) -> bool:
    """Task types are created only when logging per-task records."""
    return output_format == "records"


def github_run_extra_data() -> dict[str, str] | None:
    """GitHub Actions run id, omitted outside Actions."""
    run_id = os.getenv("GITHUB_RUN_ID")
    if not run_id:
        return None
    return {"gh_run_id": run_id}


def current_commit_hash16() -> str | None:
    """16-character commit id from `GITHUB_SHA` or `git rev-parse`."""
    github_sha = os.getenv("GITHUB_SHA")
    if github_sha:
        return github_sha[:16]
    try:
        commit_hash = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    # 1 in a million collision probability (0.0001%) for 6.07 million commits
    return commit_hash[:16] if commit_hash else None


def current_runner_env() -> str | None:
    """`github_hosted` on a GitHub-hosted Actions runner."""
    if (
        os.getenv("GITHUB_ACTIONS") == "true"
        and os.getenv("RUNNER_ENVIRONMENT") == "github-hosted"
    ):
        return "github_hosted"
    return None


def _drop_empty_dicts(value):
    """Omit empty dicts. Parquet cannot write a struct with no fields."""
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item = _drop_empty_dicts(item)
            if isinstance(item, dict) and not item:
                continue
            cleaned[key] = item
        return cleaned
    if isinstance(value, list):
        cleaned = []
        for item in value:
            item = _drop_empty_dicts(item)
            if isinstance(item, dict) and not item:
                item = None
            cleaned.append(item)
        return cleaned
    return value


def benchmark_payload(result: TaskResult) -> dict | None:
    """Parsed per-task benchmark stats."""
    if result.benchmark_json is None:
        return None
    # pytest-benchmark stores extra_info as {} unless a test fills it.
    # An empty dict becomes a struct with no fields, which Parquet rejects.
    payload = _drop_empty_dicts(json.loads(result.benchmark_json))
    if not payload:
        return None
    return payload


def categorical_column_names(features) -> list[str]:
    """Feature uids stored as categoricals, such as record links."""
    columns: list[str] = []
    for feature in features:
        dtype = getattr(feature, "dtype_as_str", None) or ""
        if dtype.startswith("cat") and feature.uid:
            columns.append(feature.uid)
    return columns


def use_feature_uid_columns(frame, features):
    """Rename feature-name columns to feature uids.

    A schema with ``itype`` ``Feature.uid`` identifies each parquet column by
    that feature's uid.
    """
    rename = {}
    for feature in features:
        if feature.name in frame.columns and feature.uid:
            rename[feature.name] = feature.uid
    if not rename:
        return frame
    return frame.rename(columns=rename)


def cast_categorical_columns(frame, columns: list[str]):
    """Give record columns a pandas categorical dtype for schema validation."""
    import pandas as pd

    for name in columns:
        if name not in frame.columns:
            continue
        frame[name] = pd.Categorical(frame[name])
    return frame


def measurement_row(
    result: TaskResult,
    *,
    product: str,
    package_version: str,
    commit_hash16: str | None,
    runner_env: str | None,
    created_at,
    run: str,
) -> dict:
    """One parquet row for a measured task."""
    return {
        "product": product,
        "task_name": result.name,
        "task_uid": result.uid,
        "package_version": package_version,
        "duration_in_sec": result.duration,
        "commit_hash16": commit_hash16,
        "runner_env": runner_env,
        "task_source_hash": result.source_hash,
        "python_version": result.python_version,
        "created_at": created_at,
        "run": run,
        "benchmark": benchmark_payload(result),
    }


def coverage_ratio(path: Path) -> float:
    """Line coverage fraction from a `coverage.xml` report."""
    root = ET.parse(path).getroot()  # noqa: S314
    lines_valid = int(root.attrib["lines-valid"])
    if lines_valid == 0:
        raise ValueError("coverage.xml has no valid lines")
    lines_covered = int(root.attrib["lines-covered"])
    return lines_covered / lines_valid
