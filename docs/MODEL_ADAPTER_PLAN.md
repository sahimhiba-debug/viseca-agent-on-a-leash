# Model adapter plan

One seam, three adapters, and a rule that outranks all of them.

> **A planner may be wrong. A planner may not decide.** No adapter below touches
> authorization, and the judged path never depends on any of them.

---

## The seam

`shop()` asks its planner for exactly two methods — `opening()` and `next_step()`.
Anything answering those two is a planner. `ModelPlanner` is passed straight in with
no adapter, which is the evidence this is a seam rather than a hole shaped like the
planner we wrote.

## The three adapters

| adapter | status | judged path | failure mode |
| --- | --- | --- | --- |
| **deterministic** | shipped | **yes** | none — it is the fallback |
| **Anthropic / Claude** | implemented, *never run* | no | degrades to deterministic |
| **Apertus 1.5 70B** | implemented, *never run* | no | degrades to deterministic |

Both model adapters are stdlib-only `complete(prompt) -> str` callables. No SDK is
added: the judged path must not acquire a dependency to satisfy an experiment.

## Degradation, specified

Every failure collapses to *"nothing usable"*, and nothing usable ever widens an
errand. Measured against six behaviours:

| behaviour | hybrid result |
| --- | --- |
| competent | 11/11 — a tie with deterministic, for 21 network calls |
| unavailable / times out | 11/11 — fallback every call |
| hallucinates item ids | 11/11 — parse fails closed |
| replies in prose | 11/11 — parse fails closed |
| flaky 50% | 11/11 |
| **confidently wrong, well-formed** | **8/11 — worse than no model** |

That last row is why the deterministic planner ships. A fallback catches answers
that are *unusable*; it cannot catch one that is merely *wrong*.

## What is NOT claimed

**No real language model has been benchmarked.** The table above is measured with
stubs standing in for model behaviours — it measures the *architecture's*
sensitivity, not any model's ability. Re-checked during the pre-jury audit:
`ANTHROPIC_API_KEY` unset, the API returns **401**, the CLI's OAuth will not refresh.

A real run is one environment variable away:

```bash
ANTHROPIC_API_KEY=...  python3 research/architecture_comparison.py
APERTUS_API_KEY=...    python3 research/architecture_comparison.py
```

With a key the script adds real-model rows on the identical eleven episodes with the
identical prompt. Without one it says so on its own output rather than printing stub
rows as though they were the whole story.

## Prompt hygiene

The prompt carries the shop's own offers, the mission, the classes that refused, and
the agent's own refused total. It carries no rule value.

It *does* carry the customer's instruction, which contains "CHF 120" — because the
errand is the customer's sentence. The shipped planner never reads it; a model
planner would. Stated here rather than discovered by a judge.
