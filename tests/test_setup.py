from __future__ import annotations

import importlib
import sys
import types


class Query:
    def __init__(self, record):
        self._record = record

    def one_or_none(self):
        return self._record


class FakeFeature:
    _store: dict[str, FakeFeature] = {}

    def __init__(self, name, dtype):
        self.name = name
        self.dtype = dtype

    @classmethod
    def filter(cls, *, name):
        return Query(cls._store.get(name))

    def with_config(self, *, optional=False):
        assert optional
        return self, {"optional": True}

    def save(self):
        self.__class__._store[self.name] = self
        return self


class _Features:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class FakeSchema:
    _store: dict[str, FakeSchema] = {}

    def __init__(self, *, features, name):
        self.name = name
        self._features = []
        for feature in features:
            self._features.append(feature[0] if isinstance(feature, tuple) else feature)
        self.features = _Features(self._features)

    @classmethod
    def filter(cls, *, name):
        return Query(cls._store.get(name))

    def add(self, features, optional=True):
        assert optional
        items = features if isinstance(features, list) else [features]
        self._features.extend(items)
        return self

    def save(self):
        self.__class__._store[self.name] = self
        return self


class FakeRecord:
    _store: list[FakeRecord] = []

    def __init__(self, *, name, is_type, schema=None, type=None):
        self.name = name
        self.is_type = is_type
        self.schema = schema
        self.type = type
        self.schema_id = 1 if schema is not None else None

    @classmethod
    def filter(cls, *, name, is_type, type=None):
        record = next(
            (
                item
                for item in cls._store
                if item.name == name and item.is_type == is_type and item.type == type
            ),
            None,
        )
        return Query(record)

    def save(self):
        self.schema_id = 1 if self.schema is not None else None
        if self not in self.__class__._store:
            self.__class__._store.append(self)
        return self


def _load_setup(monkeypatch):
    FakeFeature._store = {}
    FakeSchema._store = {}
    FakeRecord._store = []
    fake_ln = types.SimpleNamespace(
        Feature=FakeFeature,
        Schema=FakeSchema,
        Record=FakeRecord,
    )
    monkeypatch.setitem(sys.modules, "lamindb", fake_ln)
    sys.modules.pop("laminprofiler.setup", None)
    return importlib.import_module("laminprofiler.setup")


def test_setup_creates_registry_with_expected_schema(monkeypatch):
    module = _load_setup(monkeypatch)
    module.setup(
        package_name="example_pkg",
        task_names=["bench_1", "bench_2"],
        verbose=False,
    )
    module.setup(
        package_name="example_pkg",
        task_names=["bench_1", "bench_2"],
        verbose=False,
    )
    schema = FakeSchema.filter(name=module.LAMINPROFILER_SCHEMA_NAME).one_or_none()
    registry = FakeRecord.filter(name="LaminProfiler", is_type=True).one_or_none()
    package = FakeRecord.filter(
        name="example_pkg", is_type=True, type=registry
    ).one_or_none()
    task_1 = FakeRecord.filter(name="bench_1", is_type=True, type=package).one_or_none()
    task_2 = FakeRecord.filter(name="bench_2", is_type=True, type=package).one_or_none()

    assert schema is not None
    assert schema.name == module.LAMINPROFILER_SCHEMA_NAME
    assert {feature.name for feature in schema.features.all()} == {
        "package_version",
        "duration_in_sec",
        "commit_hash16",
        "runner_env",
        "task_source_hash",
        "python_version",
    }
    assert registry.schema is None
    assert package is not None
    assert package.schema is None
    assert task_1 is not None
    assert task_2 is not None
    assert task_1.schema is schema
    assert task_2.schema is schema


def test_setup_adds_missing_optional_features(monkeypatch):
    module = _load_setup(monkeypatch)
    package_version = FakeFeature("package_version", str).save()
    duration = FakeFeature("duration_in_sec", float).save()
    existing = FakeSchema(
        features=[package_version, duration], name=module.LAMINPROFILER_SCHEMA_NAME
    ).save()

    schema = module.get_or_create_schema()

    assert schema is existing
    assert {feature.name for feature in schema.features.all()} == {
        "package_version",
        "duration_in_sec",
        "commit_hash16",
        "runner_env",
        "task_source_hash",
        "python_version",
    }
