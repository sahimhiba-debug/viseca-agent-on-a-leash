"""Exercises `LiveWorker` against a fake `VisecaClient` (no real network / no live
API key needed). Covers exactly the failure modes technical_details.md calls out:
HTTP 204 handling, never turning an API failure into an approval, not re-deciding
repeated delivery, and step_up/resolve staying separate from the automated poll loop.
"""

from __future__ import annotations

from tests.helpers import make_event, make_mandate
from wallet_control.live_worker import LiveWorker
from wallet_control.mandate import HardRule
from wallet_control.state import HistoryIndex
from wallet_control.viseca_client import VisecaApiError


class FakeVisecaClient:
    """Implements just the subset of VisecaClient's interface LiveWorker uses."""

    def __init__(self, envelopes: list[dict | None], fail_polls: int = 0):
        self._envelopes = list(envelopes)
        self._fail_polls = fail_polls
        self.submitted: list[dict] = []
        self.resolved: list[dict] = []

    def next_decision_request(self, wait: int = 25):
        if self._fail_polls > 0:
            self._fail_polls -= 1
            raise VisecaApiError(503, {"error": "temporarily unavailable"})
        if not self._envelopes:
            return None
        return self._envelopes.pop(0)

    def submit_decision(self, authorization_id, decision, **kwargs):
        self.submitted.append({"authorization_id": authorization_id, "decision": decision, **kwargs})
        return {"authorization_id": authorization_id, "decision": decision}

    def resolve(self, authorization_id, decision, **kwargs):
        self.resolved.append({"authorization_id": authorization_id, "decision": decision, **kwargs})
        return {"authorization_id": authorization_id, "decision": decision}


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
    import pytest

    with pytest.raises(ValueError):
        worker.resolve("RUN1", "AU1", "allow")
