# Final agentic audit

**Is this a real agentic shopping system, or a deterministic workflow we call an
agent?** Answered by building a benchmark that could fail it, and then failing it.

This document replaces an earlier version of itself that claimed the agent did
"search / planning" and "goal-directed replanning". Both claims were false, and the
way we found out is the only part of this worth reading.

---

## 1. The honest classification

The previous audit assessed the agent by describing it. Describing an agent tells
you what its author intended. So this time the first step was a benchmark
(`research/planning_benchmark.py`), written **before** any code changed, over eleven
small worlds where the cheapest basket is usually the wrong one.

The agent as it stood scored **5/11**. More damning than the score: across all
eleven episodes it used exactly **two** distinct moves — *swap for the cheapest*
(once) and *drop the dearest* (seven times). The merchant-switch and category-filter
rungs of its own documented ladder never fired at all.

| capability | claimed before | actually measured | now |
| --- | --- | --- | --- |
| **A** workflow automation | yes | yes | yes |
| **B** search over alternatives | **yes** | **no** — greedy descent on price, no candidate set | yes — bounded exhaustive search per shop |
| **C** explicit objective function | implied | **no** — "better" meant only "cheaper" | yes — one function, stated in one place |
| **D** tool use | honestly: no | no — a module-level CSV read | yes — `Shop.search()` called on every step |
| **E** environment feedback | yes | **no** — availability frozen before the first attempt | yes |
| **F** goal-directed replanning | **yes** | **no** — no goal existed to be directed *by* | yes — the objective is what the search maximises |
| **G** uncertainty handling | yes | partial | yes |
| **H** autonomous stopping | yes | yes | yes |
| **I** policy-aware adaptation | yes | partial — only price | yes, on every constraint class it may act on |
| **J** model-based reasoning | no | no | **no, and now measured** — §4 |

**Would a senior AI engineer call the old one an agent?** They would call it a
*reactive repair loop*: agentic in architecture (perceive, decide, act, observe,
revise, with bounded autonomy and a human handoff) and not in competence. That is a
fair description and we should have written it ourselves.

**Would they call this one an agent?** A goal-directed, tool-using, bounded-
autonomy planning agent with an explicit objective and no model. The absence of a
model is a measured decision (§4), not a gap.

---

## 2. Three defects, not six failures

The six failing episodes were three causes.

**No objective function** (C, E, I, K). The agent's only notion of "better" was
"cheaper". Episode K is the whole argument in one case: three baskets look buyable,
exactly one is allowed, and it is the **dearest**. The agent deleted the right
answer first, then walked down the price ladder into a shop the customer had
excluded. Ranking by price is not ranking by what the customer asked for.

**No substitution except on price** (C, D, E, I, K). Told `blocked_by=["merchant"]`
with a familiar-merchant alternative in the same catalogue, it replied "only the
customer can resolve this". A ladder can only subtract, so every constraint it had
no rung for became a human handoff while a perfectly good alternative sat
unexamined.

**No observation of the environment** (G). `Mission.unavailable` was a frozenset
captured before the first proposal. An item sold out mid-episode, the agent
re-proposed it two attempts later, and the wallet approved — correctly, since stock
is none of the wallet's business. Nothing but the agent could have caught that.

A fourth defect surfaced only when the benchmark rendered the old agent faithfully:
it chose items from a catalogue and a merchant from the mission and **never checked
them against each other**. On C, E, I and K it reported *approved* while holding
goods from the excluded shop. The wallet had approved a truthful evaluation of an
untruthful proposal. The wallet cannot catch this — nothing in the API lets it
verify that a merchant stocks an item — so it is an agent-side integrity property
and we claim it as one, in `FINAL_CLAIMS_REGISTER.md`.

---

## 3. What changed

An **objective function**, stated once, in the order the customer would: do more of
the errand; prefer goods that can be sent back, once a refusal showed that matters;
and only then spend less. *Price is last.* A **search** over candidate baskets,
one shop at a time, bounded, replacing the ladder. A **tool**, called on every
replanning step, so the shop is looked at rather than remembered.

**5/11 → 11/11.** The old agent, re-measured against the corrected benchmark, still
scores 5/11.

What it learns from a refusal stays deliberately small, because every fact in it was
paid for with one of the customer's refused purchases. `ceiling` is not the
customer's limit; it is *"strictly less than a total I already tried"*, which is all
a refusal can honestly say. It falls monotonically and never arrives.

One regression the search introduced and the tests caught: it would happily answer a
duplicate or session-integrity flag with a different basket — an agent responding to
"you look like a runaway" by rephrasing itself until the wallet stops noticing.
Constraints on the **purchase** are shoppable; constraints on the **agent** are not,
and the latter now halt unconditionally even when a valid alternative exists.

---

## 4. The model question, measured

`technical_details.md` requires a predictable response when the model or another
external service is unavailable. That forbids *depending* on a model, not having
one. So `research/model_planner.py` puts one at the same seam and
`research/architecture_comparison.py` runs the benchmark eleven ways:

| architecture | score | model calls | fell back |
| --- | --- | --- | --- |
| deterministic (shipped) | **11/11** | 0 | 0 |
| model only, competent | 11/11 | 21 | 0 |
| model only, careless | 3/11 | 16 | 5 |
| model only, hallucinating | 1/11 | 11 | 11 |
| model only, replies in prose | 1/11 | 11 | 11 |
| model only, unavailable | 1/11 | 11 | 11 |
| hybrid, competent | 11/11 | 21 | 0 |
| **hybrid, careless** | **8/11** | 21 | 10 |
| hybrid, hallucinating | 11/11 | 21 | 21 |
| hybrid, unavailable | 11/11 | 21 | 21 |
| hybrid, flaky 50% | 11/11 | 21 | 8 |

Three readings. The best a model achieves is a **tie**, bought with twenty-one
network calls. Every failure that makes a model *unusable* is survivable — which
means the hybrid's good scores are the deterministic agent's scores plus latency.
And the failure real models actually have, *being confidently wrong in well-formed
JSON*, is exactly the one a fallback cannot catch: the net is woven to catch
unusable answers, and this answer is merely wrong. It takes the hybrid to 8/11,
**below the planner it was meant to improve**.

We ship the deterministic planner. The decision is now a measurement somebody can
re-run and disagree with.

Two things worth keeping from building it. The seam needed **no adapter** — `shop()`
asks a planner for two methods and `ModelPlanner` is passed straight in, which is
the evidence it is a seam and not a hole shaped like the planner we wrote. And the
halt rule stayed out of the planner's hands: whether a refusal may be answered by
shopping at all is a property of what the wallet objected to, and a model that could
talk its way past it would be the entire risk of having one.

---

## 5. What the agent still cannot do

- **`target_lines` is a thin notion of "the errand".** Coverage counts lines, not
  whether the household actually has what it needs. The agent buys the cheapest N
  grocery lines; a real one would model a shopping list. We do not claim otherwise.
- **It discovers the acceptable shop by being refused.** It has no prior over which
  merchants a customer has used, and it must not — that fact belongs to the wallet.
  So finding a familiar shop costs one refused purchase. Bounded, but not free.
- **It cannot tell which line in a basket caused an `order_terms` refusal.** It
  re-ranks on the whole basket's worst published return window instead. Sufficient
  here, and not the same thing as attribution.
- **The search is bounded** at 5 lines, 12 offers and 50 shops. Beyond that it is
  examining a subset, and a sufficiently adversarial catalogue can hide the best
  basket outside it.
- **Nothing verifies that the shop exists.** The agent checks that offers are
  plausible; it cannot check that they are real.
- **The customer's instruction contains the limit, and the agent holds it.** The
  errand is the customer's own sentence — "at or below CHF 120" and all. The
  *wallet* never tells the agent a rule value, and the shipped planner never reads
  the instruction at all (it uses only the category and how many lines count as the
  errand done). But a **model** planner reads it straight out of the prompt, which
  is a further reason the model is not the one we ship. An earlier version of the
  test asserting prompt hygiene sliced that line out of the assertion; it now
  asserts the leak explicitly and checks only the wallet-derived part for cleanliness.

---

## 6. Where to look

| | |
| --- | --- |
| the benchmark, and the baseline it recorded | `research/planning_benchmark.py` |
| the agent | `research/shopping_agent.py` |
| the model planner and the comparison | `research/model_planner.py`, `research/architecture_comparison.py` |
| the benchmark as a regression gate | `tests/test_planning_benchmark.py` |
| hostile shops and belief poisoning | `tests/security/test_agent_tool_boundary.py` |
| hostile planners | `tests/security/test_agent_planner_boundary.py` |
| the model seam | `tests/security/test_model_planner_seam.py` |
| the demo page's planner, pinned to the Python one | `tests/test_ui_agent_parity.py` |
