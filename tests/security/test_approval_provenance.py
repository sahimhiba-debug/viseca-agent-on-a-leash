"""An approval on evidence and an approval on the absence of evidence are not the
same event, and the customer must be able to tell them apart.

WHAT WAS WRONG

`allow` is two different things wearing one word:

    every rule was CHECKED and PASSED                 -- positive evidence
    a rule could not be checked, and the customer's
    `approve when unsure` fallback let it through     -- no evidence at all

The engine has always known which: its reason codes read `uncertain:<field>` in the
second case and `all_hard_rules_satisfied` in the first. But the one field a person
actually reads said, for both,

    "Approved: CHF 62.0 at Alpine Basket matches the rules you set."

-- of a purchase whose return terms were never established, to a customer who had
asked for a fourteen-day return window. That sentence is the only place they could
have learned that their fallback, and not their rule, is what approved this; and a
customer who cannot see when uncertainty is being spent cannot decide to stop
spending it.

1,480 tests did not catch it. None of them asserted anything about what an
approval SAYS -- only about what it decides.

THE SAME DEFECT LIVED IN TWO PLACES, as it did for invariant I39: the fresh
decision, and the stored one re-presented by `GET /api/runs/{id}`. Both are pinned
here, because fixing the first and not the second is exactly how this class of
defect has survived three times in this repository.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.api import _recorded_message
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.state import HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
RULES = [
    HardRule(field="order.return_window_days", operator=">=", value=14),
    HardRule(field="item.category", operator="in", value=["groceries"]),
]


def _decide(details: str, policy=UncertaintyPolicy.APPROVE, aid="AU1"):
    mandate = make_mandate(instruction="Order groceries I can send back within 14 days.",
                           uncertainty_policy=policy, hard_rules=RULES)
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True),
                     card_id="CA_TEST")
    event = make_event(mandate=mandate, authorization_id=aid, amount=62.0,
                       merchant_id=MERCHANT, timestamp=AT, order_returnable="true")
    event["authorization"]["items"][0].update(item_name="coffee", item_category="groceries",
                                              item_details=details)
    return evaluate_authorization(event, mandate, state), state


def test_an_approval_on_evidence_still_says_the_rules_were_met():
    decision, _ = _decide("returns accepted within 30 days")
    assert decision.decision == "allow"
    assert decision.reason_codes == ("all_hard_rules_satisfied",)
    assert "matches the rules you set" in decision.customer_message


def test_an_approval_on_absence_says_so_instead():
    decision, _ = _decide("")
    assert decision.decision == "allow"
    assert any(c.startswith("uncertain:") for c in decision.reason_codes)
    message = decision.customer_message
    assert "matches the rules you set" not in message, message
    assert "Not because the rules were met" in message, message
    # It must name WHICH fact was missing, or the customer cannot act on it.
    assert "return" in message.lower(), message
    # ...and say whose instruction let it through, so the wallet is not blamed for a
    # choice the customer made.
    assert "you told the wallet" in message.lower(), message


def test_the_two_approvals_do_not_read_alike():
    """The whole point. If a future edit made both sentences generic, every test
    above could still pass while the distinction was gone."""
    checked, _ = _decide("returns accepted within 30 days", aid="A")
    absent, _ = _decide("", aid="B")
    assert checked.decision == absent.decision == "allow"
    assert checked.customer_message != absent.customer_message


@pytest.mark.parametrize("details,expect_provenance", [
    ("returns accepted within 30 days", False),
    ("", True),
])
def test_the_re_presented_message_agrees_with_the_fresh_one(details, expect_provenance):
    """`GET /api/runs/{id}` renders a STORED decision through `_recorded_message`.
    That path fell through to "Approved: this purchase matched your wallet policy"
    for both -- the third instance of a re-presented surface contradicting its own
    record."""
    decision, state = _decide(details, aid="AU_R")
    stored = state.get_stored_decision("AU_R")
    message = _recorded_message(stored, {})
    assert ("not because the rules were met" in message.lower()) is expect_provenance, message
    if expect_provenance:
        assert "return" in message.lower(), message


def test_under_ask_the_same_purchase_is_never_approved_at_all():
    """The provenance sentence exists for `approve`. Under `ask` the customer is
    asked, which is a different and already-honest message -- asserted so that a
    future edit cannot satisfy the tests above by making everything say the same
    cautious thing."""
    decision, _ = _decide("", policy=UncertaintyPolicy.ASK)
    assert decision.decision == "review"
    assert "could not decide on its own" in decision.customer_message
