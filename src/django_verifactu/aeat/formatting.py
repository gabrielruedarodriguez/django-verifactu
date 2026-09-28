from datetime import date, datetime
from decimal import Decimal

_CENT = Decimal("0.01")
_AMOUNT_LIMIT = Decimal(10) ** 12


def format_amount(amount: Decimal) -> str:
    if not isinstance(amount, Decimal):
        raise TypeError("amount must be a Decimal")
    if not amount.is_finite() or abs(amount) >= _AMOUNT_LIMIT:
        raise ValueError(f"amount out of range: {amount}")
    cents = amount.quantize(_CENT)
    if cents != amount:
        raise ValueError(f"amount has more than two decimals: {amount}")
    return f"{abs(cents) if cents == 0 else cents:f}"


def format_date(value: date) -> str:
    return value.strftime("%d-%m-%Y")


def format_timestamp(value: datetime) -> str:
    if value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.isoformat(timespec="seconds")
