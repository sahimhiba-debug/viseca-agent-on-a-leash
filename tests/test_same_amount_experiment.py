"""Five purchases, one amount, five answers.

This experiment is the project's central claim, so it is pinned harder than
anything else: the amounts must be equal, the goods must be real, the prices must
be inside their published bands, and the verdicts must diverge for reasons that
have nothing to do with money.

If any of those stops holding, the claim on the first screen becomes false.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from research.same_amount_experiment import AMOUNT, CASES, run

ROOT = Path(__file__).resolve().parents[1]
ITEMS = {r["item_id"]: r for r in
         csv.DictReader((ROOT / "data" / "official" / "items.csv").open(encoding="utf-8"))}
MERCHANTS = {r["merchant_id"]: r for r in
             csv.DictReader((ROOT / "data" / "official" / "merchants.csv").open(encoding="utf-8"))}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0][:28])
def test_every_basket_costs_exactly_the_same(case):
    """The whole argument rests on the amount being held constant. If one basket
    drifts by a franc, a judge can say the limit was simply mis-set."""
    _title, _why, lines = case
    assert sum(l["unit_price"] * l["quantity"] for l in lines) == AMOUNT


@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0][:28])
def test_every_line_is_a_real_item_at_a_real_price(case):
    """Same rule as the demo page: if we name an official id, we tell the truth
    about it. An experiment quoting invented goods would deserve to be dismissed."""
    _title, _why, lines = case
    for line in lines:
        official = ITEMS.get(line["item_id"])
        assert official, f"{line['item_id']} is not in the official catalogue"
        assert line["name"] == official["item_name"]
        assert line["category"] == official["item_category"]
        low = float(official["unit_price_min_chf"])
        high = float(official["unit_price_max_chf"])
        assert low <= line["unit_price"] <= high, (
            f"{line['item_id']} at CHF {line['unit_price']}, band {low}-{high}")
        assert line["merchant"] in MERCHANTS


def test_the_card_says_yes_to_all_five():
    """Not because it is careless. CHF 62 is within the limit, at a grocer, in
    Switzerland -- there is nothing about the number to object to."""
    results = run()
    assert [r["card"] for r in results] == ["allow"] * 5


def test_the_wallet_says_yes_to_exactly_one():
    results = run()
    assert [r["wallet"] for r in results] == ["allow", "block", "block", "block", "block"]


def test_the_four_refusals_are_for_four_different_reasons():
    """One reason repeated would be a weaker argument: it would suggest a single
    extra rule could be bolted onto a card. Four distinct dimensions cannot."""
    results = run()
    reasons = [r["blocked_by"][0] for r in results if r["wallet"] == "block"]
    assert sorted(reasons) == ["budget_window", "item", "merchant", "order_terms"]
    assert len(set(reasons)) == 4


def test_none_of_the_refusals_is_about_the_amount():
    """The point of holding the amount constant. If `amount` ever appears here, the
    experiment has stopped isolating the variable it exists to isolate."""
    for result in run():
        assert "amount" not in result["blocked_by"], result


def test_the_experiment_is_reproducible():
    import contextlib
    import io

    from research.same_amount_experiment import main

    outputs = []
    for _ in range(2):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            assert main() == 0
        outputs.append(buffer.getvalue())
    assert outputs[0] == outputs[1]
    assert "You cannot enforce a sentence with a number" in outputs[0]


# ======================================== the page must DECIDE this, not replay it
def test_the_page_submits_the_baskets_and_never_ships_the_verdicts():
    """The generated file carries baskets only. A demo that shipped its own answers
    while the real engine behaved differently is the single thing this project most
    refuses to build."""
    import json

    from scripts.generate_attack_manifest import SAME_AMOUNT, same_amount

    payload = json.loads(SAME_AMOUNT.read_text())
    assert payload == same_amount(), "ui/same-amount.json is stale; regenerate it"

    blob = json.dumps(payload)
    for verdict_word in ('"allow"', '"block"', '"decision"', '"blocked_by"', '"wallet"'):
        assert verdict_word not in blob, f"the page ships a verdict: {verdict_word}"

    page = (ROOT / "ui" / "index.html").read_text()
    assert "same-amount.json" in page
    assert "/api/agent/propose" in page[page.index("async function runSameAmount"):
                                        page.index("async function renderAskTable")], (
        "the page stopped asking the wallet and is rendering something else")


def test_the_page_spends_the_allowance_before_the_last_basket():
    """The fifth basket is IDENTICAL to the first and must be refused for a reason
    that only exists after the earlier four have been bought. If the page stopped
    filling the window first, the row would silently become a duplicate of row one."""
    page = (ROOT / "ui" / "index.html").read_text()
    section = page[page.index("async function runSameAmount"):page.index("async function renderAskTable")]
    assert "data.cases.length - 1" in section and "for (let k = 0; k < 4" in section
