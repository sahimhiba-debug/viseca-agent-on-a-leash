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
from typing import Callable

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


# ---------------------------------------------------------------------------
# A real model, for anyone who has a key. We did not.
# ---------------------------------------------------------------------------

def anthropic_completer(model: str = "claude-haiku-4-5-20251001",
                        max_tokens: int = 256, temperature: float = 0.0):
    """Return a `complete` callable backed by the real Anthropic API.

    Stdlib only, on purpose: adding an SDK to run one experiment would put a
    dependency in the repository that the judged path must never acquire. This is
    research apparatus and stays optional.

    `temperature=0` because the comparison is only worth running if it is
    repeatable. It still will not be byte-identical across runs -- that is a
    property of the model, not of this code, and any published number from it must
    carry a variance rather than a single figure.

    Raises `RuntimeError` when `ANTHROPIC_API_KEY` is unset, rather than silently
    degrading to a stub, because a stub quietly standing in for a model is exactly
    the confusion this whole file exists to avoid.
    """
    import json as _json
    import os
    import urllib.request

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. This is the real-model arm of the "
            "comparison and it needs a key; see docs/archive/FINAL_LLM_EXPERIMENT.md for "
            "what was and was not run.")

    def complete(prompt: str) -> str:
        request = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=_json.dumps({
                "model": model, "max_tokens": max_tokens, "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }).encode(),
            headers={"content-type": "application/json", "x-api-key": key,
                     "anthropic-version": "2023-06-01"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = _json.load(response)
        return "".join(block.get("text", "") for block in payload.get("content", []))

    return complete


def apertus_completer(model: str = "swiss-ai/Apertus-70B-Instruct",
                      base_url: str = "https://api.publicai.co/v1",
                      max_tokens: int = 256, temperature: float = 0.0):
    """The same seam, pointed at Apertus 1.5 70B.

    A second adapter exists for a reason beyond completeness: it is the cheapest
    possible demonstration that the planner really is model-independent. If adding
    one had required touching anything below the seam, the seam would not be real.

    OpenAI-compatible chat completions, stdlib only, and it raises rather than
    degrading to a stub when the key is absent -- for the same reason as
    `anthropic_completer`. A stub silently standing in for a model is the confusion
    this file exists to prevent.

    NOT RUN. No Apertus key was available on this machine and none was sought. See
    `docs/archive/FINAL_LLM_EXPERIMENT.md`; nothing in this repository reports a number
    produced by any real model.
    """
    import json as _json
    import os
    import urllib.request

    key = os.environ.get("APERTUS_API_KEY") or os.environ.get("PUBLICAI_API_KEY")
    if not key:
        raise RuntimeError(
            "APERTUS_API_KEY is not set. This is a real-model arm of the comparison "
            "and it needs a key; see docs/archive/FINAL_LLM_EXPERIMENT.md for what was and "
            "was not run.")

    def complete(prompt: str) -> str:
        request = urllib.request.Request(
            f"{base_url.rstrip('/')}/chat/completions",
            data=_json.dumps({
                "model": model, "max_tokens": max_tokens, "temperature": temperature,
                "messages": [{"role": "user", "content": prompt}],
            }).encode(),
            headers={"content-type": "application/json",
                     "authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = _json.load(response)
        return payload["choices"][0]["message"]["content"]

    return complete
