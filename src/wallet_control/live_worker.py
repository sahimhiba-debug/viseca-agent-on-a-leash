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

Crash recovery
--------------
`RunState` lives only in memory. If this process crashes mid-run, an in-memory-only
design would forget every prior decision and approved-spend entry, risking both a
duplicate decision submission and a rolling-window limit being silently bypassed on
restart (see docs/archive/SECOND_ADVERSARIAL_AUDIT.md, "live worker crash consistency").
Two best-effort mitigations, neither of which is a full distributed-transaction
guarantee:

  1. `checkpoint_dir`, if given, persists `RunState` to a small JSON file after
     every decision/resolution, and `register_run`/auto-registration loads a
     matching file if one exists -- recovers this SAME process restarting.
  2. `reconcile_run` best-effort-repopulates a run's decided authorization_ids from
     the platform's own `GET /v1/authorizations` listing, for the case where even
     the checkpoint is unavailable (a different machine, a cleared checkpoint).
     Implemented defensively since the exact response shape is not pinned down in
     technical_details.md beyond "Lists pending and final runtime authorizations".
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .decision_engine import EngineDecision, evaluate_authorization, resolve_authorization
from .mandate import HardRule, MandateSnapshot, UncertaintyPolicy
from .state import HistoryIndex, RunState
from .viseca_client import VisecaApiError, VisecaClient
from .viseca_mapping import to_viseca_decision, to_wire_evidence

logger = logging.getLogger("wallet_control.live_worker")

ENGINE_VERSION = "wallet-control/0.1.0"
_SUBMIT_RETRY_DELAYS = (0.5, 1.5, 3.0)  # seconds; bounded retry for transient submit failures

# 401/403 mean the bearer key is missing, wrong, or has been revoked -- retrying
# the exact same request will never succeed, and spinning on it forever would
# silently burn the team's rate limit while looking, from the outside, like a
# worker that is merely slow. Every OTHER failure (a network error normalized to
# status 0, 429, 5xx, or an unexpected shape) is treated as transient and retried
# indefinitely with backoff, matching this module's "never approve on failure,
# degrade to waiting" contract. 404/400/409 on a specific call are handled by that
# call's own caller, not here, since they are request-specific, not connection-wide.
_FATAL_POLL_STATUS_CODES = frozenset({401, 403})
# A 4xx on submit is an answer about THIS request, and sending it again unchanged
# gets the same answer -- while the 8-second deadline runs out. Only these are worth
# repeating.
_RETRYABLE_CLIENT_STATUS_CODES = frozenset({408, 425, 429})


# Statuses of `GET /v1/authorizations` records that mean an answer exists. The first
# four are what the hosted sandbox returns; the wire decision words are kept because
# an earlier reading of the contract expected them.
_ANSWERED_STATUSES = frozenset({"approved", "declined", "timeout", "step_up",
                                "approve", "decline"})


def _listing_records(listing: Any) -> list[dict[str, Any]]:
    """The records of an authorization listing: the sandbox returns a bare list;
    an envelope under `data`/`authorizations`/`items` is accepted too."""
    records: Any = listing
    if isinstance(listing, dict):
        records = next((listing[k] for k in ("data", "authorizations", "items")
                        if isinstance(listing.get(k), list)), [])
    return [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []


def _record_decision(record: dict[str, Any]) -> str | None:
    """The wire decision a listing record carries, if it carries one. The sandbox
    nests it (`decision: {"decision": "approve", ...}`); a bare string is accepted."""
    decision = record.get("decision")
    if isinstance(decision, dict):
        decision = decision.get("decision")
    return decision if decision in ("approve", "decline", "step_up") else None


def _record_is_answered(record: dict[str, Any]) -> bool:
    return _record_decision(record) is not None or record.get("status") in _ANSWERED_STATUSES


class EchoedMandateMismatch(RuntimeError):
    """The platform echoed a policy that is not the one the customer confirmed.

    A run's policy is built from its FIRST event's `mandate` block. That block is the
    platform repeating back the rules we drafted -- but nothing compared them, so an
    echo that differed simply became the policy. An audit demonstrated the
    consequence: a widened echo turned a CHF 9,000 purchase at an unknown seller from
    BLOCK into ALLOW for the whole run.

    Any difference is fatal, including one that looks like a TIGHTENING. The platform
    is not an authority on the customer's policy; a tightening we did not author is
    still a policy we cannot explain to the customer, and treating "narrower" as
    acceptable would require trusting the same channel to tell us which direction it
    moved. The tighten-only rule governs `Mandate`, not this boundary.
    """


class FatalWorkerError(RuntimeError):
    """Raised out of `run_forever` when the API rejects our credentials outright
    (401/403). Retrying is pointless; this must be surfaced loudly to whatever is
    supervising the worker, not silently retried forever."""


@dataclass
class RunHandle:
    """Everything the worker needs to keep evaluating events for one run_id."""

    run_id: str
    mandate: MandateSnapshot
    state: RunState
    decisions: dict[str, EngineDecision] = field(default_factory=dict)
    # Authorization ids whose decision the platform has ACCEPTED (or already holds a
    # final answer for). Deciding is not the same as delivering: a redelivery of an
    # id missing from here means our answer never landed, and it is sent again.
    acknowledged: set[str] = field(default_factory=set)
    # Ids THIS process decided and failed to deliver. After a restart both sets are
    # empty, and the platform is asked instead -- see `_handle_envelope`.
    undelivered: set[str] = field(default_factory=set)


class LiveWorker:
    """Owns the poll/decide/submit loop for zero or more concurrent run_ids.

    A customer's step_up resolution is handled out-of-band via `resolve()`, called
    from the demo UI/API -- not from inside the poll loop -- because it must be
    possible to answer a step_up while the worker is mid-`wait=25` long-poll for
    the *next* purchase.
    """

    def __init__(
        self,
        client: VisecaClient,
        history: HistoryIndex,
        *,
        checkpoint_dir: Path | str | None = None,
        confirmed_rules: "Sequence[HardRule] | None" = None,
        confirmed_uncertainty_policy: "UncertaintyPolicy | None" = None,
        trust_echoed_policy: bool = False,
        on_step_up: "Callable[[str, EngineDecision, dict[str, Any]], None] | None" = None,
        on_decision: "Callable[[str, EngineDecision, dict[str, Any], RunState], None] | None" = None,
    ) -> None:
        self._client = client
        # Called after the platform accepts a step_up, with (run_id, decision, event),
        # so a customer interface can ask the question. Never called for anything else,
        # and nothing here answers on the customer's behalf.
        self._on_step_up = on_step_up
        # Called after the platform accepts ANY decision, with the run's state, so a
        # display can show what was decided. Display only: it runs after delivery.
        self._on_decision = on_decision
        self._history = history
        self._runs: dict[str, RunHandle] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._checkpoint_dir = Path(checkpoint_dir) if checkpoint_dir else None
        # What the CUSTOMER confirmed, held locally so the platform's echo can be
        # checked against it rather than adopted.
        #
        # This used to be optional and silently skipped when absent, with the safety
        # resting on one caller remembering. The stakes are on the record: an audit
        # widened the echo and turned a CHF 9,000 purchase at an unknown seller from
        # BLOCK into ALLOW for a whole run. A check whose absence is silent is the
        # same defect shape as five others found in this project, so forgetting is
        # now loud: omit the rules and you must SAY you are trusting the platform.
        if confirmed_rules is None and not trust_echoed_policy:
            raise ValueError(
                "LiveWorker needs the rules the customer confirmed, so the platform's "
                "echo of them can be checked rather than adopted. Pass "
                "confirmed_rules=..., or pass trust_echoed_policy=True to state "
                "explicitly that this worker adopts whatever policy it is sent."
            )
        self._confirmed_rules = tuple(confirmed_rules) if confirmed_rules is not None else None
        self._confirmed_uncertainty_policy = confirmed_uncertainty_policy

    @staticmethod
    def _rule_key(rule: "HardRule") -> tuple:
        return (rule.field, rule.operator, str(rule.value), rule.currency or "", rule.scope or "", rule.period_days or 0)

    def _verify_echoed_policy(self, run_id: str, snapshot: MandateSnapshot) -> None:
        """Refuse a run whose first event echoes a policy we did not confirm.

        Compares only what the CUSTOMER authored -- `hard_rules` and
        `uncertainty_policy`. `customer_id`, `card_id` and `profile_id` are assigned by
        the platform at run start and are legitimately absent from what we drafted, so
        comparing them would fail every healthy run.
        """
        if self._confirmed_rules is None:
            return
        echoed = {self._rule_key(r) for r in snapshot.hard_rules}
        confirmed = {self._rule_key(r) for r in self._confirmed_rules}
        problems = []
        if echoed != confirmed:
            for missing in sorted(confirmed - echoed):
                problems.append(f"rule the customer confirmed is ABSENT from the echo: {missing}")
            for added in sorted(echoed - confirmed):
                problems.append(f"rule in the echo that the customer never confirmed: {added}")
        if (
            self._confirmed_uncertainty_policy is not None
            and snapshot.uncertainty_policy != self._confirmed_uncertainty_policy
        ):
            problems.append(
                f"uncertainty_policy echoed as {snapshot.uncertainty_policy.value!r}, "
                f"customer confirmed {self._confirmed_uncertainty_policy.value!r}"
            )
        if problems:
            detail = "\n  - ".join(problems)
            logger.error("run %s: echoed mandate does not match the confirmed one:\n  - %s", run_id, detail)
            raise EchoedMandateMismatch(
                f"run {run_id}: the platform echoed a policy that is not the one the customer "
                f"confirmed; refusing to decide anything under it:\n  - {detail}"
            )

    def _checkpoint_path(self, run_id: str) -> Path | None:
        if self._checkpoint_dir is None:
            return None
        return self._checkpoint_dir / f"{run_id}.json"

    def _save_checkpoint(self, handle: RunHandle) -> None:
        path = self._checkpoint_path(handle.run_id)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        # The poll thread saves on every delivery and the customer's answer saves
        # from another thread; both write the same `.tmp`. The run's lock makes the
        # snapshot and the write one step, so neither sees the other half-done.
        with handle.state.decision_guard():
            tmp.write_text(json.dumps(handle.state.to_snapshot()))
            tmp.replace(path)  # atomic on POSIX and Windows: never leaves a half-written checkpoint

    def register_run(self, run_id: str, mandate: MandateSnapshot) -> RunHandle:
        """Restore this run's state, or start a fresh one.

        A FRESH STATE HAS ZERO SPEND IN IT, and that is the permissive branch: the
        rolling window starts again, so a run whose checkpoint is missing may spend
        the cap a second time. Nothing here can recover the figure -- `reconcile_run`
        says in its own docstring that the platform listing is not documented well
        enough to trust a reconstructed amount -- so the absence cannot be filled and
        must instead be made LOUD. It used to be the quietest path in the file: the
        restore branch logged, and the branch that resets the customer's allowance
        logged nothing at all.

        This is the same mistake as the six in `docs/ABSENCE.md` at a boundary none
        of those sweeps reach, because the missing thing is a FILE rather than a
        field. The honest answer here is not a default and not a refusal -- refusing
        would strand every genuinely new run -- it is to say so where an operator
        will see it, and to disclose the consequence in
        `docs/WHAT_WE_REFUSE_TO_CLAIM.md` rather than imply a bound we do not hold.
        """
        # THE PLATFORM CALL HAPPENS BEFORE THE LOCK, AND ONLY WHEN THERE IS NOTHING
        # TO RESTORE. Blocking I/O inside `self._lock` would stall every other
        # decision in this worker behind one HTTP round trip, and `register_run` is
        # on the auto-registration path taken by an ordinary first event -- so the
        # cost would land on the common case to serve the rare one.
        path = self._checkpoint_path(run_id)
        restorable = path is not None and path.exists()
        resumed_incomplete = False if restorable else not self._prior_spend_is_known(run_id)

        with self._lock:
            if restorable:
                snapshot = json.loads(path.read_text())
                state = RunState.from_snapshot(snapshot, self._history)
                logger.info("run_id=%s: restored %d prior decisions from checkpoint %s", run_id, len(snapshot["decisions"]), path)
            else:
                # WAS THERE A RUN HERE BEFORE? The old code did not ask, and could not
                # tell a genuinely new run from one whose state was lost -- so it
                # treated both as "nothing spent yet" and logged loudly about it.
                # The evidence to tell them apart was already being fetched, one
                # method down, for a different purpose.
                state = RunState(history=self._history, card_id=mandate.card_id,
                                 resumed_incomplete=resumed_incomplete)
                if resumed_incomplete:
                    logger.warning(
                        "run_id=%s: no checkpoint at %s and the platform has prior "
                        "decisions (or could not be asked); prior spend is UNKNOWN. "
                        "Rolling-period rules will evaluate `unknown` and follow this "
                        "mandate's uncertainty_policy rather than silently restarting "
                        "the customer's allowance at zero.", run_id, path)
                else:
                    logger.info(
                        "run_id=%s: no checkpoint at %s and the platform has no prior "
                        "decision for it; treating this as a genuinely new run.",
                        run_id, path)
            handle = RunHandle(run_id=run_id, mandate=mandate, state=state)
            self._runs[run_id] = handle
            return handle

    def _prior_spend_is_known(self, run_id: str) -> bool:
        """Is an empty ledger the truth, or just what survived?

        THE ASSUMPTION THIS REMOVES. `register_run` used to reason that refusing a
        run with no checkpoint "would strand every genuinely new run", and therefore
        started every such run at zero spend. That is only forced if the two cases
        are indistinguishable. They are not: a genuinely new run has no decision
        recorded anywhere, and a run whose state was lost has its earlier decisions
        sitting in `GET /v1/authorizations` -- which this worker already calls, one
        method down, to avoid double-submitting.

        So the listing is not being asked to RECONSTRUCT the spend (it cannot; see
        `reconcile_run` on why a reconstructed amount is not trustworthy). It is
        asked one binary question it can answer: **has this run decided anything
        before?** That is enough to tell "nothing was spent" from "I cannot see what
        was spent", and those two must not share a representation.

        THREE OUTCOMES, and the conservative one is the default:

            platform lists a final decision this state does not know  ->  UNKNOWN
            platform lists nothing                                    ->  known, zero
            platform cannot be reached                               ->  UNKNOWN

        The third is deliberate. Not being able to check is not evidence that
        nothing was spent, and the permissive reading of an unanswered question is
        the mistake this whole document is about. `unknown` is not a refusal: it
        routes to the mandate's own `uncertainty_policy`, so the cost of being
        careful here is an ASK, not a block.

        RUN ASSOCIATION IS BEST-EFFORT AND ERRS TOWARDS UNKNOWN. The listing's exact
        shape is not documented, so a record is attributed to this run when it
        carries a matching `run_id` and counted anyway when it carries no run field
        at all. That can over-trigger -- another run's decisions could make this one
        say "unknown" -- and over-triggering costs an ask while under-triggering
        costs the customer's ceiling. The asymmetry is the reason for the choice.
        """
        # THE SHAPE WAS GUESSED, AND THE GUESS FAILED OPEN. This matched
        # `decision == "approve"` or `status == "approve"`; the sandbox sends
        # `status: "approved"` and a nested decision object. Nothing matched, every
        # lost run looked new, and a SIGKILL test on SCEN0001 approved two purchases
        # over the customer's CHF 300 / 7 days. Both shapes are read now.
        try:
            records = _listing_records(self._client.list_authorizations())
        except Exception as exc:                  # noqa: BLE001 -- any failure means "cannot establish"
            logger.warning("run_id=%s: could not ask the platform whether this run "
                           "existed (%s); treating prior spend as UNKNOWN", run_id, exc)
            return False

        for record in records:
            if not _record_is_answered(record):
                continue
            where = record.get("run_id") or record.get("runId")
            if where is not None and where != run_id:
                continue
            return False          # something was decided here before this process started
        return True

    def reconcile_run(self, run_id: str) -> int:
        """Best-effort recovery when no local checkpoint is available: ask the
        platform which authorizations it already has a decision for, via
        `GET /v1/authorizations`, and skip re-submitting for any of them. This
        cannot rebuild rolling-window spend history (the endpoint's exact shape
        isn't documented well enough to trust a reconstructed amount/timestamp) --
        it only prevents a duplicate submission for an authorization_id whose
        decision the platform already has. Returns the number of authorization_ids
        recognized as already-decided. Never raises: a failure here degrades to
        "nothing recovered", not a crash.
        """
        handle = self._runs.get(run_id)
        if handle is None:
            raise ValueError(f"cannot reconcile unregistered run_id {run_id!r}; call register_run first")
        try:
            listing = self._client.list_authorizations()
        except VisecaApiError as exc:
            logger.warning("reconcile_run(%s): could not list authorizations (%s); nothing recovered", run_id, exc)
            return 0

        recovered = 0
        for record in _listing_records(listing):
            authorization_id = record.get("authorization_id")
            already_known = handle.state.get_stored_decision(authorization_id) is not None
            if not authorization_id or already_known or not _record_is_answered(record):
                continue
            wire_decision = _record_decision(record) or record.get("status")
            # We deliberately do NOT know this record's true amount/merchant/basket
            # with confidence from an undocumented shape, so we do not fabricate a
            # StoredDecision for it (that would corrupt rolling-window math with a
            # guess). We only note it so `evaluate_authorization`'s repeat-delivery
            # path -- which needs a real fingerprint -- is left to do the right
            # thing on next delivery; logging this is the honest, limited value
            # reconciliation can safely provide without that shape guarantee.
            logger.info("reconcile_run(%s): platform already has a decision for %s (%s)", run_id, authorization_id, wire_decision)
            recovered += 1
        return recovered

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
                if exc.status_code in _FATAL_POLL_STATUS_CODES:
                    logger.error("poll failed with a fatal auth error (%s); stopping rather than retrying forever", exc)
                    raise FatalWorkerError(f"authentication failed while polling: {exc}") from exc
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
            self._verify_echoed_policy(run_id, snapshot)
            handle = self.register_run(run_id, snapshot)
            logger.info("auto-registered run_id=%s from its first event (mandate_id=%s)", run_id, snapshot.mandate_id)

        deadline = event.get("deadline_at")
        result = evaluate_authorization(event, handle.mandate, handle.state)
        # A replay's result carries "repeated_delivery" instead of the original
        # reasons, so it must not overwrite the decision it repeats.
        handle.decisions.setdefault(authorization_id, result)
        self._save_checkpoint(handle)

        if result.authorization_id_conflict:
            # This delivery's facts don't match what we already decided (see
            # decision_engine.py): never resubmitted, whatever else is true.
            logger.error("authorization_id=%s: %s", authorization_id, result.customer_message)
            return
        if result.idempotent_replay:
            if authorization_id in handle.acknowledged:
                logger.info("authorization_id=%s already decided (%s) and accepted; reconciling without re-evaluating", authorization_id, result.decision)
                return
            # A restarted worker has forgotten what it delivered, and the platform
            # redelivers a purchase while it waits for the customer. Resending then
            # would be a second automated decision after step_up, which the contract
            # forbids -- so unless this process saw its own delivery fail, the
            # platform is asked, and only a purchase it holds NO answer for is sent.
            if authorization_id not in handle.undelivered and self._platform_has_answer(authorization_id) is not False:
                handle.acknowledged.add(authorization_id)
                logger.info("authorization_id=%s already decided (%s); the platform holds an answer or cannot be asked, so nothing is sent again", authorization_id, result.decision)
                return
            # Decided, but the platform never took our answer -- which is why it is
            # asking again. The stored decision is sent, never a fresh one. In the
            # first sandbox run this branch returned instead, and the platform
            # redelivered fifteen times before timing an ALLOW out into a decline.
            logger.warning("authorization_id=%s redelivered and our decision (%s) was never accepted; sending it again", authorization_id, result.decision)
            result = handle.decisions[authorization_id]

        if deadline:
            deadline_dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > deadline_dt:
                logger.warning("authorization_id=%s: submitting after deadline_at=%s", authorization_id, deadline)

        if self._submit_with_retry(result):
            handle.acknowledged.add(authorization_id)
            handle.undelivered.discard(authorization_id)
            if self._on_decision is not None:
                self._on_decision(run_id, result, event, handle.state)
            if result.decision == "review" and self._on_step_up is not None:
                self._on_step_up(run_id, result, event)
        else:
            handle.undelivered.add(authorization_id)

    def _platform_has_answer(self, authorization_id: str) -> bool | None:
        """Does the platform's listing show an answer for this id? None if it cannot
        be asked -- which the caller treats as yes: not resending costs a timeout,
        resending could be a second decision on a purchase the customer is holding."""
        try:
            records = _listing_records(self._client.list_authorizations())
        except Exception as exc:                  # noqa: BLE001 -- any failure means "cannot establish"
            logger.warning("could not ask the platform about %s (%s)", authorization_id, exc)
            return None
        for record in records:
            if record.get("authorization_id") == authorization_id:
                return _record_is_answered(record)
        return False

    def _submit_with_retry(self, result: EngineDecision) -> bool:
        """Deliver one decision. Returns True once the platform holds an answer for
        this id -- ours, or (409) a final one it already had."""
        wire_decision = to_viseca_decision(result.decision)
        explained: dict[str, Any] = {
            "reason_codes": list(result.reason_codes),
            "customer_message": result.customer_message,
            "evidence": to_wire_evidence(result.rule_evaluations),
            "engine_version": ENGINE_VERSION,
        }
        last_exc: Exception | None = None
        for delay in (0.0, *_SUBMIT_RETRY_DELAYS):
            if delay:
                time.sleep(delay)
            try:
                self._client.submit_decision(result.authorization_id, wire_decision, **explained)
                return True
            except VisecaApiError as exc:
                last_exc = exc
                if exc.status_code in _FATAL_POLL_STATUS_CODES:
                    logger.error("submit_decision failed for %s with a fatal auth error (%s); not retrying", result.authorization_id, exc)
                    break
                if exc.status_code == 409:
                    logger.warning("submit_decision for %s: the platform already holds a final answer (%s)", result.authorization_id, exc)
                    return True
                if exc.status_code == 422 and explained:
                    # The explanation is optional; the decision is not. Only
                    # `authorization_id` and `decision` are required, so a rejected
                    # explanation must not cost the customer their answer.
                    logger.error("submit_decision for %s: explanation rejected (%s); sending the bare decision", result.authorization_id, exc)
                    explained = {}
                    try:
                        self._client.submit_decision(result.authorization_id, wire_decision)
                        return True
                    except VisecaApiError as bare_exc:
                        last_exc = exc = bare_exc
                        if exc.status_code == 409:
                            return True
                if 400 <= exc.status_code < 500 and exc.status_code not in _RETRYABLE_CLIENT_STATUS_CODES:
                    logger.error("submit_decision failed for %s with %s; not retrying an answer the server will repeat", result.authorization_id, exc)
                    break
                logger.warning("submit_decision failed for %s (%s); retrying", result.authorization_id, exc)
        logger.error("submit_decision permanently failed for %s: %s", result.authorization_id, last_exc)
        return False

    def revoke_run(self, run_id: str) -> tuple[str, ...]:
        """The customer pulled the leash: every authority this run issued and has not
        spent dies, and every later purchase in the run is blocked (`state.is_revoked`).
        Revoking the mandate on the platform is the caller's separate call."""
        handle = self._runs[run_id]
        revoked = handle.state.revoke_outstanding_authorities()
        self._save_checkpoint(handle)
        return revoked

    def resolve(self, run_id: str, authorization_id: str, human_decision: str, *, customer_message: str | None = None) -> EngineDecision:
        """Apply a real customer's approve/decline to a stepped-up authorization and
        forward it to the API via /resolve. `human_decision` is the internal
        vocabulary ("allow"/"block"), not the wire value."""
        handle = self._runs[run_id]
        result = resolve_authorization(
            authorization_id,
            human_decision,  # type: ignore[arg-type]
            handle.state,
            resolved_at=datetime.now(timezone.utc),
            # Required: a human-approved step-up must mint a payment authority like
            # any other approval, or it cannot later be revoked. See
            # docs/archive/DEEP_SECURITY_RESEARCH.md (V2).
            mandate=handle.mandate,
        )
        self._save_checkpoint(handle)
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
