"""The stage: one run of a scenario, told as it happens, for two screens at once.

`ui/stage.html` shows the customer's phone next to the stream of purchases the agent
proposes. This module is the server side of that page. It decides nothing itself:
every purchase goes through `evaluate_authorization`, every answer through
`resolve_authorization`, exactly as in `api.py` and `live_worker.py`. What it adds
is pacing (one purchase at a time, so a presenter can talk over each one) and a
display card per decision.

Two modes, one event list:

    replay   the official scenario rows, built into official-schema events and
             judged locally. No network, no key, identical every time. The page's
             safety net.
    live     the same scenario started on the hosted Viseca sandbox. A LiveWorker
             thread polls, decides and submits; the customer's answers go back
             through /resolve. Needs TEAM_API_KEY and LEASH_BASE_URL in the server's
             environment; the key never reaches the page.

Everything in a card beyond the engine's own output is EXPLANATION ONLY and cannot
change a decision: which sentence of a seller's text was written for a machine,
which known shop a new one resembles, how much of a rolling limit is used.
"""

from __future__ import annotations

import difflib
import itertools
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable

from .csv_data import _read_csv, load_merchants, load_purchase_attempt_items, load_scenario_catalogue, scenario_rows
from .decision_engine import EngineDecision, evaluate_authorization, resolve_authorization
from .facts import _INJECTION_PATTERNS, _normalize_untrusted_text
from .mandate import HardRule, Mandate, MandateSnapshot, MandateStatus, UncertaintyPolicy
from .offline_replay import build_event, compile_and_confirm_mandate_for_scenario
from .policy_compiler import compile_instruction
from .state import HistoryIndex, RunState
from .viseca_mapping import to_wire_evidence

logger = logging.getLogger("wallet_control.stage")

# The hosted platform gives the customer this long to answer a step-up
# (bootstrap `limits.step_up_timeout_seconds`); the replay mirrors it.
STEP_UP_SECONDS = 120
_MAX_SESSIONS = 24


# ------------------------------------------------------------------ explanations

_SENTENCE_RE = re.compile(r"[^.!?]+(?:[.!?]+|$)")


def machine_directed_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges of the sentences in a seller's text that match one of the
    wallet's machine-directed patterns (`facts._INJECTION_PATTERNS`).

    For DISPLAY: the page strikes these through inside a box labelled as the
    seller's words. They never enter `customer_message`, which is built from the
    engine's own sentences and says only that someone tried. Offsets are into the
    text as sent; a sentence only counts when the pattern matches it after the same
    normalisation the engine applies.
    """
    spans = []
    for match in _SENTENCE_RE.finditer(text or ""):
        sentence = match.group(0)
        normalised = _normalize_untrusted_text(sentence)
        if any(p.search(normalised) for _, p in _INJECTION_PATTERNS):
            start = match.start() + (len(sentence) - len(sentence.lstrip()))
            spans.append((start, match.end()))
    return spans


def _squash(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def lookalike_of(merchant_name: str, known_names: list[str], *, threshold: float = 0.85) -> str | None:
    """The known shop this unknown one is named almost like, if any.

    Explanation only: the purchase is already judged on the merchant's identity,
    which a name cannot fake. This says WHY a new shop at a familiar-sounding name
    deserves a second look ("PixelHarbour" is not "PixelHarbor").
    """
    target = _squash(merchant_name)
    best, best_ratio = None, 0.0
    for name in known_names:
        other = _squash(name)
        if not other or other == target:
            continue
        ratio = difflib.SequenceMatcher(None, target, other).ratio()
        if ratio > best_ratio:
            best, best_ratio = name, ratio
    return best if best_ratio >= threshold else None


def rule_label(rule: HardRule) -> str:
    """One short line per rule for the phone. The full wording lives in the lab."""
    v = rule.value
    if rule.field == "authorization.billing_amount_chf":
        if rule.scope == "period":
            return f"At most CHF {float(v):,.0f} in any {rule.period_days} days"
        return f"At most CHF {float(v):,.0f} per order"
    return {
        "merchant.familiar": "Only shops you have paid before",
        "merchant.category": f"Only {', '.join(v) if isinstance(v, list) else v} shops",
        "item.category": f"Only {', '.join(v) if isinstance(v, list) else v}",
        "item.name_contains": f"Only the item you named ({v})",
        "item.size": f"Size {v} only",
        "item.unrequested_present": "Nothing you did not ask for",
        "order.return_window_days": f"Returnable within {v} days",
        "session.integrity_risk": "Pause if someone else seems to be driving",
    }.get(rule.field, rule.field.replace(".", " ").replace("_", " "))


_CLAUSE_RE = re.compile(r"(?<=[.,;])\s+")


def leash_field(instruction: str, familiar: frozenset[str] | None = None) -> dict[str, Any]:
    """The sentence, clause by clause, and what each prefix authorises.

    Every basket this catalogue can produce (`scope._world`) goes through the real
    engine for each cumulative prefix of the sentence, so the page can show purchases
    falling away as the customer's words arrive. One world for every step: the one
    the WHOLE sentence is about, so the dots are the same baskets throughout.
    `familiar` is the shops the customer on screen has really paid; without it, the
    scope panel's demo card.
    """
    from .scope import FAMILIAR, _categories, _world
    from .witness import judge_event, snapshot as witness_snapshot

    category = _categories(list(compile_instruction(instruction).hard_rules))
    world = _world(category)
    clauses = [c for c in _CLAUSE_RE.split(instruction.strip()) if c]
    steps = []
    for n in range(1, len(clauses) + 1):
        text = " ".join(clauses[:n])
        compiled = compile_instruction(text)
        mandate = witness_snapshot(list(compiled.hard_rules), compiled.uncertainty_policy,
                                   list(compiled.unsupported_restrictions))
        verdicts = "".join(
            {"allow": "a", "review": "q"}.get(
                judge_event(mandate, i, merchant, category, combo,
                            familiar=FAMILIAR if familiar is None else familiar), "r")
            for i, (merchant, combo) in enumerate(world))
        steps.append({"text": text, "added": clauses[n - 1], "verdicts": verdicts,
                      "allow": verdicts.count("a"), "ask": verdicts.count("q"),
                      "refuse": verdicts.count("r")})
    return {"category": category, "universe": len(world), "steps": steps}


_POLICY_LABEL = {UncertaintyPolicy.ASK: "Ask me", UncertaintyPolicy.DECLINE: "Decline",
                 UncertaintyPolicy.APPROVE: "Approve"}


def leash(mandate: MandateSnapshot) -> dict[str, Any]:
    return {
        "instruction": mandate.instruction,
        "rules": [rule_label(r) for r in mandate.hard_rules],
        "when_unsure": _POLICY_LABEL.get(mandate.uncertainty_policy, str(mandate.uncertainty_policy)),
        "card": (mandate.card_id or "")[-4:],
    }


def _window(mandate: MandateSnapshot, state: RunState, at: datetime) -> dict[str, Any] | None:
    period = next((r for r in mandate.hard_rules
                   if r.field == "authorization.billing_amount_chf" and r.scope == "period"), None)
    if period is None:
        return None
    since = at - timedelta(days=period.period_days or 0)
    spent = sum((d.billing_amount_chf for d in state.approved_decisions()
                 if since < d.timestamp <= at), Decimal("0"))
    return {"limit": float(period.value), "days": period.period_days, "spent": float(spent)}


def _customer_name(card_id: str | None) -> str | None:
    try:
        accounts = {r["account_id"]: r["customer_id"] for r in _read_csv("accounts.csv")}
        cards = {r["card_id"]: r["account_id"] for r in _read_csv("cards.csv")}
        names = {r["customer_id"]: r["persona_name"] for r in _read_csv("customers.csv")}
        return names.get(accounts.get(cards.get(card_id or "", ""), ""))
    except (OSError, KeyError):
        return None


def decision_card(event: dict[str, Any], result: EngineDecision, mandate: MandateSnapshot,
                  state: RunState, history: HistoryIndex) -> dict[str, Any]:
    """What the stream shows for one decided purchase."""
    auth = event["authorization"]
    at = datetime.fromisoformat(str(auth["timestamp"]).replace("Z", "+00:00"))
    lines = []
    for line in auth.get("items") or []:
        details = line.get("item_details") or ""
        lines.append({"name": line.get("item_name"), "qty": line.get("quantity"),
                      "price": line.get("unit_price"), "details": details,
                      "machine": machine_directed_spans(details)})

    lookalike = None
    merchant_id = auth["merchant"]["merchant_id"]
    if history.is_familiar(mandate.card_id or "", merchant_id) is False:
        merchants = _merchant_names()
        known = [merchants[m] for m in history.known_merchants(mandate.card_id or "") if m in merchants]
        lookalike = lookalike_of(auth["merchant"]["merchant_name"], known)

    return {
        "authorization_id": result.authorization_id,
        "ref": auth.get("source_authorization_id") or result.authorization_id,
        "at": at.isoformat(),
        "merchant": auth["merchant"]["merchant_name"],
        "amount": float(auth["billing_amount_chf"]),
        "lines": lines,
        "verdict": result.decision,
        "reasons": list(result.plain_reasons),
        "message": result.customer_message,
        "your_rules": result.policy_verdict,
        "wallet_checks": result.security_verdict,
        "lookalike": lookalike,
        "window": _window(mandate, state, at),
        "retry_at": result.earliest_retry_at.isoformat() if result.earliest_retry_at else None,
        "evidence": to_wire_evidence(result.rule_evaluations),
    }


_MERCHANT_NAMES: dict[str, str] | None = None


def _merchant_names() -> dict[str, str]:
    global _MERCHANT_NAMES
    if _MERCHANT_NAMES is None:
        _MERCHANT_NAMES = {m: row["merchant_name"] for m, row in load_merchants().items()}
    return _MERCHANT_NAMES


# ------------------------------------------------------------------------ sessions

@dataclass
class StageSession:
    session_id: str
    mode: str
    scenario_id: str
    scenario_name: str
    mandate: MandateSnapshot
    history: HistoryIndex
    customer: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    _seq: Any = field(default_factory=lambda: itertools.count(1))
    # authorization_id -> monotonic deadline for an unanswered step-up
    asking: dict[str, float] = field(default_factory=dict)
    finished: bool = False
    revoked: bool = False

    def emit(self, kind: str, **data: Any) -> dict[str, Any]:
        with self.lock:
            record = {"seq": next(self._seq), "kind": kind,
                      "at": datetime.now(timezone.utc).isoformat(), **data}
            self.events.append(record)
            return record

    def since(self, seq: int) -> list[dict[str, Any]]:
        with self.lock:
            self._expire_asks()
            return [e for e in self.events if e["seq"] > seq]

    def _expire_asks(self) -> None:
        now = time.monotonic()
        for authorization_id, deadline in list(self.asking.items()):
            if now >= deadline:
                del self.asking[authorization_id]
                self.emit("expired", authorization_id=authorization_id,
                          text="No answer in time. The platform declines it.")

    def _asked(self, card: dict[str, Any]) -> None:
        if card["verdict"] == "review":
            self.asking[card["authorization_id"]] = time.monotonic() + STEP_UP_SECONDS
            card["ask_seconds"] = STEP_UP_SECONDS

    def summary(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "mode": self.mode, "scenario_id": self.scenario_id,
                "scenario_name": self.scenario_name, "customer": self.customer,
                "leash": leash(self.mandate), "finished": self.finished, "revoked": self.revoked}


class ReplaySession(StageSession):
    """The official scenario, one purchase per `advance()`."""

    def __init__(self, scenario_id: str, history: HistoryIndex) -> None:
        catalogue = load_scenario_catalogue()[scenario_id]
        self._mandate_obj: Mandate = compile_and_confirm_mandate_for_scenario(scenario_id)
        snapshot = self._mandate_obj.snapshot()
        super().__init__(session_id=f"stage_{uuid.uuid4().hex[:10]}", mode="replay",
                         scenario_id=scenario_id, scenario_name=catalogue["scenario_name"],
                         mandate=snapshot, history=history, customer=_customer_name(snapshot.card_id))
        self.state = RunState(history=history, card_id=snapshot.card_id)
        self._rows = list(scenario_rows(scenario_id))
        self._items = load_purchase_attempt_items()
        self._merchants = load_merchants()
        self._events_by_id: dict[str, dict[str, Any]] = {}
        self.emit("started", text=f"{len(self._rows)} purchases queued. Replaying the official scenario locally.",
                  total=len(self._rows))

    def remaining(self) -> int:
        return len(self._rows)

    def advance(self) -> dict[str, Any]:
        """Judge the next purchase. Refused while the customer is still being asked,
        as on the platform, which queues the next purchase behind an open step-up."""
        with self.lock:
            self._expire_asks()
            if self.asking:
                return {"waiting_for": sorted(self.asking)}
            if not self._rows:
                if not self.finished:
                    self.finished = True
                    self.emit("finished", text="The agent has nothing more to propose.")
                return {"finished": True}
            row = self._rows.pop(0)
            context = {"approved_spend_in_period_chf": float(self.state.total_approved_spend_chf()),
                       "recent_authorizations": self.state.recent_authorizations_context()}
            event = build_event(row, self._items[row["authorization_id"]],
                                self._merchants[row["merchant_id"]], self.mandate, context)
            result = evaluate_authorization(event, self.mandate, self.state)
            self._events_by_id[result.authorization_id] = event
            card = decision_card(event, result, self.mandate, self.state, self.history)
            self._asked(card)
            return self.emit("decision", card=card, remaining=len(self._rows))

    def resolve(self, authorization_id: str, decision: str) -> dict[str, Any]:
        with self.lock:
            self._expire_asks()
            if authorization_id not in self.asking:
                raise ValueError(f"{authorization_id} is not waiting for an answer")
            result = resolve_authorization(authorization_id, decision, self.state,
                                           resolved_at=datetime.now(timezone.utc),
                                           mandate=self.mandate)
            del self.asking[authorization_id]
            card = decision_card(self._events_by_id[authorization_id], result, self.mandate,
                                 self.state, self.history)
            return self.emit("resolved", authorization_id=authorization_id, decision=decision, card=card)

    def revoke(self) -> dict[str, Any]:
        with self.lock:
            self._mandate_obj.revoke()
            killed = self.state.revoke_outstanding_authorities()
            self.revoked = True
            return self.emit("revoked", cancelled=list(killed),
                             text="Mandate revoked. Unspent approvals are cancelled; nothing new can be approved.")


class LiveSession(StageSession):
    """The same scenario on the hosted sandbox, driven by a LiveWorker thread."""

    def __init__(self, scenario_id: str, history: HistoryIndex, *, base_url: str, api_key: str,
                 client_factory: Callable[[str, str], Any] | None = None,
                 acknowledge_unsupported: bool = False) -> None:
        from .live_worker import LiveWorker
        from .viseca_client import VisecaClient

        catalogue = load_scenario_catalogue()[scenario_id]
        instruction = catalogue["cardholder_instruction"]
        compiled = compile_instruction(instruction)
        if compiled.unsupported_restrictions and not acknowledge_unsupported:
            raise PermissionError("; ".join(compiled.unsupported_restrictions))
        self._client = (client_factory or VisecaClient)(base_url, api_key)
        draft = self._client.create_mandate_draft(
            instruction, [r.as_dict() for r in compiled.hard_rules], compiled.uncertainty_policy.value,
            compiled.guidance, compiled.open_questions)
        self.mandate_id = self._client.confirm_mandate(draft["draft_id"])["mandate_id"]
        self.run_id = self._client.start_scenario_run(scenario_id, self.mandate_id)["run_id"]
        # What the phone shows until the first event brings the platform's own ids.
        provisional = MandateSnapshot(
            mandate_id=self.mandate_id, status=MandateStatus.ACTIVE,
            customer_id=None, card_id=None, profile_id=None, instruction=instruction,
            hard_rules=tuple(compiled.hard_rules), uncertainty_policy=compiled.uncertainty_policy)
        super().__init__(session_id=f"stage_{uuid.uuid4().hex[:10]}", mode="live",
                         scenario_id=scenario_id, scenario_name=catalogue["scenario_name"],
                         mandate=provisional, history=history)
        self._worker = LiveWorker(self._client, history, confirmed_rules=compiled.hard_rules,
                                  confirmed_uncertainty_policy=compiled.uncertainty_policy,
                                  on_decision=self._on_decision)
        self._stop = threading.Event()
        self.emit("started", text=f"Run {self.run_id} started on the Viseca sandbox.", run_id=self.run_id)
        self._thread = threading.Thread(target=self._poll, name=f"stage-{self.session_id}", daemon=True)
        self._thread.start()

    def _on_decision(self, run_id: str, result: EngineDecision, event: dict[str, Any], state: RunState) -> None:
        mandate = MandateSnapshot.from_event_mandate(event["mandate"])
        with self.lock:
            if self.customer is None:
                self.mandate = mandate
                self.customer = _customer_name(mandate.card_id)
            card = decision_card(event, result, mandate, state, self.history)
            self._asked(card)
            self.emit("decision", card=card)

    def _poll(self) -> None:
        idle = 0
        while not self._stop.is_set():
            try:
                handled = self._worker.run_forever(wait_seconds=10, max_polls=1)
                if handled:
                    idle = 0
                    continue
                idle += 1
                status = self._client.get_run(self.run_id)
                if status.get("status") == "completed" or idle >= 30:
                    break
            except Exception as exc:          # noqa: BLE001 -- shown on the page, the loop ends
                logger.exception("stage live session %s", self.session_id)
                self.emit("error", text=f"The live run stopped: {type(exc).__name__}.")
                break
        with self.lock:
            self.finished = True
            self.emit("finished", text="The platform has nothing more to send.")

    def resolve(self, authorization_id: str, decision: str) -> dict[str, Any]:
        with self.lock:
            self._expire_asks()
            if authorization_id not in self.asking:
                raise ValueError(f"{authorization_id} is not waiting for an answer")
            del self.asking[authorization_id]
        result = self._worker.resolve(self.run_id, authorization_id, decision)
        return self.emit("resolved", authorization_id=authorization_id, decision=decision,
                         card={"authorization_id": authorization_id, "verdict": result.decision})

    def revoke(self) -> dict[str, Any]:
        killed = self._worker.revoke_run(self.run_id) if self.customer is not None else ()
        try:
            self._client.revoke_mandate(self.mandate_id)
        except Exception as exc:              # noqa: BLE001 -- local revocation already holds
            logger.warning("revoking %s on the platform failed: %s", self.mandate_id, exc)
        self.revoked = True
        return self.emit("revoked", cancelled=list(killed),
                         text="Mandate revoked on the platform. Unspent approvals are cancelled.")

    def stop(self) -> None:
        self._stop.set()


# ------------------------------------------------------------------------ registry

_SESSIONS: dict[str, StageSession] = {}
_REGISTRY_LOCK = threading.Lock()


def live_configuration() -> tuple[str, str] | None:
    base_url, key = os.environ.get("LEASH_BASE_URL"), os.environ.get("TEAM_API_KEY")
    return (base_url, key) if base_url and key else None


def register(session: StageSession) -> StageSession:
    with _REGISTRY_LOCK:
        _SESSIONS[session.session_id] = session
        while len(_SESSIONS) > _MAX_SESSIONS:
            oldest = next(iter(_SESSIONS))
            stale = _SESSIONS.pop(oldest)
            if isinstance(stale, LiveSession):
                stale.stop()
    return session


def get(session_id: str) -> StageSession | None:
    return _SESSIONS.get(session_id)
