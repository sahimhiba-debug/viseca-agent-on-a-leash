"""Properties derived from the official specification, not from our architecture.

`reference/viseca-2026/technical_details.md` is the contract. These tests read
requirements out of it and check the engine against them, rather than checking the
engine against what we intended to build. Where the two disagreed, the
specification won -- and it did, four times.

WHAT THIS FOUND

The rule format is far wider than anything our compiler emits. Eight operators,
three value shapes, and NO PAIRING RULE between them:

    | field      | Yes | A nonempty string naming the fact to check.
    | operator   | Yes | `<`, `<=`, `=`, `!=`, `>`, `>=`, `in`, or `not_in`.
    | value      | Yes | A number, a string, or a list containing only strings.

So `{"field": "merchant.familiar", "operator": "in", "value": ["true"]}` is a legal
stored rule that any team can PATCH onto a live mandate. Four of them crashed this
engine outright:

    merchant.familiar in ["true"]              ValueError from `_compare`
    billing_amount_chf in ["50"]               InvalidOperation from `decimal`
    item.category in 20                        TypeError, before any rule ran
    billing_amount_chf(period) in ["a"]        TypeError while writing the SENTENCE,
                                               after the decision was already correct

The last is the sharpest: the engine computed the right answer and threw it away
trying to say it in English. In the live worker an exception means no decision is
submitted and the 8-second deadline lapses into behaviour the specification does
not define -- the worst of the three ways to fail to represent an absence (filled
in, inferred, THROWN). `docs/ABSENCE.md`.

Now: `in`/`not_in` are implemented as membership on every field, which is what the
format plainly means, and anything still uninterpretable returns UNKNOWN and goes
to `uncertainty_policy`. Fuzzed over 1,344 field x operator x value x scope
combinations: no exception, and nothing a rule cannot be applied to is ever allowed.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import agent_view, evaluate_authorization
from wallet_control.mandate import HardRule, Mandate, MandateError, UncertaintyPolicy
from wallet_control.money import to_chf
from wallet_control.rules import RuleContext, evaluate_rule
from wallet_control.state import HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)

# technical_details.md, "Rule format"
OPERATORS = ("<", "<=", "=", "!=", ">", ">=", "in", "not_in")
FIELDS = ("authorization.billing_amount_chf", "merchant.category", "merchant.familiar",
          "item.category", "item.unrequested_present", "item.name_contains", "item.size",
          "order.return_window_days", "session.integrity_risk", "unknown.future_field")
VALUES = (20, 20.5, "true", ["a", "b"], ["5411"], "5411", 0, -1, "", [], "not a number")


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT})}, available=True),
                    card_id="CA_TEST")


def _decide(rules, *, policy=UncertaintyPolicy.DECLINE, amount=50.0, aid="AU1", **event_kw):
    mandate = make_mandate(instruction="x", uncertainty_policy=policy, hard_rules=rules)
    event = make_event(mandate=mandate, authorization_id=aid, amount=amount,
                       merchant_id=MERCHANT, timestamp=AT, **event_kw)
    event["authorization"]["items"][0].update(item_name="milk", item_category="groceries")
    return evaluate_authorization(event, mandate, _state())


# ============================================================ the rule format
def test_no_legal_rule_can_crash_the_engine():
    """"`operator` | Yes | `<`, `<=`, `=`, `!=`, `>`, `>=`, `in`, or `not_in`."
    "`value` | Yes | A number, a string, or a list containing only strings."

    No pairing rule between them, so every combination is storable. An engine that
    raises on one of them submits no decision at all, and the specification does not
    say what the platform then does."""
    crashes = []
    for field, operator, value in itertools.product(FIELDS, OPERATORS, VALUES):
        for scope, days in ((None, None), ("purchase", None), ("period", 7)):
            if scope and field != "authorization.billing_amount_chf":
                continue
            try:
                rule = HardRule(field=field, operator=operator, value=value,
                                currency="CHF" if scope else None,
                                scope=scope, period_days=days)
            except MandateError:
                continue                      # rejected at construction, which is fine
            try:
                decision = _decide([rule])
                agent_view(decision)
                str(decision.customer_message)
            except Exception as exc:          # noqa: BLE001 -- that is the point
                crashes.append((field, operator, repr(value), scope, type(exc).__name__))
    assert crashes == [], crashes[:10]


@pytest.mark.parametrize("field,value,expect", [
    ("merchant.familiar", ["true"], "pass"),
    ("merchant.familiar", ["false"], "fail"),
    ("authorization.billing_amount_chf", ["50"], "pass"),
    ("authorization.billing_amount_chf", ["99"], "fail"),
    ("item.category", ["groceries"], "pass"),
])
def test_in_means_membership_on_every_field(field, value, expect):
    """The format allows `in` anywhere and means the obvious thing by it. Reading
    `billing_amount_chf in ["50"]` as membership of 50.0 -- rather than as whatever
    `str()` produces -- is what makes it useful rather than merely non-crashing."""
    scope = "purchase" if field.startswith("authorization.") else None
    rule = HardRule(field=field, operator="in", value=value,
                    currency="CHF" if scope else None, scope=scope)
    decision = _decide([rule])
    assert decision.decision == ("allow" if expect == "pass" else "block")


def test_a_rule_this_engine_cannot_apply_is_unknown_and_never_pass():
    """An ordering operator against a list is legal to store and impossible to
    apply. That is the engine's third outcome, not its first: UNKNOWN, routed to the
    customer's `uncertainty_policy`, exactly as an unrecognised FIELD already was."""
    rule = HardRule(field="authorization.billing_amount_chf", operator="<=",
                    value=["50"], currency="CHF", scope="purchase")
    assert _decide([rule], policy=UncertaintyPolicy.DECLINE).decision == "block"
    assert _decide([rule], policy=UncertaintyPolicy.ASK).decision == "review"
    allowed = _decide([rule], policy=UncertaintyPolicy.APPROVE)
    assert allowed.decision == "allow"
    assert any(c.startswith("uncertain:") for c in allowed.reason_codes), (
        "the customer's own fallback may approve it, but the record must say the "
        "rule was never checked")


def test_a_real_bug_still_crashes():
    """The guard is deliberately narrow. A bug quietly downgraded to 'ask the
    customer' is a bug nobody finds."""
    from wallet_control.rules import _evaluate_rule

    class Exploding:
        @property
        def billing_amount_chf(self):
            raise RuntimeError("engine bug")
        items = ()
    rule = HardRule(field="authorization.billing_amount_chf", operator="<=", value=1,
                    currency="CHF", scope="purchase")
    ctx = RuleContext(requested_item_categories=None, projected_period_spend_chf={})
    with pytest.raises(RuntimeError):
        evaluate_rule(rule, Exploding(), ctx)
    with pytest.raises(RuntimeError):
        _evaluate_rule(rule, Exploding(), ctx)


def test_a_rule_field_must_be_a_nonempty_string():
    """"A nonempty string naming the fact to check." Rejected at construction rather
    than interpreted as "no constraint"."""
    with pytest.raises(MandateError):
        HardRule(field="", operator="=", value="x")


# ============================================================ null and absence
def test_null_is_not_dropped_zeroed_or_treated_as_permission():
    """technical_details.md states this project's own principle as a requirement:

        "A `null` field is present but has no value; it must not be silently
         dropped, changed to zero, or treated as permission."

    Checked where it costs money: a null `order_returnable` must not satisfy a
    return-window requirement."""
    rules = [HardRule(field="order.return_window_days", operator=">=", value=14)]
    decision = _decide(rules, policy=UncertaintyPolicy.DECLINE, order_returnable="unknown")
    assert decision.decision == "block", "unknown must not become permission"
    asked = _decide(rules, policy=UncertaintyPolicy.ASK, order_returnable="unknown", aid="AU2")
    assert asked.decision == "review"


def test_not_applicable_is_not_the_same_as_unknown():
    """"`unknown` means information was not supplied. `not_applicable` means the
    term does not apply to that kind of order." Neither may satisfy a requirement
    the customer stated, and `not_applicable` used to PASS unconditionally."""
    rules = [HardRule(field="order.return_window_days", operator=">=", value=14)]
    for value in ("unknown", "not_applicable"):
        decision = _decide(rules, policy=UncertaintyPolicy.DECLINE,
                           order_returnable=value, aid=f"AU_{value}")
        assert decision.decision == "block", value


# ============================================================ money
def test_delivery_is_not_added_twice():
    """"`amount` already includes delivery; `billing_amount_chf` is that total in
    CHF. Do not add delivery again.\""""
    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=", value=100,
                      currency="CHF", scope="purchase")]
    decision = _decide(rules, amount=100.0, delivery_fee=10.0, items_subtotal=90.0)
    assert decision.decision == "allow", "the 10.00 delivery was counted a second time"
    assert any("billing_amount_chf=100" in e for e in decision.evidence), decision.evidence


def test_conversion_uses_the_rows_currency_not_the_shops_country():
    """"Use the row's currency, not the shop's country, when converting prices.\""""
    assert to_chf(Decimal("100"), "EUR") != Decimal("100")
    assert to_chf(Decimal("100"), "CHF") == Decimal("100")


# ============================================================ mandate lifecycle
def test_uncertainty_policy_may_only_move_towards_decline():
    """"You may change `uncertainty_policy` from `approve` or `ask` to `decline`.
    The documented PATCH rules do not allow changing `approve` to `ask`.\""""
    def confirmed(policy):
        mandate = Mandate.draft("x", [HardRule(field="merchant.familiar", operator="=",
                                               value="true")], policy)
        mandate.confirm(confirmed=True, customer_id="CU", card_id="CA", profile_id="P")
        return mandate

    confirmed(UncertaintyPolicy.APPROVE).set_uncertainty_policy(UncertaintyPolicy.DECLINE)
    confirmed(UncertaintyPolicy.ASK).set_uncertainty_policy(UncertaintyPolicy.DECLINE)
    for start, target in ((UncertaintyPolicy.APPROVE, UncertaintyPolicy.ASK),
                          (UncertaintyPolicy.ASK, UncertaintyPolicy.APPROVE),
                          (UncertaintyPolicy.DECLINE, UncertaintyPolicy.ASK),
                          (UncertaintyPolicy.DECLINE, UncertaintyPolicy.APPROVE)):
        with pytest.raises(MandateError):
            confirmed(start).set_uncertainty_policy(target)


def test_adding_a_rule_never_weakens_an_existing_restriction():
    """"Adding a rule must not weaken a customer's existing restriction." and
    "If you send `hard_rules`, keep every existing rule unchanged.\""""
    tight = HardRule(field="authorization.billing_amount_chf", operator="<=", value=50,
                     currency="CHF", scope="purchase")
    loose = HardRule(field="authorization.billing_amount_chf", operator="<=", value=500,
                     currency="CHF", scope="purchase")
    assert _decide([tight], amount=100.0).decision == "block"
    assert _decide([tight, loose], amount=100.0, aid="AU2").decision == "block", (
        "appending a looser rule raised the effective ceiling")


def test_a_step_up_is_not_an_approval_for_spending_limits():
    """"Count final approvals when enforcing spending limits. A purchase waiting for
    a human answer is not yet approved.\""""
    rules = [HardRule(field="order.return_window_days", operator=">=", value=14),
             HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000,
                      currency="CHF", scope="period", period_days=7)]
    mandate = make_mandate(instruction="x", uncertainty_policy=UncertaintyPolicy.ASK,
                           hard_rules=rules)
    state = _state()
    event = make_event(mandate=mandate, authorization_id="AU_PENDING", amount=400.0,
                       merchant_id=MERCHANT, timestamp=AT, order_returnable="unknown")
    event["authorization"]["items"][0].update(item_name="milk", item_category="groceries")
    assert evaluate_authorization(event, mandate, state).decision == "review"
    assert state.total_approved_spend_chf() == Decimal("0")


def test_repeated_delivery_of_one_authorization_counts_once():
    """"Recognize repeated delivery by its live purchase ID. Record it once, so a
    retry does not add the amount twice.\""""
    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000,
                      currency="CHF", scope="period", period_days=7)]
    mandate = make_mandate(instruction="x", hard_rules=rules)
    state = _state()
    for _ in range(3):
        event = make_event(mandate=mandate, authorization_id="AU_SAME", amount=400.0,
                           merchant_id=MERCHANT, timestamp=AT)
        event["authorization"]["items"][0].update(item_name="milk", item_category="groceries")
        evaluate_authorization(event, mandate, state)
    assert state.total_approved_spend_chf() == Decimal("400")


def test_simulated_time_drives_windows_and_the_real_clock_drives_deadlines():
    """"Use simulated purchase time for spending windows, and the real clock for
    response deadlines." The window must move with the purchase timestamp, not with
    when the event happened to be received."""
    rules = [HardRule(field="authorization.billing_amount_chf", operator="<=", value=500,
                      currency="CHF", scope="period", period_days=7)]
    mandate = make_mandate(instruction="x", hard_rules=rules)
    state = _state()
    for index, offset in enumerate((0, 1, 2)):
        event = make_event(mandate=mandate, authorization_id=f"AU_T{index}", amount=200.0,
                           merchant_id=MERCHANT, timestamp=AT + timedelta(days=offset))
        event["authorization"]["items"][0].update(item_name=f"milk {index}",
                                                  item_category="groceries")
        decision = evaluate_authorization(event, mandate, state)
    assert decision.decision == "block", "three x 200 inside seven days exceeds 500"

    state = _state()
    for index, offset in enumerate((0, 30, 60)):
        event = make_event(mandate=mandate, authorization_id=f"AU_W{index}", amount=200.0,
                           merchant_id=MERCHANT, timestamp=AT + timedelta(days=offset))
        event["authorization"]["items"][0].update(item_name=f"milk {index}",
                                                  item_category="groceries")
        decision = evaluate_authorization(event, mandate, state)
    assert decision.decision == "allow", "a month apart is not inside a seven-day window"


def test_a_basket_must_have_at_least_one_line():
    """"`items` must contain at least one cart line." An empty basket satisfied four
    item restrictions at once by vacuous truth before this was enforced."""
    mandate = make_mandate(instruction="x", hard_rules=[
        HardRule(field="item.category", operator="in", value=["groceries"])])
    event = make_event(mandate=mandate, authorization_id="AU_EMPTY", amount=50.0,
                       merchant_id=MERCHANT, timestamp=AT)
    event["authorization"]["items"] = []
    assert evaluate_authorization(event, mandate, _state()).decision != "allow"


def test_a_shops_category_does_not_establish_an_items_category():
    """"A shop's category also does not establish every basket item's category.\""""
    mandate = make_mandate(instruction="x", hard_rules=[
        HardRule(field="item.category", operator="in", value=["groceries"])])
    event = make_event(mandate=mandate, authorization_id="AU_CAT", amount=50.0,
                       merchant_id=MERCHANT, merchant_category="groceries", timestamp=AT)
    event["authorization"]["items"][0].update(item_name="ring", item_category="jewellery")
    assert evaluate_authorization(event, mandate, _state()).decision == "block"
