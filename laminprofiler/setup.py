import lamindb as ln

LAMINPROFILER_SCHEMA_NAME = "laminprofiler"


def _get_or_create_feature(name: str, dtype: type | str) -> ln.Feature:
    feature = ln.Feature.filter(name=name).one_or_none()
    if feature is None:
        feature = ln.Feature(name=name, dtype=dtype).save()
    return feature


def get_or_create_schema() -> ln.Schema:
    package_version = _get_or_create_feature("package_version", str)
    duration_in_sec = _get_or_create_feature("duration_in_sec", float)
    commit_hash16 = _get_or_create_feature("commit_hash16", str)
    runner_env = _get_or_create_feature("runner_env", str)
    schema = ln.Schema.filter(name=LAMINPROFILER_SCHEMA_NAME).one_or_none()
    if schema is None:
        schema = ln.Schema(
            features=[
                package_version,
                duration_in_sec,
                commit_hash16.with_config(optional=True),
                runner_env.with_config(optional=True),
            ],
            name=LAMINPROFILER_SCHEMA_NAME,
        ).save()
    return schema


def get_or_create_package(
    package_name: str, laminprofiler_registry: ln.Record, schema: ln.Schema
) -> ln.Record:
    package = ln.Record.filter(
        name=package_name, type=laminprofiler_registry, is_type=True
    ).one_or_none()
    if package is None:
        package = ln.Record(
            name=package_name, type=laminprofiler_registry, is_type=True, schema=schema
        ).save()
    elif package.schema_id is None:
        package.schema = schema
        package.save()
    return package


def get_or_create_task(
    script_basename: str, package: ln.Record, schema: ln.Schema
) -> None:
    task = ln.Record.filter(
        name=script_basename, type=package, is_type=True
    ).one_or_none()
    if task is None:
        ln.Record(
            name=script_basename, type=package, is_type=True, schema=schema
        ).save()
    elif task.schema_id is None:
        task.schema = schema
        task.save()


def setup(
    package_name: str | None = None,
    script_basenames: list[str] | None = None,
    verbose: bool = True,
) -> None:
    """Create laminprofiler dynamic registry."""
    schema = get_or_create_schema()
    laminprofiler_registry = ln.Record.filter(
        name="LaminProfiler", is_type=True
    ).one_or_none()
    if laminprofiler_registry is None:
        laminprofiler_registry = ln.Record(
            name="LaminProfiler", is_type=True, schema=schema
        )
        laminprofiler_registry.save()
    created_scripts = 0
    if package_name is not None:
        package = get_or_create_package(
            package_name=package_name,
            laminprofiler_registry=laminprofiler_registry,
            schema=schema,
        )
        for script_basename in script_basenames or []:
            get_or_create_task(
                script_basename=script_basename, package=package, schema=schema
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
