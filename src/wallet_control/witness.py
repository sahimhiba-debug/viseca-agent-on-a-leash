"""The shared apparatus for asking "what would this mandate actually do?"

A WITNESS is a concrete purchase that exposes something about a mandate the
customer would not have predicted from reading it. Three different questions in
this repository turned out to have the same answer-shape:

    ambiguity.py   two readings of one sentence      -> the basket they judge apart
    silence.py     a seller who states terms, and one who does not
    the CHF-62 experiment (research/) same money, different intent

Each builds a throwaway mandate, puts a hypothetical purchase through the REAL
engine, and reports where the verdicts diverge. None of them inspects rules and
concludes: a witness produced by reasoning about the policy instead of running it
would prove nothing about what the wallet does.

This module exists because the second of those was about to copy the first's
event builder verbatim. One event builder, one judge, one set of defaults -- so a
change to what a hypothetical purchase looks like cannot leave two witnesses
disagreeing about the same wallet.

DECIDES NOTHING. Everything here is advisory, evaluated on a mandate nobody
confirmed, against purchases that never happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import lru_cache
from typing import Any

from .decision_engine import evaluate_authorization
from .mandate import HardRule, Mandate, MandateSnapshot, UncertaintyPolicy
from .state import HistoryIndex, RunState

MERCHANT = "ME_WITNESS"
CARD = "CA_WITNESS"
AT = datetime(2026, 8, 12, 9, 0, tzinfo=timezone.utc)

# How permissive each verdict is, so "did describing this differently HELP the
# agent?" is a comparison rather than a judgement call.
PERMISSIVENESS = {"block": 0, "review": 1, "allow": 2}


@dataclass(frozen=True)
class Purchase:
    """One hypothetical purchase, described exactly as much as we choose.

    `details` and `returnable` are separated from the goods on purpose. They are
    what the SELLER says about the order, and a witness that varies them while
    holding the goods fixed is asking the one question this repository could not
    previously ask: does the same purchase become more acceptable when less is
    said about it?
    """

    amount: float
    category: str = "groceries"
    item_name: str = "item"
    returnable: str = "true"
    details: str = "returns accepted within 30 days"
    repeats: int = 1


def snapshot(rules: list[HardRule], uncertainty: UncertaintyPolicy,
             unsupported: list[str] | None = None) -> MandateSnapshot:
    """A throwaway mandate for judging one hypothetical purchase.

    Nobody confirms this; it exists for the length of a decision. It still carries
    the compiled `unsupported_restrictions` and acknowledges them, because the
    anti-rot test that enforces that plumbing caught `ambiguity.py` the moment it
    was written -- and a candidate policy built differently from the real one would
    be measuring the wrong thing anyway.
    """
    unsupported = list(unsupported or [])
    mandate = Mandate.draft("candidate reading", list(rules), uncertainty,
                            None, None, unsupported)
    mandate.confirm(confirmed=True, customer_id="CU_WITNESS", card_id=CARD,
                    profile_id="PR_WITNESS",
                    acknowledged_unsupported=tuple(unsupported))
    return mandate.snapshot()


@lru_cache(maxsize=1)
def _catalogue_id_by_category() -> dict[str, str]:
    """A REAL `items.csv` id for each category a hypothetical purchase can claim.

    These purchases are imaginary, but they are judged by the real engine, and the
    real engine now checks the stated category against the official catalogue. A
    made-up id (`IT_W3`, as this was) is one the catalogue cannot identify, which
    makes `item.category` `unknown` on exactly the mandates these witnesses exist to
    probe -- so every witness collapsed to `review` and stopped distinguishing
    anything. The witness must differ from a real purchase in the ONE fact under
    test and in nothing else; the item id is not the fact under test.
    """
    from .csv_data import load_items

    out: dict[str, str] = {}
    for item_id, row in load_items().items():
        out.setdefault(row["item_category"], item_id)
    return out


def catalogue_id_for(category: str, fallback_index: int) -> str:
    return _catalogue_id_by_category().get(category, f"IT_W{fallback_index}")


def event(mandate: MandateSnapshot, index: int, purchase: Purchase) -> dict[str, Any]:
    return event_for(
        mandate, index, amount=purchase.amount, category=purchase.category,
        merchant=MERCHANT, returnable=purchase.returnable,
        items=[{"line_no": 1,
                "item_id": catalogue_id_for(purchase.category, index),
                "item_name": f"{purchase.item_name} {index}",
                "item_category": purchase.category, "quantity": 1,
                "unit_price": purchase.amount, "currency": "CHF",
                "item_details": purchase.details}])


def event_for(mandate: MandateSnapshot, index: int, *, amount: float, category: str,
              merchant: str = MERCHANT, returnable: str = "true",
              items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One synthetic `authorization.request`. The single event builder for every
    hypothetical purchase in this system, so a change to what one looks like cannot
    leave two witnesses disagreeing about the same wallet."""
    when = AT + timedelta(hours=index * 6)
    stamp = when.isoformat().replace("+00:00", "Z")
    return {
        "type": "authorization.request", "request_id": f"req_w{index}",
        "deadline_at": (when + timedelta(seconds=8)).isoformat().replace("+00:00", "Z"),
        "authorization": {
            "authorization_id": f"AU_W{index}", "source_authorization_id": f"AU_W{index}",
            "scenario_id": "SCEN_WITNESS", "replay_order": index + 1,
            "mandate_id": mandate.mandate_id, "profile_id": mandate.profile_id,
            "card_id": CARD, "initiator_type": "agent",
            "merchant": {"merchant_id": merchant, "merchant_name": "Witness Shop",
                         "merchant_category": category, "merchant_mcc": "5411",
                         "merchant_country": "CH", "merchant_city": "Zurich",
                         "availability": "online", "recurring_capable": "false"},
            "timestamp": stamp, "amount": amount, "currency": "CHF",
            "billing_amount_chf": amount, "items_subtotal": amount,
            "delivery_fee": 0.0,
            "channel": "ecommerce", "customer_device_id": "DVC-W",
            "authority_status": "active", "card_status_at_attempt": "active",
            "spend_in_period_before_chf": None, "recent_attempt_count_10m": 0,
            "fulfillment_method": "delivery", "delivery_by": None,
            "order_returnable": returnable, "order_cancellable": "unknown",
            "related_authorization_id": None, "related_authorization_status": None,
            "purchase_description": "witness basket",
            "items": items or [],
        },
        "mandate": {"mandate_id": mandate.mandate_id, "status": mandate.status.value,
                    "customer_id": mandate.customer_id, "card_id": mandate.card_id,
                    "instruction": mandate.instruction,
                    "hard_rules": [r.as_dict() for r in mandate.hard_rules],
                    "uncertainty_policy": mandate.uncertainty_policy.value,
                    "profile_id": mandate.profile_id},
        "context": {"approved_spend_in_period_chf": 0.0, "recent_authorizations": []},
        "runtime": {"received_at": stamp, "history_window_minutes": 10,
                    "context_basis": "run_decisions_and_scenario_timestamps"},
    }


def judge_sequence(mandate: MandateSnapshot, index: int, merchant: str, category: str,
                   lines: tuple, repeats: int, *,
                   familiar: frozenset[str] = frozenset()) -> str:
    """The verdict after buying the same basket `repeats` times in one run.

    Some differences between two readings are invisible to any single purchase: a
    weekly budget and a per-order ceiling of the same figure agree on every one
    order and part company on the third. So the search has to be over SEQUENCES,
    not baskets, and this is the smallest form of that -- the same basket, again.

    Item names carry the repetition number because the engine's duplicate suspicion
    would otherwise (correctly) flag the second identical basket at the same shop,
    and the question being asked is about the budget rule, not about duplicates."""
    total = float(sum((price for _id, _name, price in lines), Decimal("0")))
    known = familiar or frozenset({merchant})
    state = RunState(history=HistoryIndex({CARD: frozenset(known)}, available=True),
                     card_id=CARD)
    verdict = "allow"
    for step in range(repeats):
        event = event_for(
            mandate, index * 16 + step, amount=total, category=category,
            merchant=merchant,
            items=[{"line_no": i, "item_id": item_id,
                    "item_name": f"{name} {step}", "item_category": category,
                    "quantity": 1, "unit_price": float(price), "currency": "CHF",
                    "item_details": ""}
                   for i, (item_id, name, price) in enumerate(lines, start=1)])
        verdict = evaluate_authorization(event, mandate, state).decision
    return verdict


def judge_event(mandate: MandateSnapshot, index: int, merchant: str, category: str,
                lines: tuple, *, familiar: frozenset[str] = frozenset()) -> str:
    """The engine's verdict on a MULTI-LINE basket at a named shop, from a fresh run
    state. `scope.py` calls this several hundred times to count what a mandate
    permits, so it takes the basket directly rather than a `Purchase`.

    Fresh state on every call because an acceptance SET is a property of the mandate
    and the world, not of what has already been bought. What accumulated spend does
    is take purchases away from that set, never add them -- which is the invariant
    `research/acceptance_set.py` checks against four different brains."""
    total = float(sum((price for _id, _name, price in lines), Decimal("0")))
    event = event_for(mandate, index, amount=total, category=category,
                      merchant=merchant,
                      items=[{"line_no": i, "item_id": item_id, "item_name": name,
                              "item_category": category, "quantity": 1,
                              "unit_price": float(price), "currency": "CHF",
                              "item_details": ""}
                             for i, (item_id, name, price) in enumerate(lines, start=1)])
    known = familiar or frozenset({merchant})
    state = RunState(history=HistoryIndex({CARD: frozenset(known)}, available=True),
                     card_id=CARD)
    return evaluate_authorization(event, mandate, state).decision


def judge_event_with_reason(mandate: MandateSnapshot, index: int, merchant: str,
                            category: str, lines: tuple, *,
                            familiar: frozenset[str] = frozenset()) -> tuple[str, str | None]:
    """The verdict, and WHICH RULE decided it.

    The delegation panel could say "0 of 124" and not why, which reads as a broken
    page rather than as the most informative thing the panel can tell a customer:
    that a mandate for a 27-inch monitor "from a seller I have bought from before"
    authorises NOTHING, because this card has never paid an electronics shop. A bare
    zero hides that; naming the rule that removed everything is the answer.
    """
    total = float(sum((price for _id, _name, price in lines), Decimal("0")))
    event = event_for(mandate, index, amount=total, category=category,
                      merchant=merchant,
                      items=[{"line_no": i, "item_id": item_id, "item_name": name,
                              "item_category": category, "quantity": 1,
                              "unit_price": float(price), "currency": "CHF",
                              "item_details": ""}
                             for i, (item_id, name, price) in enumerate(lines, start=1)])
    known = familiar or frozenset({merchant})
    state = RunState(history=HistoryIndex({CARD: frozenset(known)}, available=True),
                     card_id=CARD)
    decision = evaluate_authorization(event, mandate, state)
    blocking = next((e.rule.field for e in decision.rule_evaluations
                     if e.outcome in ("fail", "unknown")), None)
    return decision.decision, blocking


def judge(rules: list[HardRule], uncertainty: UncertaintyPolicy, purchase: Purchase,
          *, unsupported: list[str] | None = None) -> str:
    """What the real engine would decide. `repeats > 1` runs a SEQUENCE through one
    run state, because some witnesses are not a purchase but a pattern of them."""
    mandate = snapshot(rules, uncertainty, unsupported)
    state = RunState(history=HistoryIndex({CARD: frozenset({MERCHANT})}), card_id=CARD)
    verdict = "allow"
    for index in range(purchase.repeats):
        verdict = evaluate_authorization(event(mandate, index, purchase), mandate, state).decision
    return verdict
