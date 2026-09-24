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
