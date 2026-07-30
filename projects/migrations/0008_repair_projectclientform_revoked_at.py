from django.db import migrations


def ensure_revoked_at_column(apps, schema_editor):
    project_client_form = apps.get_model("projects", "ProjectClientForm")
    table = project_client_form._meta.db_table
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table)
        }
    if "revoked_at" not in columns:
        schema_editor.add_field(
            project_client_form,
            project_client_form._meta.get_field("revoked_at"),
        )


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0007_clientformtemplate_clientformquestion_and_more"),
    ]

    operations = [
        migrations.RunPython(
            ensure_revoked_at_column,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
