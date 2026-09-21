"""An adversarial planning benchmark. Built BEFORE the agent was changed, so it can
genuinely fail.

Eleven episodes (A–K) over a small deterministic world. The point is to separate

    "changed the basket because a hard-coded rule said so"

from

    "selected a different strategy because the environment changed",

which a benchmark built after the fact tends to blur. Nothing here references a
scenario id; each episode is a world plus a customer instruction, and the agent is
given no privileged knowledge of either.

BASELINE, measured before any change to the agent (commit db72435): 5/11.
AFTER the planner was rebuilt around a tool, an objective function and a search
over candidate baskets: 11/11.

    before   pass  A B F H J          fail  C D E G I K
    after    pass  all eleven

One fixture bug was found and fixed in between: this file emitted the seller's
returnable flag as English "yes"/"no" where the platform's vocabulary is
"true"/"false", so it fell through to "the seller said nothing" and episode D
escalated to a human on attempt one. That measured the fixture, not the agent. The
OLD agent was re-run against the CORRECTED benchmark and still scored 5/11, and its
failures got worse under the honest rendering: in C, E, I and K it reported
"approved" while holding the excluded shop's goods, because it chose the items from
a catalogue and the merchant from the mission and never checked them against each
other. The wallet approved a truthful evaluation of an untruthful proposal.

The six failures are three defects, not six:

  NO OBJECTIVE FUNCTION (C, E, I, K)  The agent's only notion of "better" is
      "cheaper". In K three baskets are valid-looking and only one is actually
      allowed; the agent DELETED that one first, because it was the dearest, then
      walked down the price ladder into a basket from a shop the customer had
      excluded. Ranking by price is not ranking by the customer's stated goal.

  NO SUBSTITUTION EXCEPT ON PRICE (C, D, E, I, K)  Told `blocked_by=["merchant"]`
      while a familiar-merchant alternative sits in the same catalogue, the agent
      says "only the customer can resolve this". Its ladder can shrink a basket
      and nothing else, so every non-price constraint becomes a human handoff.

  NO OBSERVATION OF THE ENVIRONMENT (G)  `Mission.unavailable` is a frozenset
      captured before the first proposal. When an item sold out mid-episode the
      agent re-proposed it and the wallet approved it -- correctly, since stock is
      none of the wallet's business. The agent had exactly one feedback channel
      (the wallet) and none to the shop it was buying from.

Across all 11 episodes it used TWO distinct moves: "swapped X for the cheaper Y"
(once) and "dropped X" (seven times). The merchant-switch and category-filter rungs
never fired at all. A greedy descent on one axis is not planning, and the honest
word for the result is a reactive repair loop.

WHAT CHANGED, and what did NOT. No model was added. The three defects were failures
of representation, not of reasoning power: the agent had no way to say what it
wanted (objective), no way to consider an option it had not already chosen
(search), and no way to look at the shop (tool). A language model would have
supplied none of those three; it would have guessed at all of them, unreproducibly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Callable


@dataclass(frozen=True)
class Product:
    item_id: str
    name: str
    category: str
    price: Decimal
    merchant: str
    returnable_days: int | None = 30      # None => the seller states nothing


@dataclass
class World:
    """What the shop looks like right now. Mutable between proposals on purpose:
    episodes F and G change it after the agent's first attempt."""

    products: list[Product]
    familiar_merchants: frozenset[str]
    unavailable: set[str] = field(default_factory=set)

    def search(self, category: str | None = None) -> list[Product]:
        return [p for p in self.products
                if p.item_id not in self.unavailable and (category is None or p.category == category)]


@dataclass
class Episode:
    key: str
    title: str
    instruction: str
    world: World
    mission_category: str
    # What a competent agent should end up doing. Deliberately expressed as an
    # OUTCOME, not as a basket, so a different-but-valid plan still passes.
    expect: str                                   # "approved" | "asked_customer"
    must_include: tuple[str, ...] = ()            # item_ids the final basket must hold
    must_exclude: tuple[str, ...] = ()
    mutate_after_first: Callable[[World], None] | None = None
    note: str = ""


_GROC = "groceries"
FAMILIAR, STRANGER = "ME0001", "ME0777"


def _p(i, n, price, merchant=FAMILIAR, cat=_GROC, ret=30):
    return Product(i, n, cat, Decimal(str(price)), merchant, ret)


def episodes() -> list[Episode]:
    return [
        Episode("A", "spend under a ceiling, keep the staples",
                "Order our household groceries, at or below CHF 120. Ask me when uncertain.",
                World([_p("a1", "Weekly basket", 95), _p("a2", "Pantry restock", 60),
                       _p("a3", "Breakfast box", 45), _p("a4", "Produce", 28), _p("a5", "Milk", 12)],
                      frozenset({FAMILIAR})),
                _GROC, "approved", note="a valid basket exists; the agent must find one"),

        Episode("B", "preferred item unavailable",
                "Order our household groceries, at or below CHF 120. Ask me when uncertain.",
                World([_p("b1", "Weekly basket", 95), _p("b2", "Pantry restock", 60), _p("b3", "Produce", 28)],
                      frozenset({FAMILIAR}), unavailable={"b1"}),
                _GROC, "approved", must_exclude=("b1",),
                note="the dearest line cannot be bought at all"),

        Episode("C", "cheaper stranger vs pricier familiar",
                "Order our household groceries from a shop I have used before, at or below CHF 120. "
                "Ask me when uncertain.",
                World([_p("c1", "Produce (unknown shop)", 84, STRANGER),
                       _p("c2", "Produce (usual shop)", 91, FAMILIAR)],
                      frozenset({FAMILIAR})),
                _GROC, "approved", must_include=("c2",), must_exclude=("c1",),
                note="CHEAPEST IS WRONG: the customer asked for a familiar merchant"),

        Episode("D", "one product cannot be returned",
                "Order our household groceries, at or below CHF 120, only if returnable within 14 days. "
                "Ask me when uncertain.",
                World([_p("d1", "Clearance box", 40, ret=0), _p("d2", "Produce", 45, ret=30)],
                      frozenset({FAMILIAR})),
                _GROC, "approved", must_exclude=("d1",),
                note="the cheapest line fails a non-price constraint"),

        Episode("E", "cheapest basket violates another rule",
                "Order our household groceries from a shop I have used before, at or below CHF 60. "
                "Ask me when uncertain.",
                World([_p("e1", "Bargain crate", 20, STRANGER), _p("e2", "Produce", 55, FAMILIAR)],
                      frozenset({FAMILIAR})),
                _GROC, "approved", must_include=("e2",), must_exclude=("e1",)),

        Episode("F", "merchant disappears after the first proposal",
                "Order our household groceries, at or below CHF 120. Ask me when uncertain.",
                World([_p("f1", "Produce", 45, FAMILIAR), _p("f2", "Produce (backup shop)", 50, "ME0002")],
                      frozenset({FAMILIAR, "ME0002"})),
                _GROC, "approved",
                mutate_after_first=lambda w: w.unavailable.add("f1"),
                note="the environment changes mid-episode"),

        Episode("G", "an item sells out after the first proposal",
                "Order our household groceries, at or below CHF 90. Ask me when uncertain.",
                World([_p("g1", "Weekly basket", 95), _p("g2", "Produce", 40), _p("g3", "Milk", 15)],
                      frozenset({FAMILIAR})),
                _GROC, "approved",
                mutate_after_first=lambda w: w.unavailable.add("g2"),
                must_exclude=("g2",)),

        Episode("H", "each item fine, the combination is not",
                "Order our household groceries, at or below CHF 100. Ask me when uncertain.",
                World([_p("h1", "Produce", 60), _p("h2", "Pantry", 55), _p("h3", "Milk", 20)],
                      frozenset({FAMILIAR})),
                _GROC, "approved", note="60+55 exceeds the ceiling; individually both are fine"),

        Episode("I", "change one property, keep the goal",
                "Order our household groceries from a shop I have used before, at or below CHF 120. "
                "Ask me when uncertain.",
                World([_p("i1", "Weekly basket", 110, STRANGER), _p("i2", "Weekly basket", 115, FAMILIAR)],
                      frozenset({FAMILIAR})),
                _GROC, "approved", must_include=("i2",),
                note="same goods, wrong shop: fix the merchant, not the basket"),

        Episode("J", "no valid basket exists",
                "Order our household groceries, at or below CHF 5. Ask me when uncertain.",
                World([_p("j1", "Produce", 45), _p("j2", "Milk", 20)], frozenset({FAMILIAR})),
                _GROC, "asked_customer", note="the agent must stop, not loop"),

        Episode("K", "several valid baskets; pick by the stated objective",
                "Order our household groceries from a shop I have used before, at or below CHF 120, "
                "only if returnable within 14 days. Ask me when uncertain.",
                World([_p("k1", "Cheap, unknown shop", 76, STRANGER, ret=30),
                       _p("k2", "Cheap, no returns", 84, FAMILIAR, ret=0),
                       _p("k3", "Dearer, familiar, returnable", 91, FAMILIAR, ret=30)],
                      frozenset({FAMILIAR})),
                _GROC, "approved", must_include=("k3",), must_exclude=("k1", "k2"),
                note="THE MULTI-OBJECTIVE CASE: cheapest is wrong twice over"),
    ]


# ---------------------------------------------------------------------------
# Running an episode against the REAL wallet and the SHIPPED agent.
# ---------------------------------------------------------------------------

def _wire() -> Any:
    import sys, os
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for p in (str(root / "src"), str(root)):
        if p not in sys.path:
            sys.path.insert(0, p)


_wire()

from wallet_control.mandate import Mandate, UncertaintyPolicy       # noqa: E402
from wallet_control.policy_compiler import compile_instruction       # noqa: E402
from wallet_control.state import HistoryIndex, RunState              # noqa: E402
from wallet_control.decision_engine import evaluate_authorization, agent_view  # noqa: E402

import research.shopping_agent as sa                                 # noqa: E402

CARD = "CA_BENCH"


@dataclass
class Result:
    key: str
    title: str
    outcome: str
    expected: str
    attempts: int
    final_items: tuple[str, ...]
    handoff_reason: str | None
    violations: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.violations


class WorldShop(sa.Shop):
    """The episode world, exposed through the agent's own tool interface. Read live
    on every call, so an episode that changes the shop mid-run actually changes what
    the agent sees -- which is the whole point of episodes F and G."""

    def __init__(self, world: World) -> None:
        self.world = world

    def search(self, category=None):
        return [sa.Offer(p.item_id, p.name, p.category, p.price, p.merchant, p.returnable_days)
                for p in self.world.search(category)]


def _event(ep: Episode, lines, merchant_id: str, n: int, mandate, world: World) -> dict[str, Any]:
    from tests.helpers import make_event
    by_id = {p.item_id: p for p in world.products}
    total = float(sum(l.total for l in lines))
    items = []
    for i, l in enumerate(lines, start=1):
        # A planner may propose something this world never offered -- an honest one
        # does not, a hostile one does, and a real shop would simply have no terms to
        # state for it. Treating an unknown line as "the seller said nothing" is both
        # the faithful behaviour and what stops a hostile brain from crashing the
        # HARNESS rather than being refused by the wallet.
        p = by_id.get(l.item_id)
        detail = ("" if p is None or p.returnable_days is None
                  else f"Returns accepted within {p.returnable_days} days")
        items.append({"line_no": i, "item_id": l.item_id, "item_name": l.name,
                      "item_category": l.category, "quantity": l.quantity,
                      "unit_price": float(l.unit_price), "currency": "CHF",
                      "item_details": detail})
    # What the seller says about returns, consistently with the per-item details the
    # agent can read. Leaving this "unknown" made episode D escalate to a human on
    # attempt one, which measured the fixture, not the agent.
    windows = [by_id[l.item_id].returnable_days if l.item_id in by_id else None
               for l in lines]
    # "true"/"false"/"unknown" -- the platform's vocabulary, not English. Emitting
    # "yes"/"no" here silently fell through to "the seller said nothing", which made
    # episode D escalate on attempt one and measured the fixture, not the agent.
    returnable = ("unknown" if any(w is None for w in windows)
                  else "true" if all(w > 0 for w in windows) else "false")
    return make_event(authorization_id=f"AU_{ep.key}_{n:04d}", mandate=mandate,
                      order_returnable=returnable,
                      merchant_id=merchant_id, merchant_category=_GROC,
                      amount=total, billing_amount_chf=total, items_subtotal=total,
                      items=items, card_id=CARD)


def run_episode(ep: Episode, *, max_revisions: int = 4, planner=None) -> Result:
    ep = replace(ep, world=World(list(ep.world.products), ep.world.familiar_merchants,
                                 set(ep.world.unavailable)))
    compiled = compile_instruction(ep.instruction)
    # Carry the unsupported restrictions into the DRAFT, not just into confirm().
    # Acknowledging at confirmation time while drafting an empty list means the gate
    # has nothing to fire on; the anti-rot test in tests/security caught this file
    # doing precisely that.
    m = Mandate.draft(ep.instruction, list(compiled.hard_rules),
                      UncertaintyPolicy(compiled.uncertainty_policy),
                      list(compiled.guidance), list(compiled.open_questions),
                      list(compiled.unsupported_restrictions))
    m.confirm(confirmed=True, customer_id="CU_BENCH", card_id=CARD, profile_id="PR_BENCH",
              acknowledged_unsupported=tuple(compiled.unsupported_restrictions))
    mandate = m.snapshot()

    state = RunState(history=HistoryIndex({CARD: frozenset(ep.world.familiar_merchants)}), card_id=CARD)
    by_id = {p.item_id: p for p in ep.world.products}
    seen = {"n": 0}

    tool = WorldShop(ep.world)

    def propose(lines, revision, merchant):
        seen["n"] += 1
        # The basket decides the shop, because the goods live at a shop. The agent
        # has no such notion; we render its intent as faithfully as we can.
        ev = _event(ep, lines, merchant, seen["n"], mandate, ep.world)
        view = agent_view(evaluate_authorization(ev, mandate, state))
        if seen["n"] == 1 and ep.mutate_after_first:
            ep.mutate_after_first(ep.world)
        return view

    mission = sa.Mission(ep.instruction, ep.mission_category, target_lines=3,
                         merchants=tuple(sorted({p.merchant for p in ep.world.products})))
    episode = sa.shop(mission, propose, max_revisions=max_revisions, shop_tool=tool,
                      planner=planner or sa.DETERMINISTIC)

    final = tuple(l.item_id for l in episode.attempts[-1].lines) if episode.attempts else ()
    v: list[str] = []
    if episode.outcome != ep.expect:
        v.append(f"outcome {episode.outcome!r}, expected {ep.expect!r}")
    if episode.outcome == "approved":
        for i in ep.must_include:
            if i not in final:
                v.append(f"final basket is missing {i}")
        for i in ep.must_exclude:
            if i in final:
                v.append(f"final basket still contains {i}")
    return Result(ep.key, ep.title, episode.outcome, ep.expect, len(episode.attempts),
                  final, episode.handoff_reason, v)


def main() -> int:
    results = [run_episode(e) for e in episodes()]
    width = max(len(r.title) for r in results)
    print(f"{'':2s}  {'episode':{width}s}  {'outcome':16s} {'att':>3s}  basket")
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        print(f"{r.key:2s}  {r.title:{width}s}  {r.outcome:16s} {r.attempts:3d}  "
              f"{','.join(r.final_items) or '-'}   [{mark}]")
        for x in r.violations:
            print(f"      -> {x}")
        if r.handoff_reason:
            print(f"      .. {r.handoff_reason}")
    n = sum(r.passed for r in results)
    print(f"\n{n}/{len(results)} episodes passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
