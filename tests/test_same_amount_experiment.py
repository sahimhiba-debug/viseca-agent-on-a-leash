"""The thesis artifact, attacked.

Five purchases at exactly CHF 62, four at the same shop, yielding three different
verdicts. Everything else in this repository exists to make this credible, so it is
pinned harder than anything else and every alternative explanation a hostile jury
member could offer is eliminated here rather than argued about on stage.

THE CONFOUNDERS, AND HOW EACH IS KILLED

    the amount explains it      the same baskets are re-judged against a mandate
                                with EVERY money rule removed; the refusals persist
    duplicate detection         every case is the first decision of its own fresh
                                session, and no verdict may cite `duplicate`
    rolling-window state        same; a fresh session has an empty window
    session ordering            20 shuffled orderings, identical results
    previous decisions          same; nothing precedes any case
    merchant coincidence        both shops are real Swiss grocers, MCC 5411
    hidden amount differences   exact equality asserted, not approximate
    different card state        one card, CA0001, throughout
    fabricated catalogue        every id, name, category and price band checked
    security not policy         every refusal is attributed to the CUSTOMER's own
                                rules, never to a wallet-side safety check
    UI-only verdicts            the page submits live and ships no verdicts

A CORRECTION THIS FILE ENFORCES. An earlier fifth case was a rolling-window breach
presented as "not about the amount". A rolling window bounds a sum of amounts, so
that was false, and the old test missed it by grepping for the literal string
"amount" after the class had been renamed to `budget_window` -- a rename that hid
the problem from the test written to catch it. The case is now the explicit
counterexample and `test_the_counterexample_is_labelled_as_a_money_rule` keeps it
honest.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from research.same_amount_experiment import (
    AMOUNT, CASES, COUNTEREXAMPLES, FAMILIAR, STRANGER, run, run_counterexamples,
)
from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex, RunState

ROOT = Path(__file__).resolve().parents[1]
_read = lambda n: list(csv.DictReader((ROOT / "data" / "official" / n).open(encoding="utf-8")))
ITEMS = {r["item_id"]: r for r in _read("items.csv")}
MERCHANTS = {r["merchant_id"]: r for r in _read("merchants.csv")}
HISTORY = _read("authorization_history.csv")

RESULTS = run()


# ================================================================ 1. the ground truth
@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0][:30])
def test_every_basket_costs_exactly_the_same(case):
    """Exact equality. "About CHF 62" would let a judge say the limit was mis-set."""
    assert sum(l["unit_price"] * l["quantity"] for l in case[3]) == AMOUNT


@pytest.mark.parametrize("case", CASES, ids=lambda c: c[0][:30])
def test_every_line_is_a_real_item_at_a_real_price(case):
    for line in case[3]:
        official = ITEMS.get(line["item_id"])
        assert official, f"{line['item_id']} is not in the official catalogue"
        assert line["name"] == official["item_name"]
        assert line["category"] == official["item_category"]
        low, high = float(official["unit_price_min_chf"]), float(official["unit_price_max_chf"])
        assert low <= line["unit_price"] <= high, (
            f"{line['item_id']} at CHF {line['unit_price']}, band {low}-{high}")


def test_every_headline_case_is_at_one_swiss_grocer():
    """Category, country and MCC identical across all four, so nothing a card can
    see distinguishes them."""
    assert {l["merchant"] for _t, _w, _e, lines in CASES for l in lines} == {FAMILIAR}
    row = MERCHANTS[FAMILIAR]
    assert (row["merchant_category"], row["merchant_country"], row["merchant_mcc"]) \
        == ("groceries", "CH", "5411")


def test_the_reason_the_merchant_case_was_held_out_is_real():
    """It is not squeamishness. In the official data CA0001 has paid every SWISS
    grocer, and the only unfamiliar one is in Germany -- so a card with a country
    allow-list would refuse it too, for a reason unrelated to intent. That is the
    dimension that cannot be held constant here."""
    swiss_grocers = [m for m, r in MERCHANTS.items()
                     if r["merchant_category"] == "groceries" and r["merchant_country"] == "CH"]
    paid = lambda m: [r for r in HISTORY if r["card_id"] == "CA0001"
                      and r["merchant_id"] == m and r["status"] == "approved"]
    assert all(paid(m) for m in swiss_grocers), (
        "a Swiss grocer is now unfamiliar to CA0001 -- the merchant case can be "
        "promoted back into the headline")
    assert MERCHANTS[STRANGER]["merchant_country"] == "DE"


def test_the_familiarity_difference_comes_from_the_official_history():
    """The one case that varies the shop rests entirely on this."""
    paid = lambda m: [r for r in HISTORY
                      if r["card_id"] == "CA0001" and r["merchant_id"] == m
                      and r["status"] == "approved"]
    assert len(paid(FAMILIAR)) > 20, "the familiar shop is no longer familiar"
    assert paid(STRANGER) == [], "the unfamiliar shop has been paid; the case is void"


# =========================================== 2. THE DECISIVE ONE: amount cannot explain it
@pytest.mark.parametrize("case", [c for c in CASES if c[2] != "allow"],
                         ids=lambda c: c[0][:30])
def test_the_refusals_survive_deleting_every_money_rule(case):
    """The confounder that would end the argument, killed directly.

    Re-judge each refused basket against a mandate that has NO amount rule of any
    scope -- no per-purchase ceiling, no rolling window, nothing about money at all.
    If a refusal were secretly about the amount it would vanish. None does.
    """
    title, _why, expected, lines = case
    moneyless = make_mandate(
        "Order groceries from a shop I have used before, only the things I asked "
        "for, only if returnable within 14 days.",
        [HardRule("merchant.familiar", "=", "true"),
         HardRule("item.category", "in", ["groceries"]),
         HardRule("order.return_window_days", ">=", 14)])
    assert not [r for r in moneyless.hard_rules
                if r.field == "authorization.billing_amount_chf"], "a money rule survived"

    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({FAMILIAR})}),
                     card_id="CA_TEST")
    windows = [l["return_days"] for l in lines]
    event = make_event(
        mandate=moneyless, authorization_id="AU_MONEYLESS",
        merchant_id=lines[0]["merchant"], amount=AMOUNT, billing_amount_chf=AMOUNT,
        items_subtotal=AMOUNT,
        order_returnable=("unknown" if any(w is None for w in windows)
                          else "true" if all(w > 0 for w in windows) else "false"),
        items=[{"line_no": i + 1, "item_id": l["item_id"], "item_name": l["name"],
                "item_category": l["category"], "quantity": l["quantity"],
                "unit_price": l["unit_price"], "currency": "CHF",
                "item_details": ("" if l["return_days"] is None
                                 else f"returns accepted within {l['return_days']} days")}
               for i, l in enumerate(lines)])

    decision = evaluate_authorization(event, moneyless, state)
    assert decision.decision != "allow", (
        f"'{title}' is allowed once money rules are removed, so the refusal WAS "
        "about the amount after all")


def test_no_verdict_in_the_five_cites_the_amount():
    for result in RESULTS:
        assert "amount" not in result["blocked_by"], result
        assert "budget_window" not in result["blocked_by"], result


# ============================================================= 3. the other confounders
def test_no_verdict_is_explained_by_duplicate_detection():
    """Cases 1 and 2 are the identical basket. In one session the second would trip
    duplicate suspicion and the experiment would be measuring that instead."""
    for result in RESULTS:
        assert "duplicate" not in result["blocked_by"], result
        assert "session" not in result["blocked_by"], result


def test_the_result_does_not_depend_on_the_order_the_cases_are_run_in():
    """Twenty orderings. A result that depends on order is not a result."""
    baseline = [(r["wallet"], tuple(r["blocked_by"])) for r in RESULTS]
    for seed in range(20):
        shuffled = [(r["wallet"], tuple(r["blocked_by"])) for r in run(shuffle_seed=seed)]
        assert shuffled == baseline, f"order {seed} changed the outcome"


def test_every_case_matches_the_verdict_it_claims():
    for result in RESULTS:
        assert result["wallet"] == result["expected"], result


def test_the_headline_produces_three_different_verdicts():
    """Allow, ask and block -- from one amount at one shop. A card control has no
    concept of the middle one at all."""
    assert sorted({r["wallet"] for r in RESULTS}) == ["allow", "block", "review"]
    reasons = [r["blocked_by"][0] for r in RESULTS if r["wallet"] == "block"]
    assert sorted(reasons) == ["item", "order_terms"]


def test_the_refusals_are_the_customers_own_rules_not_a_safety_check():
    """If a wallet-side security check were producing these, the experiment would be
    about our risk engine rather than about the customer's sentence."""
    from wallet_control.api import _AGENT_DEFAULT_INSTRUCTION
    from wallet_control.policy_compiler import compile_instruction

    customer_fields = {r.field for r in compile_instruction(_AGENT_DEFAULT_INSTRUCTION).hard_rules}
    assert {"merchant.familiar", "item.category", "order.return_window_days"} <= customer_fields


def test_the_card_says_yes_to_every_headline_case():
    """Not carelessness: CHF 62 at a Swiss grocer is, on the only evidence a card
    has, an ordinary purchase."""
    assert [r["card"] for r in RESULTS] == ["allow"] * len(CASES)


def test_the_card_is_modelled_from_the_real_merchant_row():
    """An earlier version passed country="CH" whatever the shop -- which UNDERSTATED
    the card, because Rhine Pantry is in Germany. Modelling the competitor as weaker
    than it is would be the easiest way to lose this argument on stage."""
    counters = {c["title"]: c for c in run_counterexamples()}
    shop_case = next(c for t, c in counters.items() if "never paid" in t)
    assert shop_case["card"] == "block", (
        "the card should refuse the German shop on country; if it does not, the "
        "control is being modelled too weakly")


def test_the_controlled_triple_is_one_basket_with_one_variable():
    """The experiment at its narrowest, and the strongest thing in the repository.

    Rows 1-3 are the SAME GOODS at the SAME PRICES from the SAME SHOP. The only
    thing that differs is what the seller says about sending them back, and that
    one fact produces three different authorizations: allow, ask, block.
    """
    triple = [CASES[i][3] for i in range(3)]
    signature = lambda lines: [(l["item_id"], l["unit_price"], l["merchant"]) for l in lines]
    assert signature(triple[0]) == signature(triple[1]) == signature(triple[2]), (
        "rows 1-3 are no longer the identical basket")

    # the one variable
    assert [l["return_days"] for l in triple[0]] == [30, 30]
    assert [l["return_days"] for l in triple[1]] == [None, None]
    assert [l["return_days"] for l in triple[2]] == [0, 0]

    assert [RESULTS[i]["wallet"] for i in range(3)] == ["allow", "review", "block"]
    assert RESULTS[1]["awaiting_customer"] is True


def test_the_triple_shares_one_timestamp():
    """"Same second" is a claim on the first screen, so it is checked rather than
    assumed. Each case is the first decision of its own fresh session, and the demo
    clock starts every session at the same simulated instant."""
    from wallet_control.api import _AGENT_SESSIONS, app
    from fastapi.testclient import TestClient

    client = TestClient(app)
    stamps = set()
    for index in range(3):
        session = f"ts_probe_{index}"
        client.post("/api/agent/propose",
                    json={"session_id": session, "lines": CASES[index][3]})
        event = next(iter(_AGENT_SESSIONS[session].events_by_authorization.values()))
        stamps.add(event["authorization"]["timestamp"])
    assert len(stamps) == 1, f"the triple spans {len(stamps)} timestamps: {stamps}"


def test_nothing_a_card_can_see_differs_across_all_four():
    """Amount, merchant, country and MCC are the card's entire input. If any of them
    varied, a card could in principle tell the cases apart and the experiment would
    not isolate intent."""
    for _title, _why, _expected, lines in CASES:
        assert sum(l["unit_price"] * l["quantity"] for l in lines) == AMOUNT
        assert {l["merchant"] for l in lines} == {FAMILIAR}
    row = MERCHANTS[FAMILIAR]
    assert (row["merchant_mcc"], row["merchant_country"]) == ("5411", "CH")


# =================================================== 4. the counterexample stays honest
def test_both_counterexamples_are_kept_out_and_labelled():
    """Each is refused by the wallet AND answerable by a card -- one for the right
    reason, one for the wrong one. Holding them out costs a row each and buys an
    argument with no way in."""
    counters = run_counterexamples()
    assert len(counters) == 2
    assert all(c["wallet"] == "block" for c in counters)

    window = next(c for c in counters if "allowance" in c["title"])
    assert window["blocked_by"] == ["budget_window"]
    assert "sum of amounts" in window["why"]

    shop = next(c for c in counters if "never paid" in c["title"])
    assert shop["blocked_by"] == ["merchant"]
    assert "Germany" in shop["why"]

    titles = {c[0] for c in COUNTEREXAMPLES}
    assert not (titles & {c[0] for c in CASES}), "a counterexample leaked into the headline"


def test_we_do_not_claim_more_than_the_experiment_shows():
    import contextlib
    import io

    from research.same_amount_experiment import main

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        assert main() == 0
    output = buffer.getvalue()

    assert "cannot encode these" in output
    assert "Not that it prevents fraud" in output
    for overclaim in ("prevents fraud", "always", "guarantee", "universally better"):
        bad = [line for line in output.splitlines()
               if overclaim in line.lower() and "not that" not in line.lower()]
        assert not bad, f"overclaim in the output: {bad}"
