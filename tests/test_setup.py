from __future__ import annotations

import importlib
import sys
import types


class Query:
    def __init__(self, record):
        if isinstance(record, list):
            self._records = record
        elif record is None:
            self._records = []
        else:
            self._records = [record]

    def one_or_none(self):
        if len(self._records) > 1:
            raise AssertionError(self._records)
        return self._records[0] if self._records else None

    def __iter__(self):
        return iter(self._records)


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
        return Query(hits)

    def with_config(self, *, optional=False):
        assert optional
        return self, {"optional": True}

    def save(self):
        if self not in self.__class__._store:
            self.__class__._store.append(self)
        return self


class FakeRun:
    uid = "Run.uid"


class FakeArtifact:
    pass


class _Features:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)

    def add(self, *features):
        for feature in features:
            item = feature[0] if isinstance(feature, tuple) else feature
            if item not in self._items:
                self._items.append(item)


class FakeSchema:
    _store: dict[str, FakeSchema] = {}
    _by_uid: dict[str, FakeSchema] = {}
    _next_id = 1

    def __init__(self, *, features=None, name, is_type=False, type=None):
        self.name = name
        self.is_type = is_type
        self.id = FakeSchema._next_id
        FakeSchema._next_id += 1
        self.type = type
        self.uid = None
        self._features = []
        for feature in features or []:
            self._features.append(feature[0] if isinstance(feature, tuple) else feature)
        self.features = _Features(self._features)

    @property
    def type(self):
        return self._type

    @type.setter
    def type(self, value):
        self._type = value
        self.type_id = None if value is None else value.id

    @classmethod
    def filter(cls, *, name=None, uid=None, is_type=None, type=None):
        if uid is not None:
            return Query(cls._by_uid.get(uid))
        found = cls._store.get(name) if name is not None else None
        if found is not None and is_type is not None and found.is_type != is_type:
            found = None
        if found is not None and type is not None and found.type != type:
            found = None
        return Query(found)

    def add(self, features, optional=True):
        items = features if isinstance(features, list) else [features]
        self._features.extend(items)
        return self

    def save(self, **kwargs):
        self.__class__._store[self.name] = self
        if getattr(self, "uid", None) is not None:
            self.__class__._by_uid[self.uid] = self
        return self

    @classmethod
    def get(cls, idlike=None, **kwargs):
        schema = cls._by_uid.get(idlike)
        if schema is None:
            schema = cls(features=[], name="GitCommits")
            schema.uid = idlike
            cls._by_uid[idlike] = schema
        return schema


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

    @classmethod
    def get(cls, idlike=None, **kwargs):
        if idlike == "tY22ouWHsJKDJaXL":
            return cls._type(name="Products", uid=idlike)
        if kwargs.get("is_type") and kwargs.get("schema") is not None:
            return cls._type(
                name="GitCommits", uid="GitCommitsType", schema=kwargs["schema"]
            )
        raise AssertionError((idlike, kwargs))

    @classmethod
    def _type(cls, *, name, uid, schema=None):
        found = next((item for item in cls._store if item.uid == uid), None)
        if found is not None:
            return found
        record = cls(name=name, is_type=True, schema=schema)
        record.uid = uid
        return record.save()

    def save(self):
        self.schema_id = 1 if self.schema is not None else None
        if self not in self.__class__._store:
            self.__class__._store.append(self)
        return self


def _load_setup(monkeypatch):
    FakeFeature._store = []
    FakeFeature._next_id = 1
    FakeSchema._store = {}
    FakeSchema._by_uid = {}
    FakeSchema._next_id = 1
    FakeRecord._store = []
    fake_ln = types.SimpleNamespace(
        Feature=FakeFeature,
        Schema=FakeSchema,
        Record=FakeRecord,
        Run=FakeRun,
        Artifact=FakeArtifact,
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
    schema = FakeSchema.filter(
        name=module.BENCHMARKING_SCHEMA_RECORD_NAME
    ).one_or_none()
    registry = FakeRecord.filter(name="LaminProfiler", is_type=True).one_or_none()
    package = FakeRecord.filter(
        name="example_pkg", is_type=True, type=registry
    ).one_or_none()
    task_1 = FakeRecord.filter(name="bench_1", is_type=True, type=package).one_or_none()
    task_2 = FakeRecord.filter(name="bench_2", is_type=True, type=package).one_or_none()

    assert schema is not None
    assert schema.name == module.BENCHMARKING_SCHEMA_RECORD_NAME
    assert schema.uid == module.BENCHMARKING_SCHEMA_RECORD_UID
    assert schema.type.name == module.SCHEMA_ROOT_TYPE_NAME
    assert schema.type.uid == module.SCHEMA_ROOT_TYPE_UID
    assert schema.type.is_type
    features = {feature.name: feature for feature in schema.features.all()}
    assert set(features) == set(module.BENCHMARKING_FEATURE_UIDS) | {"commit_hash16"}
    pinned = {name: features[name] for name in module.BENCHMARKING_FEATURE_UIDS}
    assert all(
        pinned[name].uid == uid
        for name, uid in module.BENCHMARKING_FEATURE_UIDS.items()
    )
    benchmark_features = [
        feature for name, feature in features.items() if name != "commit_hash16"
    ]
    assert all(feature.type.name == "Benchmarks" for feature in benchmark_features)
    assert all(
        feature.type.uid == module.FEATURE_BENCHMARKS_TYPE_UID
        for feature in benchmark_features
    )
    assert all(
        feature.type.type.name == "LaminProfiler" for feature in benchmark_features
    )
    assert all(
        feature.type.type.uid == module.FEATURE_ROOT_TYPE_UID
        for feature in benchmark_features
    )
    assert features["commit_hash16"].uid == module.ROOT_FEATURE_UIDS["commit_hash16"]
    assert features["commit_hash16"].type.uid == module.FEATURE_ROOT_TYPE_UID
    assert all(feature.type.is_type for feature in features.values())
    assert features["created_at"].values_through == "created_at"
    assert features["created_at"].dtype == "datetime64[ns, UTC]"
    assert features["run"].values_through == "run"
    assert features["run"].dtype == "Run.uid"
    assert features["runner_env"].dtype is str
    assert features["commit_hash16"].dtype.name == "GitCommits"
    assert len([feature for feature in FakeFeature._store if feature.is_type]) == 2
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
        features=[package_version, duration],
        name=module.BENCHMARKING_SCHEMA_RECORD_NAME,
    ).save()

    schema = module.get_or_create_schema()

    assert schema is existing
    assert schema.uid == module.BENCHMARKING_SCHEMA_RECORD_UID
    assert {feature.name for feature in schema.features.all()} == set(
        module.BENCHMARKING_FEATURE_UIDS
    ) | {"commit_hash16"}
    assert package_version.type is None
    assert duration.type is None
    created_at = next(
        feature for feature in schema.features.all() if feature.name == "created_at"
    )
    assert created_at.type.name == "Benchmarks"
    assert created_at.type.uid == module.FEATURE_BENCHMARKS_TYPE_UID


def test_setup_creates_str_runner_env_beside_legacy_ulabel(monkeypatch):
    module = _load_setup(monkeypatch)
    legacy = FakeFeature("runner_env", "cat[ULabel[ljbGg49g]]").save()
    legacy.uid = module.BENCHMARKING_FEATURE_UIDS["runner_env"]

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


def test_commit_hash16_is_not_the_legacy_string_feature(monkeypatch):
    module = _load_setup(monkeypatch)
    legacy = FakeFeature("commit_hash16", str).save()
    legacy.uid = "uaYdTQD761RE"

    schema = module.get_or_create_schema()

    commit = next(
        feature for feature in schema.features.all() if feature.name == "commit_hash16"
    )
    assert commit is not legacy
    assert commit.dtype.name == "GitCommits"
    assert commit.uid == module.ROOT_FEATURE_UIDS["commit_hash16"]
    assert commit.type.uid == module.FEATURE_ROOT_TYPE_UID


def test_git_commit_features_are_created(monkeypatch):
    module = _load_setup(monkeypatch)
    schema = module.ensure_git_commits_schema()
    assert schema.type.uid == module.SCHEMA_ROOT_TYPE_UID
    assert schema.type.is_type
    features = {feature.name: feature for feature in schema.features.all()}
    hash16 = features["hash16"]
    assert hash16.uid == module.GIT_COMMITS_FEATURE_UIDS["hash16"]
    assert hash16.dtype is str
    assert hash16.values_through == "name"
    assert hash16.type.uid == module.GIT_COMMITS_FEATURE_TYPE_UID
    assert hash16.type.type.uid == module.FEATURE_ROOT_TYPE_UID
    assert features["coverage"].uid == module.GIT_COMMITS_FEATURE_UIDS["coverage"]
    assert features["coverage"].dtype is float
    created_at = features["created_at"]
    assert created_at.uid == module.GIT_COMMITS_FEATURE_UIDS["created_at"]
    assert created_at.dtype == "datetime"
    assert created_at.values_through == "created_at"
    coverage_xml = features["coverage_xml"]
    assert coverage_xml.uid == module.GIT_COMMITS_FEATURE_UIDS["coverage_xml"]
    assert coverage_xml.dtype is FakeArtifact
    assert coverage_xml.values_through.uid == module.ROOT_FEATURE_UIDS["commit_hash16"]
    assert coverage_xml.values_through.type.uid == module.FEATURE_ROOT_TYPE_UID
    assert features["product"].uid == module.ROOT_FEATURE_UIDS["product"]
    assert features["product"].type.uid == module.FEATURE_ROOT_TYPE_UID
    benchmarks = FakeFeature.filter(
        uid=module.GIT_COMMITS_FEATURE_UIDS["benchmarks"]
    ).one_or_none()
    assert benchmarks is not None
    assert benchmarks.dtype == list[FakeArtifact]
    assert benchmarks.values_through.uid == module.ROOT_FEATURE_UIDS["commit_hash16"]
    assert "benchmarks" not in features


def test_artifact_schema_adds_product_task_and_benchmark(monkeypatch):
    module = _load_setup(monkeypatch)
    schema = module.get_or_create_artifact_schema()
    features = {feature.name: feature for feature in schema.features.all()}
    assert schema.name == module.BENCHMARKING_SCHEMA_ARTIFACT_NAME
    assert schema.uid == module.BENCHMARKING_SCHEMA_ARTIFACT_UID
    assert schema.type.uid == module.SCHEMA_ROOT_TYPE_UID
    assert schema.type.is_type
    assert features["product"].dtype.uid == "tY22ouWHsJKDJaXL"
    assert features["product"].uid == module.ROOT_FEATURE_UIDS["product"]
    assert features["product"].type.uid == module.FEATURE_ROOT_TYPE_UID
    assert features["commit_hash16"].type.uid == module.FEATURE_ROOT_TYPE_UID
    assert features["task_name"].type.uid == module.FEATURE_BENCHMARKS_TYPE_UID
    git_commits = FakeSchema.get(module.GIT_COMMITS_SCHEMA_UID)
    git_product = next(
        feature for feature in git_commits.features.all() if feature.name == "product"
    )
    assert git_product is features["product"]
    assert features["task_name"].dtype is str
    assert features["task_uid"].dtype is str
    assert features["benchmark"].dtype is dict
    assert features["commit_hash16"].dtype.name == "GitCommits"
    assert features["commit_hash16"].uid == module.ROOT_FEATURE_UIDS["commit_hash16"]
