from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.deployment_safety import (
    SchemaNotReadyError,
    assert_schema_current,
    missing_model_columns,
)


class DeploymentSchemaSafetyTests(SimpleTestCase):
    @patch("core.deployment_safety.missing_model_columns", return_value=())
    @patch("core.deployment_safety.MigrationExecutor")
    def test_current_schema_allows_server_startup(self, executor_class, _columns):
        executor_class.return_value.loader.graph.leaf_nodes.return_value = [
            ("projects", "0007_client_forms")
        ]
        executor_class.return_value.migration_plan.return_value = []

        assert_schema_current(object())

    @patch("core.deployment_safety.missing_model_columns", return_value=())
    @patch("core.deployment_safety.MigrationExecutor")
    def test_pending_schema_fails_closed_with_actionable_migration(
        self,
        executor_class,
        _columns,
    ):
        migration = SimpleNamespace(
            app_label="projects",
            name="0007_clientformtemplate_clientformquestion_and_more",
        )
        executor_class.return_value.loader.graph.leaf_nodes.return_value = [
            (migration.app_label, migration.name)
        ]
        executor_class.return_value.migration_plan.return_value = [(migration, False)]

        with self.assertRaisesMessage(
            SchemaNotReadyError,
            "projects.0007_clientformtemplate_clientformquestion_and_more",
        ):
            assert_schema_current(object())

    def test_missing_physical_column_is_reported_even_when_migration_is_recorded(self):
        model = SimpleNamespace(
            _meta=SimpleNamespace(
                proxy=False,
                managed=True,
                db_table="projects_projectclientform",
                local_concrete_fields=(
                    SimpleNamespace(column="id"),
                    SimpleNamespace(column="revoked_at"),
                ),
            )
        )
        app_registry = SimpleNamespace(get_models=lambda: (model,))
        database_connection = MagicMock()
        database_connection.introspection.table_names.return_value = [
            "projects_projectclientform"
        ]
        database_connection.introspection.get_table_description.return_value = [
            SimpleNamespace(name="id")
        ]

        missing = missing_model_columns(database_connection, app_registry)

        self.assertEqual(missing, ("projects_projectclientform.revoked_at",))

    @patch(
        "core.deployment_safety.missing_model_columns",
        return_value=("projects_projectclientform.revoked_at",),
    )
    @patch("core.deployment_safety.pending_migration_labels", return_value=())
    def test_recorded_migration_with_missing_column_fails_closed(
        self,
        _pending,
        _columns,
    ):
        with self.assertRaisesMessage(
            SchemaNotReadyError,
            "projects_projectclientform.revoked_at",
        ):
            assert_schema_current(object())
