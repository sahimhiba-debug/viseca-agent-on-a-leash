# Autonomous research lab — executive report

Baseline `fe571b2` (646 tests) → final `4222f97` (**647 tests**). Official replay
**45 / 19 allow / 2 review / 24 block**, unchanged throughout.

## What was found

Two passes, four real defects, one withdrawn claim.

### Pass A — temporal consistency

**The property I claimed after the previous cycle was too strong, and I withdrew it.**

> ~~same purchases + same policy + different order ⇒ same authorization outcome~~

False. Greedy admission is inherently order-dependent. On SCEN0001, 300 arrival
orders produce **14 distinct approved sets**; minimal counterexample
A=B=C=100, D=150 under a CHF 300 cap gives 3 approvals in one order and 2 in another.
**Safety holds; invariance does not.** A test now pins the negative so the stronger
claim cannot quietly return.

Three counterexamples to the surviving safety property:

| | defect | impact |
| --- | --- | --- |
| **C1** | idempotent re-resolution counted a purchase against itself (200 + 200 > 300) | **a double-clicked button crashed** |
| **C2** | the decision path was a non-atomic read-modify-write | **CHF 400 into a CHF 300 week, 40/40 trials** with a 20 ms widened window |
| **C3** | `issue_authority` checked revocation before its idempotent return | re-asking for an existing authority raised instead of returning it |

C2 was the previously *documented but never reproduced* F4 limitation. C3 was
introduced by the C2 fix and caught by the stateful model.

### Pass B — hypothesis sweep, 16 categories

Most died on evidence:

| hypothesis | verdict |
| --- | --- |
| familiarity bootstraps from one human approval | **falsified** — each purchase at an unfamiliar merchant stays a step-up |
| tighten-then-resolve escapes a mid-run tightening | **correct per spec** — *"an existing run keeps its original snapshot"* |
| empty basket bypasses item rules | **unreachable** — schema `minItems: 1` |
| quantity 0 / negative | **unreachable** — schema `quantity: minimum 1` |
| agent forges the velocity counter | **falsified** — platform-computed |
| contradictory mandate rules | already correct — strictest governs |
| self-referential `related_authorization_id` | already blocked |
| zero-width character in `merchant_id` | already blocked |
| 200-line basket | handled |

**One survived.**

> `order_returnable = "not_applicable"` made the customer's `order.return_window_days`
> requirement **pass unconditionally** — the only value of that field which neither
> blocked, escalated, nor required a stated window.

Three things were wrong: it required no evidence; it was never cross-checked against
`fulfillment_method`, so a **physical delivery** declared not-applicable passed; and it
ran *before* the final-sale logic, so an order the merchant marked **"sold as final
sale"** satisfied a *"returnable within 14 days"* requirement.

That was the one place where a customer requirement could be satisfied by asserting it
did not apply — contradicting the engine's own rule that uncertainty never silently
becomes approval. It is now **UNKNOWN**: escalates under `ask`, declines under
`decline`, as the customer chose. Blocking outright would be wrong, because for a
genuinely digital good the concept really does not apply — but that is the customer's
call, not ours.

## Adversarial optimizer

4,000 strategies varying amount, timing, forced step-ups and resolution order:
**0 window breaches.** Max total CHF 574.24 over a 10-day run, which legitimately spans
more than one 7-day window.

## Architecture changes

None. Every fix was to a caller or a rule outcome:

| file | change |
| --- | --- |
| `decision_engine.py` | only a still-pending purchase may be overridden; decision + resolution paths hold the run lock |
| `state.py` | the run lock is re-entrant; `issue_authority` idempotence before the revocation check |
| `rules.py` | `not_applicable` → `unknown` instead of `pass` |

No new module, state, endpoint, dependency or UI component. `peak_window_spend_chf` —
the previous cycle's mechanism — was **not touched**.

## Tests

+1 net (647). Four added, one inverted, one repaired:

- inverted: `test_return_window_not_applicable_always_passes` → `..._escalates_rather_than_passing`, with the reasoning in the docstring.
- repaired: the module-isolation test checked coupling by **grepping source text** and failed when a comment mentioned `fulfillment_method`. It now parses imports. *A test that cannot tell an import from a word in a comment will either block honest documentation or be silenced.*

Both fixes mutation-verified: reverting either fails exactly its own test.

## Prior art

Nothing here is novel computer science, and none is claimed. Sliding-window-log rate
limiting, non-atomic read-modify-write, and idempotent request handling are all
textbook. What is specific is the *interaction*: this protocol requires paused
purchases not to count, requires windows keyed to simulated purchase time, and defers
human answers — and those three requirements combine into the defects above.

## What we refuse to claim

- **Not formally proven.** The safety property is established by exhaustive permutation
  of small sets, 300 permutations of official data, all 6 resolution orders of three
  interleaved step-ups, hand-enumerated boundaries, a stateful model and a 4,000-strategy
  optimizer. That is evidence, not proof.
- **Not order-independent.** Who gets funded still depends on who arrives first, and
  making it otherwise would require deferring admission past the 8-second deadline.
- **Not exercised by official data.** Every counterexample here is constructed from
  official *semantics*; the replay is unchanged in all cases.
- **Concurrency is fixed for one process.** Multi-worker remains out of scope.

## Remaining limitations

Unchanged: cross-run mandate reuse, account scope, process-local single-use,
cancelled-retry, unverifiable merchant claims (saturation beats them), unauthenticated
step-up. Plus, newly documented: a cancelled or revoked purchase still consumes window
budget, and multiple overlapping period rules of different lengths are supported but
now exercised: a 3,000-run campaign with three nested caps (CHF 200/1d, 300/7d, 1000/30d), randomized amounts and timestamps over 35 days and ~45% of purchases forced into step-ups resolved in random order found **0 breaches**, with the windows filling to 199.99 / 299.95 / 956.28 -- tight, not over-conservative.
