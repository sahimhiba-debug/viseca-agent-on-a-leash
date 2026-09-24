"""Runtime state a control layer must keep across a sequence of decisions.

technical_details.md step 8 lists exactly what this module exists to get right:

  * "Count final approvals when enforcing spending limits. A purchase waiting for
    a human answer is not yet approved." -> only APPROVE (including a resolved
    step_up) ever enters `RunState._approved_spend`.
  * "Recognize repeated delivery by its live purchase ID. Record it once, so a
    retry does not add the amount twice." -> `get_stored_decision` / idempotency.
  * "Check distinct but similar purchases against earlier outcomes; different IDs
    can still describe an unwanted duplicate order." -> `find_similar_recent`.

Two different things are both called "duplicate" in this codebase and must not be
conflated:

  1. **Repeated delivery**: the platform re-sends the *same* `authorization_id*
     (a network retry). This is pure idempotency: replay the stored decision,
     do not re-evaluate, do not double-count spend.
  2. **Similar recent purchase**: a *different* `authorization_id` for what looks
     like the same real-world order (same merchant, same basket, same amount,
     shortly after). This is not automatically fraud or automatically fine --
     it is evidence fed into the normal uncertainty pathway.
"""

from __future__ import annotations

import csv
import threading
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal

Decision = Literal["allow", "review", "block"]

# One basket line as it is frozen into a purchase fingerprint:
#   (item_id, item_name, quantity, return_window_days, final_sale, stated_size,
#    order_returnable)
# The last element is ORDER-level, repeated on every line. It is here because it was
# once left out on the reasoning that it is platform-supplied and therefore a
# different trust tier -- true of the offline replay, false of `/api/agent/propose`,
# which derives it from the agent's own `return_days`. A re-delivery that changed
# only that field matched the fingerprint and inherited an ALLOW the same event would
# not have been given fresh.
# The last three are facts DERIVED from the merchant's untrusted `item_details`,
# never the raw text -- see `decision_engine._basket_key`, which is the only
# producer of this type, for why that distinction is load-bearing in both
# directions. Every element is JSON-native so `RunState.to_snapshot()` round-trips
# it without a custom encoder.
BasketLineKey = tuple[str, str, int, int | None, bool, str | None]
BasketKey = tuple[BasketLineKey, ...]

# How long a PaymentAuthority remains valid for execution after being issued.
# Not specified anywhere in technical_details.md (the official contract has no
# payment-execution endpoint at all -- see docs/VISECA_INTEGRATION.md); chosen as
# a deliberately short, demonstrable window for this synthetic prototype, real-clock
# based like a response deadline (I21 in SECURITY_INVARIANTS.md), not simulated-time
# based like a spending window -- a payment authority's validity is about how long
# the EXECUTION side has to act on an already-made decision, not about when the
# underlying purchase occurred.
DEFAULT_AUTHORITY_TTL = timedelta(minutes=15)

# Public: `decision_engine` needs the same figure to ask whether a resumed
# state has watched long enough to claim there was no similar recent order.
DUPLICATE_WINDOW = timedelta(minutes=60)
_VELOCITY_WINDOW = timedelta(minutes=10)   # matches the event's `recent_attempt_count_10m`


class HistoryIndex:
    """Answers "has this card ever had an approved purchase at this merchant?" from
    the official `authorization_history.csv`. Used for the `merchant.familiar` rule.

    `available` distinguishes "we checked and the answer is no" (False) from "we
    have no history data to check at all" (None, unknown) -- these must not be
    conflated, or a missing history fetch would silently look identical to a
    clearly-unfamiliar merchant.
    """

    def __init__(self, approved_merchants_by_card: dict[str, frozenset[str]], *,
                 available: bool = True,
                 agent_only_merchants_by_card: dict[str, frozenset[str]] | None = None) -> None:
        # The first argument is the CUSTOMER'S OWN history -- purchases they or a
        # merchant-initiated arrangement made. The second is the agent's, and it is
        # kept apart deliberately; see `is_familiar`.
        self._approved_merchants_by_card = approved_merchants_by_card
        self._agent_only_by_card = agent_only_merchants_by_card or {}
        self.available = available

    @classmethod
    def empty(cls) -> "HistoryIndex":
        return cls({}, available=False)

    @classmethod
    def from_csv(cls, path: Path) -> "HistoryIndex":
        """Split by WHO made each past purchase.

        `authorization_history.csv` carries `initiator_type` -- human, agent, or
        merchant -- and this used to collapse all three. On the official pack that
        makes 24 card/merchant pairs "familiar" on the strength of the AGENT'S own
        past purchases and nothing else. The customer never shopped there.

        Which matters because of what it composes into. Run the agent once under a
        loose mandate; it buys at ten new shops. Then tighten to "only shops I have
        used before". Those ten now qualify, and the tightening bought nothing --
        two individually valid operations composing into a policy that does not do
        what it says. The agent's own history becomes the customer's permission.

        `merchant`-initiated rows count as the customer's: a recurring charge or a
        refund both imply a relationship the customer entered. Measured on the pack,
        no merchant/card pair is familiar through those alone.
        """
        by_card: dict[str, set[str]] = {}
        agent_by_card: dict[str, set[str]] = {}
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["status"] != "approved":
                    continue
                target = agent_by_card if row.get("initiator_type") == "agent" else by_card
                target.setdefault(row["card_id"], set()).add(row["merchant_id"])
        agent_only = {card: frozenset(shops - by_card.get(card, set()))
                      for card, shops in agent_by_card.items()}
        return cls({k: frozenset(v) for k, v in by_card.items()}, available=True,
                   agent_only_merchants_by_card={k: v for k, v in agent_only.items() if v})

    def is_familiar(self, card_id: str, merchant_id: str) -> bool | None:
        """True, False, or None -- and None now has two causes, both honest.

        A card with history but never this merchant is genuinely unfamiliar (False).
        A card we have no record of at all is unknown (None) -- a brand-new card, or
        a data gap.

        AND a merchant only the AGENT has bought from is also None. The customer
        asked about their own history; the honest answer is "your agent has, you have
        not", which is neither the yes they asked for nor a flat no. It goes to their
        `uncertainty_policy` like every other unknown. Treating it as True lets an
        agent bootstrap its own permission; treating it as False would punish a
        customer who genuinely shops through one.
        """
        if not self.available:
            return None
        if card_id not in self._approved_merchants_by_card:
            return None
        if merchant_id in self._approved_merchants_by_card[card_id]:
            return True
        if merchant_id in self._agent_only_by_card.get(card_id, ()):
            return None
        return False

    def familiarity_basis(self, card_id: str, merchant_id: str) -> str:
        """Whose history answered, for the evidence line and the customer's message."""
        if not self.available:
            return "no purchase history was available"
        if merchant_id in self._approved_merchants_by_card.get(card_id, ()):
            return "you have paid this seller before"
        if merchant_id in self._agent_only_by_card.get(card_id, ()):
            return "your agent has paid this seller before, but you have not"
        if card_id not in self._approved_merchants_by_card:
            return "this card has no purchase history"
        return "you have never paid this seller"


@dataclass(frozen=True)
class StoredDecision:
    """The accepted, final-so-far result for one live authorization_id.

    `timestamp` is always the purchase's *simulated* time (`authorization.timestamp`),
    never a real-clock time -- it is what rolling-window spend is keyed on
    (technical_details.md: "Use simulated purchase time for spending windows, and
    the real clock for response deadlines"). A human resolving a step_up an hour
    (real time) after it was raised must not shift that purchase's window
    attribution; `resolved_at` carries the real-clock answer time separately, for
    audit display only.

    `merchant_id` and `basket_key` are a fingerprint of what was actually decided,
    used to detect a repeated `authorization_id` whose underlying facts changed
    between deliveries (see `find_similar_recent`'s module docstring and
    `evaluate_authorization`'s idempotency check) -- a case that must never be
    silently trusted either way.
    """

    authorization_id: str
    decision: Decision
    billing_amount_chf: Decimal
    timestamp: datetime
    counted_in_spend: bool  # True once an approve has been counted into rolling spend
    merchant_id: str
    basket_key: BasketKey
    was_reviewed: bool = False  # True iff this authorization was ever put to REVIEW
    resolved_at: datetime | None = None  # real-clock time of a human's answer, audit-only
    reason_codes: tuple[str, ...] = ()
    # --- execution lifecycle -------------------------------------------------------
    # These three used to live on a separate PaymentAuthority object in a second
    # dict. Two records describing one authorization is precisely the shape that
    # produced V2 (a decision with no authority), V3/V8/V10 (an authority lost on
    # restart) and V13/V14 (a lifecycle overwritten by a concurrent transition).
    # Holding them here makes "every approved decision has an execution lifecycle"
    # true by construction rather than by a fail-closed check.
    mandate_id: str | None = None          # provenance for the audit record
    policy_version: str | None = None      # provenance
    execution_issued_at: datetime | None = None
    execution_expires_at: datetime | None = None
    revoked: bool = False
    consumed_at: datetime | None = None


@dataclass(frozen=True)
class PaymentAuthority:
    """A read-only PROJECTION of one approved decision's execution lifecycle.

    This used to be an independently stored object in `RunState._authorities`, and
    it was the source of four vulnerabilities, all of the same shape: a second
    record describing the same authorization, free to drift from the first. It is
    now built on demand from the `StoredDecision` that already holds every fact it
    reports, so there is nothing to drift from.

    `issued_at` is RECORDED, not reconstructed. An earlier version of this merge
    derived it as `expires_at - DEFAULT_AUTHORITY_TTL`, which Audit 1 rejected: a
    derivation must rest on authoritative state, never on a program constant that a
    later edit could change under historical records.

    Every other field below except the lifecycle three is a copy that nothing read:
    a survey of the production source found `amount_ceiling_chf`,
    `basket_fingerprint`, `policy_version`, `currency`, `issued_at`, `evidence_ref`
    and `mandate_id` read ZERO times. They are kept only because the demo displays
    them, and they are now derived rather than stored.
    """

    authorization_id: str
    mandate_id: str
    merchant_id: str
    amount_ceiling_chf: Decimal
    currency: str
    issued_at: datetime
    expires_at: datetime
    basket_fingerprint: BasketKey
    policy_version: str
    evidence_ref: str
    revoked: bool = False
    consumed_at: datetime | None = None

    @classmethod
    def project(cls, stored: "StoredDecision") -> "PaymentAuthority | None":
        """Build the view, or None when this decision carries no execution
        lifecycle (i.e. it was never an approval)."""
        if stored.decision != "allow" or stored.execution_expires_at is None:
            return None
        return cls(
            authorization_id=stored.authorization_id,
            mandate_id=stored.mandate_id or "",
            merchant_id=stored.merchant_id,
            amount_ceiling_chf=stored.billing_amount_chf,
            currency="CHF",
            issued_at=stored.execution_issued_at,
            expires_at=stored.execution_expires_at,
            basket_fingerprint=stored.basket_key,
            policy_version=stored.policy_version or "",
            evidence_ref=f"decision:{stored.authorization_id}",
            revoked=stored.revoked,
            consumed_at=stored.consumed_at,
        )

    def as_dict(self) -> dict:
        return {
            "authorization_id": self.authorization_id,
            "mandate_id": self.mandate_id,
            "merchant_id": self.merchant_id,
            "amount_ceiling_chf": str(self.amount_ceiling_chf),
            "currency": self.currency,
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "basket_fingerprint": list(self.basket_fingerprint),
            "policy_version": self.policy_version,
            "evidence_ref": self.evidence_ref,
            "revoked": self.revoked,
        }


class ResolutionError(ValueError):
    """Raised when a human resolution cannot be applied as requested -- distinct
    from a plain `ValueError` so callers (api.py, live_worker.py) can map it to a
    specific HTTP status / log message rather than a generic 400/500."""


class CheckpointError(ValueError):
    """A checkpoint that cannot be restored faithfully.

    Raised rather than defaulted, and that is the whole point. `from_snapshot` used
    to read the security-relevant fields with `.get(key, permissive_default)` --
    `revoked=d.get("revoked", False)`, `consumed_at=... if d.get("consumed_at")
    else None` -- which is the ordinary forward-compatible idiom and is exactly
    wrong here, because every one of those defaults is the SPENDABLE branch.

    Measured, before the fix, on a snapshot with one key removed:

        drop `consumed_at`  ->  a spent authority is spendable again   DOUBLE SPEND
        drop `revoked`      ->  a revoked authority is live again      REVOCATION UNDONE

    `to_snapshot` always writes these, so this costs nothing for a checkpoint this
    code produced. What it changes is the OTHER cases -- an older build's file, a
    hand-edited one, a truncated write -- where the quiet default silently re-arms
    money the customer had already spent or already stopped. A checkpoint we cannot
    read is a checkpoint we refuse to read.

    Predicted before it was found: `docs/ABSENCE.md` names five earlier instances of
    one mistake and says the next one should be looked for wherever a missing fact
    is replaced by a present one. This was the first place looked.
    """


class AuthorityError(ValueError):
    """Raised when a PaymentAuthority cannot be issued, or is invalid at the point
    it is needed (expired, revoked, or the underlying decision was never allow)."""


@dataclass(frozen=True)
class _RecentAttempt:
    """A basket/merchant/amount fingerprint for duplicate detection.

    Deliberately does NOT store a copy of the decision: `find_similar_recent` looks
    the current decision up live via `RunState._decisions`, so a `review` that is
    later resolved to `block` is correctly excluded from then on -- a frozen
    snapshot here would silently go stale the moment a step_up is resolved.
    """

    authorization_id: str
    merchant_id: str
    basket_key: BasketKey
    billing_amount_chf: Decimal
    timestamp: datetime


@dataclass
class RunState:
    """All mutable state for one mandate/run. One instance per run -- the offline
    replay creates one per scenario; the live worker creates one per run_id."""

    history: HistoryIndex
    card_id: str
    # DID THIS STATE WATCH THE WHOLE RUN, OR JOIN PART-WAY THROUGH?
    #
    # A fresh `RunState` has an empty ledger, and an empty ledger has always MEANT
    # "nothing has been spent". For a genuinely new run that is true. For a run whose
    # checkpoint is missing -- a redeploy, a crash, a new machine -- it is false, and
    # the two were indistinguishable, so the second silently reopened the customer's
    # whole rolling allowance. Measured: a CHF 300 / 7-day cap approved CHF 900 in one
    # window across three restarts, and the bound is per-restart, not per-window.
    #
    # Zero is a VALUE. "I do not know what was spent" is an ABSENCE. Substituting the
    # first for the second is the mistake this repository has now found fifteen times
    # (docs/ABSENCE.md), and this is the highest-stakes place it has appeared: the
    # number being invented is the money already gone.
    #
    # THE FIRST VERSION OF THIS FIELD WAS CALLED `prior_spend_known`, AND THE NAME
    # WAS THE BUG. It named one CONSUMER of the lost state -- the rolling budget --
    # while three others went on reading an empty collection as a fact about the
    # world. Measured after a restart, same fixture, same basket, five minutes apart:
    #
    #     a duplicate order, state intact   ->  review  (order.duplicate_suspected)
    #     the same order, after a restart   ->  ALLOW
    #
    # The restart silently switched duplicate detection off too: one real order,
    # charged twice, no forgery anywhere. Fixing the budget alone would have been
    # fixing the first symptom and calling it the class.
    #
    # BUT "AFTER A RESTART, NOTHING IS KNOWN" IS UNUSABLE. It would send every
    # purchase to the customer for ever, because a lost state never becomes found.
    # The missing idea is that incompleteness has a HORIZON. Every state-derived
    # fact here answers a question about a BOUNDED window -- the last 60 minutes for
    # a duplicate, the last 10 for velocity, the last `period_days` for a ceiling --
    # and a state that has been watching for longer than the window has seen all of
    # it, whatever happened before. So the unknown expires on its own, and the cost
    # of a restart is bounded by the longest window the mandate actually uses.
    #
    # `resumed_incomplete` says this state joined part-way through. `_observed_from`
    # is when it started watching, in the SIMULATED purchase clock those windows use
    # (technical_details.md: "simulated purchase time for spending windows, and the
    # real clock for response deadlines"), taken from the first event it sees rather
    # than from a wall clock that is not comparable with them.
    #
    # Ask `has_observed(as_of, window)`. Neither field is read directly anywhere.
    resumed_incomplete: bool = False
    _observed_from: datetime | None = None
    # Set when an event arrives stamped EARLIER than the moment this state started
    # watching. See `note_observation`: it is the evidence that delivery order and
    # simulated time do not agree, which is the one assumption the horizon rests on.
    _ordering_broken: bool = False
    _decisions: dict[str, StoredDecision] = field(default_factory=dict)
    _approved_spend: list[tuple[datetime, Decimal]] = field(default_factory=list)
    # Every device this run has seen, not only the last one. A return to a device
    # already used is the commonest benign pattern in the data and must not read the
    # same as a move to a fresh one -- see `session_signals`.
    _seen_devices: set[str] = field(default_factory=set)
    _recent_attempts: list[_RecentAttempt] = field(default_factory=list)
    _last_device_id: str | None = None
    # When the customer revoked this run's mandate. This is RUN-LEVEL state, not a
    # per-record flag, and the distinction is the whole fix for F1.
    #
    # Revocation used to be only a sweep over existing records. A sweep cannot cover
    # a record that does not exist yet, so a purchase still WAITING for the customer
    # carried no lifecycle to revoke, and answering it afterwards minted a fresh,
    # unrevoked authority -- the money the customer had just tried to stop. Found by
    # an independent security audit and reproduced end-to-end through the HTTP API:
    # revoke -> resolve(allow) -> CHF 175 charged.
    #
    # Holding the fact at the scope the bound belongs to (the run) makes "nothing
    # may be authorised after revocation" true for records not yet written.
    _revoked_at: datetime | None = None
    # Guards every read-modify-write on this run: the authority compare-and-set, the
    # consent transition, and -- since the temporal-consistency audit -- the whole
    # decision path.
    #
    # RE-ENTRANT on purpose. `evaluate_authorization` holds it across "check the
    # rolling window, then record the decision", and `record_decision` takes it again
    # underneath. Without that span the period check is a read-modify-write with the
    # entire rule evaluation inside it: with a widened window, two concurrent
    # proposals both saw the same remaining budget and both passed, putting CHF 400
    # into a CHF 300 week in 40 of 40 trials. Not reachable through the
    # single-threaded LiveWorker; entirely reachable through api.py's threadpool.
    #
    # Not serialized (to_snapshot lists its keys explicitly) and excluded from
    # equality -- it is machinery, not state.
    _consume_lock: "threading.RLock" = field(default_factory=threading.RLock, repr=False, compare=False)

    def decision_guard(self):
        """Hold the run's lock across a check-then-record sequence."""
        return self._consume_lock

    # --- idempotency: repeated delivery of the same authorization_id ---------------
    def get_stored_decision(self, authorization_id: str) -> StoredDecision | None:
        return self._decisions.get(authorization_id)

    def approved_decisions(self) -> tuple[StoredDecision, ...]:
        """Read-only view of every decision that currently stands as approved.

        Includes step-ups a human later approved, because `record_resolution`
        rewrites the stored decision rather than keeping the answer somewhere
        else. Anything derived from this view therefore cannot miss a
        human-approved purchase, and is persisted for free -- decisions are in
        `to_snapshot`.
        """
        return tuple(d for d in self._decisions.values() if d.decision == "allow")

    def all_decisions(self) -> tuple[StoredDecision, ...]:
        """Read-only view of every recorded decision, whatever it was.

        Used by the audit projection. It is a VIEW, not a second record: callers get
        the same immutable `StoredDecision` objects the ledger holds, so a timeline
        built from this cannot disagree with the ledger it describes.
        """
        return tuple(self._decisions.values())

    def check_repeat_fingerprint(
        self,
        authorization_id: str,
        *,
        merchant_id: str,
        basket_key: BasketKey,
        billing_amount_chf: Decimal,
        timestamp: datetime | None = None,
    ) -> bool:
        """True if a stored decision exists for `authorization_id` AND its
        merchant/basket/amount match what is being re-delivered now -- i.e. this is
        a genuine repeated delivery of the *same* purchase, safe to reconcile
        without re-evaluation. False if the facts differ: a same-ID-different-facts
        "authorization" must never be silently reconciled either as the old
        decision (which was made on different facts) or as a fresh one (which
        would mean submitting a second decision for an ID the platform already
        has one for) -- see `decision_engine.evaluate_authorization`."""
        existing = self._decisions.get(authorization_id)
        if existing is None:
            return True  # nothing to conflict with; not a repeat at all
        # `timestamp` is the SIMULATED PURCHASE TIME -- a property of the purchase, not
        # of the delivery -- so a genuine re-delivery of the same purchase carries the
        # same value and stays a replay. Two DIFFERENT economic transactions do not.
        #
        # Without it, merchant+basket+amount alone let a same-id collision whose facts
        # happened to match read as a legitimate retry: five distinct CHF 100 orders
        # sharing one id were all approved while the rolling window counted CHF 100,
        # exceeding a CHF 300 cap in silence. A collision with DIFFERING facts already
        # failed closed; only the identical-facts case failed open, which is the shape
        # that is hardest to notice.
        #
        # The protocol makes this a defence in depth rather than a live hole: the live
        # id is a RESOURCE ADDRESS -- `POST /v1/authorizations/{authorization_id}/decision`
        # -- so two purchases sharing one would be mutually unaddressable. We no longer
        # depend on that being true.
        if timestamp is not None and existing.timestamp != timestamp:
            return False
        return (
            existing.merchant_id == merchant_id
            and existing.basket_key == basket_key
            and existing.billing_amount_chf == billing_amount_chf
        )

    def record_decision(
        self,
        authorization_id: str,
        decision: Decision,
        billing_amount_chf: Decimal,
        timestamp: datetime,
        *,
        merchant_id: str,
        basket_key: BasketKey,
        reason_codes: tuple[str, ...] = (),
    ) -> StoredDecision:
        # The ledger records WHY, not just what. `StoredDecision.reason_codes` existed
        # but was never populated, so anything reading the record back -- the audit
        # timeline, and the UI after a step-up was answered -- lost every explanation
        # and could only report the bare decision. Found at the final gate.
        if authorization_id in self._decisions:
            return self._decisions[authorization_id]  # never overwrite; first outcome for an ID is final here
        counted = decision == "allow"
        if counted:
            self._approved_spend.append((timestamp, billing_amount_chf))
        stored = StoredDecision(
            authorization_id,
            decision,
            billing_amount_chf,
            timestamp,
            counted,
            merchant_id=merchant_id,
            basket_key=basket_key,
            was_reviewed=(decision == "review"),
            reason_codes=reason_codes,
        )
        self._decisions[authorization_id] = stored
        return stored

    def record_resolution(self, authorization_id: str, final_decision: Decision, resolved_at: datetime) -> StoredDecision:
        """Apply a human's answer to a previously-`review`d authorization. Bound to
        the specific authorization_id it resolves -- it can only change *that*
        authorization's outcome, never the standing mandate (see `mandate.py`).

        Takes no `billing_amount_chf`: the amount that matters is the one the
        customer was actually shown when asked to review, never a value a caller
        could pass in fresh -- see docs/archive/SECOND_ADVERSARIAL_AUDIT.md, "human
        resolution scoped to the wrong facts". The spend-window contribution uses
        the ORIGINAL purchase's *simulated* timestamp (`existing.timestamp`), not
        `resolved_at` (a real-clock time), per technical_details.md: "Use simulated
        purchase time for spending windows, and the real clock for response
        deadlines" -- a step_up answered an hour late must not be attributed to a
        different window than the one it actually occurred in.
        """
        # Under the SAME lock that guards the payment transition. Without it this is
        # a check-then-act: two concurrent answers to one step-up were both accepted,
        # last writer wins, and a purchase the customer DECLINED could end with a live
        # payment authority. Reproduced in 75/4000 uninstrumented trials by an
        # independent audit, which put it well: the file locked the money transition
        # and left the consent transition bare.
        with self._consume_lock:
            return self._record_resolution_locked(authorization_id, final_decision, resolved_at)

    def _record_resolution_locked(
        self, authorization_id: str, final_decision: Decision, resolved_at: datetime
    ) -> StoredDecision:
        existing = self._decisions.get(authorization_id)
        if existing is None:
            raise ResolutionError(f"cannot resolve {authorization_id}: it was never sent to the customer for review")
        if not existing.was_reviewed:
            raise ResolutionError(f"cannot resolve {authorization_id}: it was decided automatically and was never put to the customer")
        if existing.decision != "review":
            # Already resolved once. Treat an identical re-submission (a retried
            # click, a retried API call) as an idempotent success; a DIFFERENT
            # answer than what was already recorded is a genuine conflict, not
            # something to silently ignore or silently overwrite.
            if existing.decision == final_decision:
                return existing
            raise ResolutionError(
                f"{authorization_id} was already resolved as {existing.decision!r}; "
                f"cannot now resolve it as {final_decision!r}"
            )
        if final_decision == "allow":
            self._approved_spend.append((existing.timestamp, existing.billing_amount_chf))
        stored = StoredDecision(
            authorization_id,
            final_decision,
            existing.billing_amount_chf,
            existing.timestamp,
            final_decision == "allow",
            merchant_id=existing.merchant_id,
            basket_key=existing.basket_key,
            was_reviewed=True,
            resolved_at=resolved_at,
            # Keep what the wallet originally said, and add the customer's answer.
            # The reason a purchase was escalated is not erased by the answer to it.
            reason_codes=existing.reason_codes + ("customer_resolution",),
        )
        self._decisions[authorization_id] = stored
        return stored

    # --- rolling-window spend -------------------------------------------------------
    def rolling_spend_chf(self, as_of: datetime, period_days: int) -> Decimal:
        window_start = as_of - timedelta(days=period_days)
        return sum((amt for ts, amt in self._approved_spend if window_start < ts <= as_of), Decimal("0"))

    def peak_window_spend_chf(self, as_of: datetime, amount: Decimal, period_days: int) -> Decimal:
        """The largest rolling window of `period_days` that would contain anything,
        if a purchase of `amount` at `as_of` were approved.

        `rolling_spend_chf` answers a narrower question -- what is in the window that
        ENDS at `as_of` -- and that is the right question only when decisions are made
        in chronological order and none is deferred. The official protocol guarantees
        neither:

          * nothing in the contract orders `/v1/decision-requests/next` by purchase
            time, and the agent chooses what to propose when;
          * `step_up` defers a decision by design, and technical_details.md requires
            that a paused purchase "does not enter approved spend until it is
            resolved" -- at which point it enters at its ORIGINAL simulated timestamp,
            behind decisions already taken against a window that could not see it.

        Following both requirements correctly is exactly what produces the breach:
        measured at CHF 480 against a CHF 300 seven-day cap, with strictly
        chronological delivery and every individual decision locally correct.

        So the bound must hold for EVERY window containing the purchase, not the one
        ending at it. Each approved purchase (and this one) is a candidate window end;
        a window that contains a purchase but ends at no purchase holds no more than
        one that does, so the maxima coincide.

        O(n^2) in the run's approved purchases. The official run is 45 events.
        """
        trial = [*self._approved_spend, (as_of, amount)]
        window = timedelta(days=period_days)
        return max(
            sum((a for ts, a in trial if end - window < ts <= end), Decimal("0"))
            for end, _ in trial
        )

    def earliest_window_retry(self, as_of: datetime, amount: Decimal, period_days: int,
                              cap: Decimal) -> datetime | None:
        """When this exact purchase would first fit inside the rolling window again.

        A customer told "it would take you over the CHF 300 you allowed across any
        7-day period" knows the week is full. They do not know when it stops being
        full. The engine does -- it holds every approved purchase's simulated
        timestamp -- and saying nothing makes the customer guess about their own
        money.

        The window is half-open, `(end - period, end]`, so an approved purchase stops
        counting the instant it is `period_days` old. Those instants are therefore the
        only times the answer can change, which makes this an exact search over at
        most one candidate per approved purchase rather than a scan over time.

        Returns None when waiting cannot help: either the purchase already fits (the
        caller should not be asking), or it is larger than the whole cap, in which
        case no amount of patience is the problem.

        CUSTOMER-FACING ONLY. `agent_view` must never carry this: a retry time plus
        an amount is the window's length and remaining balance, which is the policy
        the agent is not told. `test_agent_explanation_boundary` enforces it.
        """
        if amount > cap:
            return None
        window = timedelta(days=period_days)
        candidates = sorted({ts + window for ts, _ in self._approved_spend if ts + window > as_of})
        for moment in candidates:
            if self.peak_window_spend_chf(moment, amount, period_days) <= cap:
                return moment
        return None

    def total_approved_spend_chf(self) -> Decimal:
        """Cumulative approved spend since the run started -- mirrors the platform's
        `context.approved_spend_in_period_chf`, which technical_details.md says is
        "recomputed from the decisions actually taken in the run" (not a fixed
        window). Mandate-specific rolling windows are evaluated separately via
        `rolling_spend_chf`, not from this figure."""
        return sum((amt for _, amt in self._approved_spend), Decimal("0"))

    def recent_authorizations_context(self, limit: int = 5) -> list[dict]:
        """The last `limit` authorizations seen in this run, in the event schema's
        `context.recent_authorizations` shape, for display/evidence purposes. Status
        reflects the CURRENT stored decision (so a resolved step_up shows as
        approved/declined, not stuck at "pending")."""
        status_map = {"allow": "approved", "block": "declined", "review": "pending"}
        out = []
        for prior in self._recent_attempts[-limit:]:
            current = self._decisions.get(prior.authorization_id)
            status = status_map[current.decision] if current is not None else "pending"
            out.append(
                {
                    "authorization_id": prior.authorization_id,
                    "timestamp": prior.timestamp.isoformat().replace("+00:00", "Z"),
                    "merchant_id": prior.merchant_id,
                    "billing_amount_chf": float(prior.billing_amount_chf),
                    "status": status,
                }
            )
        return out

    # --- similar-recent-purchase (fraud-relevant) duplicate detection ---------------
    def note_observation(self, when: datetime) -> None:
        """Start the clock the first time this state sees a purchase.

        Only meaningful for a resumed-incomplete state; for one that watched the run
        from the beginning there is no horizon to track and `has_observed` says so
        without consulting this.
        """
        if not self.resumed_incomplete:
            return
        if self._observed_from is None:
            self._observed_from = when
        elif when < self._observed_from:
            # THE HORIZON RESTS ON ONE ASSUMPTION: that nothing stamped earlier than
            # the first event this state saw will arrive after it. On the official
            # pack that holds exactly -- `replay_order` agrees with `timestamp` in
            # all five scenarios, 45 of 45 rows -- and it is an observation about
            # data, not a guarantee, so it is CHECKED rather than relied upon.
            #
            # The attack it closes was found against this very mechanism. A cheap
            # purchase stamped eight days in the past, delivered first after a
            # restart, made `_observed_from` old enough that a 7-day ceiling looked
            # fully observed, and the ceiling silently reset:
            #
            #     honest first event   ->  review (the window reaches past the restart)
            #     back-dated by 8 days ->  ALLOW
            #
            # That anchor is derived from `authorization.timestamp`, which the
            # platform authors and the agent cannot choose (`provenance.py` records
            # the measurement). So the attack is not reachable today -- and a control
            # whose soundness depends on an UNDECLARED property of an input is the
            # thing this repository keeps finding. Once ordering is seen to break,
            # this state stops claiming to have observed anything.
            self._ordering_broken = True

    def has_observed(self, as_of: datetime, window: timedelta) -> bool:
        """Has this state seen the whole of `[as_of - window, as_of]`?

        A complete state has, by construction. A resumed one has only once it has
        been watching for longer than the window -- which is what makes the unknown
        TEMPORARY rather than permanent, and is the difference between a control and
        an apology.

        Note what is NOT claimed: this says the state observed the window, not that
        the window is empty. A purchase made before the restart and inside the window
        is exactly what it cannot see, which is why the answer is `unknown` and not
        `false`.
        """
        if not self.resumed_incomplete:
            return True
        if self._observed_from is None or self._ordering_broken:
            return False
        return as_of - window >= self._observed_from

    def find_similar_recent(
        self,
        *,
        authorization_id: str,
        merchant_id: str,
        basket_key: BasketKey,
        billing_amount_chf: Decimal,
        timestamp: datetime,
    ) -> tuple[str, str] | None:
        for prior in reversed(self._recent_attempts):
            if prior.authorization_id == authorization_id:
                continue
            prior_decision = self._decisions.get(prior.authorization_id)
            if prior_decision is not None and prior_decision.decision == "block":
                # A declined attempt -- including one declined only *later*, via a
                # resolved step_up -- is not "an unwanted duplicate order" to worry
                # about. Looked up live rather than from a frozen snapshot, so a
                # review that is subsequently declined stops counting from that
                # point on (see `_RecentAttempt`'s docstring).
                continue
            if prior.merchant_id != merchant_id:
                continue
            if prior.basket_key != basket_key:
                continue
            if abs(timestamp - prior.timestamp) > DUPLICATE_WINDOW:
                continue
            # The amount deliberately does NOT have to match. Requiring it read
            # "similar" as "identical", and a compromised agent evaded the whole
            # check by moving the price one centime (deep-security finding V6).
            # Ordering the same basket from the same merchant minutes later is the
            # unwanted duplicate order whether or not the price moved -- but the
            # reviewer is shown the difference, because "the same thing at a
            # different price" is what they need to judge.
            if prior.billing_amount_chf == billing_amount_chf:
                money = f"and amount (CHF {billing_amount_chf})"
            else:
                money = f"at a different amount (CHF {prior.billing_amount_chf} before, CHF {billing_amount_chf} now)"
            return prior.authorization_id, (
                f"same merchant and basket as {prior.authorization_id} {money}, "
                f"{abs(timestamp - prior.timestamp)} apart"
            )
        return None

    def remember_attempt(
        self,
        *,
        authorization_id: str,
        merchant_id: str,
        basket_key: BasketKey,
        billing_amount_chf: Decimal,
        timestamp: datetime,
    ) -> None:
        self._recent_attempts.append(_RecentAttempt(authorization_id, merchant_id, basket_key, billing_amount_chf, timestamp))

    def observed_attempts_within(self, as_of: datetime, window: timedelta = _VELOCITY_WINDOW) -> int:
        """How many attempts THIS RUN has already seen in the window ending at `as_of`.

        The event carries the platform's own `recent_attempt_count_10m`, and that is
        the authoritative figure -- the platform sees attempts this run never will.
        But it is a claim ABOUT this purchase carried BY this purchase, and the engine
        already refuses to let an event answer questions about itself when an
        independent source exists: `billing_amount_chf` is recomputed from
        `amount x fx_rates`, `items_subtotal + delivery_fee` is checked against
        `amount`, and `card_id`/`mandate_id` are checked against the run. Velocity was
        the one such claim taken on trust, and we hold our own attempt log.

        The current purchase is deliberately not counted: `remember_attempt` runs after
        evaluation, so this returns OTHER attempts, matching what the field means.
        """
        return sum(1 for a in self._recent_attempts if as_of - window < a.timestamp <= as_of)

    # --- session integrity heuristic -------------------------------------------------
    def session_signals(self, device_id: str, recent_attempt_count_10m: int,
                        merchant_familiar: bool | None) -> tuple[bool | None, tuple[str, ...]]:
        """A small, explicit heuristic -- not a model -- so it is auditable and has no
        failure mode when unavailable.

        THREE-VALUED, and it was the one rule in this engine that was not.

        It used to return `risky: bool`, so a signal too weak to condemn came back as
        CLEAN. On the scenario the challenge pack names "Session integrity" that
        meant the engine noticed the device change, wrote
        "device changed from DVC-B73E47 to DVC-4C0E9B" into its own evidence, and
        APPROVED CHF 165 on the hijacker's first purchase. It only caught up two
        purchases later, on velocity, once the burst was already running.

        The customer had written: *"Pause anything that looks like someone other than
        me is driving the session."* They asked to be ASKED. A bare device change is
        exactly "looks like" -- not proof, which is why blocking it would punish every
        ordinary person who moves from phone to laptop, and not nothing either. That
        is what UNKNOWN is for, and `uncertainty_policy` is where the customer already
        told us what to do with it.

            a NEW device, plus velocity      -> True   someone else is driving
            a NEW device on its own          -> None   it looks like someone might be
            back to a device already seen    -> False  weaker still; noted, not raised
            nothing                          -> False

        Returning to a device this run has already seen is deliberately weaker than
        moving to a fresh one: the handset coming back after the laptop is the
        commonest benign pattern in the official data.
        """
        reasons: list[str] = []
        previous = self._last_device_id
        device_changed = previous is not None and device_id != previous
        first_sight = device_id not in self._seen_devices
        if device_changed:
            reasons.append(
                f"device changed from {previous} to {device_id}"
                + ("" if first_sight else " (a device already seen in this run)"))
        if recent_attempt_count_10m >= 2:
            reasons.append(f"{recent_attempt_count_10m} other attempts in the last 10 minutes")
        if merchant_familiar is False and device_changed:
            reasons.append("unfamiliar merchant immediately after a device change")

        self._last_device_id = device_id
        self._seen_devices.add(device_id)

        if (device_changed and recent_attempt_count_10m >= 1) or recent_attempt_count_10m >= 2:
            return True, tuple(reasons)
        if device_changed and first_sight:
            return None, tuple(reasons)
        return False, tuple(reasons)

    # --- verifiable payment authority (R&D Track A) ----------------------------------
    def issue_authority(
        self, authorization_id: str, *, mandate_id: str, policy_version: str, ttl: timedelta = DEFAULT_AUTHORITY_TTL, now: datetime | None = None
    ) -> PaymentAuthority:
        """Stamp an execution lifecycle onto an approved decision and return the
        projection of it.

        Idempotent: if the decision already carries a lifecycle, that one is
        returned unchanged. An authority's window is fixed when first granted and
        is never extended by asking again.
        """
        with self._consume_lock:
            stored = self._decisions.get(authorization_id)
            if stored is None or stored.decision != "allow":
                raise AuthorityError(
                    f"cannot issue a payment authority for {authorization_id}: it is not an approved (allow) decision"
                )
            # Idempotence comes FIRST. Asking again for an authority that already
            # exists must return it -- revoked or not, the projection reports that --
            # and only MINTING a new one after revocation is forbidden. Checking
            # revocation first made a second, harmless request raise instead, which
            # the stateful model found the moment the resolution path started asking
            # again on an already-resolved purchase.
            if stored.execution_expires_at is not None:
                return PaymentAuthority.project(stored)
            if self._revoked_at is not None:
                raise AuthorityError(
                    f"cannot issue a payment authority for {authorization_id}: the customer revoked "
                    f"this mandate at {self._revoked_at.isoformat()}"
                )
            issued_at = now or datetime.now(timezone.utc)
            self._decisions[authorization_id] = replace(
                stored,
                mandate_id=mandate_id,
                policy_version=policy_version,
                execution_issued_at=issued_at,
                execution_expires_at=issued_at + ttl,
            )
            return PaymentAuthority.project(self._decisions[authorization_id])

    def get_authority(self, authorization_id: str) -> PaymentAuthority | None:
        """The projection, derived fresh each time. Never a stored second copy."""
        stored = self._decisions.get(authorization_id)
        return PaymentAuthority.project(stored) if stored is not None else None

    def revoke_authority(self, authorization_id: str) -> PaymentAuthority | None:
        """Invalidate an approved decision's execution lifecycle before it is spent.
        Does not touch the decision itself -- what the engine told the platform is
        history. Idempotent and safe on an authorization with no lifecycle."""
        with self._consume_lock:
            stored = self._decisions.get(authorization_id)
            if stored is None or stored.execution_expires_at is None:
                return None
            self._decisions[authorization_id] = replace(stored, revoked=True)
            return PaymentAuthority.project(self._decisions[authorization_id])

    def consume_authority(self, authorization_id: str, *, executed_at: datetime, now: datetime) -> PaymentAuthority:
        """Atomically validate and spend an authority: a compare-and-set, not a write.

        The validation lives HERE, at the state transition, rather than only in the
        caller. Splitting them is a check-then-act, and the window between the two
        is exactly as wide as whatever work the payment boundary does in between --
        for a real processor, an external call. Two vulnerabilities lived in that
        window (V13, V14):

          * a revocation that landed mid-charge was silently overwritten by the
            consume, so money moved on an authority the customer had already
            revoked; the result was an authority both revoked AND consumed;
          * two threads both passed the caller's `consumed_at is None` check and
            both consumed, executing one authorization twice.

        Neither was reachable when the window was a few bytecodes wide and the GIL
        closed it by luck. Both are trivially reachable once the boundary does real
        work, which is the whole point of a payment boundary.

        `now` is the TRUSTED clock reading supplied by the boundary and is what
        expiry is judged on. `executed_at` only timestamps the record, and may be a
        caller-supplied value -- it must never decide whether the authority is still
        valid (that was V4).

        The lock makes this atomic within one process. It does NOT make it atomic
        across processes: two workers restoring the same checkpoint hold separate
        `RunState` objects and separate locks, and each will consume once. Closing
        that needs a single shared store with an atomic compare-and-set; see
        docs/DISTRIBUTED_PAYMENT_BOUNDARY.md for the exact boundary and the minimum
        primitive it would take.
        """
        with self._consume_lock:
            existing = self._decisions.get(authorization_id)
            if existing is None or existing.execution_expires_at is None:
                raise AuthorityError(f"{authorization_id} has no payment authority to consume")
            if existing.consumed_at is not None:
                raise AuthorityError(
                    f"{authorization_id} was already executed at {existing.consumed_at.isoformat()}; "
                    "refusing a second execution"
                )
            if existing.revoked:
                raise AuthorityError(f"the payment authority for {authorization_id} has been revoked; refusing to consume")
            if now > existing.execution_expires_at:
                raise AuthorityError(
                    f"the payment authority for {authorization_id} expired at "
                    f"{existing.execution_expires_at.isoformat()}; refusing to consume an expired authority"
                )
            self._decisions[authorization_id] = replace(existing, consumed_at=executed_at)
            return PaymentAuthority.project(self._decisions[authorization_id])

    @property
    def is_revoked(self) -> bool:
        return self._revoked_at is not None

    def revoke_outstanding_authorities(self, *, now: datetime | None = None) -> tuple[str, ...]:
        """Revoke every still-valid authority in this run, returning the
        authorization_ids actually revoked. Called when the customer revokes the
        mandate: money that has been authorized but not yet spent must stop.

        It also records the revocation at RUN level, so that a purchase still waiting
        for the customer -- which has no lifecycle yet, and so nothing to sweep --
        cannot acquire one afterwards. Without that, the emergency brake missed
        exactly the purchase the customer had been asked about.

        This is about our own synthetic capability object, not about official
        decision semantics: technical_details.md leaves the effect of revocation
        on already-queued authorizations unspecified, and this code does not
        invent a guarantee there -- `StoredDecision` records are untouched, so
        what the engine already told the platform stays exactly as it was. What
        changes is only whether money that has NOT yet moved may still move. For
        a customer's emergency brake, fail-closed is the only defensible default.

        There is deliberately no "revoke only the authorities minted under an
        older policy version" variant: a run is bound to one mandate snapshot
        taken at run start (both `api.py` and `live_worker.py` build it once per
        run_id, per technical_details.md "An existing run keeps its original
        snapshot"), and authorities live inside one `RunState`, so a policy
        version cannot change underneath an outstanding authority. That variant
        would be an unreachable branch, and `policy_version` on the authority is
        therefore provenance -- what it was minted under -- not an enforced
        binding. See docs/archive/FINAL_ARCHITECTURE_ATTACK.md for the full analysis.
        """
        with self._consume_lock:
            # Record the run-level fact FIRST: if anything below were to fail, a run
            # marked revoked that swept nothing is safe, while a run that swept
            # records but forgot it was revoked is the bug this fixes.
            self._revoked_at = now or datetime.now(timezone.utc)
            revoked: list[str] = []
            for authorization_id, stored in list(self._decisions.items()):
                if stored.execution_expires_at is None or stored.revoked:
                    continue
                self._decisions[authorization_id] = replace(stored, revoked=True)
                revoked.append(authorization_id)
            return tuple(revoked)

    # --- crash-recovery snapshot -----------------------------------------------------
    # `RunState` otherwise lives only in process memory (see docs/ARCHITECTURE.md,
    # "State and concurrency"). That is fine while the worker runs continuously, but
    # a process crash mid-run would otherwise forget every prior decision, approved
    # spend, and duplicate-detection fingerprint -- risking both a duplicate
    # decision submission AND, more seriously, a rolling-window spending limit
    # being silently bypassed because the run "forgot" what it had already
    # approved. This is a deliberately small, single-file JSON snapshot -- not a
    # database -- written by `live_worker.py` after every decision, so the SAME
    # process restarting can resume correctly. It does NOT reconcile against the
    # platform's own authoritative state (see `live_worker.LiveWorker.reconcile_run`
    # for that best-effort, separate mechanism) -- see
    # docs/archive/SECOND_ADVERSARIAL_AUDIT.md for the residual limitation this leaves.
    def to_snapshot(self) -> dict:
        return {
            "card_id": self.card_id,
            "last_device_id": self._last_device_id,
            "revoked_at": self._revoked_at.isoformat() if self._revoked_at else None,
            "decisions": [
                {
                    "authorization_id": d.authorization_id,
                    "decision": d.decision,
                    "billing_amount_chf": str(d.billing_amount_chf),
                    "timestamp": d.timestamp.isoformat(),
                    "counted_in_spend": d.counted_in_spend,
                    "merchant_id": d.merchant_id,
                    "basket_key": list(d.basket_key),
                    "was_reviewed": d.was_reviewed,
                    "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
                    "reason_codes": list(d.reason_codes),
                    # The execution lifecycle rides WITH the decision. It used to be
                    # a separate "authorities" array; one record cannot fall out of
                    # step with itself.
                    "mandate_id": d.mandate_id,
                    "policy_version": d.policy_version,
                    "execution_issued_at": d.execution_issued_at.isoformat() if d.execution_issued_at else None,
                    "execution_expires_at": d.execution_expires_at.isoformat() if d.execution_expires_at else None,
                    "revoked": d.revoked,
                    "consumed_at": d.consumed_at.isoformat() if d.consumed_at else None,
                }
                for d in self._decisions.values()
            ],
            "approved_spend": [[ts.isoformat(), str(amt)] for ts, amt in self._approved_spend],
            "recent_attempts": [
                {
                    "authorization_id": a.authorization_id,
                    "merchant_id": a.merchant_id,
                    "basket_key": list(a.basket_key),
                    "billing_amount_chf": str(a.billing_amount_chf),
                    "timestamp": a.timestamp.isoformat(),
                }
                for a in self._recent_attempts
            ],
        }

    # Every key `to_snapshot` writes. Absence of any of them is a refusal, not a
    # default: `_SNAPSHOT_KEYS` and `_DECISION_KEYS` are checked against what
    # `to_snapshot` actually produces by `test_checkpoint_absence.py`, so the two
    # cannot drift apart.
    _SNAPSHOT_KEYS = ("card_id", "last_device_id", "revoked_at", "decisions",
                      "approved_spend", "recent_attempts")
    _DECISION_KEYS = ("authorization_id", "decision", "billing_amount_chf", "timestamp",
                      "counted_in_spend", "merchant_id", "basket_key", "was_reviewed",
                      "resolved_at", "reason_codes", "mandate_id", "policy_version")
    # THE EXECUTION LIFECYCLE IS ALL-OR-NOTHING, and the difference between its two
    # kinds of absence is the whole finding.
    #
    #   all four missing  -- a decision that was never issued an authority. A
    #                        coherent fact, written by an older two-record build,
    #                        and it restores with no authority to spend. Safe, and
    #                        `test_an_old_checkpoint_without_lifecycle_fails_closed`
    #                        has documented it since that build existed.
    #   SOME missing      -- a decision claiming an authority while omitting whether
    #                        it was spent or revoked. Not a fact; a hole. Measured:
    #                        drop `consumed_at` alone and a spent authority becomes
    #                        spendable again; drop `revoked` alone and a revoked one
    #                        comes back live.
    _LIFECYCLE_KEYS = ("execution_issued_at", "execution_expires_at", "revoked",
                       "consumed_at")
    _ATTEMPT_KEYS = ("authorization_id", "merchant_id", "basket_key",
                     "billing_amount_chf", "timestamp")

    @staticmethod
    def _require(mapping: dict, keys: tuple[str, ...], where: str) -> None:
        """PRESENCE, not truthiness. `consumed_at: null` is a fact -- this authority
        has not been spent -- and must restore. A MISSING `consumed_at` is not that
        fact; it is the absence of one, and the two used to be the same thing."""
        missing = [k for k in keys if k not in mapping]
        if missing:
            raise CheckpointError(
                f"checkpoint {where} is missing {', '.join(missing)}. These are not "
                f"defaulted: every one of their defaults would make money more "
                f"spendable than the checkpoint recorded.")

    @classmethod
    def from_snapshot(cls, snapshot: dict, history: HistoryIndex) -> "RunState":
        cls._require(snapshot, cls._SNAPSHOT_KEYS, "root")
        # A checkpoint that EXISTS carries a complete ledger, so prior spend is known.
        # `prior_spend_known` is deliberately not read from the file: the flag is a
        # statement about whether this process could restore the run, not a fact the
        # file gets to assert about itself.
        state = cls(history=history, card_id=snapshot["card_id"])
        state._last_device_id = snapshot["last_device_id"]
        revoked_at = snapshot["revoked_at"]
        state._revoked_at = datetime.fromisoformat(revoked_at) if revoked_at else None
        for d in snapshot["decisions"]:
            where = f"decision {d.get('authorization_id', '<unnamed>')!r}"
            cls._require(d, cls._DECISION_KEYS, where)
            present = [k for k in cls._LIFECYCLE_KEYS if k in d]
            if present and len(present) != len(cls._LIFECYCLE_KEYS):
                cls._require(d, cls._LIFECYCLE_KEYS, f"{where} (partial execution lifecycle)")
            state._decisions[d["authorization_id"]] = StoredDecision(
                authorization_id=d["authorization_id"],
                decision=d["decision"],
                billing_amount_chf=Decimal(d["billing_amount_chf"]),
                timestamp=datetime.fromisoformat(d["timestamp"]),
                counted_in_spend=d["counted_in_spend"],
                merchant_id=d["merchant_id"],
                basket_key=tuple(tuple(pair) for pair in d["basket_key"]),
                was_reviewed=d["was_reviewed"],
                resolved_at=datetime.fromisoformat(d["resolved_at"]) if d["resolved_at"] else None,
                reason_codes=tuple(d["reason_codes"]),
                mandate_id=d["mandate_id"],
                policy_version=d["policy_version"],
                # `.get` here ONLY because the four are checked together above: either
                # all are present, or none are and this decision never had a lifecycle.
                execution_issued_at=datetime.fromisoformat(d["execution_issued_at"]) if d.get("execution_issued_at") else None,
                execution_expires_at=datetime.fromisoformat(d["execution_expires_at"]) if d.get("execution_expires_at") else None,
                revoked=d.get("revoked", False),
                consumed_at=datetime.fromisoformat(d["consumed_at"]) if d.get("consumed_at") else None,
            )
        state._approved_spend = [(datetime.fromisoformat(ts), Decimal(amt)) for ts, amt in snapshot["approved_spend"]]
        for a in snapshot["recent_attempts"]:
            cls._require(a, cls._ATTEMPT_KEYS,
                         f"recent attempt {a.get('authorization_id', '<unnamed>')!r}")
        state._recent_attempts = [
            _RecentAttempt(
                authorization_id=a["authorization_id"],
                merchant_id=a["merchant_id"],
                basket_key=tuple(tuple(pair) for pair in a["basket_key"]),
                billing_amount_chf=Decimal(a["billing_amount_chf"]),
                timestamp=datetime.fromisoformat(a["timestamp"]),
            )
            for a in snapshot["recent_attempts"]
        ]
        return state
