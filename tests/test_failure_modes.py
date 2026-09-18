"""Failure engineering: what the product does when the world misbehaves.

The governing rule is one sentence: **security-critical ambiguity fails closed.**
A dependency that is down, slow, lying or malformed may cost availability. It may
never cost authority. In particular there is no path anywhere in this system by
which "something external failed" becomes "approve the purchase".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.decision_engine import evaluate_authorization
from wallet_control.mandate import HardRule, UncertaintyPolicy
from wallet_control.payment import MockPSP, PaymentError
from wallet_control.state import HistoryIndex, RunState
from wallet_control.viseca_client import VisecaApiError, VisecaClient

M, CARD = "ME_TEST_0001", "CA_TEST"


def _state(history=None):
    return RunState(history=history or HistoryIndex({CARD: frozenset({M})}, available=True), card_id=CARD)


def _mandate(rules=None, uncertainty=UncertaintyPolicy.ASK):
    return make_mandate(
        instruction="Buy one monitor.",
        hard_rules=rules or [HardRule(field="authorization.billing_amount_chf", operator="<=",
                                      value=500, currency="CHF", scope="purchase")],
        uncertainty_policy=uncertainty)


# --- the external API is down, slow, or refusing us -------------------------------


@pytest.mark.parametrize("failure", [
    httpx.ConnectError("network unreachable"),
    httpx.ReadTimeout("timed out"),
    httpx.RemoteProtocolError("peer closed the connection"),
])
def test_transport_failures_normalise_to_one_catchable_error(failure, monkeypatch):
    """A transport failure and an HTTP error status must raise the SAME type, so a
    caller cannot accidentally handle one and let the other escape as success."""
    client = VisecaClient("https://example.invalid", "key")
    monkeypatch.setattr(client._client, "request", lambda *a, **k: (_ for _ in ()).throw(failure))
    with pytest.raises(VisecaApiError) as exc:
        client.bootstrap()
    assert exc.value.status_code == 0


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_error_statuses_raise_rather_than_return_empty(status, monkeypatch):
    """A 401 must not look like "no work to do". The worker's single
    `except VisecaApiError` has to see every one of these."""
    client = VisecaClient("https://example.invalid", "key")
    monkeypatch.setattr(client._client, "request",
                        lambda *a, **k: httpx.Response(status, json={"detail": "nope"},
                                                       request=httpx.Request("GET", "https://example.invalid")))
    with pytest.raises(VisecaApiError) as exc:
        client.bootstrap()
    assert exc.value.status_code == status


def test_a_malformed_json_body_does_not_crash_the_error_path(monkeypatch):
    """The worst moment for a JSON decode error is while reporting another error."""
    client = VisecaClient("https://example.invalid", "key")
    monkeypatch.setattr(client._client, "request",
                        lambda *a, **k: httpx.Response(500, content=b"<html>gateway</html>",
                                                       request=httpx.Request("GET", "https://example.invalid")))
    with pytest.raises(VisecaApiError):
        client.bootstrap()


def test_the_client_never_prints_its_api_key():
    """An exception or a log line that leaks the bearer key would be a real incident."""
    client = VisecaClient("https://example.invalid", "super-secret-key")
    assert "super-secret-key" not in repr(client)
    assert "super-secret-key" not in str(client)


# --- missing / stale / duplicated inputs ------------------------------------------

@pytest.mark.parametrize("missing", [
    "billing_amount_chf", "merchant", "items", "timestamp", "card_id",
    "authority_status", "card_status_at_attempt",
])
def test_a_missing_required_field_never_becomes_an_approval(missing):
    """A malformed event may be refused, or it may raise. It may not be approved."""
    md, s = _mandate(), _state()
    event = make_event(mandate=md, authorization_id="AU1", amount=100.0, merchant_id=M)
    event["authorization"].pop(missing, None)
    try:
        result = evaluate_authorization(event, md, s)
    except Exception:
        return                                   # refusing to parse it is fail-closed
    assert result.decision != "allow", f"a missing {missing} was approved"


def test_history_being_unavailable_does_not_become_a_confirmed_fact():
    """No history is UNKNOWN, not "unfamiliar" and not "familiar". Conflating a data
    outage with a confirmed answer is how an outage becomes a decision."""
    md = _mandate(rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    s = _state(history=HistoryIndex.empty())
    result = evaluate_authorization(
        make_event(mandate=md, authorization_id="AU1", amount=100.0, merchant_id=M), md, s)
    assert result.decision == "review"
    assert any("uncertain" in c for c in result.reason_codes)


def test_under_a_decline_policy_an_outage_declines_rather_than_approves():
    md = _mandate(rules=[HardRule(field="merchant.familiar", operator="=", value="true")],
                  uncertainty=UncertaintyPolicy.DECLINE)
    s = _state(history=HistoryIndex.empty())
    result = evaluate_authorization(
        make_event(mandate=md, authorization_id="AU1", amount=100.0, merchant_id=M), md, s)
    assert result.decision == "block"


def test_a_duplicate_delivery_is_answered_once_and_counted_once():
    md, s = _mandate(), _state()
    event = make_event(mandate=md, authorization_id="AU1", amount=100.0, merchant_id=M)
    first = evaluate_authorization(event, md, s)
    again = evaluate_authorization(event, md, s)
    assert again.decision == first.decision and again.idempotent_replay
    assert s.total_approved_spend_chf() == Decimal("100")


# --- process crash and corrupted checkpoints --------------------------------------


def test_a_crash_between_decision_and_execution_preserves_the_lifecycle():
    md, s = _mandate(), _state()
    assert evaluate_authorization(
        make_event(mandate=md, authorization_id="AU1", amount=100.0, merchant_id=M), md, s).decision == "allow"
    restored = RunState.from_snapshot(json.loads(json.dumps(s.to_snapshot())), s.history)
    psp = MockPSP(restored)
    psp.charge(charge_id="C1", authorization_id="AU1", amount_chf=Decimal("100"), merchant_id=M)
    with pytest.raises(PaymentError):
        psp.charge(charge_id="C2", authorization_id="AU1", amount_chf=Decimal("100"), merchant_id=M)


@pytest.mark.parametrize("corrupt", [
    lambda snap: snap.pop("decisions", None),
    lambda snap: snap.update(decisions=[]),
    lambda snap: [d.pop("execution_expires_at", None) for d in snap["decisions"]],
    lambda snap: [d.update(decision="allow", billing_amount_chf="not-a-number") for d in snap["decisions"]],
])
def test_a_corrupted_checkpoint_never_yields_an_unconstrained_charge(corrupt):
    """A checkpoint we cannot trust must not become a charge. Either the restore
    fails, or it restores into a state that refuses to pay."""
    md, s = _mandate(), _state()
    evaluate_authorization(make_event(mandate=md, authorization_id="AU1", amount=100.0, merchant_id=M), md, s)
    snapshot = json.loads(json.dumps(s.to_snapshot()))
    corrupt(snapshot)
    try:
        restored = RunState.from_snapshot(snapshot, s.history)
    except Exception:
        return                                   # refusing to restore is fail-closed
    with pytest.raises(PaymentError):
        MockPSP(restored).charge(charge_id="C1", authorization_id="AU1",
                                 amount_chf=Decimal("100"), merchant_id=M)


# --- the human is slow ------------------------------------------------------------


def test_a_delayed_human_answer_does_not_shift_the_spending_window():
    """The customer may answer an hour later in real time. The purchase still belongs
    to the window of its SIMULATED time, or a slow human would silently move spend
    between periods."""
    md = _mandate(rules=[
        HardRule(field="authorization.billing_amount_chf", operator="<=", value=500,
                 currency="CHF", scope="purchase"),
        HardRule(field="order.return_window_days", operator=">=", value=14)])
    s = _state()
    purchase_time = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)
    evaluate_authorization(
        make_event(mandate=md, authorization_id="AU1", amount=100.0, merchant_id=M,
                   timestamp=purchase_time), md, s)

    from wallet_control.decision_engine import resolve_authorization
    resolve_authorization("AU1", "allow", s,
                          resolved_at=datetime.now(timezone.utc) + timedelta(hours=5), mandate=md)
    stored = s.get_stored_decision("AU1")
    assert stored.timestamp == purchase_time, "a late answer moved the purchase's window"
    assert stored.resolved_at is not None
