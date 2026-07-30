from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock

from django.test import SimpleTestCase

repair_client_form_upload_schema = import_module(
    "projects.migrations.0009_repair_client_form_upload_schema"
).repair_client_form_upload_schema


class RepairClientFormUploadSchemaMigrationTests(SimpleTestCase):
    def _model(self, table, field_names):
        fields = {
            name: SimpleNamespace(column=name)
            for name in field_names
        }
        model = MagicMock()
        model._meta.db_table = table
        model._meta.get_field.side_effect = fields.__getitem__
        model._meta.local_concrete_fields = tuple(fields.values())
        return model

    def _context(self, table_columns):
        client_form = self._model(
            "projects_projectclientform",
            ("id", "revoked_at", "submission_notified_at"),
        )
        upload = self._model(
            "projects_projectformupload",
            (
                "id",
                "question_id",
                "file",
                "original_name",
                "content_type",
                "size",
                "uploaded_at",
            ),
        )
        apps = MagicMock()
        apps.get_model.side_effect = lambda _app, name: {
            "ProjectClientForm": client_form,
            "ProjectFormUpload": upload,
        }[name]
        schema_editor = MagicMock()
        connection = schema_editor.connection
        connection.introspection.table_names.return_value = list(table_columns)
        connection.introspection.get_table_description.side_effect = (
            lambda _cursor, table: [
                SimpleNamespace(name=column)
                for column in table_columns[table]
            ]
        )
        return apps, schema_editor, client_form, upload

    def test_missing_column_and_upload_table_are_repaired(self):
        apps, schema_editor, client_form, upload = self._context(
            {
                "projects_projectclientform": {"id", "revoked_at"},
            }
        )

        repair_client_form_upload_schema(apps, schema_editor)

        schema_editor.add_field.assert_called_once_with(
            client_form,
            client_form._meta.get_field("submission_notified_at"),
        )
        schema_editor.create_model.assert_called_once_with(upload)

    def test_complete_schema_makes_repair_idempotent(self):
        table_columns = {
            "projects_projectclientform": {
                "id",
                "revoked_at",
                "submission_notified_at",
            },
            "projects_projectformupload": {
                "id",
                "question_id",
                "file",
                "original_name",
                "content_type",
                "size",
                "uploaded_at",
            },
        }
        apps, schema_editor, _client_form, _upload = self._context(table_columns)

        repair_client_form_upload_schema(apps, schema_editor)

        schema_editor.add_field.assert_not_called()
        schema_editor.create_model.assert_not_called()

    def test_partial_upload_table_receives_missing_columns(self):
        table_columns = {
            "projects_projectclientform": {
                "id",
                "revoked_at",
                "submission_notified_at",
            },
            "projects_projectformupload": {"id", "question_id"},
        }
        apps, schema_editor, _client_form, upload = self._context(table_columns)

        repair_client_form_upload_schema(apps, schema_editor)

        repaired_columns = {
            call.args[1].column for call in schema_editor.add_field.call_args_list
        }
        self.assertEqual(
            repaired_columns,
            {"file", "original_name", "content_type", "size", "uploaded_at"},
        )
        self.assertTrue(
            all(call.args[0] is upload for call in schema_editor.add_field.call_args_list)
        )
