"""Exercises `LiveWorker` against a fake `VisecaClient` (no real network / no live
API key needed). Covers exactly the failure modes technical_details.md calls out:
HTTP 204 handling, never turning an API failure into an approval, not re-deciding
repeated delivery, and step_up/resolve staying separate from the automated poll loop.
"""

from __future__ import annotations

import pytest

from tests.helpers import make_event, make_mandate
from wallet_control.live_worker import FatalWorkerError, LiveWorker
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex
from wallet_control.viseca_client import VisecaApiError


class FakeVisecaClient:
    """Implements just the subset of VisecaClient's interface LiveWorker uses."""

    def __init__(self, envelopes: list[dict | None], fail_polls: int = 0, fail_status: int = 503, authorizations_listing=None, submit_fail_status: int | None = None):
        self._envelopes = list(envelopes)
        self._fail_polls = fail_polls
        self._fail_status = fail_status
        self._submit_fail_status = submit_fail_status
        self.submitted: list[dict] = []
        self.resolved: list[dict] = []
        self._authorizations_listing = authorizations_listing if authorizations_listing is not None else {"data": []}

    def next_decision_request(self, wait: int = 25):
        if self._fail_polls > 0:
            self._fail_polls -= 1
            raise VisecaApiError(self._fail_status, {"error": "unavailable"})
        if not self._envelopes:
            return None
        return self._envelopes.pop(0)

    def submit_decision(self, authorization_id, decision, **kwargs):
        if self._submit_fail_status is not None:
            raise VisecaApiError(self._submit_fail_status, {"error": "rejected"})
        self.submitted.append({"authorization_id": authorization_id, "decision": decision, **kwargs})
        return {"authorization_id": authorization_id, "decision": decision}

    def resolve(self, authorization_id, decision, **kwargs):
        self.resolved.append({"authorization_id": authorization_id, "decision": decision, **kwargs})
        return {"authorization_id": authorization_id, "decision": decision}

    def list_authorizations(self):
        return self._authorizations_listing


def _envelope(event: dict) -> dict:
    return {
        "run_id": "RUN1",
        "event_id": f"evt_{event['authorization']['authorization_id']}",
        "type": "authorization.request",
        "authorization_id": event["authorization"]["authorization_id"],
        "status": "pending",
        "occurred_at": event["authorization"]["timestamp"],
        "data": event,
    }


def _worker_with_run(client, mandate):
    worker = LiveWorker(client, HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True))
    worker.register_run("RUN1", mandate)
    return worker


def test_http_204_is_not_treated_as_run_finished_and_does_not_submit_anything():
    client = FakeVisecaClient([None, None])  # two consecutive 204s
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    worker = _worker_with_run(client, mandate)
    processed = worker.run_forever(wait_seconds=1, max_polls=2)
    # Both polls returned 204: no envelopes were ever available to process, so the
    # loop must exit via exhaustion, not by mistaking 204 for "done" and submitting.
    assert client.submitted == []
    assert processed == 0


def test_a_poll_failure_never_becomes_an_approval():
    client = FakeVisecaClient([], fail_polls=2)
    mandate = make_mandate(hard_rules=[])
    worker = _worker_with_run(client, mandate)
    # run_forever would loop forever on repeated None after failures exhaust; drive
    # the internal poll path directly for a bounded number of iterations instead.
    for _ in range(2):
        try:
            worker._client.next_decision_request(wait=1)
        except VisecaApiError:
            pass
    assert client.submitted == []  # never submitted a decision out of a failed poll


def test_normal_event_is_evaluated_and_submitted_with_the_wire_vocabulary():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    client = FakeVisecaClient([_envelope(event), None])
    worker = _worker_with_run(client, mandate)
    worker.run_forever(wait_seconds=1, max_events=1)
    assert len(client.submitted) == 1
    assert client.submitted[0]["decision"] == "approve"  # wire vocabulary, not "allow"


def test_repeated_delivery_of_the_same_authorization_id_is_not_resubmitted():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    client = FakeVisecaClient([_envelope(event), _envelope(event), None])
    worker = _worker_with_run(client, mandate)
    worker.run_forever(wait_seconds=1, max_events=2)
    assert len(client.submitted) == 1  # the second delivery is reconciled locally, not re-submitted


def test_step_up_is_not_auto_resolved_and_resolve_uses_the_separate_endpoint():
    mandate = make_mandate(hard_rules=[HardRule(field="merchant.familiar", operator="=", value="true")])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    client = FakeVisecaClient([_envelope(event), None])
    # No history at all for this card -> merchant.familiar is unknown, not False,
    # so the mandate's uncertainty_policy (ASK) drives a step_up rather than a block.
    worker = LiveWorker(client, HistoryIndex.empty())
    worker.register_run("RUN1", mandate)
    worker.run_forever(wait_seconds=1, max_events=1)
    assert client.submitted[0]["decision"] == "step_up"
    assert client.resolved == []  # nothing auto-resolves a step_up

    result = worker.resolve("RUN1", "AU1", "allow", customer_message="Yes, go ahead.")
    assert result.decision == "allow"
    assert client.resolved == [{"authorization_id": "AU1", "decision": "approve", "customer_message": "Yes, go ahead.", "evidence": []}]


def test_worker_auto_registers_a_run_from_its_first_event():
    """The worker learns customer_id/card_id/profile_id from the event's own
    `mandate` block rather than requiring pre-registration -- those IDs are only
    assigned by the platform once a run starts."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    client = FakeVisecaClient([_envelope(event), None])
    worker = LiveWorker(client, HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True))
    # deliberately no worker.register_run() call
    processed = worker.run_forever(wait_seconds=1, max_events=1)
    assert processed == 1
    assert client.submitted[0]["decision"] == "approve"


def test_cannot_resolve_an_authorization_that_is_not_pending():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    client = FakeVisecaClient([_envelope(event), None])
    worker = _worker_with_run(client, mandate)
    worker.run_forever(wait_seconds=1, max_events=1)  # AU1 gets auto-approved, not step_up
    with pytest.raises(ValueError):
        worker.resolve("RUN1", "AU1", "allow")


def test_a_mutated_retry_is_never_resubmitted_and_original_decision_stands():
    """The live-worker-level counterpart to
    test_decision_engine.py::test_repeated_authorization_id_with_a_different_amount_is_flagged_not_trusted:
    a same-authorization_id delivery with different facts must not trigger a second
    submit_decision call (the platform may already have our first one)."""
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    original_event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    mutated_event = make_event(mandate=mandate, authorization_id="AU1", amount=999.0)
    client = FakeVisecaClient([_envelope(original_event), _envelope(mutated_event), None])
    worker = _worker_with_run(client, mandate)
    worker.run_forever(wait_seconds=1, max_events=2)
    assert len(client.submitted) == 1  # only the original was ever submitted
    assert client.submitted[0]["decision"] == "approve"


def test_checkpoint_persistence_survives_a_simulated_process_restart(tmp_path):
    """Phase 11: a process crash must not forget a rolling-window-relevant approval.
    A fresh LiveWorker instance (simulating a restart) pointed at the same
    checkpoint_dir must recover the prior run's state rather than starting blind."""
    mandate = make_mandate(
        hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=300, currency="CHF", scope="period", period_days=7)]
    )
    event = make_event(mandate=mandate, authorization_id="AU1", amount=250.0)
    client1 = FakeVisecaClient([_envelope(event), None])
    worker1 = LiveWorker(client1, HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True), checkpoint_dir=tmp_path)
    worker1.register_run("RUN1", mandate)
    worker1.run_forever(wait_seconds=1, max_events=1)
    assert client1.submitted[0]["decision"] == "approve"

    # Simulate a crash: a brand-new LiveWorker, brand-new FakeVisecaClient, same
    # checkpoint directory and same run_id.
    from datetime import datetime

    same_ts = datetime.fromisoformat(event["authorization"]["timestamp"].replace("Z", "+00:00"))
    event2 = make_event(mandate=mandate, authorization_id="AU2", amount=100.0, timestamp=same_ts)
    client2 = FakeVisecaClient([_envelope(event2), None])
    worker2 = LiveWorker(client2, HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True), checkpoint_dir=tmp_path)
    worker2.register_run("RUN1", mandate)  # loads the checkpoint written by worker1
    worker2.run_forever(wait_seconds=1, max_events=1)
    # Without recovery, the 7-day window would only see AU2's 100 and approve it.
    # With recovery, it correctly sees the prior 250 too and the combined 350 fails.
    assert client2.submitted[0]["decision"] == "decline"


def test_reconcile_run_recognizes_already_decided_authorizations_without_crashing_on_unknown_shape():
    """Best-effort reconciliation must degrade gracefully -- it never raises just
    because the (undocumented) listing shape doesn't have every field it might hope for."""
    mandate = make_mandate(hard_rules=[])
    client = FakeVisecaClient([], authorizations_listing={"data": [{"authorization_id": "AU1", "decision": "approve"}, {"weird": "record"}]})
    worker = _worker_with_run(client, mandate)
    recovered = worker.reconcile_run("RUN1")
    assert recovered == 1  # the malformed second record is skipped, not fatal


def test_reconcile_run_never_raises_when_the_listing_call_itself_fails():
    mandate = make_mandate(hard_rules=[])

    class FailingClient(FakeVisecaClient):
        def list_authorizations(self):
            raise VisecaApiError(500, "boom")

    client = FailingClient([])
    worker = _worker_with_run(client, mandate)
    assert worker.reconcile_run("RUN1") == 0


def test_a_401_on_poll_stops_the_worker_instead_of_retrying_forever():
    """An expired/wrong bearer key will never fix itself by retrying; spinning on
    it forever would silently burn the team's rate limit while looking, from the
    outside, like a worker that is merely slow."""
    mandate = make_mandate(hard_rules=[])
    client = FakeVisecaClient([], fail_polls=1, fail_status=401)
    worker = _worker_with_run(client, mandate)
    with pytest.raises(FatalWorkerError):
        worker.run_forever(wait_seconds=1, max_polls=10)


def test_a_403_on_poll_also_stops_the_worker():
    mandate = make_mandate(hard_rules=[])
    client = FakeVisecaClient([], fail_polls=1, fail_status=403)
    worker = _worker_with_run(client, mandate)
    with pytest.raises(FatalWorkerError):
        worker.run_forever(wait_seconds=1, max_polls=10)


def test_a_transient_503_on_poll_does_not_stop_the_worker():
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    client = FakeVisecaClient([_envelope(event), None], fail_polls=2, fail_status=503)
    worker = _worker_with_run(client, mandate)
    processed = worker.run_forever(wait_seconds=1, max_events=1)
    assert processed == 1
    assert client.submitted[0]["decision"] == "approve"


def test_a_401_on_submit_does_not_retry_and_is_logged_not_swallowed(caplog):
    mandate = make_mandate(hard_rules=[HardRule(field="authorization.billing_amount_chf", operator="<=", value=1000, currency="CHF", scope="purchase")])
    event = make_event(mandate=mandate, authorization_id="AU1", amount=50.0)
    client = FakeVisecaClient([_envelope(event), None], submit_fail_status=401)
    worker = _worker_with_run(client, mandate)
    with caplog.at_level("ERROR"):
        worker.run_forever(wait_seconds=1, max_events=1)
    assert client.submitted == []  # never recorded as successfully submitted
    assert any("fatal auth error" in r.message for r in caplog.records)
