import lamindb as ln

BENCHMARKING_SCHEMA_ARTIFACT_NAME = "laminprofiler-benchmarks-artifact"
BENCHMARKING_SCHEMA_RECORD_NAME = "laminprofiler-benchmarks-record"
FEATURE_TYPE_NAME = "LaminProfiler"
FEATURE_TYPE_UID = "uBBUYLh5VFbo"
PRODUCTS_TYPE_UID = "tY22ouWHsJKDJaXL"
GIT_COMMITS_SCHEMA_UID = "LLgPZodc1iazGcVv"
BENCHMARKING_FEATURE_UIDS = {
    "package_version": "3jrklzyM82cU",
    "duration_in_sec": "QsC24kltUffN",
    "runner_env": "fJUXc02btoaI",
    "task_source_hash": "rnr6tCzZyZMR",
    "python_version": "DbXIpju3hjt0",
    "created_at": "nXiW5L1obr3u",
    "run": "z4SI35hBSvVw",
    "commit_hash16": "tViF46horYOI",
}
PRODUCT_FEATURE_UID = "nc9f3tG4LUoF"


def _get_or_create_feature_type() -> ln.Feature:
    feature_type = ln.Feature.filter(uid=FEATURE_TYPE_UID).one_or_none()
    if feature_type is None:
        feature_type = ln.Feature.filter(
            name=FEATURE_TYPE_NAME, is_type=True
        ).one_or_none()
    if feature_type is None:
        feature_type = ln.Feature(name=FEATURE_TYPE_NAME, is_type=True)
        feature_type.uid = FEATURE_TYPE_UID
        feature_type.save()
    return feature_type


def _is_str_feature(feature: ln.Feature) -> bool:
    dtype = getattr(feature, "dtype_as_str", None)
    if dtype is None:
        dtype = getattr(feature, "dtype", None)
    return dtype is str or dtype == "str"


def _stored_dtype(feature: ln.Feature):
    dtype = getattr(feature, "dtype_as_str", None)
    if dtype is None:
        dtype = getattr(feature, "dtype", None)
    return dtype


def _dtype_matches(feature: ln.Feature, dtype) -> bool:
    if dtype is str:
        return _is_str_feature(feature)
    if dtype is dict:
        stored = _stored_dtype(feature)
        return stored is dict or stored == "dict"
    if getattr(dtype, "is_type", False):
        stored = feature.dtype
        return stored is dtype or getattr(stored, "uid", None) == dtype.uid
    stored = _stored_dtype(feature)
    return stored == dtype or stored is dtype


def _find_feature(name: str, uid: str | None, feature_type: ln.Feature, dtype):
    if uid is not None:
        feature = ln.Feature.filter(uid=uid).one_or_none()
        # A pinned uid can still point at an older dtype, such as categorical runner_env.
        if feature is not None and (dtype is not str or _is_str_feature(feature)):
            return feature
    for scope in (feature_type, None):
        for feature in ln.Feature.filter(name=name, type=scope):
            if _dtype_matches(feature, dtype):
                return feature
    return None


def _get_or_create_feature(
    name: str,
    dtype,
    feature_type: ln.Feature,
    *,
    values_through: str | None = None,
    uid: str | None = None,
) -> ln.Feature:
    if uid is None and name in BENCHMARKING_FEATURE_UIDS:
        uid = BENCHMARKING_FEATURE_UIDS[name]
    feature = _find_feature(name, uid, feature_type, dtype)
    if feature is None:
        kwargs = {"name": name, "dtype": dtype, "type": feature_type}
        if values_through is not None:
            kwargs["values_through"] = values_through
        feature = ln.Feature(**kwargs)
        if uid is not None and ln.Feature.filter(uid=uid).one_or_none() is None:
            feature.uid = uid
        return feature.save()
    if feature.type_id != feature_type.id:
        feature.type = feature_type
        feature.save()
    return feature


def _optional(feature: ln.Feature):
    return feature.with_config(optional=True)


def product_feature(feature_type: ln.Feature | None = None) -> ln.Feature:
    """The one `product` feature, shared by GitCommits and benchmark artifacts."""
    if feature_type is None:
        feature_type = _get_or_create_feature_type()
    return _get_or_create_feature(
        "product", products_type(), feature_type, uid=PRODUCT_FEATURE_UID
    )


def products_type() -> ln.Record:
    """Products record type on lamindb-dev."""
    return ln.Record.get(PRODUCTS_TYPE_UID)


def git_commits_type() -> ln.Record:
    """GitCommits record type whose schema is `LLgPZodc1iazGcVv`."""
    schema = ln.Schema.get(GIT_COMMITS_SCHEMA_UID)
    return ln.Record.get(schema=schema, is_type=True)


def require_product(name: str) -> ln.Record:
    """Look up a Products record. Laminprofiler does not create products."""
    product = ln.Record.filter(name=name, type=products_type()).one_or_none()
    if product is None:
        raise LookupError(f"No Products record named {name!r}")
    return product


def ensure_git_commits_schema(
    feature: ln.Feature | None = None,
) -> ln.Schema:
    """GitCommits schema, including the shared product feature."""
    schema = ln.Schema.get(GIT_COMMITS_SCHEMA_UID)
    feature = product_feature() if feature is None else feature
    if any(member.uid == feature.uid for member in schema.features.all()):
        return schema
    # Schema.add(optional=False) is not implemented. Membership without an
    # optionals entry is what makes the feature required.
    schema.features.add(feature)
    schema.save(print_hash_mutation_warning=False)
    return schema


def ensure_git_commit(hash16: str, product: ln.Record | None = None) -> ln.Record:
    """Return the GitCommits record named with this hash, creating it if needed."""
    ensure_git_commits_schema()
    git_commits = git_commits_type()
    record = ln.Record.filter(name=hash16, type=git_commits).one_or_none()
    if record is not None:
        return record
    features = {"hash16": hash16}
    if product is not None:
        features["product"] = product
    return ln.Record(name=hash16, type=git_commits, features=features).save()


def _base_features(feature_type: ln.Feature) -> tuple[list, list]:
    package_version = _get_or_create_feature("package_version", str, feature_type)
    duration_in_sec = _get_or_create_feature("duration_in_sec", float, feature_type)
    commit_hash16 = _get_or_create_feature(
        "commit_hash16", git_commits_type(), feature_type
    )
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
    return required, optional


def _sync_schema(name: str, required: list, optional: list) -> ln.Schema:
    schema = ln.Schema.filter(name=name).one_or_none()
    if schema is None:
        return ln.Schema(
            features=[*required, *map(_optional, optional)],
            name=name,
        ).save()
    existing = {feature.name for feature in schema.features.all()}
    missing_required = [feature for feature in required if feature.name not in existing]
    missing_optional = [feature for feature in optional if feature.name not in existing]
    if missing_required:
        schema.features.add(*missing_required)
        schema.save(print_hash_mutation_warning=False)
    if missing_optional:
        schema.add(missing_optional, optional=True)
    return schema


def get_or_create_schema() -> ln.Schema:
    feature_type = _get_or_create_feature_type()
    required, optional = _base_features(feature_type)
    return _sync_schema(BENCHMARKING_SCHEMA_RECORD_NAME, required, optional)


def get_or_create_artifact_schema() -> ln.Schema:
    """Schema for one benchmark run: record features plus product, task, and benchmark."""
    feature_type = _get_or_create_feature_type()
    required, optional = _base_features(feature_type)
    product = product_feature(feature_type)
    ensure_git_commits_schema(product)
    task_name = _get_or_create_feature("task_name", str, feature_type, uid=None)
    task_uid = _get_or_create_feature("task_uid", str, feature_type, uid=None)
    benchmark = _get_or_create_feature("benchmark", dict, feature_type, uid=None)
    return _sync_schema(
        BENCHMARKING_SCHEMA_ARTIFACT_NAME,
        [*required, product, task_name],
        [*optional, task_uid, benchmark],
    )


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


def get_or_create_task(
    task_name: str,
    package: ln.Record,
    schema: ln.Schema,
    *,
    uid: str | None = None,
) -> None:
    """Find a task type by uid, or by name, and keep the uid when the name changes."""
    task = None
    if uid is not None:
        task = ln.Record.filter(uid=uid).one_or_none()
    if task is None:
        task = ln.Record.filter(
            name=task_name, type=package, is_type=True
        ).one_or_none()
    if task is None:
        task = ln.Record(name=task_name, type=package, is_type=True, schema=schema)
        if uid is not None:
            task.uid = uid
        task.save()
        return
    changed = False
    if task.name != task_name:
        task.name = task_name
        changed = True
    if uid is not None and task.uid != uid:
        task.uid = uid
        changed = True
    if task.schema_id is None:
        task.schema = schema
        changed = True
    if changed:
        task.save()


def setup(
    package_name: str | None = None,
    task_names: list[str] | None = None,
    verbose: bool = True,
    task_uids: dict[str, str] | None = None,
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
            get_or_create_task(
                task_name=task_name,
                package=package,
                schema=schema,
                uid=None if task_uids is None else task_uids.get(task_name),
            )
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
