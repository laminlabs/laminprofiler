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
    _store: list[FakeFeature] = []
    _next_id = 1

    def __init__(
        self, name, dtype=None, *, type=None, is_type=False, values_through=None
    ):
        self.name = name
        self.dtype = dtype
        self.id = FakeFeature._next_id
        FakeFeature._next_id += 1
        self.type = type
        self.is_type = is_type
        self.values_through = values_through
        self.uid = None

    @property
    def type(self):
        return self._type

    @type.setter
    def type(self, value):
        self._type = value
        self.type_id = None if value is None else value.id

    @classmethod
    def filter(cls, **kwargs):
        hits = [
            item
            for item in cls._store
            if all(getattr(item, key) == value for key, value in kwargs.items())
        ]
        if len(hits) > 1:
            raise AssertionError(kwargs)
        return Query(hits[0] if hits else None)

    def with_config(self, *, optional=False):
        assert optional
        return self, {"optional": True}

    def save(self):
        if self not in self.__class__._store:
            self.__class__._store.append(self)
        return self


class FakeRun:
    uid = "Run.uid"


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
        self.uid = None

    @classmethod
    def filter(cls, *, name=None, is_type=None, type=None, uid=None):
        if uid is not None and name is None:
            record = next((item for item in cls._store if item.uid == uid), None)
            return Query(record)
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
    FakeFeature._store = []
    FakeFeature._next_id = 1
    FakeSchema._store = {}
    FakeRecord._store = []
    fake_ln = types.SimpleNamespace(
        Feature=FakeFeature,
        Schema=FakeSchema,
        Record=FakeRecord,
        Run=FakeRun,
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
    features = {feature.name: feature for feature in schema.features.all()}
    assert set(features) == set(module.FEATURE_UIDS)
    assert all(features[name].uid == uid for name, uid in module.FEATURE_UIDS.items())
    assert all(feature.type.name == "LaminProfiler" for feature in features.values())
    assert all(
        feature.type.uid == module.FEATURE_TYPE_UID for feature in features.values()
    )
    assert all(feature.type.is_type for feature in features.values())
    assert features["created_at"].values_through == "created_at"
    assert features["created_at"].dtype == "datetime64[ns, UTC]"
    assert features["run"].values_through == "run"
    assert features["run"].dtype == "Run.uid"
    assert features["runner_env"].dtype is str
    assert len([feature for feature in FakeFeature._store if feature.is_type]) == 1
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
    assert {feature.name for feature in schema.features.all()} == set(
        module.FEATURE_UIDS
    )
    assert package_version.type.name == "LaminProfiler"
    assert package_version.type.is_type
    assert duration.type.name == "LaminProfiler"


def test_setup_creates_str_runner_env_beside_legacy_ulabel(monkeypatch):
    module = _load_setup(monkeypatch)
    legacy = FakeFeature("runner_env", "cat[ULabel[ljbGg49g]]").save()
    legacy.uid = module.FEATURE_UIDS["runner_env"]

    schema = module.get_or_create_schema()

    runner_env = next(
        feature for feature in schema.features.all() if feature.name == "runner_env"
    )
    assert runner_env is not legacy
    assert runner_env.dtype is str
    assert runner_env.uid != legacy.uid
    assert legacy.type is None


def test_setup_keeps_a_task_uid_when_the_name_changes(monkeypatch):
    module = _load_setup(monkeypatch)
    module.setup(
        package_name="example_pkg",
        task_names=["curate_simple_dataframe"],
        verbose=False,
    )
    module.setup(
        package_name="example_pkg",
        task_names=["curate_simple_dataframe"],
        task_uids={"curate_simple_dataframe": "k5F8p2Q1nX9a"},
        verbose=False,
    )
    module.setup(
        package_name="example_pkg",
        task_names=["curate_dataframe"],
        task_uids={"curate_dataframe": "k5F8p2Q1nX9a"},
        verbose=False,
    )
    registry = FakeRecord.filter(name="LaminProfiler", is_type=True).one_or_none()
    package = FakeRecord.filter(
        name="example_pkg", is_type=True, type=registry
    ).one_or_none()
    renamed = FakeRecord.filter(uid="k5F8p2Q1nX9a").one_or_none()
    assert renamed is not None
    assert renamed.name == "curate_dataframe"
    assert renamed.type is package
    assert (
        FakeRecord.filter(
            name="curate_simple_dataframe", is_type=True, type=package
        ).one_or_none()
        is None
    )
