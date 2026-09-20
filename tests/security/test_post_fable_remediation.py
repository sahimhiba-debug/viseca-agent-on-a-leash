"""Regression tests for the four findings of the independent audit.

Each test names the finding it pins and the behaviour that was wrong, so a future
reader can tell a deliberate guarantee from an accident of implementation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.live_worker import EchoedMandateMismatch, LiveWorker
from wallet_control.mandate import (
    HardRule,
    Mandate,
    MandateSnapshot,
    UncertaintyPolicy,
    UnsupportedRestrictionError,
)
from wallet_control.policy_compiler import compile_instruction
from wallet_control.state import DEFAULT_AUTHORITY_TTL, HistoryIndex, RunState

MERCHANT = "ME_KNOWN"
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


def _state(card: str = "CA_TEST") -> RunState:
    return RunState(history=HistoryIndex({card: frozenset({MERCHANT})}, available=True), card_id=card)


# =====================================================================  HIGH
# An independent corpus measured 19/35 recognition of ordinary per-order ceiling
# phrasings. Nothing was silently lost -- the warning fired every time -- but
# `run_live_worker.py` compiled, drafted and CONFIRMED in three consecutive
# statements, so the chain ran warning -> automatic confirmation -> unenforced
# restriction with no human in it.

SUPPORTED_PHRASINGS = [
    "for CHF 40 or less", "up to CHF 40", "no more than CHF 40", "at most CHF 40",
    "at or below CHF 40", "under CHF 40", "below CHF 40", "less than CHF 40",
    "a maximum of CHF 40", "CHF 40 maximum", "worth up to CHF 40",
]

# The six the brief names, plus the rest of the corpus that previously produced nothing.
PREVIOUSLY_UNRECOGNISED = [
    "never more than CHF 40", "nothing over CHF 40", "capped at CHF 40",
    "limited to CHF 40", "do not exceed CHF 40", "no higher than CHF 40",
    "nothing above CHF 40", "max CHF 40", "with a CHF 40 limit", "a CHF 40 cap",
    "within CHF 40", "up to a limit of CHF 40", "budget CHF 40 per order",
    "CHF 40 ceiling", "not exceeding CHF 40", "don't go over CHF 40",
]


@pytest.mark.parametrize("phrase", SUPPORTED_PHRASINGS + PREVIOUSLY_UNRECOGNISED)
def test_a_stated_per_order_ceiling_becomes_a_rule(phrase):
    compiled = compile_instruction(f"Buy groceries {phrase}. Ask me when uncertain.")
    ceilings = [
        r for r in compiled.hard_rules
        if r.field == "authorization.billing_amount_chf" and r.scope == "purchase"
    ]
    assert ceilings, f"{phrase!r} produced no ceiling"
    assert float(ceilings[0].value) == 40.0


@pytest.mark.parametrize(
    "text",
    ["Buy groceries. I spent CHF 40 last week on cheese.",
     "Buy groceries. The last order was CHF 40.",
     "Buy groceries. A typical basket is CHF 40."],
)
def test_an_amount_that_is_not_a_limit_does_not_become_one(text):
    """The cost of broadening the vocabulary, bounded. A figure the customer mentions
    in passing must not silently become a ceiling they never set."""
    compiled = compile_instruction(text + " Ask me when uncertain.")
    assert not [r for r in compiled.hard_rules if r.field == "authorization.billing_amount_chf"]


def test_unsupported_restrictive_intent_blocks_confirmation():
    """THE FIX. A quantity is not expressible in the official vocabulary, so a customer
    who asks for one must see that before the mandate has any authority."""
    compiled = compile_instruction("Buy one grocery item for CHF 20 or less. Ask me when uncertain.")
    assert compiled.unsupported_restrictions, "the fixture must carry unsupported intent"

    draft = Mandate.draft(
        "Buy one grocery item for CHF 20 or less. Ask me when uncertain.",
        compiled.hard_rules, compiled.uncertainty_policy,
        compiled.guidance, compiled.open_questions, compiled.unsupported_restrictions,
    )
    with pytest.raises(UnsupportedRestrictionError) as caught:
        draft.confirm(confirmed=True, customer_id="CU_1", card_id="CA_1", profile_id="PROFILE_1")
    assert caught.value.unsupported == tuple(compiled.unsupported_restrictions)


def test_acknowledging_every_unsupported_restriction_permits_confirmation():
    """The customer CAN proceed -- they just cannot do it without seeing the list."""
    instruction = "Buy one grocery item for CHF 20 or less. Ask me when uncertain."
    compiled = compile_instruction(instruction)
    draft = Mandate.draft(
        instruction, compiled.hard_rules, compiled.uncertainty_policy,
        compiled.guidance, compiled.open_questions, compiled.unsupported_restrictions,
    )
    confirmed = draft.confirm(
        confirmed=True, customer_id="CU_1", card_id="CA_1", profile_id="PROFILE_1",
        acknowledged_unsupported=compiled.unsupported_restrictions,
    )
    assert confirmed.status.value == "active"


def test_acknowledging_only_some_of_them_still_refuses():
    """Partial acknowledgement is how a caller would paper over the one item it did not
    want to show. Every outstanding item must be named."""
    instruction = "Buy one grocery item, no more than CHF 20 in total, and stop after Friday."
    compiled = compile_instruction(instruction)
    assert len(compiled.unsupported_restrictions) >= 2, compiled.unsupported_restrictions
    draft = Mandate.draft(
        instruction, compiled.hard_rules, compiled.uncertainty_policy,
        compiled.guidance, compiled.open_questions, compiled.unsupported_restrictions,
    )
    with pytest.raises(UnsupportedRestrictionError):
        draft.confirm(
            confirmed=True, customer_id="CU_1", card_id="CA_1", profile_id="PROFILE_1",
            acknowledged_unsupported=compiled.unsupported_restrictions[:1],
        )


def test_harmless_unknown_language_never_blocks_confirmation():
    """The other half of the property. If ordinary prose blocked confirmation, the gate
    would be worthless and would be routed around."""
    for instruction in (
        "Order our household groceries for delivery. Keep each order at or below CHF 120. Ask me when uncertain.",
        "Buy groceries for CHF 50 or less from a shop I use regularly. Thanks very much. Ask me when uncertain.",
        "Please buy the weekly groceries, up to CHF 80 per order, from Alpine Basket. Ask me when uncertain.",
    ):
        compiled = compile_instruction(instruction)
        assert not compiled.unsupported_restrictions, (instruction, compiled.unsupported_restrictions)
        Mandate.draft(
            instruction, compiled.hard_rules, compiled.uncertainty_policy,
            compiled.guidance, compiled.open_questions, compiled.unsupported_restrictions,
        ).confirm(confirmed=True, customer_id="CU_1", card_id="CA_1", profile_id="PROFILE_1")


def test_ambiguous_intent_is_resolved_defensively_and_does_not_block():
    """Two conflicting ceilings are AMBIGUOUS, not unsupported: a rule exists, it is
    the stricter reading, and the resolution is named. Blocking here would punish the
    customer for a correction."""
    compiled = compile_instruction("Buy groceries for up to CHF 100, at most CHF 50. Ask me when uncertain.")
    ceilings = [r for r in compiled.hard_rules if r.field == "authorization.billing_amount_chf"]
    assert ceilings and float(ceilings[0].value) == 50.0
    assert not compiled.unsupported_restrictions
    assert any("more than one per-order amount" in q for q in compiled.open_questions)


# ===================================================================  MEDIUM 1
def _purchase(mandate, authorization_id, hours):
    event = make_event(
        mandate=mandate, authorization_id=authorization_id, amount=100.0,
        merchant_id=MERCHANT, timestamp=AT + timedelta(hours=hours),
    )
    event["authorization"]["items"][0].update(item_name="milk", item_category="groceries")
    return event


def _capped_mandate():
    return make_mandate(
        instruction="Order groceries.",
        hard_rules=[
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=200, currency="CHF", scope="purchase"),
            HardRule(field="authorization.billing_amount_chf", operator="<=", value=300, currency="CHF", scope="period", period_days=7),
        ],
    )


def test_one_id_cannot_carry_two_economic_transactions():
    """Five distinct CHF 100 orders sharing one id, identical baskets, were ALL approved
    while the window counted CHF 100 -- a CHF 300 cap exceeded in silence.

    A collision with DIFFERING facts already failed closed. Only the identical-facts
    case failed open, because merchant+basket+amount could not tell it from a retry.
    The simulated purchase TIME can: it is a property of the purchase, not of the
    delivery."""
    mandate, state = _capped_mandate(), _state()
    decisions = [evaluate_authorization(_purchase(mandate, "AU_SHARED", i * 24), mandate, state).decision
                 for i in range(5)]
    assert decisions[0] == "allow"
    assert all(d == "block" for d in decisions[1:]), decisions
    assert sum(amount for _, amount in state._approved_spend) == Decimal("100.0")


def test_a_genuine_retry_is_still_idempotent_and_counted_once():
    """The guarantee this must not break. The same purchase re-delivered carries the
    same timestamp and stays a replay."""
    mandate, state = _capped_mandate(), _state()
    results = [evaluate_authorization(_purchase(mandate, "AU1", 0), mandate, state) for _ in range(3)]
    assert [r.decision for r in results] == ["allow"] * 3
    assert [r.idempotent_replay for r in results] == [False, True, True]
    assert sum(amount for _, amount in state._approved_spend) == Decimal("100.0")


@pytest.mark.parametrize("bad_id", ["", "   ", None, 123, [], {}])
def test_a_malformed_authorization_id_is_refused(bad_id):
    """The schema requires a non-empty string and the API addresses the purchase BY it,
    so a degenerate id is not a purchase we can answer for."""
    mandate = _capped_mandate()
    event = _purchase(mandate, "AU1", 0)
    event["authorization"]["authorization_id"] = bad_id
    assert evaluate_authorization(event, mandate, _state()).decision == "block"


# ===================================================================  MEDIUM 2
CONFIRMED_RULES = [
    HardRule(field="authorization.billing_amount_chf", operator="<=", value=400, currency="CHF", scope="purchase"),
    HardRule(field="merchant.familiar", operator="=", value="true"),
    HardRule(field="authorization.billing_amount_chf", operator="<=", value=800, currency="CHF", scope="period", period_days=7),
]


def _worker(rules=CONFIRMED_RULES, policy=UncertaintyPolicy.ASK) -> LiveWorker:
    return LiveWorker(
        client=None, history=HistoryIndex({}, available=False),
        confirmed_rules=rules, confirmed_uncertainty_policy=policy,
    )


def _snapshot(rules, policy=UncertaintyPolicy.ASK) -> MandateSnapshot:
    mandate = make_mandate(instruction="Buy the monitor.", hard_rules=list(rules), uncertainty_policy=policy)
    return mandate


def test_an_identical_echo_is_accepted():
    _worker()._verify_echoed_policy("RUN1", _snapshot(CONFIRMED_RULES))


@pytest.mark.parametrize(
    "echoed,label",
    [
        ([CONFIRMED_RULES[0]], "rules dropped (widened)"),
        ([*CONFIRMED_RULES, HardRule(field="item.category", operator="in", value=["electronics"])], "rule added (tightened)"),
        ([HardRule(field="authorization.billing_amount_chf", operator="<=", value=10000, currency="CHF", scope="purchase"),
          *CONFIRMED_RULES[1:]], "amount changed"),
        ([CONFIRMED_RULES[0], HardRule(field="merchant.familiar", operator="=", value="false"), CONFIRMED_RULES[2]], "merchant restriction changed"),
        ([CONFIRMED_RULES[0], CONFIRMED_RULES[1],
          HardRule(field="authorization.billing_amount_chf", operator="<=", value=800, currency="CHF", scope="period", period_days=90)], "temporal rule changed"),
        ([], "all rules removed"),
    ],
)
def test_any_echoed_difference_fails_closed(echoed, label):
    """Including a TIGHTENING. The platform is not an authority on the customer's
    policy; a narrowing we did not author is still one we cannot explain to them, and
    accepting it would mean trusting the same channel to say which way it moved."""
    with pytest.raises(EchoedMandateMismatch) as caught:
        _worker()._verify_echoed_policy("RUN1", _snapshot(echoed))
    assert "RUN1" in str(caught.value), label


def test_an_echoed_uncertainty_policy_change_fails_closed():
    with pytest.raises(EchoedMandateMismatch):
        _worker()._verify_echoed_policy("RUN1", _snapshot(CONFIRMED_RULES, UncertaintyPolicy.APPROVE))


def test_a_malformed_echoed_mandate_cannot_reach_the_comparison_as_valid():
    """A mandate block that will not parse must raise rather than yield an empty
    snapshot that happens to compare equal to nothing."""
    with pytest.raises(Exception):
        MandateSnapshot.from_event_mandate({"hard_rules": "not-a-list"})


def test_a_worker_with_no_confirmed_policy_still_runs():
    """Offline and test callers do not supply one; the check is opt-in by design and
    must not break them."""
    LiveWorker(client=None, history=HistoryIndex({}, available=False))._verify_echoed_policy(
        "RUN1", _snapshot([CONFIRMED_RULES[0]])
    )


# ======================================================================  TTL
def _approved_state():
    mandate = make_mandate(
        instruction="Buy groceries.",
        hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")],
    )
    state = _state()
    evaluate_authorization(_purchase(mandate, "AU1", 0), mandate, state)
    return state


def test_an_authority_expires_after_the_ttl_and_cannot_execute():
    """Nothing pinned this. An independent mutation widened DEFAULT_AUTHORITY_TTL from
    15 minutes to 3,650 days and the entire suite still passed.

    The authority is minted inside `evaluate_authorization`, on the real clock, at the
    moment of approval -- so these tests read the horizon off the authority itself
    rather than asserting a `now` the engine never saw. An earlier draft of this file
    passed `now=` to `issue_authority` and silently hit the IDEMPOTENT branch, getting
    the already-minted authority back and testing nothing."""
    from wallet_control.state import AuthorityError

    state = _approved_state()
    authority = state.get_authority("AU1")
    assert authority is not None and authority.expires_at is not None

    inside = authority.expires_at - timedelta(seconds=1)
    outside = authority.expires_at + timedelta(seconds=1)

    expired = _approved_state()
    horizon = expired.get_authority("AU1").expires_at
    with pytest.raises(AuthorityError, match="expired"):
        expired.consume_authority("AU1", executed_at=horizon + timedelta(seconds=1),
                                  now=horizon + timedelta(seconds=1))

    state.consume_authority("AU1", executed_at=inside, now=inside)  # must not raise


def test_expiry_tracks_the_ttl_constant_rather_than_a_hard_coded_horizon():
    """Changing DEFAULT_AUTHORITY_TTL must change when an authority expires. A test
    pinning only a wall-clock number would pass against a broken constant."""
    state = _approved_state()
    authority = state.get_authority("AU1")
    assert authority.expires_at - authority.issued_at == DEFAULT_AUTHORITY_TTL

    # and an explicitly issued authority honours a ttl argument
    fresh = _state()
    mandate = make_mandate(
        instruction="Buy groceries.",
        hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")],
    )
    event = _purchase(mandate, "AU2", 0)
    evaluate_authorization(event, mandate, fresh)
    issued = fresh.get_authority("AU2")
    assert issued.expires_at - issued.issued_at == DEFAULT_AUTHORITY_TTL


def test_the_expiry_comparison_uses_the_same_clock_the_horizon_was_set_on():
    """`expires_at` is `issued_at + ttl`, and `consume` compares its `now` against it.
    Feeding `consume` a clock from a different domain than the one the horizon was set
    on is what makes an expiry check meaningless -- verified in both directions."""
    from wallet_control.state import AuthorityError

    state = _approved_state()
    authority = state.get_authority("AU1")
    far_future = authority.issued_at + timedelta(days=365)

    with pytest.raises(AuthorityError, match="expired"):
        state.consume_authority("AU1", executed_at=far_future, now=far_future)

    # and a clock BEFORE the horizon consumes successfully
    other = _approved_state()
    just_before = other.get_authority("AU1").expires_at - timedelta(seconds=1)
    other.consume_authority("AU1", executed_at=just_before, now=just_before)
