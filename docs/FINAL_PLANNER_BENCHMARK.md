# The planning benchmark

`research/planning_benchmark.py` — eleven episodes, built **before** the agent was
changed, so that it could genuinely fail. It did: **5/11**.

Run it:

```bash
python3 research/planning_benchmark.py
```

---

## Why it exists

The previous agentic audit assessed the agent by *describing* it, and concluded it
did "search / planning" and "goal-directed replanning". It did neither. Describing
an agent tells you what its author intended; only a benchmark tells you what it
does. So the rule for this one was: write the episodes first, run them, and publish
whatever comes out.

The episodes are adversarial in one specific way. **In five of eleven, the cheapest
valid-looking basket is the wrong basket** — because it is at a shop the customer
excluded, or because the goods cannot be sent back. An agent whose only notion of
"better" is "cheaper" cannot pass those, and cannot be made to pass them by tuning.

Nothing references a scenario id. Each episode is a small world plus a customer
instruction, compiled by the real policy compiler and decided by the real decision
engine. The agent is given no privileged knowledge of either.

---

## The eleven

| | episode | what it tests |
| --- | --- | --- |
| A | spend under a ceiling | a valid basket exists; find one |
| B | preferred item unavailable | the dearest line cannot be bought at all |
| C | cheaper stranger vs pricier familiar | **cheapest is wrong** — the customer asked for a familiar shop |
| D | one product cannot be returned | the cheapest line fails a non-price constraint |
| E | cheapest basket violates another rule | same, with a tighter ceiling |
| F | merchant disappears after the first proposal | the environment changes mid-episode |
| G | an item sells out after the first proposal | does the agent look at the shop again? |
| H | each item fine, the combination is not | the constraint is on the basket, not the line |
| I | change one property, keep the goal | same goods, wrong shop — fix the shop |
| J | no valid basket exists | stop, do not loop |
| K | several valid baskets | **the multi-objective case: cheapest is wrong twice over** |

Episode K is the whole argument in one case. Three baskets look buyable; exactly one
is allowed; and it is the **dearest**.

---

## Results

| agent | score | notes |
| --- | --- | --- |
| the old repair ladder | **5/11** | measured before anything changed |
| the old ladder, re-measured on the corrected benchmark | **5/11** | see *One fixture bug*, below |
| the search-based agent (shipped) | **11/11** | |

Across all eleven episodes the old agent used **two** distinct moves: *swap for the
cheapest* (once) and *drop the dearest* (seven times). The merchant-switch and
category-filter rungs of its own documented ladder never fired at all.

The three defects behind the six failures, and the fourth the benchmark exposed on
the way, are set out in `FINAL_AGENTIC_AUDIT.md` §2.

### One fixture bug, disclosed

Between the two runs a bug in *this file* was found and fixed: it emitted the
seller's returnable flag as English `"yes"`/`"no"` where the platform's vocabulary
is `"true"`/`"false"`, so it fell through to "the seller said nothing" and episode D
escalated to a human on attempt one. That measured the fixture, not the agent.

The honest thing to do with a corrected benchmark is to re-run the **old** agent
against it, which we did. It still scored 5/11, and its failures got *worse* under
the faithful rendering: on C, E, I and K it reported **approved** while holding the
excluded shop's goods, because it chose items from a catalogue and a merchant from
the mission and never checked them against each other.

---

## What the benchmark is, and is not

It **is** a regression gate. `tests/test_planning_benchmark.py` runs every episode
and additionally asserts the benchmark is not trivially satisfiable — that at least
one episode must end in a handoff, that at least five have excluded items, and that
episode K's correct answer is still the most expensive one (the episode proves
nothing the moment that stops being true).

It is **not** a score to optimise, and it is not the official replay. The official
replay (45 events, 19/2/24) remains the regression boundary for the wallet and is
untouched by any of this work. The benchmark measures the **agent**, which holds no
authority and decides nothing about money.

It is **not** large. Eleven episodes over small synthetic worlds is a sample chosen
to be diagnostic, not representative. It cannot tell you how the agent behaves in a
real catalogue, and we do not claim it does.

---

## Three architectures

`research/architecture_comparison.py` runs the same benchmark eleven ways to answer
whether a model belongs in the planner. The table and the reading are in
`FINAL_AGENTIC_AUDIT.md` §4. The short version: the best a model achieves is a tie,
and a confidently-wrong model *with a fallback* scores **8/11** — below the
deterministic planner it was meant to improve.

The stubs there are stubs. No API was called and no language model was benchmarked;
what is measured is the architecture's sensitivity to model behaviours, not any
model's ability. That distinction is recorded in `WHAT_WE_REFUSE_TO_CLAIM.md`.
