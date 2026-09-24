# Product evolution — three directions, one choice

The security work is done and is not repeated here. The question now is what this
*is* as a product, and which version of it a senior engineer would remember.

Current shape: `agent → proposal → wallet → decision`.
Target shape: `mission → observe → plan → propose → feedback → replan → execute`.

---

## What we already have that competitors will not

Worth naming before designing, because the right direction is the one that makes
these *visible* rather than the one that adds features beside them.

1. **The agent adapts without ever being told a number.** It settles CHF 7.50
   against a hidden CHF 137 ceiling; it fits a remaining rolling budget it was never
   told. Not a claim — measured.
2. **A benchmark written before the agent was fixed, which the agent failed.** 5/11
   → 11/11, with the old planner still scoring 5/11 on the same episodes.
3. **A measured answer to "why no LLM".** A confidently-wrong model *with* a
   fallback scores 8/11 — below the deterministic planner.
4. **An authority boundary that has survived four self-inflicted breaches**, each
   found, fixed and written up.

The weakness is not the engineering. It is that almost none of this is *visible* in
ninety seconds.

---

## Direction A — "The Protocol"

Elevate the interface into a versioned wire protocol with first-class `Mission`,
`Proposal`, `Decision`, `Feedback`, `Intervention`, `Authority`. Publish it as a
spec. Any agent can plug in.

| criterion | score |
| --- | --- |
| strengthens the leash | **high** — the boundary becomes an interface, not a convention |
| makes commerce more useful | medium |
| clarifies authority | **high** |
| judge comprehension in 90s | **low** — protocols are invisible on screen |
| memorable moment | low |

**Verdict: necessary, not sufficient.** A protocol nobody can see does not win a
demo. But the objects are real and the planner needs them anyway.

## Direction B — "The Control Plane"

A live mission console: watch the agent work, see each proposal and verdict, the
agent's reasoning, and intervene.

| criterion | score |
| --- | --- |
| strengthens the leash | medium |
| makes commerce more useful | **high** |
| clarifies authority | **high** — if the layout carries it |
| judge comprehension | **high** |
| memorable moment | medium |

**Verdict: the right surface, the wrong centre.** The brief explicitly warns against
dashboards, and a console with nothing surprising in it is a dashboard. It needs a
thesis to display.

## Direction C — "Swap the brain, same leash"

The headline capability is a **brain selector**: deterministic, language model, or
deliberately adversarial. Same mission, same wallet, three different intelligences —
and the wallet's authority is invariant across all three.

| criterion | score |
| --- | --- |
| strengthens the leash | **very high** — it is the thesis, executable |
| makes commerce more useful | medium |
| clarifies authority | **very high** |
| judge comprehension | **high** — one control, one obvious meaning |
| memorable moment | **very high** |

**Verdict: the strongest single idea.** It converts our adversarial-planner research
from a test suite into the product's central claim. No competing team will have it,
because it only makes sense if your authority boundary is genuinely separable — and
most teams put the model in the decision path.

---

## Chosen architecture — "Mission Control"

**C as the thesis, B as the surface, A as the substrate.** Not a compromise: each
layer is load-bearing.

```
        MISSION            the customer delegates an errand, in their words
           |
   [ BRAIN: deterministic | model | adversarial ]     <-- swappable, C
           |
   observe -> plan -> PROPOSE                          <-- goal-oriented, A
           |
        WALLET             the one authority, unchanged by the brain above it
           |
   ALLOW / STEP_UP / BLOCK + FEEDBACK                  <-- typed, minimal, A
           |
   replan  or  hand back to the customer
```

The demo is a single mission running under three brains. The wallet's verdicts are
the constant. **Different intelligence, same authority** — stated once, then
demonstrated rather than argued.

### Why this wins a room of senior engineers

- It is the only configuration where *"the agent may be unreliable"* stops being a
  disclaimer and becomes a **feature you can toggle**.
- It makes the boundary falsifiable on stage: pick the adversarial brain and try to
  break it in front of them.
- It is reproducible — every brain is deterministic or degrades to one.

---

## What we will build, ranked by (payoff ÷ risk)

| # | change | payoff | risk | verdict |
| --- | --- | --- | --- | --- |
| 1 | **Typed feedback**: split `amount` into *this order is too large* vs *the rolling window is used up* | **high** — the agent finally replans differently for different economics; Workstreams 5+6 | low — one extra class, no value leaked | **build** |
| 2 | **Brain selector** (deterministic / model / adversarial) in the API and UI | **very high** | low — all three planners already exist behind one seam | **build** |
| 3 | **Adversarial brain as a product capability**, eight attacks against the live wallet | **very high** | low — research exists | **build** |
| 4 | **Mission Control UI**: one vertical narrative from mandate to execution | **high** | medium — UI work | **build** |
| 5 | **Protocol objects** (`Mission`, `Proposal`, `Decision`, `Feedback`) as real types | medium | low | **build, minimally** |
| 6 | Apertus adapter alongside Anthropic | medium | low | **build** (adapter only; no fabricated results) |
| 7 | Multi-mission scheduling / budgets across missions | low | high | **reject** — invents scope the protocol lacks |
| 8 | Agent-to-agent negotiation | low | high | **reject** — not in the challenge |
| 9 | Learned utility weights | low | high | **reject** — unreproducible, and the objective is the thing we want legible |

### Explicitly rejected, and why

- **Anything that moves authorization toward the planner.** The whole value is that
  it cannot.
- **A "total spend" control.** The rule vocabulary cannot express one. Adding a UI
  for it would be inventing a guarantee.
- **Live model calls in the judged path.** `technical_details.md` requires a
  predictable response when the model is unavailable.
