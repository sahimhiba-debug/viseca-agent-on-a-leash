"""Tests for the three R&D concepts selected in docs/RND_FINAL_DECISION.md:

  A. PaymentAuthority -- a narrow, expiring, inspectable capability issued only
     from an ALLOW decision.
  D. AuthorizationDrift -- a structured field-level diff against a related or
     conflicting prior authorization.
  E. policy_verdict / security_verdict -- the same evaluations scoped by source,
     provably never more permissive than the full decision.

All three are additive: none of this file's tests modify or depend on removing
any prior test's behavior, and the full pre-existing suite (test_payment_boundary.py,
test_decision_engine.py, etc.) is unaffected -- see the "before/after: 187 -> 187"
note in docs/RND_FINAL_DECISION.md for confirmation this really is additive.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization, resolve_authorization
from wallet_control.drift import compute_drift
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.rules import RuleEvaluation
from wallet_control.state import AuthorityError, HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True), card_id="CA_TEST")


# --- Track A: PaymentAuthority ----------------------------------------------------


def test_allow_decision_issues_a_payment_authority():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=MERCHANT_ID)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "allow"
    assert result.payment_authority is not None
    assert result.payment_authority.merchant_id == MERCHANT_ID
    assert result.payment_authority.amount_ceiling_chf == 50
    assert result.payment_authority.mandate_id == mandate.mandate_id
    assert not result.payment_authority.revoked
    assert result.payment_authority.expires_at > result.payment_authority.issued_at


def test_block_and_review_decisions_never_issue_an_authority():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=10, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=100.0, merchant_id=MERCHANT_ID)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "block"
    assert result.payment_authority is None
    assert state.get_authority("AU1") is None


def test_cannot_issue_an_authority_directly_for_a_non_allow_decision():
    state = _state()
    with pytest.raises(AuthorityError):
        state.issue_authority("AU_NEVER_DECIDED", mandate_id="TM1", policy_version="abc123")


def test_re_evaluating_an_allowed_authorization_does_not_mint_a_second_authority():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=MERCHANT_ID)
    first = evaluate_authorization(event, mandate, state)
    second = evaluate_authorization(event, mandate, state)  # idempotent replay
    assert first.payment_authority == state.issue_authority("AU1", mandate_id=mandate.mandate_id, policy_version="anything")
    # issuing again with a DIFFERENT policy_version must still return the ORIGINAL --
    # an authority's terms are fixed at first issuance, not refreshable.
    assert first.payment_authority.issued_at == state.get_authority("AU1").issued_at


def test_charge_via_authority_succeeds_within_bounds():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=MERCHANT_ID)
    result = evaluate_authorization(event, mandate, state)
    psp = MockPSP(state)
    record = psp.charge_via_authority(charge_id="CH1", authority=result.payment_authority, amount_chf=Decimal("50"))
    assert record.amount_chf == 50
    assert psp.is_charged("AU1")


def test_charge_via_authority_rejects_amount_over_the_authoritys_own_ceiling():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=MERCHANT_ID)
    result = evaluate_authorization(event, mandate, state)
    psp = MockPSP(state)
    with pytest.raises(PaymentError):
        psp.charge_via_authority(charge_id="CH1", authority=result.payment_authority, amount_chf=Decimal("50.01"))


def test_charge_via_authority_rejects_an_expired_authority():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=MERCHANT_ID)
    result = evaluate_authorization(event, mandate, state)
    psp = MockPSP(state)
    way_later = result.payment_authority.expires_at + timedelta(seconds=1)
    with pytest.raises(PaymentError, match="expired"):
        psp.charge_via_authority(charge_id="CH1", authority=result.payment_authority, amount_chf=Decimal("50"), now=way_later)
    assert not psp.is_charged("AU1")


def test_charge_via_authority_rejects_a_revoked_authority():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=MERCHANT_ID)
    result = evaluate_authorization(event, mandate, state)
    state.revoke_authority("AU1")
    psp = MockPSP(state)
    revoked_authority = state.get_authority("AU1")
    with pytest.raises(PaymentError, match="revoked"):
        psp.charge_via_authority(charge_id="CH1", authority=revoked_authority, amount_chf=Decimal("50"))
    assert not psp.is_charged("AU1")


def test_revoking_a_never_issued_authority_is_a_safe_no_op():
    state = _state()
    assert state.revoke_authority("AU_NEVER_SEEN") is None


def test_revoking_an_already_revoked_authority_stays_revoked():
    """I27: revocation is monotonic -- a second revoke can never un-revoke."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=MERCHANT_ID)
    evaluate_authorization(event, mandate, state)
    first = state.revoke_authority("AU1")
    second = state.revoke_authority("AU1")
    assert first.revoked and second.revoked
    assert state.get_authority("AU1").revoked


def test_a_step_up_resolved_to_allow_also_issues_an_authority_when_mandate_is_supplied():
    mandate = make_mandate(hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    first = evaluate_authorization(event, mandate, state)
    assert first.decision == "review"
    assert first.payment_authority is None

    resolved = resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc), mandate=mandate)
    assert resolved.payment_authority is not None
    assert resolved.payment_authority.amount_ceiling_chf == 50


def test_resolving_without_a_mandate_argument_stays_fully_backward_compatible():
    """Every pre-existing caller of resolve_authorization omits `mandate` -- this
    must keep working exactly as before, just without issuing an authority."""
    mandate = make_mandate(hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    state = RunState(history=HistoryIndex.empty(), card_id="CA_TEST")
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    evaluate_authorization(event, mandate, state)
    resolved = resolve_authorization("AU1", "allow", state, resolved_at=datetime.now(timezone.utc))
    assert resolved.decision == "allow"
    assert resolved.payment_authority is None


# --- Track D: AuthorizationDrift ---------------------------------------------------


def test_compute_drift_reports_no_change_when_nothing_differs():
    basket = (("IT1", 1),)
    drift = compute_drift(
        reference_authorization_id="AU1",
        prior_merchant_id="ME_A", prior_basket_key=basket, prior_amount_chf=Decimal("100"),
        current_merchant_id="ME_A", current_basket_key=basket, current_amount_chf=Decimal("100"),
    )
    assert drift.classification == "none"
    assert drift.changed_fields == ()


def test_compute_drift_classifies_a_lower_requote_as_narrowing():
    """Mirrors the real AU0037 (declined, CHF 520) -> AU0042 (re-quoted, CHF 350) pair."""
    basket = (("IT0017", 1),)
    drift = compute_drift(
        reference_authorization_id="AU0037",
        prior_merchant_id="ME0022", prior_basket_key=basket, prior_amount_chf=Decimal("520"),
        current_merchant_id="ME0022", current_basket_key=basket, current_amount_chf=Decimal("350"),
    )
    assert drift.classification == "narrowing"
    assert drift.changed_fields == (drift.changed_fields[0],)  # exactly one field changed
    assert drift.changed_fields[0].field == "billing_amount_chf"


def test_compute_drift_classifies_a_higher_amount_as_widening():
    basket = (("IT1", 1),)
    drift = compute_drift(
        reference_authorization_id="AU1",
        prior_merchant_id="ME_A", prior_basket_key=basket, prior_amount_chf=Decimal("100"),
        current_merchant_id="ME_A", current_basket_key=basket, current_amount_chf=Decimal("150"),
    )
    assert drift.classification == "widening"


def test_compute_drift_classifies_a_new_item_as_widening_even_if_amount_is_flat():
    drift = compute_drift(
        reference_authorization_id="AU1",
        prior_merchant_id="ME_A", prior_basket_key=(("IT1", 1),), prior_amount_chf=Decimal("100"),
        current_merchant_id="ME_A", current_basket_key=(("IT1", 1), ("IT2", 1)), current_amount_chf=Decimal("100"),
    )
    assert drift.classification == "widening"


def test_compute_drift_classifies_a_merchant_change_as_unrelated_regardless_of_amount():
    basket = (("IT1", 1),)
    drift = compute_drift(
        reference_authorization_id="AU1",
        prior_merchant_id="ME_A", prior_basket_key=basket, prior_amount_chf=Decimal("100"),
        current_merchant_id="ME_B", current_basket_key=basket, current_amount_chf=Decimal("50"),  # even a LOWER amount
    )
    assert drift.classification == "unrelated_change"


def test_a_mutated_retry_carries_drift_evidence():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    state = _state()
    first_event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id=MERCHANT_ID)
    evaluate_authorization(first_event, mandate, state)
    mutated_event = make_event(mandate=mandate, authorization_id="AU1", amount=999.0, merchant_id=MERCHANT_ID)
    second = evaluate_authorization(mutated_event, mandate, state)
    assert second.authorization_id_conflict
    assert second.drift is not None
    assert second.drift.classification == "widening"


def test_a_legitimate_requote_after_a_decline_carries_narrowing_drift_evidence():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=400, currency="CHF", scope="purchase")])
    state = _state()
    monitor_item = [{"line_no": 1, "item_id": "IT0017", "item_name": "27-inch monitor", "item_category": "electronics", "quantity": 1, "unit_price": 520.0, "currency": "CHF", "item_details": ""}]
    declined_event = make_event(mandate=mandate, authorization_id="AU_OVERPRICED", amount=520.0, items=monitor_item, merchant_id=MERCHANT_ID)
    r1 = evaluate_authorization(declined_event, mandate, state)
    assert r1.decision == "block"

    requote_item = [{**monitor_item[0], "unit_price": 350.0}]
    requote_event = make_event(
        mandate=mandate, authorization_id="AU_REQUOTE", amount=350.0, items=requote_item, merchant_id=MERCHANT_ID,
        related_authorization_id="AU_OVERPRICED", related_authorization_status="declined",
    )
    r2 = evaluate_authorization(requote_event, mandate, state)
    assert r2.decision == "allow"
    assert r2.drift is not None
    assert r2.drift.classification == "narrowing"
    assert r2.drift.reference_authorization_id == "AU_OVERPRICED"


# --- Track E: policy_verdict / security_verdict ------------------------------------


def test_a_pure_policy_violation_shows_up_only_in_the_policy_verdict():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=10, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=100.0, merchant_id=MERCHANT_ID)
    result = evaluate_authorization(event, mandate, state)
    assert result.decision == "block"
    assert result.policy_verdict == "block"
    assert result.security_verdict == "allow"  # no safety-sourced evaluation exists here at all -> vacuously allow


def test_a_pure_safety_signal_shows_up_only_in_the_security_verdict():
    """Mirrors AU0036: policy is satisfied, but a duplicate-order safety signal
    alone drives the purchase to REVIEW."""
    mandate = make_mandate(
        uncertainty_policy=UncertaintyPolicy.ASK,
        hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")],
    )
    state = _state()
    items = [{"line_no": 1, "item_id": "IT1", "item_name": "Monitor", "item_category": "electronics", "quantity": 1, "unit_price": 289.0, "currency": "CHF", "item_details": ""}]
    first_event = make_event(mandate=mandate, authorization_id="AU_FIRST", amount=289.0, items=items, merchant_id=MERCHANT_ID)
    r1 = evaluate_authorization(first_event, mandate, state)
    assert r1.decision == "allow" and r1.policy_verdict == "allow" and r1.security_verdict == "allow"

    second_event = make_event(
        mandate=mandate, authorization_id="AU_SECOND", amount=289.0, items=items, merchant_id=MERCHANT_ID,
        timestamp=datetime.fromisoformat(first_event["authorization"]["timestamp"].replace("Z", "+00:00")) + timedelta(minutes=25),
    )
    r2 = evaluate_authorization(second_event, mandate, state)
    assert r2.decision == "review"
    assert r2.policy_verdict == "allow"      # the customer's own rules are fully satisfied
    assert r2.security_verdict == "review"   # the wallet's own safety check is what's asking


@given(
    policy_outcomes=st.lists(st.sampled_from(["pass", "fail", "unknown"]), min_size=0, max_size=3),
    safety_outcomes=st.lists(st.sampled_from(["pass", "fail", "unknown"]), min_size=0, max_size=3),
    uncertainty=st.sampled_from(list(UncertaintyPolicy)),
)
@settings(max_examples=200)
def test_property_final_decision_is_never_more_permissive_than_either_scoped_verdict(policy_outcomes, safety_outcomes, uncertainty):
    """FOR ALL combinations of policy/safety outcomes: the final decision (over the
    full evaluation list) is never LESS restrictive than either scoped verdict --
    i.e. if either sub-verdict is BLOCK, the final is BLOCK; if either is REVIEW and
    neither is BLOCK, the final is not ALLOW (unless uncertainty_policy says so for
    BOTH, since they share the same mandate-level policy)."""
    from wallet_control.decision_engine import _decide, _scoped_verdict
    from wallet_control.mandate import HardRule as HR

    rank = {"allow": 0, "review": 1, "block": 2}

    def _mk(outcomes, source):
        return [RuleEvaluation(rule=HR(field=f"x.{i}", operator="=", value="v"), outcome=o, detail="", source=source) for i, o in enumerate(outcomes)]

    evaluations = _mk(policy_outcomes, "customer") + _mk(safety_outcomes, "safety")
    final_decision, _ = _decide(evaluations, uncertainty)
    policy_verdict = _scoped_verdict(evaluations, "customer", uncertainty)
    security_verdict = _scoped_verdict(evaluations, "safety", uncertainty)

    assert rank[final_decision] >= rank[policy_verdict]
    assert rank[final_decision] >= rank[security_verdict]
