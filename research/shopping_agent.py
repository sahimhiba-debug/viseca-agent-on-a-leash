"""An autonomous shopping agent that proposes, is refused, and adapts.

RESEARCH APPARATUS, never imported by `src/wallet_control/` -- the wallet must run
identically with this file deleted, which `tests/test_runtime_boundary.py` enforces.
The agent is a CLIENT of the wallet, and putting it anywhere else would blur the one
boundary this whole project exists to draw.

WHY IT IS DETERMINISTIC AND NOT A MODEL
---------------------------------------
`technical_details.md` requires a solution that "must still give a predictable
response when the model or another external service is unavailable". An LLM here
would make the demo unreproducible and the wallet's guarantees conditional on a
third party. The planning is a few lines of arithmetic; the interesting part was
never the planner, it is what the agent is allowed to LEARN.

WHAT THE AGENT MAY SEE
----------------------
Only `decision_engine.agent_view(...)`: the decision, the CLASS of constraint that
failed, and whether a human is being asked. No rule values, no remaining budget, no
evidence strings.

That restriction is the mechanism, not a courtesy. The wallet is an oracle -- every
decision system is -- and an agent seeing only ALLOW/BLOCK recovers a secret CHF 137
ceiling to within CHF 0.24 in twelve probes, spending CHF 531 of the customer's money
to do it. The customer's own payload carries the rule's `value` and "projected 7-day
spend=287.50 CHF", which would collapse that to zero probes. So the agent adapts
without ever being told the limit: it learns "propose less", never "propose 119.99".

The loop cannot manufacture authority. A revised basket is approved only if it
independently satisfies the same confirmed mandate; the wallet re-decides it from
scratch. Adaptation consumes the delegation, it never widens it.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

_ITEMS = Path(__file__).resolve().parents[1] / "data" / "official" / "items.csv"

# How many revisions before the agent gives up and asks the customer. Bounded because
# an unbounded loop is exactly the cheap-probing case the oracle analysis warns about,
# and because every attempt is a recorded decision an auditor can count.
MAX_REVISIONS = 4


@dataclass(frozen=True)
class Line:
    item_id: str
    name: str
    category: str
    unit_price: Decimal
    quantity: int = 1

    @property
    def total(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass
class Attempt:
    revision: int
    lines: tuple[Line, ...]
    amount_chf: Decimal
    agent_view: dict[str, Any]
    rationale: str


@dataclass
class Episode:
    """The whole plan→propose→observe→revise trace, for the audit trail and the demo."""

    mission: str
    attempts: list[Attempt] = field(default_factory=list)
    outcome: str = "unresolved"

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission": self.mission,
            "outcome": self.outcome,
            "attempts": [
                {
                    "revision": a.revision,
                    "amount_chf": float(a.amount_chf),
                    "lines": [{"name": l.name, "category": l.category,
                               "unit_price": float(l.unit_price), "quantity": l.quantity}
                              for l in a.lines],
                    "wallet": a.agent_view,
                    "rationale": a.rationale,
                }
                for a in self.attempts
            ],
        }


def catalogue(category: str | None = None) -> list[Line]:
    with _ITEMS.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f)]
    if category:
        rows = [r for r in rows if r["item_category"] == category]
    return [
        Line(r["item_id"], r["item_name"], r["item_category"], Decimal(r["unit_price_typical_chf"]))
        for r in rows
    ]


def plan(mission_category: str, target_lines: int = 5) -> list[Line]:
    """Build an opening basket. Deliberately ambitious: the agent does not know the
    customer's ceiling, so its first proposal is the one most likely to be refused --
    which is the whole point of the demonstration."""
    items = sorted(catalogue(mission_category), key=lambda l: l.unit_price, reverse=True)
    return items[:target_lines]


def revise(lines: list[Line], blocked_by: list[str]) -> tuple[list[Line], str] | None:
    """One adaptation step, from the CLASS of constraint alone.

    The agent never learns a threshold, so it cannot jump straight to the boundary --
    it can only move in the right direction and try again. That is the difference
    between adapting and extracting.
    """
    if "amount" in blocked_by:
        if len(lines) <= 1:
            cheaper = sorted(catalogue(lines[0].category), key=lambda l: l.unit_price)
            if cheaper and cheaper[0].unit_price < lines[0].unit_price:
                return [cheaper[0]], f"swapped to the cheapest {lines[0].category} line"
            return None
        dropped = max(lines, key=lambda l: l.total)
        return [l for l in lines if l is not dropped], f"dropped the most expensive line ({dropped.name})"
    if "basket" in blocked_by or "item" in blocked_by:
        wanted = lines[0].category if lines else None
        kept = [l for l in lines if l.category == wanted]
        if kept and len(kept) < len(lines):
            return kept, "removed lines outside the requested kind of item"
    return None


def shop(
    mission: str,
    mission_category: str,
    propose: Callable[[list[Line], int], dict[str, Any]],
    max_revisions: int = MAX_REVISIONS,
) -> Episode:
    """Run the loop. `propose` submits a basket to the wallet and returns an
    `agent_view` -- the ONLY channel through which the agent learns anything."""
    episode = Episode(mission=mission)
    lines = plan(mission_category)
    rationale = f"opening basket: the {len(lines)} best {mission_category} lines"

    for revision in range(max_revisions + 1):
        amount = sum((l.total for l in lines), Decimal("0"))
        view = propose(lines, revision)
        episode.attempts.append(Attempt(revision, tuple(lines), amount, view, rationale))

        if view["decision"] == "allow":
            episode.outcome = "approved"
            return episode
        if view.get("awaiting_customer"):
            episode.outcome = "awaiting_customer"
            return episode

        step = revise(lines, view.get("blocked_by", []))
        if step is None:
            episode.outcome = "gave_up"
            return episode
        lines, rationale = step

    episode.outcome = "gave_up"
    return episode
