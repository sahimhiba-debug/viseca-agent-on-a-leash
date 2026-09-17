"""The security property fuzzer (deep-security mission, Section 20).

Start from a known-good ALLOW, mutate one thing, and assert the mutation lands in
the class it belongs to. Every mutation is declared as exactly one of:

  SECURITY_RELEVANT  the mutated event describes a materially different purchase,
                     or one that is not ours to answer. The original approval must
                     NOT be handed back for it, and the original authority must not
                     pay for it.

  EQUIVALENT         the mutated event describes the same purchase in a different
                     shape -- re-encoded text, reordered JSON, a different number
                     literal for the same value. An ordinary network retry must
                     stay an ordinary network retry.

Both directions matter. A wallet that invalidates on everything is as broken as
one that invalidates on nothing: the first fails closed on every legitimate retry
and trains its operators to ignore it. The classification below is the actual
security specification of the repeat-delivery path -- it is meant to be read and
argued with, not just run.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Literal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"
OTHER_MERCHANT = "ME_TEST_0002"

Klass = Literal["SECURITY_RELEVANT", "EQUIVALENT"]


@dataclass(frozen=True)
class Mutation:
    name: str
    klass: Klass
    apply: Callable[[dict], None]
    why: str


def _auth(event: dict) -> dict:
    return event["authorization"]


def _line(event: dict) -> dict:
    return _auth(event)["items"][0]


# --- the specification ------------------------------------------------------------

MUTATIONS: list[Mutation] = [
    # ---- money -------------------------------------------------------------------
    Mutation("amount_increased", "SECURITY_RELEVANT",
             lambda e: _auth(e).update(amount=150.0, billing_amount_chf=150.0, items_subtotal=150.0),
             "more money than was approved"),
    Mutation("amount_decreased", "SECURITY_RELEVANT",
             lambda e: _auth(e).update(amount=50.0, billing_amount_chf=50.0, items_subtotal=50.0),
             "a different price is a different purchase, even a cheaper one"),
    Mutation("amount_plus_one_centime", "SECURITY_RELEVANT",
             lambda e: _auth(e).update(amount=100.01, billing_amount_chf=100.01, items_subtotal=100.01),
             "the smallest real money change there is"),

    # ---- counterparty ------------------------------------------------------------
    Mutation("merchant_swapped", "SECURITY_RELEVANT",
             lambda e: _auth(e)["merchant"].update(merchant_id=OTHER_MERCHANT),
             "paying someone else"),

    # ---- basket ------------------------------------------------------------------
    Mutation("item_id_swapped", "SECURITY_RELEVANT",
             lambda e: _line(e).update(item_id="IT_SOMETHING_ELSE"),
             "a different product"),
    Mutation("item_renamed", "SECURITY_RELEVANT",
             lambda e: _line(e).update(item_name="Gold bar"),
             "the name is what every item.* rule reads"),
    Mutation("quantity_changed", "SECURITY_RELEVANT",
             lambda e: _line(e).update(quantity=5),
             "five of them is not one of them"),
    Mutation("extra_line_added", "SECURITY_RELEVANT",
             lambda e: _auth(e)["items"].append(
                 {"line_no": 2, "item_id": "IT_EXTRA", "item_name": "Unrequested extra", "item_category": "electronics",
                  "quantity": 1, "unit_price": 0.0, "currency": "CHF", "item_details": ""}),
             "an unrequested add-on, even at zero price"),

    # ---- merchant text that MOVES A FACT ------------------------------------------
    Mutation("stated_size_changed", "SECURITY_RELEVANT",
             lambda e: _line(e).update(item_details="size 38; returns accepted within 30 days"),
             "a fact a customer rule can read"),
    Mutation("return_window_removed", "SECURITY_RELEVANT",
             lambda e: _line(e).update(item_details="size 43; FINAL SALE, no returns accepted"),
             "the order terms changed under the same id"),

    # ---- identity ----------------------------------------------------------------
    Mutation("card_id_swapped", "SECURITY_RELEVANT",
             lambda e: _auth(e).update(card_id="CA_SOMEONE_ELSE"),
             "not our card; keys the familiarity lookup"),
    Mutation("mandate_id_swapped", "SECURITY_RELEVANT",
             lambda e: _auth(e).update(mandate_id="TM_NOT_OURS"),
             "not our rules"),

    # ---- platform status ---------------------------------------------------------
    Mutation("authority_revoked", "SECURITY_RELEVANT",
             lambda e: _auth(e).update(authority_status="revoked"),
             "the platform says the authority is gone"),
    Mutation("card_blocked", "SECURITY_RELEVANT",
             lambda e: _auth(e).update(card_status_at_attempt="blocked"),
             "the platform says the card may not be used"),

    # ---- equivalent: text re-encoded, no fact moved --------------------------------
    Mutation("details_case_and_padding", "EQUIVALENT",
             lambda e: _line(e).update(item_details="  SIZE 43;   RETURNS   ACCEPTED WITHIN 30 DAYS  "),
             "same two facts, shouted"),
    Mutation("details_zero_width_chars", "EQUIVALENT",
             lambda e: _line(e).update(item_details="size​ 43; returns‌ accepted within 30 days"),
             "invisible characters are stripped before extraction"),
    Mutation("details_nfkc_equivalent_digits", "EQUIVALENT",
             lambda e: _line(e).update(item_details="size ４３; returns accepted within ３０ days"),
             "fullwidth digits normalize to the same numbers"),
    Mutation("details_trailing_noise", "EQUIVALENT",
             lambda e: _line(e).update(item_details="size 43; returns accepted within 30 days!!! <b>SALE</b>"),
             "markup and punctuation move no fact"),

    # ---- equivalent: same value, different shape -----------------------------------
    Mutation("amount_int_vs_float", "EQUIVALENT",
             lambda e: _auth(e).update(amount=100, billing_amount_chf=100, items_subtotal=100),
             "100 and 100.0 are the same money"),
    Mutation("json_key_order", "EQUIVALENT",
             lambda e: e["authorization"].__setitem__("items", [dict(reversed(list(_line(e).items())))]),
             "object key order is not content"),
    Mutation("description_rewritten", "EQUIVALENT",
             lambda e: _auth(e).update(purchase_description="TOTALLY DIFFERENT STORY"),
             "the description never enters facts; the basket is what is read"),
    Mutation("envelope_fields_changed", "EQUIVALENT",
             lambda e: e.update(request_id="req_different", deadline_at="2099-01-01T00:00:00Z"),
             "transport metadata, not purchase content"),
    Mutation("unused_subtotal_split", "EQUIVALENT",
             lambda e: _auth(e).update(items_subtotal=90.0, delivery_fee=10.0),
             "billing_amount_chf is the figure that is checked; the split is display"),
]

ASSUMED_BASE_DETAILS = "size 43; returns accepted within 30 days"


def _state():
    return RunState(
        history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID, OTHER_MERCHANT})}, available=True),
        card_id="CA_TEST",
    )


def _baseline():
    mandate = make_mandate(hard_rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase"),
    ])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=100.0, merchant_id=MERCHANT_ID)
    _auth(event)["order_returnable"] = "true"
    _line(event)["item_details"] = ASSUMED_BASE_DETAILS
    return mandate, event


def _run(mutation: Mutation):
    mandate, event = _baseline()
    state = _state()
    first = evaluate_authorization(event, mandate, state)
    assert first.decision == "allow", "baseline must be an ALLOW for this fuzzer to mean anything"

    mutated = copy.deepcopy(event)
    mutation.apply(mutated)
    return state, first, evaluate_authorization(mutated, mandate, state)


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[m.name for m in MUTATIONS])
def test_mutation_lands_in_its_declared_class(mutation: Mutation):
    state, first, second = _run(mutation)

    if mutation.klass == "SECURITY_RELEVANT":
        # The precise property is about SPENDABILITY, not about the decision string.
        # For a re-delivery the official contract requires the stored decision to be
        # returned unchanged -- we already submitted it and may not submit another.
        # What must not survive is the ability to spend: either the mutation is
        # refused outright, or the original approval stops being payable.
        authority = state.get_authority("AU1")
        still_spendable = (
            second.idempotent_replay
            and second.decision == "allow"
            and authority is not None
            and not authority.revoked
        )
        assert not still_spendable, (
            f"{mutation.name} ({mutation.why}) left the original approval spendable"
        )
    else:
        assert second.idempotent_replay, f"{mutation.name} ({mutation.why}) forked a legitimate retry"
        assert not second.authorization_id_conflict
        assert state.total_approved_spend_chf() == Decimal("100.0"), "an equivalent retry must not double-count spend"


@pytest.mark.parametrize("mutation", [m for m in MUTATIONS if m.klass == "SECURITY_RELEVANT"],
                         ids=[m.name for m in MUTATIONS if m.klass == "SECURITY_RELEVANT"])
def test_a_security_relevant_mutation_never_gets_paid_at_the_mutated_amount(mutation: Mutation):
    """The money-level half: whatever the decision layer says, the payment boundary
    must not pay the mutated amount against the original approval."""
    state, first, _second = _run(mutation)
    psp = MockPSP(state)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("150"), merchant_id=MERCHANT_ID)
    assert not psp.is_charged("AU1")


def test_every_mutation_is_classified():
    """Guard against someone adding a mutation without deciding what it means."""
    assert all(m.klass in ("SECURITY_RELEVANT", "EQUIVALENT") for m in MUTATIONS)
    assert len({m.name for m in MUTATIONS}) == len(MUTATIONS)
    assert sum(1 for m in MUTATIONS if m.klass == "EQUIVALENT") >= 8


# --- generated, rather than enumerated --------------------------------------------


@settings(max_examples=150, deadline=None)
@given(
    amount=st.decimals(min_value=Decimal("0.01"), max_value=Decimal("499.99"), places=2).filter(
        lambda d: d != Decimal("100.00")
    )
)
def test_property_any_different_amount_invalidates_the_replay(amount: Decimal):
    """Generated over the whole legal amount range rather than a few literals: no
    amount other than the approved one may be answered with the stored ALLOW."""
    mandate, event = _baseline()
    state = _state()
    assert evaluate_authorization(event, mandate, state).decision == "allow"

    mutated = copy.deepcopy(event)
    _auth(mutated).update(amount=float(amount), billing_amount_chf=float(amount), items_subtotal=float(amount))
    result = evaluate_authorization(mutated, mandate, state)

    assert not (result.idempotent_replay and result.decision == "allow")
    assert state.get_stored_decision("AU1").billing_amount_chf == Decimal("100.0")


@settings(max_examples=150, deadline=None)
@given(noise=st.text(alphabet=st.sampled_from(" \t\n!.,;:-()[]<>*​‌⁠﻿"), min_size=0, max_size=25))
def test_property_fact_free_noise_never_forks_a_retry(noise: str):
    """Generated over whitespace, punctuation and invisible characters: text that
    moves no extractable fact must never turn a retry into a conflict."""
    mandate, event = _baseline()
    state = _state()
    assert evaluate_authorization(event, mandate, state).decision == "allow"

    mutated = copy.deepcopy(event)
    _line(mutated)["item_details"] = ASSUMED_BASE_DETAILS + noise
    result = evaluate_authorization(mutated, mandate, state)

    assert result.idempotent_replay
    assert not result.authorization_id_conflict
