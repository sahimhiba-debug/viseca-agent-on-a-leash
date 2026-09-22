"""When a sentence has two defensible readings, find the purchase that separates them.

The compiler already detects ambiguity and explains it in prose: "the instruction
mentions more than one per-order amount; the smallest was used defensively". That
is honest and nearly useless, because it asks the customer to imagine a
consequence. People do not audit prose about hypothetical purchases; they agree to
it.

So do not describe the ambiguity. **Find the purchase it changes.** Compile the
sentence twice -- once as the compiler read it, once as the other defensible
reading -- and search for a basket the two policies judge differently. That basket
is a witness: concrete proof the sentence is underdetermined, and the only question
a customer can actually answer.

    "Order groceries, under CHF 120."
        as compiled      CHF 120.00 is too much   -> BLOCK
        also defensible  CHF 120.00 is fine       -> ALLOW
        WITNESS: a basket costing exactly CHF 120.00

THIS MODULE DECIDES NOTHING. It is advisory, like the compiler's open questions,
and it lives in the runtime for the same reason they do: it is shown to the
customer before they confirm. Every verdict it reports comes from the real engine
deciding a real event -- if it inspected rules instead, it would prove nothing
about what the wallet would actually do.

THE PROPERTY THAT MATTERS MOST IS THE SILENCE. A disambiguator that fires on clear
language teaches people to click through it, and then it protects nobody. "at or
below CHF 120" is not ambiguous and this module says nothing about it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .decision_engine import evaluate_authorization
from .mandate import HardRule, Mandate, MandateSnapshot, UncertaintyPolicy
from .policy_compiler import compile_instruction
from .state import HistoryIndex, RunState

_MERCHANT = "ME_WITNESS"
_CARD = "CA_WITNESS"
_AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class Reading:
    """One defensible interpretation, as a transformation of the compiled rules."""

    key: str
    question: str
    labels: Callable[[list[HardRule]], tuple[str, str]]
    transform: Callable[[list[HardRule]], list[HardRule] | None]
    applies: Callable[[str], bool] | None = None


def _flip_strictness(rules):
    out, changed = [], False
    for rule in rules:
        if (rule.field == "authorization.billing_amount_chf" and rule.scope == "purchase"
                and rule.operator in ("<", "<=")):
            out.append(replace(rule, operator="<=" if rule.operator == "<" else "<"))
            changed = True
        else:
            out.append(rule)
    return out if changed else None


def _period_as_per_order(rules):
    out, changed = [], False
    for rule in rules:
        if rule.field == "authorization.billing_amount_chf" and rule.scope == "period":
            out.append(replace(rule, scope="purchase", period_days=None))
            changed = True
        else:
            out.append(rule)
    return out if changed else None


def _strictness_labels(rules):
    operator = next((r.operator for r in rules
                     if r.field == "authorization.billing_amount_chf"
                     and r.scope == "purchase"), "<=")
    strict, inclusive = "the amount itself is too much", "the amount itself is fine"
    return (strict, inclusive) if operator == "<" else (inclusive, strict)


# "at or below", "or less" and "no more than" all say plainly that the amount is
# included. Asking about them is crying wolf.
_VAGUE_BOUND = re.compile(r"\b(?:under|below|less\s+than)\b", re.IGNORECASE)
_EXPLICIT_BOUND = re.compile(
    r"\b(?:at\s+or\s+below|or\s+less|at\s+most|no\s+more\s+than|up\s+to)\b", re.IGNORECASE)


def _bound_is_vague(instruction: str) -> bool:
    return bool(_VAGUE_BOUND.search(instruction)) and not _EXPLICIT_BOUND.search(instruction)


READINGS: tuple[Reading, ...] = (
    Reading("strictness",
            "Is an order of exactly that amount allowed, or must it be below?",
            _strictness_labels, _flip_strictness, _bound_is_vague),
    Reading("period_scope",
            "Is that a budget for the week, or a ceiling for each order?",
            lambda _r: ("a rolling budget for the period", "a ceiling on each order"),
            _period_as_per_order),
    # A reading that separates EVERY sentence is not a reading. "Did naming the
    # goods restrict what may be bought, or only describe it?" did exactly that and
    # was deleted: "order our household groceries" plainly restricts to groceries.
)


def _snapshot(rules: list[HardRule], uncertainty: UncertaintyPolicy,
              unsupported: list[str] | None = None) -> MandateSnapshot:
    """A throwaway mandate for judging one hypothetical purchase.

    Nobody confirms this; it exists for the length of a decision. It still carries
    the compiled `unsupported_restrictions` and acknowledges them, because the
    anti-rot test that enforces that plumbing caught this module the moment it was
    written -- and a candidate reading built from a different policy than the real
    one would be measuring the wrong thing anyway.
    """
    unsupported = list(unsupported or [])
    mandate = Mandate.draft("candidate reading", list(rules), uncertainty,
                            None, None, unsupported)
    mandate.confirm(confirmed=True, customer_id="CU_WITNESS", card_id=_CARD,
                    profile_id="PR_WITNESS",
                    acknowledged_unsupported=tuple(unsupported))
    return mandate.snapshot()


def _event(snapshot: MandateSnapshot, index: int, amount: float, category: str) -> dict[str, Any]:
    when = _AT + timedelta(hours=index * 6)
    stamp = when.isoformat().replace("+00:00", "Z")
    return {
        "type": "authorization.request", "request_id": f"req_w{index}",
        "deadline_at": (when + timedelta(seconds=8)).isoformat().replace("+00:00", "Z"),
        "authorization": {
            "authorization_id": f"AU_W{index}", "source_authorization_id": f"AU_W{index}",
            "scenario_id": "SCEN_WITNESS", "replay_order": index + 1,
            "mandate_id": snapshot.mandate_id, "profile_id": snapshot.profile_id,
            "card_id": _CARD, "initiator_type": "agent",
            "merchant": {"merchant_id": _MERCHANT, "merchant_name": "Witness Shop",
                         "merchant_category": category, "merchant_mcc": "5411",
                         "merchant_country": "CH", "merchant_city": "Zurich",
                         "availability": "online", "recurring_capable": "false"},
            "timestamp": stamp, "amount": amount, "currency": "CHF",
            "billing_amount_chf": amount, "items_subtotal": amount, "delivery_fee": 0.0,
            "channel": "ecommerce", "customer_device_id": "DVC-W",
            "authority_status": "active", "card_status_at_attempt": "active",
            "spend_in_period_before_chf": None, "recent_attempt_count_10m": 0,
            "fulfillment_method": "delivery", "delivery_by": None,
            "order_returnable": "true", "order_cancellable": "unknown",
            "related_authorization_id": None, "related_authorization_status": None,
            "purchase_description": "witness basket",
            "items": [{"line_no": 1, "item_id": f"IT_W{index}", "item_name": f"item {index}",
                       "item_category": category, "quantity": 1, "unit_price": amount,
                       "currency": "CHF",
                       "item_details": "returns accepted within 30 days"}],
        },
        "mandate": {"mandate_id": snapshot.mandate_id, "status": snapshot.status.value,
                    "customer_id": snapshot.customer_id, "card_id": snapshot.card_id,
                    "instruction": snapshot.instruction,
                    "hard_rules": [r.as_dict() for r in snapshot.hard_rules],
                    "uncertainty_policy": snapshot.uncertainty_policy.value,
                    "profile_id": snapshot.profile_id},
        "context": {"approved_spend_in_period_chf": 0.0, "recent_authorizations": []},
        "runtime": {"received_at": stamp, "history_window_minutes": 10,
                    "context_basis": "run_decisions_and_scenario_timestamps"},
    }


def _judge(rules, uncertainty, amount: float, *, category="groceries", repeats=1,
           unsupported=None) -> str:
    snapshot = _snapshot(rules, uncertainty, unsupported)
    state = RunState(history=HistoryIndex({_CARD: frozenset({_MERCHANT})}), card_id=_CARD)
    verdict = "allow"
    for index in range(repeats):
        verdict = evaluate_authorization(_event(snapshot, index, amount, category),
                                         snapshot, state).decision
    return verdict


def find_witness(instruction: str, reading: Reading) -> dict[str, Any] | None:
    """A concrete purchase the two readings judge differently, or None."""
    if reading.applies is not None and not reading.applies(instruction):
        return None
    compiled = compile_instruction(instruction)
    rules_a = list(compiled.hard_rules)
    rules_b = reading.transform(rules_a)
    if rules_b is None:
        return None

    uncertainty = compiled.uncertainty_policy
    ceilings = [r.value for r in rules_a if r.field == "authorization.billing_amount_chf"]

    candidates = []
    for ceiling in ceilings:
        for amount in (ceiling, ceiling - 0.01, ceiling + 0.01):
            candidates.append({"amount": round(float(amount), 2), "repeats": 1})
        candidates.append({"amount": round(float(ceiling) / 2, 2), "repeats": 3})

    for candidate in candidates:
        unsupported = list(compiled.unsupported_restrictions)
        verdict_a = _judge(rules_a, uncertainty, candidate["amount"],
                           repeats=candidate["repeats"], unsupported=unsupported)
        verdict_b = _judge(rules_b, uncertainty, candidate["amount"],
                           repeats=candidate["repeats"], unsupported=unsupported)
        if verdict_a != verdict_b:
            return {"reading": reading, "labels": reading.labels(rules_a),
                    "amount": candidate["amount"], "repeats": candidate["repeats"],
                    "category": "groceries",
                    "verdict_a": verdict_a, "verdict_b": verdict_b}
    return None


def witnesses(instruction: str) -> list[dict[str, Any]]:
    return [w for w in (find_witness(instruction, r) for r in READINGS) if w]
