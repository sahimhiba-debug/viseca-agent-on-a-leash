"""Asserts the new, clearly-synthetic R&D demo scenario (`wallet_control.demo_scenario`)
tells the exact story it claims to: prompt injection -> compromised re-quote ->
drift-detected REVIEW -> customer decline -> legitimate continuation -> narrow
payment authority -> final execution boundary check. Kept separate from the
official-replay tests since this scenario is not official data.
"""

from __future__ import annotations

from decimal import Decimal

from wallet_control.demo_scenario import run_demo_scenario


def test_step1_honest_proposal_allows_despite_injected_text():
    result = run_demo_scenario()
    step1 = result.steps[0]
    assert step1.result.decision == "allow"
    assert step1.result.payment_authority is not None
    assert step1.result.payment_authority.merchant_id == "ME_DEMO_TRUSTED"


def test_step2_redirected_requote_is_reviewed_not_silently_allowed_or_blocked():
    result = run_demo_scenario()
    step2 = result.steps[1]
    assert step2.result.decision == "review"
    assert step2.result.payment_authority is None


def test_step2_drift_flags_the_merchant_change_as_unrelated():
    result = run_demo_scenario()
    step2 = result.steps[1]
    assert step2.result.drift is not None
    assert step2.result.drift.classification == "unrelated_change"
    changed_fields = {f.field for f in step2.result.drift.changed_fields}
    assert "merchant_id" in changed_fields


def test_no_hard_rule_in_the_mandate_mentions_merchant_identity():
    """The whole point of this scenario: a conventional hard-rule-only wallet has
    no rule that would ever notice the merchant changed. Only drift evidence does."""
    result = run_demo_scenario()
    fields = {r.field for r in result.mandate.hard_rules}
    assert not any("merchant" in f for f in fields)


def test_customer_declines_the_redirected_purchase():
    result = run_demo_scenario()
    assert result.resolution is not None
    assert result.resolution.decision == "block"


def test_legitimate_continuation_allows_with_a_fresh_narrow_authority():
    result = run_demo_scenario()
    step3 = result.steps[2]
    assert step3.result.decision == "allow"
    authority = step3.result.payment_authority
    assert authority is not None
    assert authority.merchant_id == "ME_DEMO_TRUSTED"
    assert authority.amount_ceiling_chf == Decimal("299.0")


def test_final_execution_boundary_allows_legitimate_charge_and_refuses_tampered_one():
    result = run_demo_scenario()
    assert result.legitimate_charge is not None
    assert result.legitimate_charge.amount_chf == Decimal("299.0")
    assert result.tampered_charge_error is not None
    assert "exceeds" in result.tampered_charge_error


def test_scenario_never_touches_official_data():
    """Every id in this scenario is DEMO-prefixed so it can never collide with, or
    be mistaken for, the official 45-event replay data."""
    result = run_demo_scenario()
    for step in result.steps:
        auth = step.event["authorization"]
        assert auth["authorization_id"].startswith("AU_DEMO_")
        assert auth["merchant"]["merchant_id"].startswith("ME_DEMO_")
        assert auth["scenario_id"] == "DEMO_RND_0001"
