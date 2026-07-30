from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from core.deployment_safety import SchemaNotReadyError, assert_schema_current


class DeploymentSchemaSafetyTests(SimpleTestCase):
    @patch("core.deployment_safety.MigrationExecutor")
    def test_current_schema_allows_server_startup(self, executor_class):
        executor_class.return_value.loader.graph.leaf_nodes.return_value = [
            ("projects", "0007_client_forms")
        ]
        executor_class.return_value.migration_plan.return_value = []

        assert_schema_current(object())

    @patch("core.deployment_safety.MigrationExecutor")
    def test_pending_schema_fails_closed_with_actionable_migration(self, executor_class):
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
