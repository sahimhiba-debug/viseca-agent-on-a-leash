"""The agent's own past purchases were answering a question about the customer's.

THE COMPOSITION DEFECT

`authorization_history.csv` carries `initiator_type` -- human, agent, or merchant --
and the familiarity index collapsed all three. So when a customer writes *"from a
shop I have used before"*, a shop only the AGENT had ever bought from answered yes.
On the official pack that is **24 card/merchant pairs across 18 cards**.

Two individually valid operations compose into a policy that does not do what it
says:

    1. run the agent under a mandate with no familiarity clause;
       it buys at ten shops the customer has never heard of
    2. tighten the mandate to "only shops I have used before"

Every one of those ten now qualifies. The tightening bought nothing, and the
customer believes it bought something. The agent's own history became the
customer's permission -- the authorship defect, one level below the request fields
where `scripts/run_authorship_audit.py` looks.

NOT TRUE, NOT FALSE

Treating it as familiar lets an agent bootstrap its own permission. Treating it as
unfamiliar punishes a customer who genuinely shops through one. It is neither, so
it is UNKNOWN, routed through `uncertainty_policy` like every other unknown -- and
the customer is told *whose* history answered.

`merchant`-initiated rows (recurring charges, refunds) count as the customer's: both
imply a relationship they entered. Measured on the pack, no pair is familiar through
those alone, so nothing turns on the choice.

THE OFFICIAL REPLAY DOES NOT MOVE. The demo card has no agent-only merchants, so
this is a latent defect fixed with no scenario forcing it -- which is the only kind
you get to fix before someone else finds it.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.csv_data import history_csv_path
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.offline_replay import replay_all
from wallet_control.state import HistoryIndex, RunState

AT = datetime(2026, 8, 12, tzinfo=timezone.utc)
MINE, THEIRS, NOBODY = "ME_MINE", "ME_AGENT", "ME_NEW"


def _history():
    return HistoryIndex({"CA_TEST": frozenset({MINE})}, available=True,
                        agent_only_merchants_by_card={"CA_TEST": frozenset({THEIRS})})


def _decide(merchant, *, policy=UncertaintyPolicy.ASK):
    mandate = make_mandate(instruction="x", uncertainty_policy=policy, hard_rules=[
        HardRule(field="merchant.familiar", operator="=", value="true")])
    event = make_event(mandate=mandate, authorization_id=f"AU_{merchant}", amount=50.0,
                       merchant_id=merchant, timestamp=AT)
    event["authorization"]["items"][0].update(item_name="x", item_category="groceries")
    return evaluate_authorization(event, mandate, RunState(history=_history(),
                                                           card_id="CA_TEST"))


def test_the_defect_is_real_in_the_official_data():
    """Not a hypothetical. If this ever came back zero, the finding would be about a
    dataset that no longer exists and this file should be reread, not deleted."""
    seen = defaultdict(lambda: defaultdict(set))
    with history_csv_path().open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["status"] == "approved":
                seen[row["card_id"]][row["merchant_id"]].add(row["initiator_type"])
    agent_only = [(c, m) for c in seen for m, who in seen[c].items() if who == {"agent"}]
    assert len(agent_only) >= 20, len(agent_only)


def test_a_shop_only_the_agent_used_is_not_a_shop_you_have_used():
    assert _decide(MINE).decision == "allow"
    assert _decide(THEIRS).decision == "review"
    assert _decide(NOBODY).decision == "block"


def test_the_customer_is_told_whose_history_answered():
    """The evidence said "your agent has paid this seller before, but you have not"
    while the customer's own message said "the wallet has no purchase history to
    check this seller against" -- a record that is right and a rendering that is
    wrong, in the feature built to fix exactly that."""
    message = _decide(THEIRS).customer_message
    assert "your agent has paid this seller before, but you have not" in message
    assert "no purchase history" not in message


def test_no_history_at_all_still_says_that_instead():
    """The two unknowns must not collapse back into one."""
    mandate = make_mandate(instruction="x", hard_rules=[
        HardRule(field="merchant.familiar", operator="=", value="true")])
    event = make_event(mandate=mandate, authorization_id="AU_NONE", amount=50.0,
                       merchant_id=THEIRS, timestamp=AT)
    event["authorization"]["items"][0].update(item_name="x", item_category="groceries")
    decision = evaluate_authorization(event, mandate,
                                      RunState(history=HistoryIndex.empty(), card_id="CA_TEST"))
    assert decision.decision == "review"
    assert "no purchase history" in decision.customer_message
    assert "your agent" not in decision.customer_message


@pytest.mark.parametrize("policy,expected", [
    (UncertaintyPolicy.APPROVE, "allow"),
    (UncertaintyPolicy.ASK, "review"),
    (UncertaintyPolicy.DECLINE, "block"),
])
def test_the_customers_own_fallback_decides(policy, expected):
    """Not an override. A customer who shops through an agent and says "approve when
    unsure" still gets their purchase."""
    assert _decide(THEIRS, policy=policy).decision == expected


def test_a_merchant_initiated_row_counts_as_the_customers_own():
    """A recurring charge or a refund both imply a relationship the customer entered.
    Measured on the pack: no card/merchant pair is familiar through those alone, so
    nothing turns on the choice -- but it is a choice, and it is written down."""
    seen = defaultdict(lambda: defaultdict(set))
    with history_csv_path().open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["status"] == "approved":
                seen[row["card_id"]][row["merchant_id"]].add(row["initiator_type"])
    merchant_only = [(c, m) for c in seen for m, who in seen[c].items()
                     if who == {"merchant"}]
    assert merchant_only == []

    index = HistoryIndex.from_csv(history_csv_path())
    assert index.is_familiar("CA0003", "ME0020") is None, "an agent-only pair"
    assert index.is_familiar("CA0001", "ME0001") is True


def test_the_official_replay_does_not_move():
    """The demo card has no agent-only merchants. A latent defect fixed with no
    scenario forcing it."""
    assert replay_all().total_counts() == {"allow": 17, "review": 4, "block": 24}
