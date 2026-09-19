# Autonomous R&D final report

## 1. Executive summary

A falsifiable question — *same transactions, same rules, different order: can the
security meaning differ?* — turned out to have a measured answer: **yes**, and the
consequence is a real breach of the only economic control the customer actually has.

> **Finding.** The customer's rolling spending cap can be exceeded by up to **60%**
> while every individual decision is locally correct and every requirement of the
> official specification is followed.
>
> **Cause.** A rolling window evaluated *backward from the purchase being judged* is
> correct only if decisions are made in chronological order and none is deferred. The
> official protocol violates both: nothing guarantees arrival order, and `step_up`
> defers by design, re-entering the ledger later at its **original** timestamp.
>
> **Fix.** A purchase must fit every window that **contains** it, not the window that
> **ends** at it. One pure function over state we already persist.

Measured: 367/400 random arrival orders breach a CHF 300 / 7-day cap (worst CHF 389);
with strictly chronological delivery, a deferred step-up reaches **CHF 480 against CHF
300**. After the fix: **0/400**, worst window exactly CHF 300. **Official replay
unchanged.**

## 2. Current architecture

Two authoritative objects — the mandate snapshot and the decision ledger — plus one
execution boundary. Full description in `PRODUCT_ARCHITECTURE.md` and
`CODEBASE_GUIDE.md`. 4,875 runtime lines across 19 modules; research apparatus
separated into `research/` and asserted unreachable from the runtime by test.

## 3. Current security model

Ten invariants (`SENIOR_REVIEW_BASELINE.md` §"Critical invariants"), 24 claims
classified in `SENIOR_SECURITY_CLAIMS_AUDIT.md`, governed by one discipline: *every
security-relevant fact is authoritative-and-recorded, or a deterministic function of
authoritative recorded facts.*

## 4. Current limitations

Six, carried forward and unchanged by this pass: cross-run mandate reuse, account-scope
unenforceability, process-local single-use, the cancelled-retry blind spot, unverifiable
merchant claims, and an unauthenticated step-up channel.

## 5. Threat-space map

`THREAT_SPACE_FINAL.md`. Seventeen boundaries. The empty cell this pass found is not a
missing control but a **wrong one**: the rolling-window check is present, tested, and
incorrect under the protocol's own timing semantics.

## 6. Authority and scope map

Re-tested every candidate scope. No new scope survives; the three-scope conclusion
stands (`FINAL_SECURITY_SCOPE_MODEL.md`). What this pass adds is orthogonal: the
**period** bound is correctly run-scoped — the platform defines it that way — but its
*evaluation* was wrong within that scope.

## 7. Policy compliance vs delegation fidelity

Re-examined. An agent can remain rule-compliant and escape the delegated job — already
established and quantified (6 approved purchases, CHF 1,787.40, repeating a job
described once). No new representable signal was found: intent beyond the mandate text
is not observable, and we do not infer it.

## 8. Transaction vs sequence vs state — **the decisive experiment**

Permuting arrival order across all five scenarios, timestamps unchanged:

| scenario | distinct outcome sets | allows |
| --- | ---: | --- |
| SCEN0000 | 1 | 1 |
| **SCEN0001** | **5** | **5 … 7** |
| SCEN0002 | 1 | 3 |
| SCEN0003 | 1 | 5 |
| SCEN0004 | 2 | 5 (only *which* twin is flagged as duplicate) |

Only SCEN0001 varies materially — the only mandate with a rolling cap. Reordering funds
**two extra purchases, CHF 387.50 → CHF 477.00, starving nothing.**

So the answer to *"can the same transactions with the same rules mean something
different in a different order?"* is **yes, and only where a period bound exists.**

## 9. Fulfilment analysis

Unchanged from prior research. Derived from the ledger, holds within a run, not in the
decision path. This pass gives no reason to move it.

## 10. Uncertainty analysis

Step-ups already name the specific unresolved fact. The deeper decomposition collapses
into fabricability, which the C1 audit measured as non-binding. **But uncertainty turned
out to matter here for a different reason:** `step_up` is precisely the mechanism that
defers a decision and creates the out-of-order insertion. Uncertainty is not just a
decision outcome — it is a **timing** event.

## 11. Evidence and provenance

The `source` tag already carries authority and now drives the shipped verdict split. No
further structure justified.

## 12. Cross-domain research

Sliding-window rate limiting is thoroughly standard (token bucket, leaky bucket, sliding
window log/counter). Out-of-order aggregation over sliding windows is a known problem in
stream processing, with patents. **The technique we need — evaluate every containing
window — is essentially "sliding window log", which is textbook.**

What is not textbook is the *authorization* setting where a deferred human decision
re-inserts an event behind the watermark, and where the consequence is a breached
customer spending limit rather than a dropped metric.

## 13. Industry and standards

Overlap noted honestly: attenuating capability tokens are crowded in 2026 (IETF draft,
DeepMind Delegation Capability Tokens, `capmas`, macaroons); AP2 separates mandate
types; Visa TAP and Mastercard agentic tokens authenticate the agent, which the
challenge excludes. **None of these addresses window evaluation under deferred
decisions.**

## 14. Competitor simulation

`COMPETITOR_SIMULATION.md`. Fifteen architectures; almost all need both a rolling window
and a pausing step-up, and the natural implementation of the first is wrong in the
presence of the second.

## 15. Empty-cell analysis

C1 taught us that an empty theoretical cell is worthless if the protocol never exposes
it. This cell is exposed by the protocol itself — both attack paths are ordinary
official behaviour.

## 16. Candidate hypotheses

Sixteen, in `HYPOTHESIS_FALSIFICATION.md`.

## 17. Falsification

Fifteen rejected with a measurement or a citation. One survived every test.

## 18. Adversarial optimizer results

An offline search over arrival orderings (no model, no LLM), objective *maximise
approved spend subject to every explicit rule passing*:

```
baseline order   : 5 approved, CHF 387.50, worst 7-day window CHF 299.50
best adversarial : 7 approved, CHF 477.00, worst 7-day window CHF 389.00   (cap 300)
367/400 random orderings breach the cap
after the fix    : 0/400 breach, worst window exactly CHF 300.00
```

## 19. Selected concept

> **Window-containment correctness.** A purchase may be approved only if, *after*
> admitting it, no rolling window of the customer's stated length contains more than
> the customer's stated amount — evaluated over every window that contains the
> purchase, not only the one ending at it.

## 20. Exact invariant

> **For every approved set S and every period rule (N days, cap C): for all t,
> Σ{ amount(p) : p ∈ S, t−N < time(p) ≤ t } ≤ C.**

Today's check enforces this only for `t` equal to the timestamp of the purchase being
judged. The invariant must hold for **all** `t`, including instants that become
reachable only after a later insertion.

## 21. Exact authoritative source

`RunState._approved_spend` — already authoritative, already checkpointed, already under
the consume lock. **No new state.**

## 22. Exact attack

Two, both within official semantics:

- **Reordering** — the agent proposes in an order of its choosing; 367/400 random orders breach.
- **Deferred step-up** (chronological delivery, no reordering) — CHF 180 paused; CHF 150 and CHF 150 approved against a window that cannot see it; the customer then approves the paused one. **CHF 480 in a CHF 300 window.**

## 23. Exact demo

1. Customer: *"each order ≤ CHF 120, and ≤ CHF 300 across any seven days."*
2. A CHF 180 purchase is paused for the customer — the wallet is being careful.
3. Two CHF 150 purchases arrive and are approved. Spend reaches exactly the cap.
4. The customer approves the paused one. **Every decision was correct. The week now holds CHF 480 against a CHF 300 limit.**
5. Turn the corrected check on. The third purchase is refused, naming the window it would breach.

The memorable sentence: **"Being careful created the hole. The pause is what broke the budget."**

## 24. Complexity estimate

| | |
| --- | --- |
| new production LOC | ~35 (one pure function + call sites) |
| new modules / state / endpoints / dependencies | **0 / 0 / 0 / 0** |
| new tests | ~8 |
| UI | one clearer block reason |
| cost | O(n²) per decision over approved purchases in a run (n ≤ 45 officially); trivially reducible if ever needed |

## 25. Risks

1. **It changes behaviour** — by design, in exactly the case that was wrong. The official replay is unchanged, but a hypothetical run *could* now see a block where it previously saw an allow. That is the point, and it must be stated.
2. **The fix is textbook once known** (sliding-window log). Our contribution is finding that the protocol induces the bug, not inventing the algorithm.
3. **O(n²)** is fine at run scale and would not be at ledger scale.
4. **It does not fix the account scope**, which remains unenforceable.
5. **Refusing a purchase because of a *pending* step-up** is deliberately *not* done — that would let a pause block unrelated spending. Only resolution is re-checked.

## 26. What we refuse to claim

- **Not** that sliding-window-log evaluation is novel. It is textbook rate limiting.
- **Not** that out-of-order window aggregation is a new problem. It is well studied in stream processing.
- **Not** that other teams will definitely have this bug. `COMPETITOR_SIMULATION.md` is scenario analysis, not prediction.
- **Not** that this fixes delegation fidelity, account scope, or any of the six standing limitations.
- **Not** that the official data exercises it. **It does not** — the official replay is unchanged, and the attack requires an ordering or a step-up timing the fixtures do not contain. We demonstrate it on constructed-but-official-semantics inputs and say so.
