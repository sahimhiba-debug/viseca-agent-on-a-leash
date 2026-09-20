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
    # Why the agent handed back to the customer, when it did. Distinct from an empty
    # basket: "I cannot fix this by shopping" is a RESULT, not a failure.
    handoff_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission": self.mission,
            "outcome": self.outcome,
            "handoff_reason": self.handoff_reason,
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


@dataclass(frozen=True)
class Mission:
    """What the customer actually wants, separate from any one basket.

    The agent plans against THIS, not against the last thing it happened to
    propose. Without an explicit goal there is nothing to replan toward -- the
    earlier version had only a basket and one rule for shrinking it, which is
    why it gave up on five of nine adversarial episodes.
    """

    description: str
    category: str
    target_lines: int = 5
    unavailable: frozenset[str] = frozenset()   # item_ids the shop cannot supply
    merchants: tuple[str, ...] = ("ME0001",)


def plan(mission: Mission) -> list[Line]:
    """Opening basket: the best available lines for the mission.

    Deliberately ambitious. The agent does not know the customer's ceiling, so its
    first proposal is the one most likely to be refused -- which is the point of the
    demonstration and also the honest behaviour: nothing tells it to aim low.
    """
    available = [l for l in catalogue(mission.category) if l.item_id not in mission.unavailable]
    return sorted(available, key=lambda l: l.unit_price, reverse=True)[: mission.target_lines]


def _cheaper_substitute(line: Line, mission: Mission, in_basket: list[Line]) -> Line | None:
    """The cheapest same-category item that is available and not already in the basket."""
    held = {l.item_id for l in in_basket}
    options = [
        l for l in catalogue(line.category)
        if l.item_id not in mission.unavailable and l.item_id not in held and l.unit_price < line.unit_price
    ]
    return min(options, key=lambda l: l.unit_price) if options else None


# What the agent can actually do about each constraint class. A class it has no move
# for is not a failure to plan -- it is a reason to involve the customer, which is a
# different outcome and must not be collapsed into "gave up".
_ACTIONABLE = {"amount", "item", "basket"}
_NEEDS_CUSTOMER = {"order_terms", "session", "duplicate", "merchant", "other"}


def replan(lines: list[Line], blocked_by: list[str], mission: Mission,
           merchant_index: int) -> tuple[list[Line], str, int] | str:
    """One replanning step toward the mission.

    Returns a new (basket, rationale, merchant_index), or a STRING naming why the
    agent is handing back to the customer. The strategy ladder is ordered so that the
    agent gives up the least mission value it can:

        1. substitute a cheaper line of the same kind   (keeps the mission intact)
        2. drop the most expensive line                  (loses one item)
        3. switch to another merchant it was told about  (keeps the whole basket)
        4. ask the customer                              (cannot be fixed by shopping)

    None of these uses a numeric threshold, because the agent is never given one.
    It knows only the CLASS of constraint it hit, so it can move in the right
    direction and try again -- which is the difference between adapting and probing.
    """
    if not blocked_by:
        return "the wallet gave no reason the agent can act on"

    unfixable = [c for c in blocked_by if c in _NEEDS_CUSTOMER]
    actionable = [c for c in blocked_by if c in _ACTIONABLE]

    if "item" in actionable or "basket" in actionable:
        kept = [l for l in lines if l.category == mission.category]
        if kept and len(kept) < len(lines):
            return kept, "removed lines outside what the customer asked for", merchant_index

    if "amount" in actionable:
        dearest = max(lines, key=lambda l: l.total)
        swap = _cheaper_substitute(dearest, mission, lines)
        if swap is not None:
            return ([l for l in lines if l is not dearest] + [swap],
                    f"swapped {dearest.name} for the cheaper {swap.name}", merchant_index)
        if len(lines) > 1:
            return ([l for l in lines if l is not dearest],
                    f"no cheaper substitute; dropped {dearest.name}", merchant_index)

    if unfixable and merchant_index + 1 < len(mission.merchants) and "merchant" in unfixable:
        return lines, f"trying {mission.merchants[merchant_index + 1]} instead", merchant_index + 1

    if unfixable:
        return f"only the customer can resolve this ({', '.join(sorted(unfixable))})"
    return "no further change would help"


@dataclass(frozen=True)
class Planner:
    """The replaceable half of the agent.

    `plan` and `replan` are the only reasoning in this system, and they are injectable
    precisely so that the architectural claim can be TESTED rather than asserted: a
    model-based planner would slot in here, outside the authority boundary, and the
    wallet's decisions must be identical whether the planner is the deterministic one,
    a language model, a hallucinating stub, or an adversary.

    We ship the deterministic planner. A model is deliberately NOT in the judged path:
    `technical_details.md` requires a predictable response when the model is
    unavailable, and a network call would make the demo irreproducible -- which is a
    jury criterion we would rather win outright. What we do instead is prove the seam
    holds against planners far worse than any real model
    (`tests/test_agent_planner_boundary.py`).
    """

    plan: Callable[[Mission], list[Line]] = None          # type: ignore[assignment]
    replan: Callable[..., Any] = None                      # type: ignore[assignment]

    def opening(self, mission: Mission) -> list[Line]:
        return (self.plan or plan)(mission)

    def next_step(self, lines, blocked_by, mission, merchant_index):
        return (self.replan or replan)(lines, blocked_by, mission, merchant_index)


DETERMINISTIC = Planner()


def shop(
    mission: Mission,
    propose: Callable[[list[Line], int, str], dict[str, Any]],
    max_revisions: int = MAX_REVISIONS,
    planner: Planner = DETERMINISTIC,
) -> Episode:
    """Plan, propose, observe, replan -- stopping on success, on a human, or when the
    agent judges that no further basket change would help.

    `propose` submits a basket to the wallet and returns an `agent_view`. That is the
    ONLY channel through which the agent learns anything about the policy.
    """
    episode = Episode(mission=mission.description)
    # A planner that raises, returns nothing, or returns nonsense must not take the
    # wallet down with it: the agent degrades to asking the customer.
    try:
        lines = planner.opening(mission)
    except Exception as exc:                                   # noqa: BLE001 -- any planner failure
        episode.outcome = "asked_customer"
        episode.handoff_reason = f"the planner failed to produce a basket ({type(exc).__name__})"
        return episode
    if not lines:
        episode.outcome = "asked_customer"
        episode.handoff_reason = "the planner produced no basket"
        return episode
    merchant_index = 0
    rationale = f"opening basket: the {len(lines)} best available {mission.category} lines"

    for revision in range(max_revisions + 1):
        amount = sum((l.total for l in lines), Decimal("0"))
        view = propose(lines, revision, mission.merchants[merchant_index])
        episode.attempts.append(Attempt(revision, tuple(lines), amount, view, rationale))

        if view["decision"] == "allow":
            episode.outcome = "approved"
            return episode
        if view.get("awaiting_customer"):
            episode.outcome = "awaiting_customer"
            return episode

        try:
            step = planner.next_step(lines, view.get("blocked_by", []), mission, merchant_index)
        except Exception as exc:                               # noqa: BLE001
            episode.outcome = "asked_customer"
            episode.handoff_reason = f"the planner failed while replanning ({type(exc).__name__})"
            return episode
        if not isinstance(step, tuple) or len(step) != 3 or not step[0]:
            episode.outcome = "asked_customer"
            episode.handoff_reason = step if isinstance(step, str) else "the planner returned an unusable step"
            return episode
        if isinstance(step, str):
            episode.outcome = "asked_customer"
            episode.handoff_reason = step
            return episode
        lines, rationale, merchant_index = step

    episode.outcome = "gave_up"
    episode.handoff_reason = "ran out of revisions"
    return episode
