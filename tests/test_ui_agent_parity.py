"""The browser agent and the Python agent must plan identically.

The demo page runs its own copy of the planner, because the wallet's HTTP API must
not import `research/` and so the server cannot plan on the agent's behalf. Two
implementations of the same reasoning is a real risk and the honest way to carry it
is a test, not a comment: the previous version carried a comment claiming the page
used "the same strategy ladder the Python agent uses", and by the time anyone read
it that had stopped being true.

This runs BOTH planners over the SAME fixture -- the offer list written into the
page -- and fails if they choose different baskets, in a different order, for a
different shop, at any point in an episode.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from decimal import Decimal
from pathlib import Path

import pytest

from research.shopping_agent import Beliefs, Mission, Offer, Shop, best_basket

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "index.html"


def _page_js() -> str:
    text = PAGE.read_text()
    return text[text.index("const AG_OFFERS=["):text.index("async function runAgent(){")]


def _fixture_offers() -> list[Offer]:
    """Parse the page's own offer list, so the fixture cannot fall out of step with
    what the demo actually shows."""
    js = _page_js()
    block = js[js.index("const AG_OFFERS=["):js.index("];", js.index("const AG_OFFERS=[")) + 1]
    rows = re.findall(
        r"\{item_id:'([^']+)',name:'([^']+)',category:'([^']+)',"
        r"unit_price:([\d.]+),merchant:'([^']+)',mname:'[^']+',ret:(\d+|null)\}", block)
    assert rows, "could not read the demo page's offer list"
    return [Offer(i, n, c, Decimal(p), m, None if r == "null" else int(r))
            for i, n, c, p, m, r in rows]


class _Fixture(Shop):
    def __init__(self, offers): self._offers = offers
    def search(self, category=None):
        return [o for o in self._offers if category is None or o.category == category]


# The refusal sequences to walk both planners through. Each is a plausible run of
# the wallet's own vocabulary, including the ones the old browser loop could not
# handle at all.
_SEQUENCES = [
    ["amount"],
    ["amount", "amount"],
    ["amount", "amount", "amount"],
    ["merchant"],
    ["order_terms"],
    ["amount", "merchant"],
    ["order_terms", "amount"],
    ["amount", "order_terms", "merchant"],
]


def _python_trace(offers, sequence):
    shop, beliefs = _Fixture(offers), Beliefs()
    mission = Mission("Order groceries", "groceries", target_lines=3)
    trace, found = [], best_basket(shop, mission, beliefs)
    for blocked in sequence:
        if found is None:
            break
        combo, merchant = found
        trace.append({"items": sorted(o.item_id for o in combo), "merchant": merchant})
        if not beliefs.learn([o.line() for o in combo], merchant, [blocked]):
            break
        found = best_basket(shop, mission, beliefs)
    if found is not None:
        trace.append({"items": sorted(o.item_id for o in found[0]), "merchant": found[1]})
    return trace


_NODE = shutil.which("node")


@pytest.mark.skipif(_NODE is None, reason=(
    "node is not installed, so the demo page's planner CANNOT be checked against the "
    "Python one on this machine -- the two may have drifted and this run did not look"
))
@pytest.mark.parametrize("sequence", _SEQUENCES, ids=lambda s: "-".join(s))
def test_the_page_plans_exactly_as_the_python_agent_does(sequence):
    script = _page_js() + """
const seq = JSON.parse(process.argv[1]);
const b = {ruledOut:new Set(), ceiling:null, returnsMatter:false, tried:new Set(), budgetWindowHit:false};
let found = agBest(b), trace = [];
for (const blocked of seq) {
  if (!found) break;
  trace.push({items: found.lines.map(o=>o.item_id).sort(), merchant: found.merchant});
  if (!agLearn(b, found.lines, found.merchant, [blocked])) break;
  found = agBest(b);
}
if (found) trace.push({items: found.lines.map(o=>o.item_id).sort(), merchant: found.merchant});
console.log(JSON.stringify(trace));
"""
    out = subprocess.run([_NODE, "-e", script, json.dumps(sequence)],
                         capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == _python_trace(_fixture_offers(), sequence), (
        f"the demo page and the Python agent disagree after {sequence}"
    )


def test_the_page_halts_on_the_same_refusals_the_python_agent_halts_on():
    """Both must refuse to shop their way out of a session-level flag. A demo that
    kept proposing here would be showing the jury the exact behaviour we claim the
    design prevents."""
    js = _page_js()
    shoppable = re.search(r"AG_SHOPPABLE=new Set\(\[([^\]]*)\]\)", js)
    assert shoppable, "the page no longer distinguishes shoppable refusals"
    from research.shopping_agent import _SHOPPABLE
    assert {s.strip().strip("'") for s in shoppable.group(1).split(",")} == _SHOPPABLE


def test_the_page_does_not_claim_something_it_stopped_doing():
    """The comment that used to sit here said the page ran "the same strategy ladder
    the Python agent uses". There is no ladder any more in either place."""
    assert "strategy ladder" not in PAGE.read_text()


def test_the_demo_endpoint_refuses_a_basket_no_single_shop_could_supply():
    """Quietly re-attributing a mixed basket to a default merchant would hand the
    engine a truthful evaluation of a false description -- the same defect that let
    an earlier agent be "approved" while holding goods from a shop the customer had
    excluded. The endpoint refuses instead."""
    from fastapi.testclient import TestClient
    from wallet_control.api import app

    client = TestClient(app)
    mixed = [{"item_id": "IT0001", "name": "a", "category": "groceries",
              "unit_price": 10, "quantity": 1, "merchant": "ME0001", "return_days": 30},
             {"item_id": "IT0002", "name": "b", "category": "groceries",
              "unit_price": 12, "quantity": 1, "merchant": "ME0005", "return_days": 30}]
    assert client.post("/api/agent/propose",
                       json={"session_id": "t_mixed", "lines": mixed}).status_code == 400

    unknown = [dict(mixed[0], merchant="ME_NOT_A_REAL_SHOP")]
    assert client.post("/api/agent/propose",
                       json={"session_id": "t_unknown", "lines": unknown}).status_code == 400

    good = [mixed[0]]
    ok = client.post("/api/agent/propose", json={"session_id": "t_ok", "lines": good})
    assert ok.status_code == 200
    assert set(ok.json()) == {"authorization_id", "decision", "blocked_by", "awaiting_customer"}
