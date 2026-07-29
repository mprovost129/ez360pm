from django.apps import apps
from django.db.models import AutoField, BigAutoField
from django.test import SimpleTestCase


class PrimaryKeyConfigurationTests(SimpleTestCase):
    def test_jet_models_match_their_committed_legacy_migrations(self):
        for app_label, model_name in (
            ("jet", "Bookmark"),
            ("jet", "PinnedApplication"),
            ("dashboard", "UserDashboardModule"),
        ):
            with self.subTest(app_label=app_label, model_name=model_name):
                model = apps.get_model(app_label, model_name)
                self.assertIs(type(model._meta.pk), AutoField)

    def test_project_models_keep_big_auto_field_primary_keys(self):
        for app_label, model_name in (
            ("accounts", "Company"),
            ("clients", "Client"),
            ("projects", "Project"),
            ("intake", "Note"),
            ("documents", "Document"),
            ("assistant", "AIInteraction"),
        ):
            with self.subTest(app_label=app_label, model_name=model_name):
                model = apps.get_model(app_label, model_name)
                self.assertIs(type(model._meta.pk), BigAutoField)
