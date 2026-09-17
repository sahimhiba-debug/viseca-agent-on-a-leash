"""Property-based tests (Hypothesis) for the invariants in
docs/SECURITY_INVARIANTS.md that are meaningful to state as universal properties
rather than hand-picked examples.

These are deliberately NOT tautological: each property is phrased as something
that could plausibly be TRUE of a broken implementation too (e.g. "charging never
succeeds unless decision==allow" is a property a buggy PSP could easily violate in
either direction), not as "assert the function returns what the function returns."
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.money import to_chf, to_decimal
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.policy_compiler import compile_instruction
from wallet_control.state import HistoryIndex, RunState

_SLOW_SETTINGS = settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])

_CURRENCIES = st.sampled_from(["CHF", "EUR", "GBP", "USD"])
_MONEY = st.decimals(min_value="0.01", max_value="100000", places=2, allow_nan=False, allow_infinity=False)


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True), card_id="CA_TEST")


# --- I9/I10: payment amount and merchant binding ----------------------------------


@given(
    approved=_MONEY,
    requested=_MONEY,
    same_merchant=st.booleans(),
)
@settings(max_examples=150)
def test_property_charge_never_exceeds_approved_amount_or_wrong_merchant(approved, requested, same_merchant):
    """FOR ALL (approved_amount, requested_charge_amount, merchant):
    a charge succeeds if and only if requested <= approved AND merchant matches.
    """
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100000, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=float(approved), merchant_id="ME_REAL")
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "allow"

    psp = MockPSP(state)
    merchant = "ME_REAL" if same_merchant else "ME_IMPOSTOR"
    should_succeed = (requested <= approved) and same_merchant

    if should_succeed:
        record = psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=requested, merchant_id=merchant)
        assert record.amount_chf == requested
    else:
        try:
            psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=requested, merchant_id=merchant)
            raised = False
        except PaymentError:
            raised = True
        assert raised, f"charge should have been refused: approved={approved} requested={requested} merchant_match={same_merchant}"


# --- I7/I8: BLOCK and unresolved REVIEW can never pay -----------------------------


@given(amount=_MONEY, merchant_familiar=st.one_of(st.none(), st.booleans()))
@settings(max_examples=100)
def test_property_block_or_review_can_never_be_charged(amount, merchant_familiar):
    """FOR ALL purchase attempts: if decision != allow, no charge can ever succeed
    against that authorization_id, regardless of the requested amount or merchant."""
    mandate = make_mandate(
        uncertainty_policy=UncertaintyPolicy.ASK,
        hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")],
    )
    by_card = {"CA_TEST": frozenset({"ME_TEST_0001"})} if merchant_familiar else {}
    history = HistoryIndex(by_card, available=merchant_familiar is not None)
    state = RunState(history=history, card_id="CA_TEST")
    event = make_event(mandate=mandate, authorization_id="AU1", amount=float(amount), merchant_id="ME_UNFAMILIAR")
    result = evaluate_authorization(event, mandate, state)
    assert result.decision in ("review", "block")  # merchant.familiar can never pass for "ME_UNFAMILIAR" here

    psp = MockPSP(state)
    try:
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=amount, merchant_id="ME_UNFAMILIAR")
        raised = False
    except PaymentError:
        raised = True
    assert raised


# --- I9 restated as a pure ceiling property, no confounding rules -----------------


@given(ceiling=_MONEY, amount=_MONEY)
@settings(max_examples=200)
def test_property_amount_over_ceiling_never_allows(ceiling, amount):
    """FOR ALL (ceiling C, purchase amount): if amount > C, the decision must never
    be ALLOW -- a single hard rule with no other confounding unknowns, so this is a
    clean test of _decide()'s "any fail always blocks" priority."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=float(ceiling), currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=float(amount))
    result = evaluate_authorization(event, mandate, state)
    if amount > ceiling:
        assert result.decision == "block"
    else:
        assert result.decision == "allow"


# --- I13/I14: identical repeat is safe; mutated repeat is a conflict --------------


@given(
    amount1=_MONEY,
    amount2=_MONEY,
    merchant1=st.sampled_from(["ME_A", "ME_B"]),
    merchant2=st.sampled_from(["ME_A", "ME_B"]),
)
@settings(max_examples=150)
def test_property_repeated_authorization_id_is_safe_iff_facts_are_identical(amount1, amount2, merchant1, merchant2):
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100000, currency="CHF", scope="purchase")])
    state = _state()
    first_event = make_event(mandate=mandate, authorization_id="AU1", amount=float(amount1), merchant_id=merchant1)
    first = evaluate_authorization(first_event, mandate, state)

    second_event = make_event(mandate=mandate, authorization_id="AU1", amount=float(amount2), merchant_id=merchant2)
    second = evaluate_authorization(second_event, mandate, state)

    identical = (amount1 == amount2) and (merchant1 == merchant2)
    if identical:
        assert second.idempotent_replay is True
        assert second.authorization_id_conflict is False
        assert second.decision == first.decision
    else:
        assert second.authorization_id_conflict is True
        assert second.decision == "block"
    # Either way, the ORIGINAL stored decision must never be overwritten by the
    # second (possibly mutated) delivery.
    assert state.get_stored_decision("AU1").billing_amount_chf == to_decimal(amount1)
    assert state.get_stored_decision("AU1").merchant_id == merchant1


# --- money: conversion always rounds to 2dp and is monotonic ----------------------


@given(amount=_MONEY, currency=_CURRENCIES)
@settings(max_examples=200)
def test_property_to_chf_always_rounds_to_two_decimal_places(amount, currency):
    result = to_chf(amount, currency)
    assert result == result.quantize(Decimal("0.01"))


@given(amount1=_MONEY, amount2=_MONEY, currency=_CURRENCIES)
@settings(max_examples=200)
def test_property_to_chf_is_monotonic_in_amount(amount1, amount2, currency):
    """A larger amount in the same currency must never convert to a smaller CHF
    figure -- a monotonicity property a broken rounding rule could violate."""
    chf1, chf2 = to_chf(amount1, currency), to_chf(amount2, currency)
    if amount1 < amount2:
        assert chf1 <= chf2
    elif amount1 > amount2:
        assert chf1 >= chf2


# --- policy compiler: must never crash, regardless of input -----------------------


@given(text=st.text(max_size=500))
@_SLOW_SETTINGS
def test_property_compile_instruction_never_crashes_on_arbitrary_text(text):
    """FOR ALL strings (garbage, empty, huge, adversarial, any Unicode): the
    compiler must return a CompiledPolicy, never raise. A crash here would be a
    denial-of-service in the mandate-creation path."""
    compiled = compile_instruction(text)
    assert compiled.uncertainty_policy in (UncertaintyPolicy.ASK, UncertaintyPolicy.DECLINE, UncertaintyPolicy.APPROVE)
    # Every produced rule already passed HardRule.__post_init__'s validation at
    # construction time, so reaching this line at all is part of the property.
    for rule in compiled.hard_rules:
        assert rule.field and rule.operator


@given(
    injected=st.text(alphabet=st.characters(blacklist_categories=("Cs",)), max_size=200),
)
@_SLOW_SETTINGS
def test_property_arbitrary_item_details_never_changes_the_mandates_own_rules(injected):
    """FOR ALL merchant-supplied item_details text: the mandate's hard_rules --
    fixed once at mandate-creation time -- are never touched by evaluating a
    purchase whose item_details is that text, no matter what it says."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    rules_before = mandate.hard_rules
    event = make_event(
        mandate=mandate,
        amount=50.0,
        items=[{"line_no": 1, "item_id": "IT1", "item_name": "Test item", "item_category": "groceries", "quantity": 1, "unit_price": 50.0, "currency": "CHF", "item_details": injected}],
    )
    evaluate_authorization(event, mandate, _state())
    assert mandate.hard_rules == rules_before
