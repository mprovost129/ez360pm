from django.db import migrations


def _column_names(connection, cursor, table):
    return {
        column.name
        for column in connection.introspection.get_table_description(cursor, table)
    }


def repair_client_form_upload_schema(apps, schema_editor):
    project_client_form = apps.get_model("projects", "ProjectClientForm")
    project_form_upload = apps.get_model("projects", "ProjectFormUpload")
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        existing_tables = set(connection.introspection.table_names(cursor))
        client_form_columns = _column_names(
            connection,
            cursor,
            project_client_form._meta.db_table,
        )
        for field_name in ("revoked_at", "submission_notified_at"):
            field = project_client_form._meta.get_field(field_name)
            if field.column not in client_form_columns:
                schema_editor.add_field(project_client_form, field)

        upload_table = project_form_upload._meta.db_table
        if upload_table not in existing_tables:
            schema_editor.create_model(project_form_upload)
            return

        upload_columns = _column_names(connection, cursor, upload_table)
        for field in project_form_upload._meta.local_concrete_fields:
            if field.column not in upload_columns:
                schema_editor.add_field(project_form_upload, field)


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0008_repair_projectclientform_revoked_at"),
    ]

    operations = [
        migrations.RunPython(
            repair_client_form_upload_schema,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
