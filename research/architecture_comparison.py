"""Run the planning benchmark three ways and print the table.

The point is to answer "would a model make this agent better" with a number instead
of an opinion. The stub models below stand in for a real one's behaviour, including
the behaviour that matters most -- being wrong, and being unavailable.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research import planning_benchmark as B
from research.model_planner import ModelPlanner
from research.shopping_agent import DETERMINISTIC


def _offers(prompt: str) -> list[dict]:
    """Read the offer block. Only the lines after "Offers:" -- the errand itself
    mentions CHF, and a stub that parses it as an offer is measuring my parser
    rather than the architecture."""
    block = prompt.split("Offers:\n", 1)[1].split("\nReply with JSON", 1)[0]
    rows = []
    for line in block.splitlines():
        parts = line.split()
        if "CHF" not in parts:
            continue
        rows.append({"id": parts[0],
                     "price": float(parts[parts.index("CHF") + 1]),
                     "shop": parts[parts.index("at") + 1],
                     "ret": parts[-1].split("=")[1]})
    return rows


def competent(prompt: str) -> str:
    """A model that reads the prompt properly: avoids refused shops, prefers stated
    return windows when told they matter, keeps to one shop, and spends little."""
    rows = _offers(prompt)
    refused = prompt.split("Shops already refused: ")[1].split("\n")[0]
    refused = set() if refused == "none" else {
        s.strip().strip("'[]") for s in refused.split(",")}
    rows = [r for r in rows if r["shop"] not in refused]
    if "Returns have been an issue: True" in prompt:
        rows = [r for r in rows if r["ret"] not in {"0", "None"}]
    cap = prompt.split("Spend strictly less than: ")[1].split("\n")[0]
    if not rows:
        return "{}"
    best = None
    for shop in sorted({r["shop"] for r in rows}):
        here = sorted((r for r in rows if r["shop"] == shop), key=lambda r: r["price"])[:3]
        while here and cap != "no limit known" and sum(r["price"] for r in here) >= float(cap):
            here.pop()
        if here and (best is None or len(here) > len(best)
                     or (len(here) == len(best)
                         and sum(r["price"] for r in here) < sum(r["price"] for r in best))):
            best = here
    return json.dumps({"item_ids": [r["id"] for r in best]}) if best else "{}"


def careless(prompt: str) -> str:
    """A model that ignores the refusals it was told about and just picks cheap. The
    single most likely way a real one goes wrong here."""
    rows = sorted(_offers(prompt), key=lambda r: r["price"])[:3]
    return json.dumps({"item_ids": [r["id"] for r in rows]})


def hallucinating(prompt: str) -> str:
    return json.dumps({"item_ids": ["ITEM_THAT_DOES_NOT_EXIST", "ALSO_NOT_REAL"]})


def chatty(prompt: str) -> str:
    return "Certainly! Here is a sensible basket for you:\n- Fresh produce\n- Milk"


def unavailable(prompt: str) -> str:
    raise TimeoutError("the model endpoint did not answer")


def flaky(prompt: str) -> str:
    return competent(prompt) if random.random() < 0.5 else unavailable(prompt)


ARCHS = [
    ("deterministic (shipped)", None, None),
    ("model only, competent", competent, False),
    ("model only, careless", careless, False),
    ("model only, hallucinating", hallucinating, False),
    ("model only, replies in prose", chatty, False),
    ("model only, unavailable", unavailable, False),
    ("hybrid, competent", competent, True),
    ("hybrid, careless", careless, True),
    ("hybrid, hallucinating", hallucinating, True),
    ("hybrid, unavailable", unavailable, True),
    ("hybrid, flaky 50%", flaky, True),
]


def main() -> int:
    random.seed(20260920)
    print(f"{'architecture':30s} {'score':>7s} {'calls':>6s} {'fell back':>10s}  failed")
    for label, complete, fallback in ARCHS:
        if complete is None:
            planner, model = DETERMINISTIC, None
        else:
            model = planner = ModelPlanner(complete=complete, fallback=fallback)
        passed, failed = 0, []
        for ep in B.episodes():
            r = B.run_episode(ep, planner=planner)
            passed += r.passed
            if not r.passed:
                failed.append(ep.key)
        calls = model.calls if model else 0
        fell = model.fallbacks if model else 0
        print(f"{label:30s} {passed:4d}/11 {calls:6d} {fell:10d}  {','.join(failed) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
