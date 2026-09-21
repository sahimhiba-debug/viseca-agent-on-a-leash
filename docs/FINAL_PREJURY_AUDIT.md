# Pre-jury zero-surprise audit

The objective was zero **surprises**, not zero limitations. What follows is every
finding, including the two I raised and then disproved myself.

---

## Findings

| # | finding | verdict | status |
| --- | --- | --- | --- |
| 1 | `instruction` on the agent's endpoint let an agent author its own mandate: CHF 500 refused under the customer's rules, **approved** at "CHF 900" | **real, serious** | fixed, mutated |
| 2 | `confirmed_at` let a caller stamp an audit entry attributed to `actor="customer"` (`1999-01-01`) | **real** | fixed, mutated |
| 3 | `customer_message` on a step-up answer: caller-controlled, never read | **latent** | removed, mutated |
| 4 | missing `item_id` → uncaught `KeyError`, 500 with a stack trace | **real** | fixed |
| 5 | a revoked run kept saying **"Waiting for you"** | **real** | fixed, mutated |
| 6 | the Delegate box dropped a clause from the official instruction | **real** | fixed |
| 7 | `resolve_authorization(mandate=None)` silently disables the window re-check | **latent** | AST-guarded |
| 8 | every press of the demo button opened a fresh session, so the rolling cap could never bind | **real** | fixed, mutated |
| 9 | the page disclosed that the window re-opens over *time*, never that a new session resets it | **real** | disclosed |
| — | **60 × CHF 108 = CHF 6,480 approved** | **NOT a defect** | see below |
| — | **CHF 400 against a CHF 300 cap** via two step-ups | **NOT a defect** | see below |

## The two I got wrong

Both matter more than the fixes, because both are what a jury would raise.

**CHF 6,480 under a "CHF 120" mandate.** I flagged it. It is correct behaviour. The
mandate says *each order*; sixty orders of CHF 108 satisfy it; no rule in that
mandate is one a sequence could violate. The control: add the seven-day clause the
protocol already supports and the same attack yields **2 approved, 58 blocked,
CHF 216**. Same engine. The mandate was the weakest shape the protocol allows, which
is a poor thing to hand a jury — so the demo mandate now paces, and **the engine was
not touched**.

**CHF 400 against a CHF 300 cap.** I reproduced it through two pending step-ups and
it looked live for several minutes. It was not: my test called
`resolve_authorization` **without the mandate**, which is optional, and the
rolling-window re-check silently never runs when it is omitted. Called the way
`api.py` calls it, the second approval is blocked. The near-miss produced finding 7.

## The demo, after

Pressing the button repeatedly is now the best thing on the page:

```
errand 1   CHF 108 allowed          two non-price refusals, unchanged
errand 2   CHF 108 allowed          running total 216
errand 3   refused on amount, then BUY LESS → CHF 62 allowed, total 278
errand 4   "no basket would satisfy what you asked for"
```

The agent fitted itself to a remaining budget it was never told, then stopped. The
rolling window demonstrating itself, which nothing else on the page did.

## The jury attack, answered

> *"Your wallet let me spend CHF 6,480 even though you told me it had a CHF 120
> limit. Why should I trust it?"*

**The answer, in the order to say it:**

> "It doesn't have a CHF 120 limit. The customer wrote *'keep each **order** at or
> below CHF 120'*, and every one of those orders was under 120. The wallet enforced
> exactly what it was told — that's the system working, not failing.
>
> What you've actually found is that a per-order rule doesn't bound a sequence, and
> you're right that it doesn't. So watch this." *(add the seven-day clause)* "Same
> engine, same agent, same attack: two approved, fifty-eight blocked, CHF 216
> against a stated CHF 300.
>
> And here's the part I'd rather tell you than have you find: that CHF 300 is a
> **rolling window, not a total**. It re-opens over time, and it starts again in a
> new session. The screen says both, under *'not limited by anything you wrote'*.
> There is no total-spend rule in the protocol's vocabulary — `scope` is `purchase`
> or `period`, and the spec closes the set. We can't express one, so we don't claim
> one."

**Never say:** "CHF 120 is the limit." Say "CHF 120 per order."

## Not closed, and why

Cross-run aggregation (CHF 2,160 across ten sessions), merchant lies, step-up
identity, exactly-once across processes, the decision oracle. Each bounded exactly
in `FINAL_LIMITATIONS_AUDIT.md`. None is claimed away, and we do **not** claim the
cross-run case is impossible — it is a choice under uncertainty.

## Evidence

| area | file |
| --- | --- |
| actor authority | `tests/security/test_actor_authority.py` |
| agent cannot author policy | `tests/security/test_agent_cannot_author_policy.py` |
| resolution checks not optional | `tests/security/test_resolution_checks_are_not_optional.py` |
| demo economic scope | `tests/security/test_demo_economic_scope.py` |
| information boundary | `tests/security/test_agent_information_boundary.py` |
| message ↔ decision agreement | `tests/security/test_recorded_message_matches_decision.py` |
| demo data is official | `tests/test_demo_data_is_real.py` |
| cited evidence exists | `tests/test_cited_evidence_exists.py` |
