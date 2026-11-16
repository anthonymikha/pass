"""Money rules: minor units (GEN-15), rounding (GEN-16), typed amounts (GEN-17), currency codes (GEN-14)."""
import re
from decimal import ROUND_HALF_UP, Decimal

from rest_framework import serializers

ZERO_MINOR = {  # 0 decimals; LBP on purpose (owner decision, 2026-11-16)
    "BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "LBP", "PYG", "RWF", "UGX", "UYI", "VND", "VUV", "XAF", "XOF", "XPF",
}
THREE_MINOR = {"BHD", "IQD", "JOD", "KWD", "LYD", "OMR", "TND"}


def minor_units(currency):
    return 0 if currency in ZERO_MINOR else 3 if currency in THREE_MINOR else 2


def round_money(x, currency):
    """GEN-16: half away from zero. Use for every amount the system computes."""
    return Decimal(x).quantize(Decimal(1).scaleb(-minor_units(currency)), rounding=ROUND_HALF_UP)


def validate_currency(value):
    # ponytail: format check only (GEN-14); add the ISO 4217 list if bad codes ever appear
    if not re.fullmatch(r"[A-Z]{3}", value):
        raise serializers.ValidationError("Use a 3-letter uppercase currency code, e.g. USD.")
    return value


def validate_typed_money(value, currency):
    """GEN-17: an amount the user typed. Call from a serializer once the currency is known."""
    if value < 0:
        raise serializers.ValidationError("Must not be negative.")
    if value != round_money(value, currency):  # trailing zeros ("25.500" USD) are fine, extra digits are not
        raise serializers.ValidationError(f"Too many decimal places for {currency}")
    return value
