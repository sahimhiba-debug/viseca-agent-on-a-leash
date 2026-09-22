"""V12 (CRITICAL): a revoked mandate still authorized purchases.

`mandate.status` is a required field of the official event schema with enum
`["active", "superseded", "revoked", "expired"]`. It is the platform stating
whether the mandate itself is still in force -- the direct result of the
customer's `DELETE /v1/mandates`.

The decision engine never read it. A `Mandate` that had been revoked still
produced ALLOW, minted a payment authority, and charged. Both paths were
affected: a locally revoked `Mandate.snapshot()`, and a live snapshot rebuilt by
`MandateSnapshot.from_event_mandate` from an event whose mandate block said
`revoked`.

This is the twin of V1. The deep-security pass enforced `authority_status` (is
this authorization still authorized?) and missed `mandate.status` (is the mandate
behind it still in force?). It also means the previous pass's claim that
revocation was enforced held only for revocations issued through our own demo
endpoint, never for one the platform told us about.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule, Mandate, MandateSnapshot, MandateStatus, UncertaintyPolicy
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState

MERCHANT_ID = "ME_TEST_0001"


def _state():
    return RunState(history=HistoryIndex({"CA_TEST": frozenset({MERCHANT_ID})}, available=True), card_id="CA_TEST")


def _snapshot_with_status(status: MandateStatus) -> MandateSnapshot:
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    return MandateSnapshot(
        mandate_id=mandate.mandate_id,
        status=status,
        customer_id=mandate.customer_id,
        card_id=mandate.card_id,
        profile_id=mandate.profile_id,
        instruction=mandate.instruction,
        hard_rules=mandate.hard_rules,
        uncertainty_policy=mandate.uncertainty_policy,
    )


@pytest.mark.parametrize("status", [MandateStatus.REVOKED, MandateStatus.EXPIRED, MandateStatus.SUPERSEDED, MandateStatus.DRAFT])
def test_a_mandate_that_is_not_active_authorizes_nothing(status):
    mandate = _snapshot_with_status(status)
    state = _state()
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)

    assert result.decision == "block"
    assert any("mandate_status" in code for code in result.reason_codes)
    assert result.payment_authority is None


def test_an_active_mandate_is_unaffected():
    """What keeps the official replay at 18/3/24: every scenario mandate is
    compiled and confirmed, so all 45 events run under an ACTIVE mandate."""
    mandate = _snapshot_with_status(MandateStatus.ACTIVE)
    state = _state()
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)
    assert result.decision == "allow"


def test_a_revoked_mandate_cannot_reach_payment():
    mandate = _snapshot_with_status(MandateStatus.REVOKED)
    state = _state()
    evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, state)
    psp = MockPSP(state)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="CH1", authorization_id="AU1", amount_chf=Decimal("400"), merchant_id=MERCHANT_ID)
    assert not psp.is_charged("AU1")


def test_a_locally_revoked_mandate_stops_authorizing():
    """The `Mandate.revoke()` path, not just the event-carried status."""
    mandate = Mandate.draft(
        "test",
        [HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")],
        UncertaintyPolicy.ASK,
    )
    mandate.confirm(confirmed=True, customer_id="CU_TEST", card_id="CA_TEST", profile_id="PROFILE_TEST")
    state = _state()
    snapshot = mandate.snapshot()
    assert evaluate_authorization(make_event(mandate=snapshot, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), snapshot, state).decision == "allow"

    mandate.revoke()
    revoked = mandate.snapshot()
    result = evaluate_authorization(make_event(mandate=revoked, authorization_id="AU2", amount=400.0, merchant_id=MERCHANT_ID), revoked, state)
    assert result.decision == "block"


def test_the_live_path_rebuilt_from_a_revoked_event_mandate_blocks():
    """`live_worker` builds its snapshot from the event's own mandate block."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=500, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID)
    event["mandate"]["status"] = "revoked"
    rebuilt = MandateSnapshot.from_event_mandate(event["mandate"])
    assert rebuilt.status is MandateStatus.REVOKED

    result = evaluate_authorization(event, rebuilt, _state())
    assert result.decision == "block"


def test_the_mandate_status_check_is_wallet_safety_not_customer_policy():
    mandate = _snapshot_with_status(MandateStatus.REVOKED)
    result = evaluate_authorization(make_event(mandate=mandate, authorization_id="AU1", amount=400.0, merchant_id=MERCHANT_ID), mandate, _state())
    status_evals = [e for e in result.rule_evaluations if "mandate_status" in e.rule.field]
    assert status_evals and all(e.source == "safety" for e in status_evals)


# --- external-auditor pass: three status fields, one was inert --------------------


def _live_mandate_event(status, aid, hours):
    from datetime import datetime, timedelta, timezone

    from tests.helpers import make_event, make_mandate
    from wallet_control.mandate import HardRule

    mandate = make_mandate(instruction="Buy groceries.", hard_rules=[HardRule(
        field="authorization.billing_amount_chf", operator="<=", value=500,
        currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id=aid, amount=100.0,
                       merchant_id="ME_KNOWN",
                       timestamp=datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc) + timedelta(hours=hours))
    event["authorization"]["items"][0]["item_name"] = f"g{aid}"
    event["mandate"]["status"] = status
    return mandate, event


def test_a_mid_run_mandate_revocation_reported_by_the_platform_is_honoured():
    """The run's snapshot is frozen -- correctly, so a mid-run tightening cannot apply
    retroactively to the RULES. But `live_worker` builds that snapshot from a run's
    FIRST event and reuses it, so `mandate.status` could never change, while
    `authority_status` and `card_status_at_attempt` were read live from every event.

    Three platform status fields, two live and one frozen. The check existed and was
    wired to a source that could not move."""
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.state import HistoryIndex, RunState

    mandate, first = _live_mandate_event("active", "E1", 0)
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_KNOWN"})}, available=True),
                     card_id="CA_TEST")
    assert evaluate_authorization(first, mandate, state).decision == "allow"

    _, later = _live_mandate_event("revoked", "E2", 2)
    later["mandate"]["mandate_id"] = mandate.mandate_id
    result = evaluate_authorization(later, mandate, state)
    assert result.decision == "block", "a platform-reported revocation was ignored"
    assert any("mandate_status" in c for c in result.reason_codes), result.reason_codes


def test_an_unrecognised_reported_mandate_status_escalates_rather_than_passing():
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.state import HistoryIndex, RunState

    mandate, event = _live_mandate_event("quantum-superposed", "E3", 0)
    event["mandate"]["mandate_id"] = mandate.mandate_id
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_KNOWN"})}, available=True),
                     card_id="CA_TEST")
    assert evaluate_authorization(event, mandate, state).decision != "allow"


def test_an_active_report_does_not_override_a_dead_snapshot():
    """The live report may only ever narrow. A platform saying "active" must not
    resurrect a run whose own snapshot is revoked."""
    from wallet_control.decision_engine import evaluate_authorization
    from wallet_control.mandate import MandateStatus
    from wallet_control.state import HistoryIndex, RunState

    mandate, event = _live_mandate_event("active", "E4", 0)
    event["mandate"]["mandate_id"] = mandate.mandate_id
    dead = replace(mandate, status=MandateStatus.REVOKED)
    state = RunState(history=HistoryIndex({"CA_TEST": frozenset({"ME_KNOWN"})}, available=True),
                     card_id="CA_TEST")
    assert evaluate_authorization(event, dead, state).decision == "block"
