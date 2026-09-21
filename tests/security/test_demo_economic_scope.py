"""What the demo mandate permits, and that the demo never implies more.

A pre-jury attack proposed the same CHF 108 basket sixty times and every one was
approved: CHF 6,480 under a mandate whose headline number is CHF 120. That looks
like a bypass and is not one. The mandate said *"keep each order at or below
CHF 120"*, sixty orders of CHF 108 each satisfy it, and there was no rule a
SEQUENCE of orders could violate. The wallet enforced exactly what it was told.

The fix is therefore not in the engine. It is that the demo's own mandate was the
weakest shape the protocol allows — a per-order ceiling and nothing pacing it —
which is a poor thing to hand a jury that will click the button twice.

The mandate now also carries the rolling cap the protocol already supports and
SCEN0001 already uses. Same engine, same agent, same attack: bounded at CHF 216.

This is NOT a total-spend cap and nothing here should be read as one. A rolling
window re-opens. `WHAT_WE_REFUSE_TO_CLAIM.md` says so and the delegation panel on
the page says so in the customer's own words.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wallet_control.api import _AGENT_DEFAULT_INSTRUCTION, app
from wallet_control.policy_compiler import compile_instruction

client = TestClient(app)

BASKET = [
    {"item_id": "IT0018", "name": "Fresh produce order", "category": "groceries",
     "unit_price": 30, "quantity": 1, "merchant": "ME0001", "return_days": 30},
    {"item_id": "IT0020", "name": "Family breakfast supplies", "category": "groceries",
     "unit_price": 32, "quantity": 1, "merchant": "ME0001", "return_days": 30},
    {"item_id": "IT0019", "name": "Pantry restock", "category": "groceries",
     "unit_price": 46, "quantity": 1, "merchant": "ME0001", "return_days": 30},
]


def _rules():
    return compile_instruction(_AGENT_DEFAULT_INSTRUCTION).hard_rules


def test_the_demo_mandate_paces_spending_as_well_as_bounding_each_order():
    per_purchase = [r for r in _rules()
                    if r.field == "authorization.billing_amount_chf" and r.scope == "purchase"]
    per_period = [r for r in _rules()
                  if r.field == "authorization.billing_amount_chf" and r.scope == "period"]
    assert per_purchase, "the demo lost its per-order ceiling"
    assert per_period, (
        "the demo mandate has no rolling cap, so clicking the button repeatedly is "
        "approved without bound — correct, but a poor thing to hand a jury")
    assert per_period[0].period_days == 7


def test_clicking_buy_sixty_times_is_bounded_by_the_rolling_cap():
    """The exact jury attack: hammer the button and watch the total."""
    approved, outcomes, first_refusal = 0.0, {}, None
    for attempt in range(60):
        view = client.post("/api/agent/propose",
                           json={"session_id": "econ_hammer", "lines": BASKET}).json()
        outcomes[view["decision"]] = outcomes.get(view["decision"], 0) + 1
        if view["decision"] == "allow":
            approved += 108.0
        elif first_refusal is None:
            first_refusal = (attempt + 1, view["blocked_by"])

    cap = next(r.value for r in _rules()
               if r.field == "authorization.billing_amount_chf" and r.scope == "period")
    assert approved <= cap, f"approved CHF {approved} against a stated CHF {cap} cap"
    assert outcomes["block"] > 0
    # `budget_window`, not `amount`. The two used to be the same class, so the agent
    # answered "this order is too large" and "the allowance is used up" identically.
    # They call for different moves and now read differently.
    assert first_refusal is not None and first_refusal[1] == ["budget_window"], first_refusal


def test_the_demo_trace_still_shows_two_non_price_refusals():
    """Pacing must not have bought safety at the cost of the story: the first run
    is unaffected, because only one of its three attempts is ever approved."""
    from research.planning_benchmark import _wire  # noqa: F401  (path setup)
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the page's planner cannot be run here")

    page = (Path(__file__).resolve().parents[2] / "ui" / "index.html").read_text()
    js = page[page.index("const AG_OFFERS=["):page.index("async function runAgent(){")]
    script = js.replace("\nconst ", "\nglobalThis.") + """
const b={ruledOut:new Set(),ceiling:null,returnsMatter:false,tried:new Set(),budgetWindowHit:false};
const out=[];
for (const blocked of [['merchant'],['order_terms'],[]]) {
  const s=agBest(b); if(!s) break;
  out.push({merchant:s.merchant, total:s.lines.reduce((a,o)=>a+o.unit_price,0)});
  if(!blocked.length) break;
  agLearn(b,s.lines,s.merchant,blocked);
}
console.log(JSON.stringify(out));
"""
    trace = json.loads(subprocess.run([node, "-e", script], capture_output=True,
                                      text=True, timeout=30).stdout)
    assert [t["total"] for t in trace] == [47, 107, 108], trace


def test_we_never_call_the_rolling_cap_a_total():
    """A window re-opens. The one thing the demo must never imply is that CHF 300
    is the most that can ever be spent."""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[2] / "ui" / "index.html").read_text()
    assert "does not cap the total" in page, (
        "the delegation panel stopped saying that a rolling window re-opens")
    assert "Total amount — the rule format cannot express one" in page


def test_repeated_errands_accumulate_against_the_rolling_cap():
    """The behaviour a judge actually produces by pressing the button again.

    Every press used to open a fresh session, and a session is where rolling spend
    is counted -- so repeated errands were approved without bound and the seven-day
    cap could never be reached on screen. The page now keeps one session per
    mandate, which makes the rolling window the only thing on the whole page that
    demonstrates itself.

    Measured through the API the page uses: 108 + 108 + 62 = 278 against a stated
    CHF 300, and the third errand is SMALLER because the agent was refused and
    fitted itself to a remaining budget it was never told.
    """
    session = "econ_accumulate"
    approved = []
    for _ in range(4):
        for _ in range(4):
            view = client.post("/api/agent/propose",
                               json={"session_id": session, "lines": BASKET}).json()
            if view["decision"] == "allow":
                approved.append(108.0)
                break
            if view["blocked_by"] == ["amount"]:
                smaller = BASKET[:1]
                view = client.post("/api/agent/propose",
                                   json={"session_id": session, "lines": smaller}).json()
                if view["decision"] == "allow":
                    approved.append(30.0)
                break

    cap = next(r.value for r in _rules()
               if r.field == "authorization.billing_amount_chf" and r.scope == "period")
    assert sum(approved) <= cap, f"CHF {sum(approved)} approved against CHF {cap}"
    assert len(approved) >= 2, "the cap now bites before a second errand completes"


def test_the_page_keeps_one_session_per_mandate_not_per_click():
    from pathlib import Path

    page = (Path(__file__).resolve().parents[2] / "ui" / "index.html").read_text()
    assert "if (!AGENT_SESSION) AGENT_SESSION = 'ui_' + Date.now();" in page, (
        "the page opens a fresh session per click again, so rolling spend resets "
        "every time and the cap in the mandate can never be reached on screen")


def test_the_page_discloses_that_a_new_session_restarts_the_counter():
    """The rolling cap is per RUN. A customer reading "Maximum per 7 days: CHF 300"
    would not guess that starting another errand session resets it to zero, and
    until a pre-jury audit measured it -- CHF 2,160 across ten sessions against a
    stated CHF 300 -- nothing on screen said so. The panel said the window re-opens
    over TIME, which is the less surprising half."""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[2] / "ui" / "index.html").read_text()
    assert "counter starts again in each one" in page, (
        "the delegation panel no longer discloses that spend is scoped to one session")
    assert "within one errand session" in page


def test_the_agent_fits_the_remaining_allowance_then_stops():
    """Workstream 6, end to end, through the API the page uses.

        errand 1   CHF 108  allow
        errand 2   CHF 108  allow
        errand 3   CHF 108  BLOCK (budget_window) -> replan -> CHF 62 allow
        errand 4   "what is left is less than anything worth buying"

    The agent fits a remaining allowance it was never told. It learns only the KIND
    of limit it hit; CHF 300, the remainder, and the window length never reach it.
    """
    session = "ws6"
    approved, stopped = [], None
    for _ in range(5):
        lines = list(BASKET)
        for _ in range(4):
            view = client.post("/api/agent/propose",
                               json={"session_id": session, "lines": lines}).json()
            if view["decision"] == "allow":
                approved.append(sum(l["unit_price"] for l in lines))
                break
            if "budget_window" in view["blocked_by"] or "amount" in view["blocked_by"]:
                if len(lines) == 1:
                    stopped = view["blocked_by"]
                    break
                lines = lines[:-1]          # the agent's "buy less" move
                continue
            break
        if stopped:
            break

    assert approved[:2] == [108.0, 108.0], approved
    assert 0 < approved[2] < 108.0, f"the third errand did not shrink to fit: {approved}"
    cap = next(r.value for r in _rules()
               if r.field == "authorization.billing_amount_chf" and r.scope == "period")
    assert sum(approved) <= cap
    assert stopped == ["budget_window"], stopped


def test_exhaustion_is_reported_as_an_allowance_not_as_a_bad_shop():
    """"No basket this shop can supply" would be wrong and misleading -- it sends a
    customer looking for a better shop when the shop was never the problem."""
    from pathlib import Path

    page = (Path(__file__).resolve().parents[2] / "ui" / "index.html").read_text()
    assert "spending allowance for this period" in page
    assert "once the window moves on" in page
