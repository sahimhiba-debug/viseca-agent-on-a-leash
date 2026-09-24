"""No silent semantic loss over 840 generated customer instructions (research/generated_corpus.py).

The meaning of every instruction was drawn in code BEFORE a model phrased it, so the
grader compares against a spec, not against a model's opinion. The corpora are
committed; this runs offline. docs/GENERATED_CORPUS.md records what each corpus found
before the fixes it prompted, which is the number that matters.
"""

from __future__ import annotations

from collections import Counter

import pytest

from research import generated_corpus as G
from wallet_control.policy_compiler import compile_instruction

CORPORA = {"tuning": G.CORPUS, "holdout": G.HOLDOUT, "blind": G.BLIND, "final": G.FINAL}


@pytest.mark.parametrize("name", CORPORA)
def test_no_restriction_is_lost_or_weakened_without_a_word(name):
    entries = G.load(CORPORA[name])
    assert len(entries) >= 200
    graded = [G.grade(dict(e, _corpus=name if name == "final" else "")) for e in entries]
    bad = [(g["id"], k, v) for g in graded for k, v in g["grades"].items()
           if v in ("SILENT_LOSS", "ENFORCED_LOOSER")]
    assert bad == []


@pytest.mark.parametrize("name", CORPORA)
def test_nothing_is_made_stricter_than_the_customer_asked(name):
    graded = [G.grade(e) for e in G.load(CORPORA[name])]
    assert [g["id"] for g in graded if "STRENGTHENED" in g["grades"].values()] == []


def test_warnings_are_rare_on_instructions_that_are_fully_enforced():
    """A warning on everything is a warning on nothing. Measured, not asserted zero:
    two blind-corpus texts add "one every week", a count the wallet really cannot hold."""
    noisy = Counter()
    for name, path in CORPORA.items():
        noisy[name] = sum(G.grade(e)["noisy"] for e in G.load(path))
    assert sum(noisy.values()) <= 3, noisy


def test_the_grader_is_not_blind():
    """Negative control: a compiler that returns nothing must be graded as losing."""
    entry = G.load(G.FINAL)[0]
    original = G.compile_instruction
    try:
        G.compile_instruction = lambda text: type("C", (), {"hard_rules": [], "unsupported_restrictions": []})()
        assert "SILENT_LOSS" in G.grade(entry)["grades"].values()
    finally:
        G.compile_instruction = original


# ---------------------------------------------------------------- the families found

def _rules(text):
    return {(r.field, r.scope, r.period_days): r.value for r in compile_instruction(text).hard_rules}


@pytest.mark.parametrize("text,days", [
    ("Buy groceries, total no more than CHF 400 within any seven-day period.", 7),
    ("Buy groceries, max 120 CHF/month.", 30),
    ("Buy groceries, max Fr. 1200/wk.", 7),
    ("Buy groceries, not exceeding 40 CHF weekly.", 7),
    ("Buy groceries, keep the total below 150.- for the week.", 7),
    ("Buy groceries, max CHF 400 any 7 days.", 7),
])
def test_a_rolling_limit_is_never_turned_into_a_per_order_ceiling(text, days):
    rules = _rules(text)
    assert ("authorization.billing_amount_chf", "period", days) in rules, rules
    assert not any(k[1] == "purchase" for k in rules if k[0] == "authorization.billing_amount_chf")


@pytest.mark.parametrize("text", [
    "Buy the monitor, CHF 150 max (that's my weekly spending limit).",
    "Buy the monitor, every month's total stays within CHF 150.",
])
def test_a_period_the_compiler_cannot_read_is_named(text):
    assert any("period of time" in u for u in compile_instruction(text).unsupported_restrictions)


@pytest.mark.parametrize("text", [
    "Buy groceries from shops I've previously purchased from, max CHF 80.",
    "Buy groceries from a store where I have made previous purchases, max CHF 80.",
    "Buy groceries from places I’ve shopped before, max CHF 80.",
    "Buy groceries, same shop as before, max CHF 80.",
    "Buy groceries from one of my usual shops, max CHF 80.",
])
def test_familiar_shop_paraphrases(text):
    assert ("merchant.familiar", None, None) in _rules(text)


@pytest.mark.parametrize("text", [
    "Buy that winter jacket I picked out, max CHF 150.",
    "Buy a winter jacket, I've already picked it, one-time thing, max CHF 150.",
    "Buy the jacket, just one, max CHF 150.",
    "Buy the jacket, 1x only, max CHF 150.",
    "Buy the jacket I've already selected as a one-time purchase, max CHF 150 per month.",
])
def test_one_off_paraphrases(text):
    assert ("order.errand_already_fulfilled", None, None) in _rules(text)


def test_one_off_and_repeat_wording_together_is_named_not_guessed():
    compiled = compile_instruction("Buy the jacket I picked, a one-time thing, and do it every week. Max CHF 150.")
    assert not any(r.field == "order.errand_already_fulfilled" for r in compiled.hard_rules)
    assert any("one-off purchase" in u for u in compiled.unsupported_restrictions)


@pytest.mark.parametrize("text", [
    "Buy a jacket, max CHF 150, must be refundable.",
    "Buy a jacket, max CHF 150, no final-sale items.",
    "Buy a jacket, max CHF 150, must be exchangeable.",
])
def test_return_terms_without_a_day_count_are_named(text):
    assert any("returns" in u for u in compile_instruction(text).unsupported_restrictions)


def test_a_formal_italian_email_is_recognised_as_not_english():
    text = ("Gentile assistente, vorrei acquistare un monitor da 27 pollici, con la possibilità di "
            "restituirlo per almeno 30 giorni. Ti prego inoltre di non superare la spesa di 40 al mese.")
    assert any("not appear to be in English" in u for u in compile_instruction(text).unsupported_restrictions)


def test_an_inch_mark_is_a_size_not_a_count():
    assert not compile_instruction('buy 27" monitor, max CHF 400, ask me if not sure').unsupported_restrictions
