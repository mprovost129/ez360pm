"""Fail-closed deployment checks shared by commands and server startup."""

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


def assert_schema_current(database_connection=None):
    pending = pending_migration_labels(database_connection)
    if pending:
        labels = ", ".join(pending)
        raise SchemaNotReadyError(
            "Refusing to serve traffic with unapplied migrations: "
            f"{labels}. Run 'python manage.py migrate --noinput' before Gunicorn."
        )
