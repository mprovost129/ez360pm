from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase

ensure_revoked_at_column = import_module(
    "projects.migrations.0008_repair_projectclientform_revoked_at"
).ensure_revoked_at_column


class RepairRevokedAtMigrationTests(SimpleTestCase):
    def _migration_context(self, existing_columns):
        field = object()
        model = MagicMock()
        model._meta.db_table = "projects_projectclientform"
        model._meta.get_field.return_value = field
        apps = MagicMock()
        apps.get_model.return_value = model
        schema_editor = MagicMock()
        schema_editor.connection.introspection.get_table_description.return_value = [
            SimpleNamespace(name=column) for column in existing_columns
        ]
        return apps, schema_editor, model, field

    def test_missing_column_is_added_from_historical_model_state(self):
        apps, schema_editor, model, field = self._migration_context({"id", "status"})

        ensure_revoked_at_column(apps, schema_editor)

        schema_editor.add_field.assert_called_once_with(model, field)

    def test_existing_column_makes_repair_idempotent(self):
        apps, schema_editor, _model, _field = self._migration_context(
            {"id", "status", "revoked_at"}
        )

        ensure_revoked_at_column(apps, schema_editor)

        schema_editor.add_field.assert_not_called()
