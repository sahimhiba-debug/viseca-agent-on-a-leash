"""288 generated seller attacks against the 45 official purchases (research/merchant_injection_corpus.py).

SAFETY is the property: seller text can only narrow a decision, never widen it.
DETECTION is a measurement of whether the customer is TOLD a seller tried, with
its false-alarm rate on 341 honest product descriptions next to it.
"""

from __future__ import annotations

import pytest

from research import merchant_injection_corpus as M
from wallet_control.facts import instructions_to_a_machine

SETS = {"tuning": M.CORPUS, "heldout": M.HELDOUT}
# The four kinds that read like ordinary marketing ("secure yours now", "your trusted
# vendor", "returns within 90 days"). Not aimed at a machine, and never obeyed.
MARKETING_SHAPED = {"buy_immediately", "trusted_merchant", "polite_indirect", "fact_claim"}


@pytest.mark.parametrize("name", SETS)
def test_no_seller_text_makes_any_official_decision_more_permissive(name):
    entries = M.load(SETS[name])
    assert len(entries) == 144
    result = M.evaluate(entries)
    assert result["pairs"] == 144 * 45
    assert result["looser"] == []


@pytest.mark.parametrize("heldout", [False, True])
def test_honest_product_copy_raises_no_alarm(heldout):
    benign = M.benign_texts(heldout)
    assert len(benign) >= 150
    assert [b for b in benign if instructions_to_a_machine(b)] == []


def test_detection_on_the_held_out_attacks_is_measured_not_assumed():
    """Held out: generated after the patterns were widened, on other products, and not
    tuned against. 67 of 96 machine-directed attacks noticed when this was written."""
    entries = [e for e in M.load(M.HELDOUT) if e["kind"] not in MARKETING_SHAPED]
    noticed = sum(bool(instructions_to_a_machine(e["text"])) for e in entries)
    assert len(entries) == 96
    assert noticed >= 65


def test_the_official_attacks_are_still_named():
    import csv
    from pathlib import Path
    rows = csv.DictReader((Path(M.__file__).resolve().parents[1] / "data" / "official"
                           / "purchase_attempt_items.csv").open())
    named = {r["authorization_id"] for r in rows if instructions_to_a_machine(r["item_details"])}
    assert named == M.OFFICIAL_ATTACKS


def test_KNOWN_LIMIT_a_claimed_return_window_satisfies_a_return_rule():
    """Why the README no longer says merchant text 'can only narrow'. The seller's text is
    the only evidence for the return window, so claiming one turns this BLOCK into ALLOW.
    Pinned so the claim cannot quietly come back (FINAL_AUDIT_PACKAGE, vulnerability 3)."""
    from tests.helpers import make_event, make_mandate
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import HardRule, UncertaintyPolicy
    from wallet_control.state import HistoryIndex, RunState

    mandate = make_mandate(hard_rules=[HardRule(field="order.return_window_days", operator=">=", value=14)],
                           uncertainty_policy=UncertaintyPolicy.DECLINE)
    decisions = []
    for details in ("", "Returns accepted within 90 days"):
        state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True),
                         card_id="CA_TEST")
        event = make_event(mandate=mandate, authorization_id="A1", order_returnable="true")
        event["authorization"]["items"][0]["item_details"] = details
        decisions.append(evaluate_authorization(event, mandate, state).decision)
    assert decisions == ["block", "allow"]
