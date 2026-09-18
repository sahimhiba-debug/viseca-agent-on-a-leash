"""Tests for the fulfilment observer (`wallet_control.fulfillment`), including the
two defects found by the independent audits in
docs/ARCHITECTURAL_BREAKTHROUGH_AUDIT_1.md and _AUDIT_2.md.

The observer is a research module. It gates nothing, and the last test in this
file is the one that keeps that true.
"""

from __future__ import annotations

import pytest

from tests.helpers import make_event
from wallet_control.fulfillment import (
    FulfilmentMonitor,
    MandateShape,
    classify_shape,
    job_anchor,
    units_in,
)
from wallet_control.mandate import HardRule, Mandate, UncertaintyPolicy

MERCHANT_ID = "ME_TEST_0001"


def _mandate(instruction: str, *, anchor: str | None = "road-running") -> object:
    rules = [HardRule(field="item.category", operator="in", value=["sporting_goods"])]
    if anchor:
        rules.append(HardRule(field="item.name_contains", operator="=", value=anchor))
    mandate = Mandate.draft(instruction, rules, UncertaintyPolicy.ASK)
    mandate.confirm(confirmed=True, customer_id="CU_TEST", card_id="CA_TEST", profile_id="PROFILE_TEST")
    return mandate.snapshot()


def _event(mandate, lines):
    event = make_event(mandate=mandate, authorization_id="AU1", amount=180.0, merchant_id=MERCHANT_ID)
    event["authorization"]["items"] = [
        {
            "line_no": i + 1, "item_id": f"IT{i}", "item_name": name, "item_category": "sporting_goods",
            "quantity": qty, "unit_price": 50.0, "currency": "CHF", "item_details": "",
        }
        for i, (name, qty) in enumerate(lines)
    ]
    return event


# --- classification ---------------------------------------------------------------


@pytest.mark.parametrize("instruction,expected", [
    ("Buy the 27-inch monitor I chose, for CHF 400 or less.", MandateShape.ONE_SHOT),
    ("Replace my worn road-running shoes in size 43.", MandateShape.ONE_SHOT),
    ("Buy one ordinary grocery item for CHF 20 or less.", MandateShape.ONE_SHOT),
    ("Order our household groceries for delivery.", MandateShape.RECURRING),
    ("Restock the kitchen every week.", MandateShape.RECURRING),
    ("The agent may buy clothing for me, up to CHF 250 per order.", MandateShape.STANDING),
    ("Buy things.", MandateShape.UNCLEAR),
    ("", MandateShape.UNCLEAR),
])
def test_shape_classification(instruction, expected):
    assert classify_shape(instruction).shape is expected


def test_an_open_grant_beats_a_singular_phrase():
    """Precedence matters: "may buy the monitor I chose" is a standing permission
    that happens to name an item, not a one-shot job."""
    assert classify_shape("The agent may buy the monitor I chose.").shape is MandateShape.STANDING


def test_every_classification_carries_its_evidence():
    """An unexplained classification is not reviewable by a customer."""
    for instruction in ["Replace my shoes.", "Order our groceries.", "The agent may buy food.", "xyz"]:
        assert classify_shape(instruction).evidence.strip()


# --- the core property ------------------------------------------------------------


def test_a_one_shot_job_is_flagged_on_its_second_fulfilment():
    mandate = _mandate("Replace my worn road-running shoes in size 43.")
    monitor = FulfilmentMonitor(mandate)

    assert monitor.assess("AU1").verdict == "first_fulfilment"
    monitor.observe_allow("AU1")

    second = monitor.assess("AU2")
    assert second.verdict == "already_fulfilled"
    assert second.would_ask_customer
    assert second.prior_authorization_id == "AU1"


@pytest.mark.parametrize("instruction", [
    "Order our household groceries for delivery.",
    "The agent may buy clothing for me, up to CHF 250 per order.",
    "Buy things.",
])
def test_repeatable_and_unclear_mandates_are_never_questioned(instruction):
    """The observer must stay silent on anything that is not a finished job --
    this is what keeps it quiet on 2 of the 5 official scenarios."""
    monitor = FulfilmentMonitor(_mandate(instruction))
    monitor.observe_allow("AU1")
    verdict = monitor.assess("AU2")
    assert verdict.verdict == "not_applicable"
    assert not verdict.would_ask_customer


# --- AUDIT 1: the quantity evasion ------------------------------------------------


def test_audit1_one_purchase_cannot_perform_a_one_shot_job_twice():
    """Audit 1's attack: buy two pairs in a single authorization, under the cap.
    One purchase, so the purchase-counting version stayed silent."""
    mandate = _mandate("Replace my worn road-running shoes in size 43.")
    event = _event(mandate, [("Road-running shoes", 2)])

    verdict = FulfilmentMonitor(mandate).assess("AU1", units=units_in(event, mandate))
    assert verdict.verdict == "over_fulfilled"
    assert verdict.would_ask_customer


# --- AUDIT 2: the false positive the quantity fix introduced -----------------------


def test_audit2_an_accessory_line_is_not_a_second_fulfilment():
    """Audit 2's finding: counting the whole basket flagged one pair of shoes plus
    a care kit as buying the shoes twice. Only items matching the job's own anchor
    count."""
    mandate = _mandate("Replace my worn road-running shoes in size 43.")
    event = _event(mandate, [("Road-running shoes", 1), ("Shoe care kit", 1)])

    assert units_in(event, mandate) == 1
    assert FulfilmentMonitor(mandate).assess("AU1", units=units_in(event, mandate)).verdict == "first_fulfilment"


def test_a_mandate_with_no_specific_product_is_never_questioned():
    """"One ordinary grocery item" names a kind, not a job. Without a
    distinguishing phrase, repeat fulfilment is not identifiable and the observer
    says nothing rather than guessing."""
    mandate = _mandate("Buy one ordinary grocery item for CHF 20 or less.", anchor=None)
    assert job_anchor(mandate) is None
    monitor = FulfilmentMonitor(mandate)
    monitor.observe_allow("AU1")
    assert monitor.assess("AU2").verdict == "not_applicable"


# --- the guarantee that it remains an observer -------------------------------------


def test_the_observer_is_not_wired_into_the_decision_path():
    """Structural, not behavioural: if this module is ever imported by the engine,
    the official replay stops being a statement about the shipping architecture."""
    import pathlib

    engine = pathlib.Path("src/wallet_control/decision_engine.py").read_text()
    rules = pathlib.Path("src/wallet_control/rules.py").read_text()
    facts = pathlib.Path("src/wallet_control/facts.py").read_text()
    for source in (engine, rules, facts):
        assert "fulfillment" not in source, "the observer must not gate official decisions"


def test_the_observer_can_only_ever_recommend_asking():
    """It has no verdict that blocks. The strongest thing it can say is "ask"."""
    mandate = _mandate("Replace my worn road-running shoes in size 43.")
    monitor = FulfilmentMonitor(mandate)
    monitor.observe_allow("AU1")
    for verdict in (monitor.assess("AU2"), monitor.assess("AU1"), FulfilmentMonitor(_mandate("Buy things.")).assess("AU3")):
        assert verdict.verdict in ("first_fulfilment", "already_fulfilled", "over_fulfilled", "not_applicable")
        assert not hasattr(verdict, "blocks")
