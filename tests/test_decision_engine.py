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


# --- a mandate with zero hard rules must never become unlimited authority --------


def test_mandate_with_no_hard_rules_asks_by_default_rather_than_allowing_everything():
    """The single most important finding of the second adversarial audit: an empty
    or unparseable instruction must not silently become a blank cheque. With zero
    hard_rules, the mandate's uncertainty_policy (ASK by default) must govern every
    purchase, since there is nothing else to check it against."""
    mandate = make_mandate(hard_rules=[], uncertainty_policy=UncertaintyPolicy.ASK)
    event = make_event(mandate=mandate, amount=999999.0)
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "review"
    assert any("has_no_rules" in code for code in result.reason_codes)


def test_mandate_with_no_hard_rules_and_decline_policy_declines_everything():
    mandate = make_mandate(hard_rules=[], uncertainty_policy=UncertaintyPolicy.DECLINE)
    event = make_event(mandate=mandate, amount=10.0)
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "block"


def test_mandate_with_no_hard_rules_and_explicit_approve_policy_still_allows():
    """A customer who explicitly, visibly chose 'approve when uncertain' (a
    deliberate, informed choice reflected in the compiled uncertainty_policy) gets
    what they asked for -- the safety net only stops an ACCIDENTAL blank cheque,
    not a customer's genuine, explicit instruction."""
    mandate = make_mandate(hard_rules=[], uncertainty_policy=UncertaintyPolicy.APPROVE)
    event = make_event(mandate=mandate, amount=999999.0)
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "allow"


# --- amount-integrity check: billing_amount_chf must match amount * fx_rate ------


def test_amount_integrity_check_blocks_a_mismatched_billing_amount():
    """An always-on safety check, independent of the mandate: if billing_amount_chf
    does not match amount*fx_rate, something is wrong with the data (a bug or
    manipulation), and it must never be trusted for the ceiling comparison."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, amount=50.0, currency="CHF", billing_amount_chf=5.0)  # tampered: should be 50.0
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "block"
    assert any("amount_integrity" in code for code in result.reason_codes)


def test_amount_integrity_check_passes_for_consistent_data():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, amount=100.0, currency="USD", billing_amount_chf=87.0)  # 100 * 0.87 = 87.00
    result = evaluate_authorization(event, mandate, _state())
    assert result.decision == "allow"


# --- repeated authorization_id with mutated facts must never be silently trusted --


def test_repeated_authorization_id_with_a_different_amount_is_flagged_not_trusted():
    """A same-ID retry whose facts changed is neither the same purchase (so the old
    decision must not be blindly returned) nor safely a new one (the platform may
    already have a decision for this ID) -- it must fail closed and say so."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    state = _state()
    first_event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    first = evaluate_authorization(first_event, mandate, state)
    assert first.decision == "allow"

    mutated_event = make_event(mandate=mandate, authorization_id="AU1", amount=999.0)  # same ID, different amount
    second = evaluate_authorization(mutated_event, mandate, state)
    assert second.authorization_id_conflict is True
    assert second.decision == "block"
    # The ORIGINAL decision must remain untouched for payment-boundary purposes.
    assert state.get_stored_decision("AU1").decision == "allow"
    assert state.get_stored_decision("AU1").billing_amount_chf == 50


def test_repeated_authorization_id_with_a_different_merchant_is_flagged():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    state = _state()
    first_event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id="ME_A")
    evaluate_authorization(first_event, mandate, state)

    mutated_event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0, merchant_id="ME_B")
    second = evaluate_authorization(mutated_event, mandate, state)
    assert second.authorization_id_conflict is True


def test_genuinely_identical_repeated_delivery_is_not_flagged_as_a_conflict():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    evaluate_authorization(event, mandate, state)
    second = evaluate_authorization(event, mandate, state)  # exact same event, redelivered
    assert second.authorization_id_conflict is False
    assert second.idempotent_replay is True
