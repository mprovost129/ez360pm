from decimal import Decimal

from django.test import SimpleTestCase

from core.templatetags.core_extras import fee_effect_money, hours_minutes, signed_money


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


class SignedMoneyTests(SimpleTestCase):
    def test_formats_positive_zero_and_negative_values(self):
        self.assertEqual(signed_money(Decimal("12.50")), "$12.50")
        self.assertEqual(signed_money(Decimal("0")), "$0.00")
        self.assertEqual(signed_money(Decimal("-12.50")), "-$12.50")


class FeeEffectMoneyTests(SimpleTestCase):
    def test_formats_cost_credit_and_zero(self):
        self.assertEqual(fee_effect_money(Decimal("3.20")), "-$3.20")
        self.assertEqual(fee_effect_money(Decimal("-0.30")), "+$0.30")
        self.assertEqual(fee_effect_money(Decimal("0")), "$0.00")
