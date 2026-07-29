from decimal import Decimal

from django.test import SimpleTestCase

from core.templatetags.core_extras import hours_minutes


class HoursMinutesFilterTests(SimpleTestCase):
    def test_mixed_hours_and_minutes(self):
        self.assertEqual(hours_minutes(Decimal("3.75")), "3h 45m")

    def test_whole_hour_omits_minutes(self):
        self.assertEqual(hours_minutes(Decimal("3.00")), "3h")

    def test_under_an_hour_omits_hours(self):
        self.assertEqual(hours_minutes(Decimal("0.75")), "45m")

    def test_zero_renders_as_zero_minutes(self):
        self.assertEqual(hours_minutes(Decimal("0")), "0m")

    def test_rounds_partial_minutes(self):
        self.assertEqual(hours_minutes(Decimal("1.23")), "1h 14m")

    def test_none_renders_empty(self):
        self.assertEqual(hours_minutes(None), "")
