"""An INDEPENDENT corpus of customer restrictions, and the one invariant that matters.

The phrases in `research/intent_taxonomy.py` were written from a taxonomy of what a
person might plausibly say -- amount, period, merchant, returns, basket, quantity,
time, total, and adversarial phrasings -- and only then run through the compiler. A
corpus written by reading the regexes would measure the regexes.

    NO RESTRICTIVE STATEMENT MAY DISAPPEAR SILENTLY.

A restriction the vocabulary cannot express is SAFE as long as the customer is told
before confirming. One that vanishes with no rule and no warning is the worst
failure this system can have: the customer believes they said something the wallet
is not enforcing.
"""

from __future__ import annotations

import pytest

from research.intent_taxonomy import CORPUS, classify
from wallet_control.policy_compiler import compile_instruction

BASE = "Order our household groceries. "


@pytest.mark.parametrize("phrase,dimension,expected", CORPUS,
                         ids=lambda v: v[:30] if isinstance(v, str) else str(v))
def test_no_restriction_disappears_silently(phrase, dimension, expected):
    verdict, detail = classify(phrase, expected)
    assert verdict != "SILENTLY-WEAKENED", (
        f"[{dimension}] {phrase!r}: {detail}. The customer believes they said this "
        "and the wallet is not enforcing it.")


def test_the_corpus_is_broad_enough_to_mean_something():
    dimensions = {d for _, d, _ in CORPUS}
    assert len(CORPUS) >= 35
    assert len(dimensions) >= 9, dimensions
    inexpressible = [c for c in CORPUS if c[2] is None]
    assert inexpressible, (
        "every phrase is expressible, so the corpus is only testing the happy path")


# ============================ the inversion a vocabulary widening re-created
@pytest.mark.parametrize("phrase,scope,days", [
    ("Weekly spending must not exceed CHF 300.", "period", 7),
    ("Monthly spend must not exceed CHF 500.", "period", 30),
    ("Don't let the weekly total exceed CHF 300.", "period", 7),
    ("Spending must not exceed CHF 300 per week.", "period", 7),
    ("Don't let any single order exceed CHF 120.", "purchase", None),
    ("Cap each order at CHF 120.", "purchase", None),
    ("No order above CHF 120.", "purchase", None),
    ("I don't want to pay more than CHF 120 at a time.", "purchase", None),
    # The false positives the tightness has to avoid: "weekly" qualifying the
    # ORDERING, not a total. Both phrasings, because mutation showed the comma
    # version passed while the "and" version did not -- with a loose pattern the
    # second became a CHF 120 WEEKLY budget and the per-order ceiling vanished.
    ("Order groceries weekly, each order under CHF 120.", "purchase", None),
    ("Order weekly and keep each order under CHF 120.", "purchase", None),
    ("Deliver monthly and keep each order under CHF 120.", "purchase", None),
])
def test_a_period_word_does_not_become_a_per_order_ceiling(phrase, scope, days):
    """Widening the amount vocabulary so "must not exceed" matched re-created the
    inversion this compiler already warns about at length: a WEEKLY cap compiled to
    `scope=purchase`, letting the agent spend CHF 300 every order against a customer
    who wrote CHF 300 a week.

    Found by attacking the change, not by the suite -- which had no phrase of this
    shape, which is why the corpus above had to be written independently.
    """
    compiled = compile_instruction(BASE + phrase)
    money = [r for r in compiled.hard_rules if r.field == "authorization.billing_amount_chf"]
    assert money, f"no amount rule at all for {phrase!r}"
    matching = [r for r in money if r.scope == scope]
    assert matching, (
        f"{phrase!r} compiled to {[(r.value, r.scope) for r in money]}, expected scope={scope}")
    # ...and the WINDOW LENGTH the customer named. A weekly cap mapped to one day is
    # stricter and still wrong: it is not what they said. Mutation found this gap --
    # mapping "weekly" to 1 day survived the first version of this test.
    assert any(r.period_days == days for r in matching), (
        f"{phrase!r}: expected period_days={days}, got "
        f"{[r.period_days for r in matching]}")


def test_the_widened_vocabulary_did_not_move_the_official_replay():
    """Four new amount phrasings and one new period phrasing. The regression
    boundary must be untouched by a vocabulary change."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, str(root / "scripts" / "run_replay.py")],
                            capture_output=True, text=True, cwd=root)
    assert "{'allow': 18, 'review': 3, 'block': 24}" in result.stdout, result.stdout[-400:]
