"""A rule evaluated over an empty collection is UNCHECKABLE, not satisfied.

Found by cross-invariant attack Y (decision ledger x malformed platform event).

Every `item.*` branch in `rules.py` reasons over a list, and each of them read an
empty list as agreement:

    item.category in [electronics]      -- nothing is outside the set        -> pass
    item.name_contains = "27-inch"      -- no name fails to match            -> pass
    item.unrequested_present = false    -- nothing unrequested is present    -> pass

So a CHF 400 purchase carrying NO items satisfied four item restrictions at once and
was **ALLOWED under every uncertainty policy, `decline` included**. The strictest
setting a customer can choose was not stricter, which is the tell that this is
structural rather than uncertain.

This is the same class as the `mandate.status` omission fixed earlier: a check
switched off by deleting what it guards, needing no forgery at all. There the
attacker removed a required field; here they empty a required array.

`minItems: 1` in authorization_event.schema.json makes an empty basket malformed, and
nothing in this service validates events against that schema -- which is exactly why
"the platform would never send it" is not a defence we rely on.

TWO LAYERS, deliberately:

  * `decision_engine` rejects an empty basket outright, as a `source="safety"` hard
    failure, so it blocks regardless of `uncertainty_policy`.
  * `rules.py` answers `unknown` for any `item.*` rule with no items, so the vacuity
    is fixed where it lives. Delete the engine check and this file still refuses to
    answer "pass" to a question whose subject it cannot see.

All 45 official events carry items, so neither layer can move the replay.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.state import HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
PERMISSIVENESS = {"block": 0, "review": 1, "allow": 2}

ITEM_RULES = [
    HardRule(field="item.category", operator="in", value=["electronics"]),
    HardRule(field="item.name_contains", operator="=", value="27-inch"),
    HardRule(field="item.unrequested_present", operator="=", value="false"),
    HardRule(field="item.size", operator="=", value="27"),
]

MATCHING_ITEM = {
    "line_no": 1, "item_id": "I1", "item_name": "27-inch monitor", "item_category": "electronics",
    "quantity": 1, "unit_price": 400.0, "currency": "CHF", "item_details": "size 27",
}


def _state() -> RunState:
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True), card_id="CA_TEST")


def _mandate(item_rules, policy=UncertaintyPolicy.ASK):
    return make_mandate(
        instruction="Buy the 27-inch monitor I chose.",
        uncertainty_policy=policy,
        hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=400, currency="CHF", scope="purchase"),
            *item_rules,
        ],
    )


def _decide(mandate, items) -> str:
    event = make_event(mandate=mandate, authorization_id="AU_EMPTY", amount=400.0, merchant_id=MERCHANT, timestamp=AT)
    event["authorization"]["items"] = items
    return evaluate_authorization(event, mandate, _state()).decision


@pytest.mark.parametrize("policy", list(UncertaintyPolicy))
def test_an_empty_basket_is_refused_under_every_uncertainty_policy(policy):
    """Including `approve`. A customer who accepts uncertainty has not accepted
    paying for a purchase with no contents."""
    mandate = _mandate([ITEM_RULES[0]], policy)
    assert _decide(mandate, []) == "block", policy


@pytest.mark.parametrize("rule", ITEM_RULES, ids=lambda r: r.field)
def test_no_item_rule_is_satisfied_by_an_empty_basket(rule):
    """Stated per rule so that a new `item.*` branch added later, written in the same
    list-comprehension style, is caught here rather than in production."""
    from wallet_control.facts import build_purchase_facts
    from wallet_control.rules import RuleContext, evaluate_rule

    mandate = _mandate([rule])
    event = make_event(mandate=mandate, authorization_id="AU_EMPTY", amount=400.0, merchant_id=MERCHANT, timestamp=AT)
    event["authorization"]["items"] = []
    facts = build_purchase_facts(
        event, merchant_familiar=True, session_integrity_risk=False,
        session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None,
    )
    ctx = RuleContext(requested_item_categories=frozenset({"electronics"}), projected_period_spend_chf={})

    assert evaluate_rule(rule, facts, ctx).outcome != "pass", f"{rule.field} is vacuously satisfied by an empty basket"


def test_emptying_the_basket_is_never_more_permissive_than_filling_it():
    """The general property, in the same shape as the required-field omission one:
    removing evidence must not buy a better answer than supplying it."""
    mandate = _mandate(ITEM_RULES)
    populated = _decide(mandate, [MATCHING_ITEM])
    emptied = _decide(mandate, [])
    assert populated == "allow", "the fixture must have something to lose"
    assert PERMISSIVENESS[emptied] < PERMISSIVENESS[populated]


def test_the_official_replay_is_untouched_by_this():
    """All 45 official events carry items, so neither layer of the fix can bite."""
    from wallet_control.offline_replay import replay_all

    result = replay_all()
    assert result.total_counts() == {"allow": 18, "review": 3, "block": 24}
