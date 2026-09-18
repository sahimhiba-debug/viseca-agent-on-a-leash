"""Fulfilment derived from the run's persisted decision ledger
(`wallet_control.fulfillment`).

Four real defects are pinned here. Two came from the audits of the earlier
*stateful* prototype, two killed that prototype outright:

  AUDIT 1  counting purchases let two pairs of shoes in ONE authorization pass.
  AUDIT 2  counting the whole basket flagged shoes + a care kit as buying twice.
  A8       a human-approved step-up never reached the tally, so an agent that
           routed everything through step-up was never seen to finish the job.
  A12      a restart reset the tally to zero.

A8 and A12 are the same defect class found three times in `PaymentAuthority`
(V2, V3, V8, V10): lifecycle state kept BESIDE the record it describes. The fix
is not a better tally -- it is deriving the answer from the decision ledger, so
there is no second record that can drift.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from tests.helpers import make_event
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.fulfillment import MandateShape, classify_shape, fulfilment_state, job_anchor
from wallet_control.mandate import HardRule, Mandate, UncertaintyPolicy
from wallet_control.state import HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"
ONE_SHOT = "Buy the 27-inch monitor I chose, for CHF 400 or less."


def _mandate(instruction: str = ONE_SHOT, *, anchor: str | None = "27-inch", familiar_rule: bool = False):
    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=", value=400, currency="CHF", scope="purchase")]
    if anchor:
        rules.append(HardRule(field="item.name_contains", operator="=", value=anchor))
    if familiar_rule:
        rules.append(HardRule(field="merchant.familiar", operator="=", value="true"))
    mandate = Mandate.draft(instruction, rules, UncertaintyPolicy.ASK)
    mandate.confirm(confirmed=True, customer_id="CU_TEST", card_id="CA_TEST", profile_id="PROFILE_TEST")
    return mandate.snapshot()


def _state(*, with_history: bool = True) -> RunState:
    history = HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True) if with_history else HistoryIndex.empty()
    return RunState(history=history, card_id="CA_TEST")


def _buy(mandate, state, authorization_id, *, name="27-inch computer monitor", qty=1, amount=300.0, extra=None):
    event = make_event(mandate=mandate, authorization_id=authorization_id, amount=amount, merchant_id=MERCHANT_ID)
    event["authorization"]["items"][0].update(item_name=name, quantity=qty, item_category="electronics")
    if extra:
        event["authorization"]["items"].append(extra)
    return evaluate_authorization(event, mandate, state)


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
    assert classify_shape("The agent may buy the monitor I chose.").shape is MandateShape.STANDING


def test_every_classification_carries_evidence():
    for instruction in ["Replace my shoes.", "Order our groceries.", "The agent may buy food.", "xyz"]:
        assert classify_shape(instruction).evidence.strip()


# --- the core property ------------------------------------------------------------


def test_a_one_shot_job_is_flagged_on_its_second_fulfilment():
    mandate, state = _mandate(), _state()
    _buy(mandate, state, "AU1")
    assert fulfilment_state(mandate, state, assessing="AU1").verdict == "first_fulfilment"

    _buy(mandate, state, "AU2")
    verdict = fulfilment_state(mandate, state, assessing="AU2")
    assert verdict.verdict == "already_fulfilled"
    assert verdict.would_ask_customer
    assert verdict.prior_authorization_id == "AU1"


@pytest.mark.parametrize("instruction", [
    "Order our household groceries for delivery.",
    "The agent may buy clothing for me, up to CHF 250 per order.",
    "Buy things.",
])
def test_repeatable_and_unclear_mandates_are_never_questioned(instruction):
    mandate, state = _mandate(instruction), _state()
    _buy(mandate, state, "AU1")
    _buy(mandate, state, "AU2")
    verdict = fulfilment_state(mandate, state, assessing="AU2")
    assert verdict.verdict == "not_applicable"
    assert not verdict.would_ask_customer


def test_a_one_shot_mandate_with_no_specific_product_still_counts_purchases():
    """This test previously asserted the opposite -- that an anchorless one-shot
    mandate is never questioned -- on the reasoning that "a category is not specific
    enough to count against". That reasoning is sound about UNITS WITHIN A BASKET and
    was wrongly extended to REPETITION ACROSS baskets.

    The economic-delegation pass measured what the gap was worth: SCEN0000 says "buy
    one ordinary grocery item for CHF 20 or less" and a fully policy-compliant agent
    draws CHF 172,320 through it in a simulated year, unquestioned. Counting
    purchases (not units) closes it without making any claim about basket
    composition, and changes nothing on the official data."""
    mandate, state = _mandate("Buy one ordinary grocery item.", anchor=None), _state()
    assert job_anchor(mandate) is None
    _buy(mandate, state, "AU1")
    assert fulfilment_state(mandate, state, assessing="AU1").verdict == "first_fulfilment"

    _buy(mandate, state, "AU2")
    verdict = fulfilment_state(mandate, state, assessing="AU2")
    assert verdict.verdict == "already_fulfilled"
    assert verdict.prior_authorization_id == "AU1"
    assert verdict.would_ask_customer


def test_an_anchorless_one_shot_mandate_makes_no_claim_about_basket_composition():
    """The other half: counting PURCHASES must not become counting ITEMS. A single
    first purchase containing several groceries is one performance of the job -- the
    module has no basis to say how many items belong in one grocery basket."""
    mandate, state = _mandate("Buy one ordinary grocery item.", anchor=None), _state()
    _buy(mandate, state, "AU1", qty=4)
    assert fulfilment_state(mandate, state, assessing="AU1").verdict == "first_fulfilment"


# --- AUDIT 1: batch evasion --------------------------------------------------------


def test_audit1_one_authorization_cannot_perform_a_one_shot_job_twice():
    mandate, state = _mandate(), _state()
    _buy(mandate, state, "AU1", qty=2, amount=398.0)
    verdict = fulfilment_state(mandate, state, assessing="AU1")
    assert verdict.verdict == "over_fulfilled"
    assert verdict.would_ask_customer


# --- AUDIT 2: the false positive that fix introduced -------------------------------


def test_audit2_an_accessory_line_is_not_a_second_fulfilment():
    mandate, state = _mandate(), _state()
    _buy(mandate, state, "AU1", amount=320.0, extra={
        "line_no": 2, "item_id": "IT2", "item_name": "HDMI cable", "item_category": "electronics",
        "quantity": 1, "unit_price": 20.0, "currency": "CHF", "item_details": "",
    })
    assert fulfilment_state(mandate, state, assessing="AU1").verdict == "first_fulfilment"


# --- A8: the defect that killed the stateful prototype -----------------------------


def test_a8_a_human_approved_step_up_counts_as_fulfilment():
    """The stateful prototype was fed from engine ALLOWs, so a step-up the customer
    approved never reached it -- an agent routing everything through step-up was
    never seen to finish the job. Deriving from the decision ledger includes it,
    because `record_resolution` rewrites the stored decision."""
    mandate = _mandate(familiar_rule=True)
    state = _state(with_history=False)  # unknown merchant -> review

    assert _buy(mandate, state, "AU1").decision == "review"
    resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc), mandate=mandate)

    _buy(mandate, state, "AU2")
    verdict = fulfilment_state(mandate, state, assessing="AU2")
    assert verdict.verdict == "already_fulfilled"
    assert verdict.prior_authorization_id == "AU1"


def test_a_step_up_the_customer_declined_does_not_fulfil_the_job():
    mandate = _mandate(familiar_rule=True)
    state = _state(with_history=False)
    assert _buy(mandate, state, "AU1").decision == "review"
    resolve_authorization("AU1", "block", state, resolved_at=datetime.now(timezone.utc), mandate=mandate)

    _buy(mandate, state, "AU2")
    assert fulfilment_state(mandate, state, assessing="AU2").verdict == "first_fulfilment"


# --- A12: restart ------------------------------------------------------------------


def test_a12_fulfilment_survives_a_restart():
    mandate, state = _mandate(), _state()
    _buy(mandate, state, "AU1")
    _buy(mandate, state, "AU2")

    restored = RunState.from_snapshot(json.loads(json.dumps(state.to_snapshot())), state.history)
    verdict = fulfilment_state(mandate, restored, assessing="AU2")
    assert verdict.verdict == "already_fulfilled"


def test_two_workers_restoring_one_checkpoint_agree():
    """Nothing to synchronise: both compute the same function of the same input.
    The stateful prototype could not have this property at all."""
    mandate, state = _mandate(), _state()
    _buy(mandate, state, "AU1")
    _buy(mandate, state, "AU2")
    snapshot = json.dumps(state.to_snapshot())

    a = RunState.from_snapshot(json.loads(snapshot), state.history)
    b = RunState.from_snapshot(json.loads(snapshot), state.history)
    assert fulfilment_state(mandate, a, assessing="AU2").verdict == fulfilment_state(mandate, b, assessing="AU2").verdict == "already_fulfilled"


def test_the_derivation_is_a_pure_function_of_state():
    """Called twice with no intervening decision, it must give the same answer --
    the property that makes a restart and a second worker safe."""
    mandate, state = _mandate(), _state()
    _buy(mandate, state, "AU1")
    _buy(mandate, state, "AU2")
    first = fulfilment_state(mandate, state, assessing="AU2")
    second = fulfilment_state(mandate, state, assessing="AU2")
    assert first == second


# --- AUDIT 2 findings ---------------------------------------------------------------


def test_audit2_repeated_delivery_is_counted_once():
    """A structural consequence of deriving rather than tallying: the ledger is a
    dict keyed by authorization_id, so replays cannot inflate it. A tally fed from
    engine results would have counted six."""
    mandate, state = _mandate(), _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=300.0, merchant_id=MERCHANT_ID)
    event["authorization"]["items"][0].update(item_name="27-inch computer monitor", item_category="electronics")
    for _ in range(6):
        evaluate_authorization(event, mandate, state)
    assert fulfilment_state(mandate, state, assessing="AU1").verdict == "first_fulfilment"


def test_audit2_a_conflicting_redelivery_does_not_fulfil_the_job():
    mandate, state = _mandate(), _state()
    _buy(mandate, state, "AU1")
    _buy(mandate, state, "AU1", amount=399.0)  # same id, different amount -> conflict, not a new approval
    assert [d.authorization_id for d in state.approved_decisions()] == ["AU1"]


def test_audit2_denial_of_fulfilment_is_a_known_limitation():
    """Audit 2's real finding, pinned as a limitation rather than fixed.

    The anchor is a substring, so a cheap decoy that legitimately contains it
    ("27-inch monitor stand") burns the job and forces the real purchase to need
    customer approval. It costs the attacker money and yields friction, not funds.
    Fixing it would need a product taxonomy this project does not have and has
    repeatedly declined to fake."""
    mandate, state = _mandate(), _state()
    _buy(mandate, state, "AU1", name="27-inch monitor stand", amount=25.0)
    _buy(mandate, state, "AU2", name="27-inch computer monitor", amount=350.0)
    assert fulfilment_state(mandate, state, assessing="AU2").verdict == "already_fulfilled"


# --- the guarantee that it remains an observer -------------------------------------


def test_the_observer_is_not_wired_into_the_decision_path():
    import pathlib

    for module in ("decision_engine.py", "rules.py", "facts.py"):
        source = pathlib.Path(f"src/wallet_control/{module}").read_text()
        assert "fulfillment" not in source, f"{module} must not consult fulfilment"


def test_the_strongest_recommendation_is_to_ask():
    mandate, state = _mandate(), _state()
    _buy(mandate, state, "AU1")
    _buy(mandate, state, "AU2")
    for verdict in (fulfilment_state(mandate, state, assessing="AU1"), fulfilment_state(mandate, state, assessing="AU2")):
        assert verdict.verdict in ("first_fulfilment", "already_fulfilled", "over_fulfilled", "not_applicable")


# --- ECONOMIC-DELEGATION PASS: audit findings on the anchorless one-shot change ----


@pytest.mark.parametrize("instruction", [
    "Buy one of each item on my shopping list, CHF 30 or less each.",
    "Buy one of every size, CHF 30 or less each.",
    "Purchase one per child, CHF 30 or less each.",
])
def test_a_distributive_quantity_is_not_a_single_job(instruction):
    """Audit 1 of the economic-delegation pass.

    "one of each" says how many of EACH thing, over a list whose length is not one.
    While anchorless one-shot mandates were silent, misreading this was free. Once
    they count purchases it is not: a nine-item shopping list would interrupt the
    customer eight times, and a control that cries wolf eight times is training them
    to dismiss the one interruption that matters."""
    assert classify_shape(instruction).shape is not MandateShape.ONE_SHOT


def test_a_cancelled_first_purchase_is_a_known_blind_spot():
    """Audit 1, the finding NOT fixed, pinned here so it cannot be forgotten or
    quietly claimed away.

    If the first purchase is approved and later cancelled, a legitimate retry is
    still reported as a repeat. Fixing it needs `related_authorization_id` on the
    authoritative `StoredDecision`, and this pass declined to widen the security
    core for it: the verdict only ASKS the customer, who can answer "the first one
    was cancelled", and the measured cost on the official data is zero rows --
    `related_authorization_status` appears once, as "declined", and a declined
    purchase was never approved so it never enters this count."""
    mandate, state = _mandate("Buy one ordinary grocery item.", anchor=None), _state()
    _buy(mandate, state, "AU1")
    _buy(mandate, state, "AU2")
    verdict = fulfilment_state(mandate, state, assessing="AU2")
    assert verdict.verdict == "already_fulfilled"     # even if AU1 was later cancelled
    assert verdict.would_ask_customer                 # it asks; it never blocks
