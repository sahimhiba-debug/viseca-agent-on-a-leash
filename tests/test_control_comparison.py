"""A card limit and a mandate, judging the same proposals.

"A spending limit already does that" is the most likely product objection to this
whole project, and it deserves a measurement. The card side is modelled generously
-- per-transaction cap, monthly cap, MCC allow-list, country allow-list -- because
a strawman would be refuted in one sentence by anyone who has worked at an issuer.

The finding is not "we block more". Measured, a card limit stops most crude attacks
perfectly well, because crude attacks are expensive and a cap is good at expensive.
The finding is that every proposal it lets through is ORDINARY: affordable,
in-category, and wrong for reasons a limit cannot express.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from research.card_limit_control import EXPRESSIBLE, CardLimitControl


def test_the_card_is_modelled_generously_enough_to_be_fair():
    """It must be able to refuse things, and to win rows the mandate loses."""
    card = CardLimitControl()
    assert card.decide({"amount_chf": 500, "mcc": "5411", "country": "CH"})["decision"] == "block"
    assert card.decide({"amount_chf": 50, "mcc": "7011", "country": "CH"})["decision"] == "block"
    assert card.decide({"amount_chf": 50, "mcc": "5411", "country": "FR"})["decision"] == "block"
    assert card.decide({"amount_chf": 50, "mcc": "5411", "country": "CH"})["decision"] == "allow"

    card_only = [q for q, c, w in EXPRESSIBLE if c and not w]
    assert card_only, (
        "if the card can express nothing the mandate cannot, the comparison is a "
        "strawman and a judge will say so")


def test_the_monthly_limit_is_a_row_the_card_genuinely_wins():
    """`accounts.csv` carries a monthly limit we display and explicitly do not
    enforce. Claiming this row would be an overclaim."""
    questions = dict((q, (c, w)) for q, c, w in EXPRESSIBLE)
    assert questions["How much this month?"] == (True, False)


@pytest.mark.parametrize("spent,amount,expected", [
    (Decimal("0"), 100, "allow"),
    (Decimal("1950"), 100, "block"),        # monthly cap bites
    (Decimal("0"), 121, "block"),           # per-transaction cap bites
])
def test_the_card_enforces_what_it_can(spent, amount, expected):
    card = CardLimitControl(spent_this_month=spent)
    assert card.decide({"amount_chf": amount, "mcc": "5411", "country": "CH"})["decision"] == expected


def test_a_card_cannot_see_inside_the_basket():
    """The hotel room in a grocery basket. MCC is a property of the MERCHANT, so a
    grocer selling a hotel room reads as groceries -- and that is not a bug in the
    card, it is the resolution the primitive has."""
    card = CardLimitControl()
    assert card.decide({"amount_chf": 110, "mcc": "5411", "country": "CH"})["decision"] == "allow"


def test_the_comparison_runs_and_is_reproducible():
    """The whole script, twice, byte-identical. It is quoted in the pitch."""
    import io
    import contextlib

    from research.control_comparison import main

    runs = []
    for _ in range(2):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            assert main() == 0
        runs.append(buffer.getvalue())
    assert runs[0] == runs[1]
    assert "None of them is about the amount" in runs[0]
    assert "a refusal is a steer" in runs[0].lower()
