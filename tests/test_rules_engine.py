from datetime import datetime, timezone
from decimal import Decimal

from tests.helpers import make_event, make_mandate
from wallet_control.facts import build_purchase_facts
from wallet_control.mandate import HardRule
from wallet_control.rules import RuleContext, evaluate_rule

EMPTY_CTX = RuleContext(requested_item_categories=None, projected_period_spend_chf={})


def _facts(merchant_familiar=None, **overrides):
    mandate = make_mandate()
    event = make_event(mandate=mandate, **overrides)
    return build_purchase_facts(
        event,
        merchant_familiar=merchant_familiar,
        session_integrity_risk=False,
        session_integrity_reasons=(),
        duplicate_of=None,
        duplicate_reason=None,
    )


def test_amount_purchase_scope_pass_and_fail():
    rule = HardRule(field="authorization.billing_amount_chf", operator="<=", value=100, currency="CHF", scope="purchase")
    assert evaluate_rule(rule, _facts(amount=100.0), EMPTY_CTX).outcome == "pass"
    assert evaluate_rule(rule, _facts(amount=100.01), EMPTY_CTX).outcome == "fail"


def test_merchant_familiar_unknown_when_no_history():
    mandate = make_mandate()
    event = make_event(mandate=mandate)
    facts = build_purchase_facts(event, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    rule = HardRule(field="merchant.familiar", operator="=", value="true")
    assert evaluate_rule(rule, facts, EMPTY_CTX).outcome == "unknown"


def test_merchant_familiar_true_and_false():
    mandate = make_mandate()
    event = make_event(mandate=mandate)
    rule = HardRule(field="merchant.familiar", operator="=", value="true")
    familiar_facts = build_purchase_facts(event, merchant_familiar=True, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    unfamiliar_facts = build_purchase_facts(event, merchant_familiar=False, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    assert evaluate_rule(rule, familiar_facts, EMPTY_CTX).outcome == "pass"
    assert evaluate_rule(rule, unfamiliar_facts, EMPTY_CTX).outcome == "fail"


def test_item_category_in_flags_any_line_outside_the_set():
    mandate = make_mandate()
    items = [
        {"line_no": 1, "item_id": "IT1", "item_name": "A", "item_category": "groceries", "quantity": 1, "unit_price": 10.0, "currency": "CHF", "item_details": ""},
        {"line_no": 2, "item_id": "IT2", "item_name": "B", "item_category": "cosmetics", "quantity": 1, "unit_price": 5.0, "currency": "CHF", "item_details": ""},
    ]
    event = make_event(mandate=mandate, items=items, amount=15.0)
    facts = build_purchase_facts(event, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    rule = HardRule(field="item.category", operator="in", value=["groceries"])
    assert evaluate_rule(rule, facts, EMPTY_CTX).outcome == "fail"


def test_item_unrequested_present_needs_a_requested_set():
    mandate = make_mandate()
    event = make_event(mandate=mandate)
    facts = build_purchase_facts(event, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    rule = HardRule(field="item.unrequested_present", operator="=", value="false")
    assert evaluate_rule(rule, facts, EMPTY_CTX).outcome == "unknown"
    ctx = RuleContext(requested_item_categories=frozenset({"groceries"}), projected_period_spend_chf={})
    assert evaluate_rule(rule, facts, ctx).outcome == "pass"


def test_return_window_unknown_vs_final_sale_vs_ok():
    mandate = make_mandate()
    rule = HardRule(field="order.return_window_days", operator=">=", value=14)

    unknown_event = make_event(mandate=mandate, order_returnable="unknown")
    unknown_facts = build_purchase_facts(unknown_event, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    assert evaluate_rule(rule, unknown_facts, EMPTY_CTX).outcome == "unknown"

    final_sale_event = make_event(
        mandate=mandate,
        order_returnable="false",
        items=[{"line_no": 1, "item_id": "IT1", "item_name": "A", "item_category": "groceries", "quantity": 1, "unit_price": 10.0, "currency": "CHF", "item_details": "final sale"}],
    )
    final_sale_facts = build_purchase_facts(final_sale_event, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    assert evaluate_rule(rule, final_sale_facts, EMPTY_CTX).outcome == "fail"

    ok_event = make_event(
        mandate=mandate,
        order_returnable="true",
        items=[{"line_no": 1, "item_id": "IT1", "item_name": "A", "item_category": "groceries", "quantity": 1, "unit_price": 10.0, "currency": "CHF", "item_details": "returns accepted within 30 days"}],
    )
    ok_facts = build_purchase_facts(ok_event, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    assert evaluate_rule(rule, ok_facts, EMPTY_CTX).outcome == "pass"


def test_return_window_not_applicable_always_passes():
    mandate = make_mandate()
    rule = HardRule(field="order.return_window_days", operator=">=", value=14)
    event = make_event(mandate=mandate, order_returnable="not_applicable")
    facts = build_purchase_facts(event, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    assert evaluate_rule(rule, facts, EMPTY_CTX).outcome == "pass"


def test_item_name_contains_case_insensitive():
    mandate = make_mandate()
    rule = HardRule(field="item.name_contains", operator="=", value="road-running")
    matching = make_event(mandate=mandate, items=[{"line_no": 1, "item_id": "IT1", "item_name": "Road-Running Shoe", "item_category": "sporting_goods", "quantity": 1, "unit_price": 100.0, "currency": "CHF", "item_details": ""}])
    mismatching = make_event(mandate=mandate, items=[{"line_no": 1, "item_id": "IT1", "item_name": "Trail-running Shoe", "item_category": "sporting_goods", "quantity": 1, "unit_price": 100.0, "currency": "CHF", "item_details": ""}])
    mf = build_purchase_facts(matching, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    xf = build_purchase_facts(mismatching, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    assert evaluate_rule(rule, mf, EMPTY_CTX).outcome == "pass"
    assert evaluate_rule(rule, xf, EMPTY_CTX).outcome == "fail"


def test_item_size_unknown_when_not_stated():
    mandate = make_mandate()
    rule = HardRule(field="item.size", operator="=", value="43")
    event = make_event(mandate=mandate)  # default item has empty item_details
    facts = build_purchase_facts(event, merchant_familiar=None, session_integrity_risk=False, session_integrity_reasons=(), duplicate_of=None, duplicate_reason=None)
    assert evaluate_rule(rule, facts, EMPTY_CTX).outcome == "unknown"


def test_period_scope_uses_projected_spend_from_context():
    rule = HardRule(field="authorization.billing_amount_chf", operator="<=", value=300, currency="CHF", scope="period", period_days=7)
    facts = _facts(amount=50.0)
    ctx_ok = RuleContext(requested_item_categories=None, projected_period_spend_chf={7: Decimal("250.00")})
    ctx_over = RuleContext(requested_item_categories=None, projected_period_spend_chf={7: Decimal("350.00")})
    assert evaluate_rule(rule, facts, ctx_ok).outcome == "pass"
    assert evaluate_rule(rule, facts, ctx_over).outcome == "fail"


def test_unrecognized_field_fails_closed_to_unknown():
    rule = HardRule(field="not.a.real.field", operator="=", value="x")
    assert evaluate_rule(rule, _facts(), EMPTY_CTX).outcome == "unknown"
