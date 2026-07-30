"""Fail-closed deployment checks shared by commands and server startup."""

from django.apps import apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


class SchemaNotReadyError(RuntimeError):
    """Raised when application code is newer than the database schema."""


def pending_migration_labels(database_connection=None):
    database_connection = database_connection or connection
    executor = MigrationExecutor(database_connection)
    targets = executor.loader.graph.leaf_nodes()
    return tuple(
        f"{migration.app_label}.{migration.name}"
        for migration, _backwards in executor.migration_plan(targets)
    )


def missing_model_columns(database_connection=None, app_registry=None):
    database_connection = database_connection or connection
    app_registry = app_registry or apps
    introspection = database_connection.introspection
    missing = []
    with database_connection.cursor() as cursor:
        existing_tables = set(introspection.table_names(cursor))
        for model in app_registry.get_models():
            options = model._meta
            if options.proxy or not options.managed:
                continue
            table = options.db_table
            if table not in existing_tables:
                missing.append(f"{table}.*")
                continue
            actual_columns = {
                column.name
                for column in introspection.get_table_description(cursor, table)
            }
            expected_columns = {
                field.column for field in options.local_concrete_fields
            }
            missing.extend(
                f"{table}.{column}"
                for column in sorted(expected_columns - actual_columns)
            )
    return tuple(missing)


def assert_schema_current(database_connection=None, app_registry=None):
    pending = pending_migration_labels(database_connection)
    if pending:
        labels = ", ".join(pending)
        raise SchemaNotReadyError(
            "Refusing to serve traffic with unapplied migrations: "
            f"{labels}. Run 'python manage.py migrate --noinput' before Gunicorn."
        )
    missing = missing_model_columns(database_connection, app_registry)
    if missing:
        labels = ", ".join(missing)
        raise SchemaNotReadyError(
            "Refusing to serve traffic because the physical database schema "
            f"does not match Django models: {labels}. Inspect migration history "
            "and restore the missing schema before Gunicorn."
        )
