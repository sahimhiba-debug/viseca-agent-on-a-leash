from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.state import HistoryIndex, RunState


def _state(available=True, familiar_merchants=None):
    # Only populate the card's entry when the test wants a *known* (possibly empty)
    # merchant set; omitting it means "no history at all for this card" -> unknown,
    # not "confirmed unfamiliar" -- see HistoryIndex.is_familiar.
    by_card = {"CA_TEST": frozenset(familiar_merchants)} if familiar_merchants is not None else {}
    history = HistoryIndex(by_card, available=available)
    return RunState(history=history, card_id="CA_TEST")


def test_all_pass_allows():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, amount=50.0)
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "allow"


def test_a_clear_failure_blocks_even_with_other_unknowns_present():
    """Priority rule: FAIL always wins over UNKNOWN, regardless of uncertainty_policy."""
    mandate = make_mandate(
        uncertainty_policy=UncertaintyPolicy.APPROVE,  # would auto-allow on pure uncertainty
        hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=10, currency="CHF", scope="purchase"),
            HardRule(field="merchant.familiar", operator="=", value="true"),  # unknown: no history
        ],
    )
    event = make_event(mandate=mandate, amount=50.0)
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "block"


def test_unknown_only_follows_uncertainty_policy_ask():
    mandate = make_mandate(uncertainty_policy=UncertaintyPolicy.ASK, hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    event = make_event(mandate=mandate)
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "review"
    assert result.intervention == "ask_missing_fact"


def test_unknown_only_follows_uncertainty_policy_decline():
    mandate = make_mandate(uncertainty_policy=UncertaintyPolicy.DECLINE, hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    event = make_event(mandate=mandate)
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "block"


def test_unknown_only_follows_uncertainty_policy_approve():
    mandate = make_mandate(uncertainty_policy=UncertaintyPolicy.APPROVE, hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    event = make_event(mandate=mandate)
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "allow"


def test_idempotent_replay_of_same_authorization_id_does_not_recompute_or_double_count():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU_DUP", amount=50.0)
    first = evaluate_authorization(event, mandate, state)
    second = evaluate_authorization(event, mandate, state)
    assert first.decision == second.decision == "allow"
    assert second.idempotent_replay is True
    assert first.idempotent_replay is False
    # spend must be counted exactly once
    assert state.total_approved_spend_chf() == 50


def test_intervention_never_for_a_hard_block():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=10, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, amount=100.0)
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "block"
    assert result.intervention == "never"


def test_evidence_and_reason_codes_reference_the_actual_failing_field():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=10, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, amount=100.0)
    result = evaluate_authorization(event, mandate, _state())
    assert any("authorization.billing_amount_chf" in code for code in result.reason_codes)
    assert any("authorization.billing_amount_chf" in e for e in result.evidence)
