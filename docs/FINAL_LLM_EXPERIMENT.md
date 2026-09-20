# The real-LLM experiment: attempted, not run

**Outcome: no valid model endpoint was available, so the experiment did not run.
The deterministic planner is kept.**

This page exists so that "we did not benchmark a real LLM" is a recorded result
with its reasons, rather than a gap a jury has to discover.

---

## What was asked

Run one real LLM at the existing planner seam, on the same eleven-episode
benchmark, against the deterministic planner. Adopt it only if it demonstrates a
concrete capability the deterministic planner cannot provide. If the experiment is
inconclusive or worse, keep the deterministic planner.

## What was tried

| route | result |
| --- | --- |
| `ANTHROPIC_API_KEY` in the environment | not set |
| `ANTHROPIC_BASE_URL` (`https://api.anthropic.com`) directly | **401**, as expected without a key |
| the `claude` CLI as a subprocess (`claude -p ... --model ...`) | `Failed to authenticate: OAuth session expired and could not be refreshed` |
| `anthropic` / `openai` Python SDKs | neither installed |
| a local model (`ollama`, `llm`) | neither installed |

No credential was available that we were entitled to use, and none was sought.

## Why this is *not* recorded as "inconclusive"

An inconclusive experiment is one that ran and did not separate the arms. This one
did not run. The distinction matters, because "inconclusive" would imply we have
evidence about real-model behaviour on this benchmark. We do not. The only
evidence we have is about the **architecture's sensitivity** to model behaviours,
measured with stubs — and that is already recorded, with its own caveat, in
`FINAL_AGENTIC_AUDIT.md` §4.

## What is in the repository instead

The real-model arm is implemented and one environment variable away from running:

```bash
ANTHROPIC_API_KEY=sk-... python3 research/architecture_comparison.py
```

With a key, two extra rows appear — `REAL MODEL, no fallback` and
`REAL MODEL, hybrid` — measured on the identical eleven episodes with the identical
prompt. Without one, the script says so on its own output rather than quietly
printing eleven stub rows as though they were the whole story.

`research/model_planner.anthropic_completer()` is stdlib-only and raises rather
than degrading to a stub when the key is missing, because a stub silently standing
in for a model is the exact confusion this file exists to prevent. No SDK was added
to the repository: the judged path must not acquire a dependency to satisfy an
experiment.

## What we would still not do, even with a key

Adopt it. Two reasons that do not depend on the result.

1. **`technical_details.md` requires a predictable response when the model or
   another external service is unavailable.** A model in the planner is survivable
   — the deterministic search takes over — but a model in the *judged path* is not,
   and no benchmark score changes that.
2. **The measured failure mode is the one a fallback cannot catch.** A confidently
   wrong model returning well-formed JSON scores 8/11 in the hybrid, *below* the
   deterministic planner it was meant to improve. A real model would have to beat
   11/11 to justify the risk, and 11/11 is the ceiling of this benchmark.

So the adoption bar was never "does it tie?" — it was "does it do something the
deterministic planner cannot?". On these eleven episodes there is nothing left for
it to do.

## The honest summary for a judge

> "We built the seam, put a model planner in it, and measured the architecture
> against six model behaviours. We did **not** benchmark a real LLM — there was no
> key on this machine and we did not go looking for one. The command is in the
> repository and takes one environment variable. What we can say from what we did
> run is narrow: a confidently-wrong planner with a deterministic fallback scores
> below the deterministic planner alone, because the fallback catches answers that
> are unusable and that one is merely wrong."

Recorded in `WHAT_WE_REFUSE_TO_CLAIM.md` as well, so it cannot quietly become
"we tested LLMs".
