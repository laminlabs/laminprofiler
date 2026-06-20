import importlib
import sys
import types


def test_setup_creates_registry_with_expected_schema(monkeypatch):
    class Query:
        def __init__(self, record):
            self._record = record

        def one_or_none(self):
            return self._record

    class FakeFeature:
        _store = {}

        def __init__(self, name, dtype):
            self.name = name
            self.dtype = dtype

        @classmethod
        def filter(cls, *, name):
            return Query(cls._store.get(name))

        def with_config(self, *, optional=False):
            assert optional
            return self

        def save(self):
            self.__class__._store[self.name] = self
            return self

    class FakeSchema:
        _store = {}

        def __init__(self, *, features, name):
            self.features = features
            self.name = name

        @classmethod
        def filter(cls, *, name):
            return Query(cls._store.get(name))

        def save(self):
            self.__class__._store[self.name] = self
            return self

    class FakeRecord:
        _store = []

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
                    if item.name == name
                    and item.is_type == is_type
                    and item.type == type
                ),
                None,
            )
            return Query(record)

        def save(self):
            self.schema_id = 1 if self.schema is not None else None
            if self not in self.__class__._store:
                self.__class__._store.append(self)
            return self

    fake_ln = types.SimpleNamespace(
        Feature=FakeFeature,
        Schema=FakeSchema,
        Record=FakeRecord,
    )

    monkeypatch.setitem(sys.modules, "lamindb", fake_ln)
    sys.modules.pop("laminprofiler.setup", None)
    module = importlib.import_module("laminprofiler.setup")

    schema = module.setup(
        package_name="example_pkg",
        script_basenames=["bench_1.py", "bench_2.py"],
        verbose=False,
    )
    schema_repeat = module.setup(
        package_name="example_pkg",
        script_basenames=["bench_1.py", "bench_2.py"],
        verbose=False,
    )
    registry = FakeRecord.filter(name="LaminProfiler", is_type=True).one_or_none()
    package = FakeRecord.filter(
        name="example_pkg", is_type=True, type=registry
    ).one_or_none()
    task_1 = FakeRecord.filter(
        name="bench_1.py", is_type=True, type=package
    ).one_or_none()
    task_2 = FakeRecord.filter(
        name="bench_2.py", is_type=True, type=package
    ).one_or_none()

    assert schema_repeat is schema
    assert schema.name == module.LAMINPROFILER_SCHEMA_NAME
    assert {feature.name for feature in schema.features} == {
        "package_version",
        "duration_in_sec",
        "commit_hash16",
        "runner_env",
    }
    assert registry.schema is schema
    assert package is not None
    assert package.schema is schema
    assert task_1 is not None
    assert task_2 is not None
    assert task_1.schema is schema
    assert task_2.schema is schema
