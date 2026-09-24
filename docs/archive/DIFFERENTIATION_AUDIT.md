# Differentiation audit

Written before any implementation, as the mission requires.

## 1. Table stakes — well built, not differentiating

Every competent team will have these, and ours being solid earns no points:

ALLOW / STEP_UP / BLOCK · per-purchase and rolling spending limits · merchant
restrictions · item restrictions · revocation · an audit history · a mobile UI ·
prompt-injection handling · duplicate detection · natural-language → rules.

## 2. Strong engineering — credibility, not differentiation

A deterministic engine with no model at runtime; one execution boundary; an atomic
consume; lifecycle durability across restart; 628 tests including property and
stateful tests; failure engineering; a 133-case corpus. **This is what makes the rest
believable. It is not itself a story.** A strong team will have much of it.

## 3. Distinctive R&D — real, but mostly invisible

| finding | distinctive? | visible to a judge? |
| --- | --- | --- |
| **The scope model** — a bound is enforceable only where authoritative state exists at the same scope | yes, and it survived falsification | **no** — it is a document |
| **Economic delegation** — a rolling cap is a *rate*, not a total; 4 of 5 official mandates are unbounded in total | yes, and it is measured | **partly** — the Delegate tab says it |
| **Derived fulfilment** — "has this job already been done?", 6 approved purchases worth CHF 1,787 repeating a job described once | yes | **no** — deliberately not in the decision path |
| **Security-object falsification** — eight competing models measured against each other | yes, as method | **no** |
| **Policy verdict vs security verdict** — every check is tagged with *whose authority* it comes from, and two verdicts are computed from one pass | **yes** | **no — computed, exposed by the API, never shown** |

## 4. The hard question

> What could we demonstrate that a competent team could not reproduce by building a
> normal wallet policy engine?

A normal policy engine produces **one verdict**: permitted or not. Ours produces two,
because every rule evaluation carries the authority it came from:

- `source="customer"` — a rule the customer wrote
- `source="safety"` — a control-layer integrity check the customer never opted into

That yields a state a single-verdict engine **cannot express**:

> **Your policy said yes. The wallet stopped it anyway, because it could not trust it.**

On the official 45 events this occurs exactly once — **AU0036, CHF 289.00 at
PixelHarbor**: every rule the customer wrote passed, and the wallet escalated because it
could not tell whether this was the same order placed twice.

And the converse, 24 times: **policy said no, nothing was untrustworthy.** A customer
told "declined" deserves to know which of those two happened, because the remedy is
completely different — change your rules, versus something is wrong with this purchase.

## 5. Candidates, and why each fails or survives

| candidate | verdict |
| --- | --- |
| **A. Delegation boundary** (compare each proposal to a bounded job) | **Reject.** This is the fulfilment work, deliberately *outside* the decision path. Moving it in is an architecture change during a freeze, and the scope model says it needs mandate-scoped state we do not have. |
| **B. Authorization drift** | **Already built** (`drift.py`) and genuinely nice, but it only fires on a re-quote referencing a prior authorization — 0 occurrences in the official data. A differentiator that never fires in the demo is not one. |
| **C. Intent-to-transaction diff** | **Partly built** — the decision cards already show the proposed basket against the compiled rules. Extending it to a full side-by-side is presentation, and it does not express anything the rules do not already say. |
| **D. Delegation consumption** | Same objection as A. |
| **E. Evidence / authority boundary** | **Survives** — and it is the mechanism behind F. Every fact already carries its provenance: customer rule, platform fact, merchant claim, derived fact. |
| **F. Security / policy split** | **Selected.** See below. |

## 6. Why F, specifically

It is the only candidate that is **already enforced in the backend, already computed on
every decision, already exposed by the API, and completely invisible to the judge.** The
work is surfacing, not building.

Against the falsification checklist:

| question | answer |
| --- | --- |
| Is it actually new? | **The concept is not.** Card networks already separate a limit decline from a fraud decline. What is ours is that both verdicts fall out of *one* rule-evaluation pass because every check is tagged with its authority source, and that the customer is shown which one stopped them. |
| Merely a renamed existing feature? | No — a single-verdict engine cannot represent "policy allowed, security did not". |
| Could another team do it in a few hours? | They could add a flag. They could not retrofit authority-tagging onto every check without reworking their evaluation model. |
| Does it solve a real challenge problem? | Yes: the challenge asks the wallet to *explain* its decisions and to handle uncertainty rather than guess. This is the explanation that matters most. |
| Technically enforceable? | It already is. The `source` tag drives both verdicts. |
| Demonstrable? | Yes, on official data: AU0036, one of 45. |
| Understandable in 20 seconds? | Yes: *"Your rules said yes. The wallet still asked."* |
| Works on a phone? | Yes — two lines on an existing card. |
| New complexity? | **Near zero.** No new state, no new endpoint, no new module. |
| Second source of truth? | No — it is derived from the same evaluations that produce the decision. |
| Weakens the security model? | No. It changes no decision; `_decide()` is untouched. |
| Deterministically testable? | Yes. |
| Provable by attack? | Yes — an agent that satisfies every stated rule and is stopped anyway. |

## 7. External precedent — what is NOT ours

- **Card networks / EMVCo** separate authorization declines from fraud/risk declines, with
  distinct reason codes. The *idea* of two verdicts is standard industry practice.
- **Google AP2** separates Intent, Cart and Payment mandates — a related separation of
  concerns, but about mandate types, not verdict provenance.
- **Visa TAP / Mastercard Agentic Tokens** authenticate the agent. We do not; the challenge
  explicitly excludes agent identity.
- **3-D Secure** has a step-up concept driven by risk. Ours is driven by the same thing.

**So we will not claim the concept is novel.** We claim our implementation: two verdicts
derived from one authority-tagged evaluation pass, surfaced to the customer, with the
official corpus showing both directions.

## 8. Complexity budget

| | estimate |
| --- | --- |
| new production LOC | ~10 (pass two fields already computed through one more response shape) |
| new modules | 0 |
| new state | 0 |
| new persistence | 0 |
| new API endpoints | 0 |
| new dependencies | 0 |
| new UI | one badge + one line on the existing decision card |
| new tests | 4–5 |

## 9. Selected mechanism

> **Two verdicts from one pass.** Every check the wallet runs is tagged with the
> authority it comes from — the customer's own rule, or the wallet's integrity check.
> The decision reports both, so a customer always knows *whose* boundary they hit.

## 10. Demo scenario (deterministic, official data)

1. Run **Manipulated agent** (SCEN0004).
2. **AU0037 — CHF 520**: *Your rule stopped this.* Policy blocked; nothing untrustworthy.
3. **AU0036 — CHF 289**: *Your rules allowed this. The wallet stopped it anyway* — it could
   not tell whether this was the same order twice. **This is the screen.**
4. The customer decides. The audit records both the wallet's own answer and the override.

## 11. Security invariant

> The two verdicts are derived from the same rule evaluations that produce the decision,
> and neither can change it. `_decide()` reads outcomes, never sources.

Falsifiable: if a `source` tag could alter a decision, a mutation changing only the tag
would move the official replay. It must not.

## 12. Tests required

1. Both verdicts are present on every decision.
2. On the official corpus, `policy=allow, security=review` occurs and is AU0036.
3. `policy=block, security=allow` occurs (24 times).
4. Changing only a `source` tag changes **no** decision (the invariant).
5. The split survives a refetch and appears in the audit.
