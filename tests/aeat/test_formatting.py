from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from django_verifactu.aeat.formatting import format_amount, format_date, format_timestamp


def test_amount_always_has_two_decimals():
    assert format_amount(Decimal("241.4")) == "241.40"
    assert format_amount(Decimal("-5")) == "-5.00"
    assert format_amount(Decimal("999999999999.99")) == "999999999999.99"


def test_amount_negative_zero_becomes_zero():
    assert format_amount(Decimal("-0.00")) == "0.00"


def test_amount_is_never_rounded():
    with pytest.raises(ValueError):
        format_amount(Decimal("1.235"))


def test_amount_over_twelve_integer_digits_is_rejected():
    with pytest.raises(ValueError):
        format_amount(Decimal("1000000000000"))


def test_amount_must_be_decimal():
    with pytest.raises(TypeError):
        format_amount(241.4)


def test_date():
    assert format_date(date(2024, 1, 1)) == "01-01-2024"


def test_timestamp_includes_the_offset():
    moment = datetime(2024, 1, 1, 19, 20, 30, 123456, tzinfo=ZoneInfo("Europe/Madrid"))
    assert format_timestamp(moment) == "2024-01-01T19:20:30+01:00"


def test_timestamp_without_timezone_is_rejected():
    with pytest.raises(ValueError):
        format_timestamp(datetime(2024, 1, 1, 19, 20, 30))
