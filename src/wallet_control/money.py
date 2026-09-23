"""Exact-decimal money handling.

The official data dictionary requires CHF conversions and monetary totals to be
"rounded to two decimal places using decimal half-even rounding" (data/data_dictionary.md
`Units and nulls`). Using floats for authorization amounts risks off-by-a-cent
comparisons at a limit boundary, which is exactly the kind of bug that would make a
mandate's hard rule ("<=" CHF 200) non-deterministic. Every money value in this
package is therefore a `Decimal`, constructed from the original string/number and
never from a float that has already lost precision.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

# Fixed synthetic rates from data/fx_rates.csv (2026-08-01, "synthetic_fixed").
# These are part of the official challenge fixtures, not a live FX feed.
FX_RATES_TO_CHF: dict[str, Decimal] = {
    "CHF": Decimal("1.000000"),
    "EUR": Decimal("0.950000"),
    "GBP": Decimal("1.120000"),
    "USD": Decimal("0.870000"),
}

TWO_PLACES = Decimal("0.01")


def to_decimal(value: float | int | str | Decimal) -> Decimal:
    """Convert an incoming JSON number to Decimal without float-precision loss.

    JSON numbers arrive in Python as `float`. We route them through `str()` first
    so that ``20.0`` becomes ``"20.0"`` -> ``Decimal("20.0")`` rather than picking up
    the binary-float representation error a direct ``Decimal(float)`` call would.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def round_chf(amount: Decimal) -> Decimal:
    """Round a CHF amount to two decimals using banker's rounding (half-even)."""
    return amount.quantize(TWO_PLACES, rounding=ROUND_HALF_EVEN)


def to_chf(amount: Decimal, currency: str) -> Decimal:
    """Convert `amount` in `currency` to CHF using the fixed synthetic rate table.

    Mirrors the official rule: ``billing_amount_chf = amount * fx_rates[currency]``,
    rounded half-even to two decimals (data/data_dictionary.md `Units and nulls`).
    """
    try:
        rate = FX_RATES_TO_CHF[currency]
    except KeyError as exc:
        raise ValueError(f"Unsupported currency: {currency!r}") from exc
    return round_chf(amount * rate)


def annual_exposure(cap_chf: Decimal | float, period_days: int) -> tuple[float, float]:
    """What a rolling cap is worth in a year: (exact, rounded-for-a-person).

    ONE COMPUTATION, THREE READERS. The official rule format has `scope` of
    `"purchase"`, `"period"` or null and NOTHING ELSE -- there is no total, no
    lifetime, no end date. So a rolling cap paces spending and never caps it: the
    window re-opens and the agent may spend up to that amount again, indefinitely.
    The only bound on what a standing mandate can cost is revocation.

    That sentence is the most important thing this product says about a mandate, and
    it was being computed in three different places -- the compiler's open questions,
    the audit timeline, and the delegation panel -- with two different units between
    them. A fact rendered twice is a fact that will eventually be rendered
    differently; `test_one_wording_not_two.py` exists because of exactly that.

    The rounding is deliberate. "About CHF 15,643 a year" reads as a calculation the
    customer is expected to check, and the spurious precision invites them to argue
    with the last three digits instead of the magnitude.
    """
    exact = float(cap_chf) * (365 / max(1, period_days))
    step = 100 if exact >= 1000 else 10
    return exact, max(step, round(exact / step) * step)
