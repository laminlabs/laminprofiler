import lamindb as ln

LAMINPROFILER_SCHEMA_NAME = "laminprofiler"
FEATURE_TYPE_NAME = "LaminProfiler"
# Uids registered on laminlabs/lamindb-benchmarks.
FEATURE_UIDS = {
    "package_version": "3jrklzyM82cU",
    "duration_in_sec": "QsC24kltUffN",
    "commit_hash16": "uaYdTQD761RE",
    "runner_env": "fJUXc02btoaI",
    "task_source_hash": "rnr6tCzZyZMR",
    "python_version": "DbXIpju3hjt0",
    "created_at": "nXiW5L1obr3u",
    "run": "z4SI35hBSvVw",
}


def _get_or_create_feature_type() -> ln.Feature:
    feature_type = ln.Feature.filter(name=FEATURE_TYPE_NAME, is_type=True).one_or_none()
    if feature_type is None:
        feature_type = ln.Feature(name=FEATURE_TYPE_NAME, is_type=True).save()
    return feature_type


def _is_str_feature(feature: ln.Feature) -> bool:
    dtype = getattr(feature, "dtype_as_str", None)
    if dtype is None:
        dtype = getattr(feature, "dtype", None)
    return dtype is str or dtype == "str"


def _find_feature(name: str, uid: str, feature_type: ln.Feature, dtype):
    candidates = (
        ln.Feature.filter(uid=uid).one_or_none(),
        ln.Feature.filter(name=name, type=feature_type).one_or_none(),
        ln.Feature.filter(name=name, type=None).one_or_none(),
    )
    for feature in candidates:
        if feature is None:
            continue
        # The benchmarks instance still has a categorical runner_env under this uid.
        if dtype is str and not _is_str_feature(feature):
            continue
        return feature
    return None


def _get_or_create_feature(
    name: str,
    dtype,
    feature_type: ln.Feature,
    *,
    values_through: str | None = None,
) -> ln.Feature:
    uid = FEATURE_UIDS[name]
    feature = _find_feature(name, uid, feature_type, dtype)
    if feature is None:
        kwargs = {"name": name, "dtype": dtype, "type": feature_type}
        if values_through is not None:
            kwargs["values_through"] = values_through
        feature = ln.Feature(**kwargs)
        if ln.Feature.filter(uid=uid).one_or_none() is None:
            feature.uid = uid
        return feature.save()
    if feature.type != feature_type:
        feature.type = feature_type
        feature.save()
    return feature


def _optional(feature: ln.Feature):
    return feature.with_config(optional=True)


def get_or_create_schema() -> ln.Schema:
    feature_type = _get_or_create_feature_type()
    package_version = _get_or_create_feature("package_version", str, feature_type)
    duration_in_sec = _get_or_create_feature("duration_in_sec", float, feature_type)
    commit_hash16 = _get_or_create_feature("commit_hash16", str, feature_type)
    runner_env = _get_or_create_feature("runner_env", str, feature_type)
    task_source_hash = _get_or_create_feature("task_source_hash", str, feature_type)
    python_version = _get_or_create_feature("python_version", str, feature_type)
    created_at = _get_or_create_feature(
        "created_at",
        "datetime64[ns, UTC]",
        feature_type,
        values_through="created_at",
    )
    run = _get_or_create_feature(
        "run",
        ln.Run.uid,
        feature_type,
        values_through="run",
    )
    required = [package_version, duration_in_sec, created_at, run]
    optional = [commit_hash16, runner_env, task_source_hash, python_version]
    schema = ln.Schema.filter(name=LAMINPROFILER_SCHEMA_NAME).one_or_none()
    if schema is None:
        schema = ln.Schema(
            features=[*required, *map(_optional, optional)],
            name=LAMINPROFILER_SCHEMA_NAME,
        ).save()
        return schema
    existing = {feature.name for feature in schema.features.all()}
    missing = [
        feature for feature in [*required, *optional] if feature.name not in existing
    ]
    if missing:
        schema.add(missing, optional=True)
    return schema


def get_or_create_package(
    package_name: str, laminprofiler_registry: ln.Record
) -> ln.Record:
    package = ln.Record.filter(
        name=package_name, type=laminprofiler_registry, is_type=True
    ).one_or_none()
    if package is None:
        package = ln.Record(
            name=package_name, type=laminprofiler_registry, is_type=True
        ).save()
    elif package.schema_id is not None:
        # Type records that type other type records must be schema-less.
        package.schema = None
        package.save()
    return package


def get_or_create_task(task_name: str, package: ln.Record, schema: ln.Schema) -> None:
    task = ln.Record.filter(name=task_name, type=package, is_type=True).one_or_none()
    if task is None:
        ln.Record(name=task_name, type=package, is_type=True, schema=schema).save()
    elif task.schema_id is None:
        task.schema = schema
        task.save()


def setup(
    package_name: str | None = None,
    task_names: list[str] | None = None,
    verbose: bool = True,
) -> None:
    """Create laminprofiler dynamic registry."""
    schema = get_or_create_schema()
    laminprofiler_registry = ln.Record.filter(
        name="LaminProfiler", is_type=True
    ).one_or_none()
    if laminprofiler_registry is None:
        laminprofiler_registry = ln.Record(name="LaminProfiler", is_type=True)
        laminprofiler_registry.save()
    elif laminprofiler_registry.schema_id is not None:
        # Keep the root type schema-less so nested types remain valid.
        laminprofiler_registry.schema = None
        laminprofiler_registry.save()
    created_scripts = 0
    if package_name is not None:
        package = get_or_create_package(
            package_name=package_name,
            laminprofiler_registry=laminprofiler_registry,
        )
        for task_name in task_names or []:
            get_or_create_task(task_name=task_name, package=package, schema=schema)
            created_scripts += 1

    if verbose:
        print(
            "Configured LaminProfiler registry "
            f"'{laminprofiler_registry.name}' with schema '{schema.name}'."
        )
        if package_name is not None:
            print(
                f"Configured package '{package_name}' with {created_scripts} profiling task "
                "registries."
            )
