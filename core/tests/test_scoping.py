from types import SimpleNamespace

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.test import TestCase
from django.views.generic import ListView

from accounts.models import Company, User
from core.mixins import CompanyScopedQuerysetMixin
from core.validation import validate_same_company


class ScopedUserListView(CompanyScopedQuerysetMixin, ListView):
    model = User


class CompanyScopingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Provost Home Design")
        self.other_company = Company.objects.create(name="Other Company")
        self.owner = User.objects.create_user(
            "owner@example.com",
            "Strong-Test-Password-483!",
            company=self.company,
        )
        self.other_user = User.objects.create_user(
            "other@example.com",
            "Strong-Test-Password-483!",
            company=self.other_company,
        )

    def test_view_mixin_limits_queryset_to_request_company(self):
        view = ScopedUserListView()
        view.request = SimpleNamespace(user=self.owner)

        self.assertEqual(list(view.get_queryset()), [self.owner])

    def test_view_mixin_requires_company_context(self):
        view = ScopedUserListView()
        view.request = SimpleNamespace(user=SimpleNamespace(company=None))

        with self.assertRaises(ImproperlyConfigured):
            view.get_queryset()

    def test_validation_rejects_cross_company_relationship(self):
        validate_same_company(self.company, self.owner)

        with self.assertRaises(ValidationError):
            validate_same_company(self.company, self.other_user)

