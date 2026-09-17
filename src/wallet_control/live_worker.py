"""The executable live worker: long-polls the hosted API, decides, and submits.

Follows the worker outline in technical_details.md step 6 verbatim:

    While the run has work remaining:
        Poll for a request.
        If the response is 204, check progress and continue.
        If the response is an error, handle it before reading purchase data.
        Read the envelope's run ID and validate its data event.
        If this live purchase ID was already handled, reconcile its saved result.
        Otherwise, evaluate the policy and submit a decision before deadline_at.
        Record the result accepted by the API.
        If it needs a human answer, show it in the customer interface.
        Keep receiving requests while the interface waits for the customer.

    Separately, when the customer answers:
        Submit their answer through /resolve and record the accepted result.

Deliberately not a job queue or a distributed worker: one process, one thread,
one `RunState` per run_id, matching the event-day operating model (a single team
running a single worker against a single hosted run at a time). See
docs/ARCHITECTURE.md "Concurrency" for why this is an explicit, documented choice
rather than an oversight.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .decision_engine import EngineDecision, evaluate_authorization, resolve_authorization
from .mandate import MandateSnapshot
from .state import HistoryIndex, RunState
from .viseca_client import VisecaApiError, VisecaClient
from .viseca_mapping import to_viseca_decision

logger = logging.getLogger("wallet_control.live_worker")

ENGINE_VERSION = "wallet-control/0.1.0"
_SUBMIT_RETRY_DELAYS = (0.5, 1.5, 3.0)  # seconds; bounded retry for transient submit failures


@dataclass
class RunHandle:
    """Everything the worker needs to keep evaluating events for one run_id."""

    run_id: str
    mandate: MandateSnapshot
    state: RunState
    decisions: dict[str, EngineDecision] = field(default_factory=dict)


class LiveWorker:
    """Owns the poll/decide/submit loop for zero or more concurrent run_ids.

    A customer's step_up resolution is handled out-of-band via `resolve()`, called
    from the demo UI/API -- not from inside the poll loop -- because it must be
    possible to answer a step_up while the worker is mid-`wait=25` long-poll for
    the *next* purchase.
    """

    def __init__(self, client: VisecaClient, history: HistoryIndex) -> None:
        self._client = client
        self._history = history
        self._runs: dict[str, RunHandle] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def register_run(self, run_id: str, mandate: MandateSnapshot) -> RunHandle:
        with self._lock:
            handle = RunHandle(run_id=run_id, mandate=mandate, state=RunState(history=self._history, card_id=mandate.card_id))
            self._runs[run_id] = handle
            return handle

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self, *, wait_seconds: int = 25, max_events: int | None = None, max_polls: int | None = None) -> int:
        """Poll and decide until stopped, `max_events` decisions have been made, or
        `max_polls` poll attempts (200s, 204s, and failures alike) have happened --
        `max_polls` exists mainly so tests can bound a run that only ever sees 204s.
        Returns the number of events processed. Never raises out of the loop body
        for a single bad event/poll -- a fault here must degrade to "keep waiting",
        not "approve by default"."""
        processed = 0
        polls = 0
        while not self._stop.is_set():
            if max_events is not None and processed >= max_events:
                return processed
            if max_polls is not None and polls >= max_polls:
                return processed
            polls += 1
            try:
                envelope = self._client.next_decision_request(wait=wait_seconds)
            except VisecaApiError as exc:
                logger.warning("poll failed (%s); backing off and retrying, no decision was made", exc)
                time.sleep(1.0)
                continue

            if envelope is None:
                # HTTP 204: no work right now. NOT "run finished" (technical_details.md
                # step 6). Just poll again; the caller decides when to stop this loop
                # (e.g. after inspecting GET /v1/scenario-runs/{run_id}).
                continue

            try:
                self._handle_envelope(envelope, wait_seconds=wait_seconds)
                processed += 1
            except Exception:
                logger.exception("failed to process envelope %r; continuing to poll rather than approving by default", envelope.get("event_id"))
        return processed

    def _handle_envelope(self, envelope: dict, *, wait_seconds: int) -> None:
        run_id = envelope["run_id"]
        event = envelope["data"]
        authorization_id = event["authorization"]["authorization_id"]

        handle = self._runs.get(run_id)
        if handle is None:
            # First time we've seen this run_id: build the mandate snapshot from the
            # event's own `mandate` block, since customer_id/card_id/profile_id are
            # only known once the platform assigns them at run start (see
            # `MandateSnapshot.from_event_mandate`).
            snapshot = MandateSnapshot.from_event_mandate(event["mandate"])
            handle = self.register_run(run_id, snapshot)
            logger.info("auto-registered run_id=%s from its first event (mandate_id=%s)", run_id, snapshot.mandate_id)

        already = handle.state.get_stored_decision(authorization_id)
        if already is not None:
            logger.info("authorization_id=%s already decided (%s); reconciling without re-evaluating", authorization_id, already.decision)
            # The platform already has our original submission; nothing further to send.
            return

        deadline = event.get("deadline_at")
        result = evaluate_authorization(event, handle.mandate, handle.state)
        handle.decisions[authorization_id] = result

        if deadline:
            deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > deadline_dt:
                logger.warning("authorization_id=%s: submitting after deadline_at=%s", authorization_id, deadline)

        self._submit_with_retry(result)

    def _submit_with_retry(self, result: EngineDecision) -> None:
        last_exc: Exception | None = None
        for delay in (0.0, *_SUBMIT_RETRY_DELAYS):
            if delay:
                time.sleep(delay)
            try:
                self._client.submit_decision(
                    result.authorization_id,
                    to_viseca_decision(result.decision),
                    reason_codes=list(result.reason_codes),
                    customer_message=result.customer_message,
                    evidence=list(result.evidence),
                    engine_version=ENGINE_VERSION,
                )
                return
            except VisecaApiError as exc:
                last_exc = exc
                logger.warning("submit_decision failed for %s (%s); retrying", result.authorization_id, exc)
        logger.error("submit_decision permanently failed for %s: %s", result.authorization_id, last_exc)

    def resolve(self, run_id: str, authorization_id: str, human_decision: str, *, customer_message: str | None = None) -> EngineDecision:
        """Apply a real customer's approve/decline to a stepped-up authorization and
        forward it to the API via /resolve. `human_decision` is the internal
        vocabulary ("allow"/"block"), not the wire value."""
        handle = self._runs[run_id]
        stored = handle.state.get_stored_decision(authorization_id)
        if stored is None or stored.decision != "review":
            raise ValueError(f"{authorization_id} is not currently pending customer review")
        result = resolve_authorization(
            authorization_id,
            human_decision,  # type: ignore[arg-type]
            handle.state,
            billing_amount_chf=stored.billing_amount_chf,
            timestamp=datetime.now(timezone.utc),
        )
        if customer_message is None:
            customer_message = "The customer confirmed this purchase." if human_decision == "allow" else "The customer declined this purchase."
        self._client.resolve(
            authorization_id,
            to_viseca_decision(human_decision),  # "allow"/"block" -> "approve"/"decline"
            customer_message=customer_message,
            evidence=[],
        )
        handle.decisions[authorization_id] = result
        return result
