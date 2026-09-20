"""A model-based planner at the same seam, so the decision not to ship one is a
MEASUREMENT rather than a preference.

RESEARCH APPARATUS. Never imported by `src/wallet_control/`, and not imported by
`shopping_agent` either -- it is a consumer of the seam, not part of it.

`technical_details.md` requires a solution that "must still give a predictable
response when the model or another external service is unavailable". That sentence
does not forbid a model; it forbids depending on one. So the question is not "LLM
or no LLM", it is: what does a model actually contribute HERE, given that the agent
already has an objective function, a search over candidate baskets, and a tool?

This file lets that be answered by running the same benchmark three ways:

    DETERMINISTIC   search only                     (what we ship)
    MODEL           the model's basket, no fallback
    HYBRID          the model proposes, the search checks and repairs

`complete` is any callable from prompt to text. No network is involved here and none
is wired into the demo: the stubs in `tests/security/test_model_planner_seam.py`
stand in for a model's behaviour, including its failure modes, because those are the
part worth testing. A real client would drop straight in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from research.shopping_agent import (
    Beliefs, Line, Mission, Offer, Shop, best_basket, replan,
)


def describe(shop: Shop, mission: Mission, beliefs: Beliefs) -> str:
    """The prompt. Deliberately carries NOTHING the deterministic agent is not also
    allowed to see -- the shop's own offers, the mission, and the classes of
    constraint that have refused it. A model given more than that would be a
    privacy regression wearing a capability costume."""
    offers = [f"{o.item_id} {o.name} CHF {o.unit_price} at {o.merchant} "
              f"returns={o.stated_return_days}" for o in shop.search(mission.category)]
    refused = sorted(beliefs.ruled_out_merchants)
    return (f"Errand: {mission.description}\n"
            f"Buy up to {mission.target_lines} lines of {mission.category} from ONE shop.\n"
            f"Shops already refused: {refused or 'none'}\n"
            f"Returns have been an issue: {beliefs.returns_matter}\n"
            f"Spend strictly less than: {beliefs.ceiling if beliefs.ceiling else 'no limit known'}\n"
            f"Offers:\n" + "\n".join(offers) +
            '\nReply with JSON only: {"item_ids": ["..."]}')


def parse(text: str, shop: Shop, mission: Mission) -> list[Offer] | None:
    """Read a basket out of the model's reply, or give up cleanly.

    Every failure mode collapses to None: bad JSON, the wrong shape, item ids that
    do not exist, or a basket spanning several shops. A planner that cannot be
    trusted to return a list of strings must not be trusted to widen an errand.
    """
    try:
        payload = json.loads(text)
        wanted = [str(i) for i in payload["item_ids"]]
    except (ValueError, TypeError, KeyError):
        return None
    if not wanted:
        return None
    by_id = {o.item_id: o for o in shop.search(mission.category)}
    if not set(wanted) <= by_id.keys():
        return None                                  # hallucinated goods
    chosen = [by_id[i] for i in wanted]
    if len({o.merchant for o in chosen}) != 1:
        return None                                  # a basket no single shop can supply
    return chosen


@dataclass
class ModelPlanner:
    """Architecture 2 and 3, selected by `fallback`.

    With `fallback=False` the model's answer is used or the agent hands back, which
    is the pure model-based agent. With `fallback=True` the deterministic search
    checks the model's basket and takes over whenever the model returns nothing
    usable -- the hybrid, and the only one of the three that satisfies the
    predictability requirement.
    """

    complete: Callable[[str], str]
    fallback: bool = True
    calls: int = 0
    fallbacks: int = 0

    def _ask(self, shop, mission, beliefs) -> list[Offer] | None:
        self.calls += 1
        try:
            chosen = parse(self.complete(describe(shop, mission, beliefs)), shop, mission)
        except Exception:                            # noqa: BLE001 -- the model is a network
            chosen = None
        if chosen is None:
            self.fallbacks += 1
        return chosen

    def opening(self, mission, shop=None, beliefs=None) -> list[Line]:
        beliefs = beliefs if beliefs is not None else Beliefs()
        chosen = self._ask(shop, mission, beliefs)
        if chosen is not None:
            return [o.line() for o in chosen]
        if not self.fallback:
            return []
        found = best_basket(shop, mission, beliefs)
        return [o.line() for o in found[0]] if found else []

    def next_step(self, lines, blocked_by, mission, merchant_index, shop=None,
                  beliefs=None, merchant=None):
        beliefs = beliefs if beliefs is not None else Beliefs()
        # The HALT rule is not the planner's to make. Whether a refusal may be
        # answered by shopping at all is a property of what the wallet objected to,
        # and a model that could talk its way past it would be the whole risk of
        # putting a model here in the first place.
        deterministic = replan(lines, blocked_by, mission, merchant_index, shop, beliefs, merchant)
        if isinstance(deterministic, str):
            return deterministic
        chosen = self._ask(shop, mission, beliefs)
        if chosen is not None:
            return [o.line() for o in chosen], "the model proposed this basket", merchant_index
        if not self.fallback:
            return "the model returned nothing usable"
        return deterministic


# No adapter is needed to plug this in. `shop()` asks its planner for exactly two
# things -- `opening` and `next_step` -- so anything answering those two is a
# planner, and `ModelPlanner` is passed to `shop(..., planner=...)` directly. That
# the seam turned out to need no wrapper is the strongest evidence it is a real
# seam and not a hole shaped like the deterministic planner.
