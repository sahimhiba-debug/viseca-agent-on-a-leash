from decimal import Decimal

from wallet_control.money import round_chf, to_chf, to_decimal


def test_to_decimal_avoids_float_precision_error():
    # Decimal(0.1) directly would be 0.1000000000000000055511151231257827021181583404541015625
    assert to_decimal(0.1) == Decimal("0.1")


def test_to_chf_uses_fixed_synthetic_rate():
    assert to_chf(Decimal("100"), "EUR") == Decimal("95.00")
    assert to_chf(Decimal("100"), "USD") == Decimal("87.00")
    assert to_chf(Decimal("100"), "GBP") == Decimal("112.00")
    assert to_chf(Decimal("100"), "CHF") == Decimal("100.00")


def test_to_chf_matches_known_csv_example():
    # AU0025: 199.00 EUR -> billing_amount_chf 189.05
    assert to_chf(Decimal("199.00"), "EUR") == Decimal("189.05")
    # AU0029: 219.00 GBP -> billing_amount_chf 245.28
    assert to_chf(Decimal("219.00"), "GBP") == Decimal("245.28")
    # AU0038: 450.00 USD -> billing_amount_chf 391.50
    assert to_chf(Decimal("450.00"), "USD") == Decimal("391.50")


def test_round_chf_half_even():
    assert round_chf(Decimal("1.005")) == Decimal("1.00")  # banker's rounding, not away-from-zero
    assert round_chf(Decimal("1.015")) == Decimal("1.02")
    assert round_chf(Decimal("2.675")) == Decimal("2.68")


def test_to_chf_rejects_unsupported_currency():
    import pytest

    with pytest.raises(ValueError):
        to_chf(Decimal("10"), "JPY")
