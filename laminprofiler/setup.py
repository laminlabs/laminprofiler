import lamindb as ln

LAMINPROFILER_SCHEMA_NAME = "laminprofiler"


def _get_or_create_feature(name: str, dtype: type | str) -> ln.Feature:
    feature = ln.Feature.filter(name=name).one_or_none()
    if feature is None:
        feature = ln.Feature(name=name, dtype=dtype).save()
    return feature


def _optional(feature: ln.Feature):
    return feature.with_config(optional=True)


def get_or_create_schema() -> ln.Schema:
    package_version = _get_or_create_feature("package_version", str)
    duration_in_sec = _get_or_create_feature("duration_in_sec", float)
    commit_hash16 = _get_or_create_feature("commit_hash16", str)
    runner_env = _get_or_create_feature("runner_env", str)
    task_source_hash = _get_or_create_feature("task_source_hash", str)
    python_version = _get_or_create_feature("python_version", str)
    optional = [commit_hash16, runner_env, task_source_hash, python_version]
    schema = ln.Schema.filter(name=LAMINPROFILER_SCHEMA_NAME).one_or_none()
    if schema is None:
        schema = ln.Schema(
            features=[package_version, duration_in_sec, *map(_optional, optional)],
            name=LAMINPROFILER_SCHEMA_NAME,
        ).save()
        return schema
    existing = {feature.name for feature in schema.features.all()}
    missing = [feature for feature in optional if feature.name not in existing]
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
