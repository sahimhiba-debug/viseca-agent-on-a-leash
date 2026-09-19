"""`customer_message` goes to a person. It used to carry the engine's debug output.

`technical_details.md` shows this field carrying sentences -- "Please review this
purchase." -- and instructs solutions to "show the reason and purchase details to the
real customer". What `live_worker` actually submitted was:

    Declined: CHF 62.0 at Alpine Basket -- authorization.billing_amount_chf (fail):
    projected 7-day spend=361.5 CHF (including this purchase); item.category (fail):
    item_categories=['cosmetics', 'groceries'], outside requested set: ['cosmetics']

Internal field names, the engine's own `(fail)` vocabulary, and a Python list repr,
in a field named `customer_message`.

WHY THIS SURVIVED EVERY PREVIOUS AUDIT. The demo UI was never affected: it renders
`reason_codes` through its own plain-language table and hides raw evidence behind a
"Technical evidence" disclosure. So every pass that looked at the UI saw polished
explanations, and the OFFICIAL submission path -- the one an actual customer would
read -- had no such layer. The polish existed exactly where we were looking.

The technical facts still reach the platform; they belong in `evidence`, which the
spec describes as "facts supporting the result".

One trap, found while fixing it: a per-order breach and a rolling-window breach are
the same FIELD and mean completely different things to a person -- "this order is too
big" versus "you have spent too much this week". Collapsing them to one sentence
blames the wrong boundary and would send the customer to look at the order instead of
at the week.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wallet_control.decision_engine import _PLAIN_FAIL, _PLAIN_UNKNOWN
from wallet_control.offline_replay import replay_all

UI = Path(__file__).resolve().parents[2] / "ui" / "index.html"

# Anything that betrays the engine's internals to someone reading their wallet.
LEAKS = [
    (re.compile(r"\(fail\)|\(unknown\)|\(pass\)"), "the engine's internal outcome vocabulary"),
    (re.compile(r"\[['\"]"), "a Python list repr"),
    (re.compile(r"\b\w+\.\w+_\w+\b"), "an internal dotted field name"),
    (re.compile(r"projected \d+-day spend="), "an internal computation dump"),
    (re.compile(r"item_categories=|item_sizes=|merchant_familiar=|billing_amount_chf="), "an internal variable"),
]


@pytest.mark.parametrize("scenario", replay_all().scenarios, ids=lambda s: s.scenario_id)
def test_no_official_decision_leaks_engine_internals_to_the_customer(scenario):
    for decision in scenario.decisions:
        for pattern, what in LEAKS:
            assert not pattern.search(decision.customer_message), (
                f"{decision.authorization_id}: {what} in customer_message -- {decision.customer_message!r}"
            )


@pytest.mark.parametrize("scenario", replay_all().scenarios, ids=lambda s: s.scenario_id)
def test_every_message_still_names_the_amount_and_the_merchant(scenario):
    """Plain does not mean vague. The spec asks for the reason AND the purchase
    details; a message a customer cannot tie to a specific purchase is useless."""
    for decision in scenario.decisions:
        assert "CHF" in decision.customer_message, decision.authorization_id
        assert decision.facts.merchant_name in decision.customer_message, decision.authorization_id


def test_a_rolling_window_breach_does_not_read_like_an_oversized_order():
    """The two boundaries must not be confused. SCEN0001 produces both."""
    messages = [
        d.customer_message
        for s in replay_all().scenarios
        for d in s.decisions
        if d.decision == "block"
    ]
    period = [m for m in messages if "across any" in m]
    assert period, "the fixture must contain a rolling-window breach"
    for message in period:
        assert "period" in message or "day" in message, message


def test_every_block_and_review_gives_at_least_one_reason():
    for scenario in replay_all().scenarios:
        for decision in scenario.decisions:
            if decision.decision == "allow":
                continue
            assert "Reason:" in decision.customer_message or "because" in decision.customer_message, (
                decision.customer_message
            )


def _ui_map(name: str) -> set[str]:
    """The keys of a JS object literal in the UI, parsed rather than eyeballed."""
    match = re.search(rf"const {name} = \{{(.*?)\n\}};", UI.read_text(), re.S)
    assert match, f"{name} not found in ui/index.html"
    return set(re.findall(r"'([^']+)'\s*:", match.group(1)))


def test_plain_language_is_consistent_between_the_engine_and_the_ui():
    """Two copies of the same wording, in two languages, is a drift hazard. The engine
    must explain at least every field the UI knows how to explain -- otherwise a
    customer reading the platform's message gets "a check did not pass" for something
    the demo screen describes properly."""
    missing_fail = _ui_map("RULE_TEXT") - set(_PLAIN_FAIL)
    assert not missing_fail, f"the UI explains these but the engine does not: {sorted(missing_fail)}"
    missing_unknown = _ui_map("UNSURE_TEXT") - set(_PLAIN_UNKNOWN)
    assert not missing_unknown, f"the UI explains these but the engine does not: {sorted(missing_unknown)}"


def test_an_unmapped_field_degrades_to_prose_not_to_a_field_name():
    from wallet_control.decision_engine import _plain_reason
    from wallet_control.mandate import HardRule
    from wallet_control.rules import RuleEvaluation

    unknown_field = HardRule(field="item.colour", operator="=", value="red")
    text = _plain_reason(RuleEvaluation(rule=unknown_field, outcome="fail", detail="x"))
    assert "item.colour" not in text, text
    assert text.startswith("a check on "), text
