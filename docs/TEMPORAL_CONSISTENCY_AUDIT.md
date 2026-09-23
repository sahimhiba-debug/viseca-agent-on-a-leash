# Temporal-consistency adversarial audit

<!-- snapshot -->
> **SNAPSHOT — written 19 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

## Executive conclusion

**The property claimed after the previous pass was too strong, and I have withdrawn
it. Two genuine counterexamples to the surviving property were found, fixed and
mutation-verified; a third was introduced by one of those fixes and caught by the
stateful model.**

The claim under test was:

> ~~same purchases + same policy + different order ⇒ same authorization outcome~~

**That is false.** Greedy admission is inherently order-dependent: whoever arrives
first is funded. On SCEN0001, 300 random arrival orders produce **14 distinct approved
sets**. And the *count* is not invariant either — minimal counterexample below.

What survives is the safety half, and only that:

> **No arrival order and no late human answer may cause the approved history to
> contain more than the customer's stated amount in any window of the customer's
> stated length.**

This is **empirically established, not formally proven.** See §"What this is not".

## The invariant, in one sentence

> For every approved set *S* and every period rule *(N days, cap C)*:
> **∀t : Σ{ amount(p) : p ∈ S, t−N < time(p) ≤ t } ≤ C.**

## Minimal counterexample to the withdrawn claim

```
A = B = C = CHF 100, D = CHF 150      cap CHF 300 / 7 days
order (A,B,C,D) -> 3 approved, total CHF 300
order (A,D,B,C) -> 2 approved, total CHF 250
```

Safety holds in all 24 permutations. Invariance does not. Pinned by
`test_the_approved_set_is_NOT_order_invariant_and_we_do_not_claim_it_is`.

## Counterexamples to safety — found, minimised, fixed

### C1 · Idempotent re-resolution counted a purchase against itself

```
CHF 200 stepped up under a CHF 300 cap
customer answers "allow"      -> allow, spend 200
client retries the SAME answer -> ResolutionError: already resolved as 'allow',
                                  cannot now resolve it as 'block'
```

The period re-check added the purchase's own amount to `_approved_spend`, which
already contained it: 200 + 200 = 400 > 300. It decided to record a block, which
conflicted with the `allow` it had just recorded. **A double-clicked button crashed.**

*Why the suite missed it:* the existing idempotence test's mandate had no period rule,
so the re-check returned immediately.

**Fix:** only a purchase still *waiting* may be overridden. Once resolved,
`record_resolution` owns the outcome.

### C2 · The decision path was a non-atomic read-modify-write

The period check reads the window, the rules evaluate, then the decision is recorded.
Widening that gap to 20 ms:

```
before: both threads allowed 40/40, window breaches 40/40  (CHF 400 vs cap 300)
after : both threads allowed  0/40, window breaches  0/40
```

This was the **previously documented but never reproduced** F4 limitation. It is
reachable through `api.py`'s Starlette threadpool, not through the single-threaded
worker.

**Fix:** the run's lock is held across check-then-record, made re-entrant because
`record_decision` takes it underneath. Lock order is a single lock, so no cycle; a
deadlock probe (evaluate → charge → revoke) passes.

### C3 · Introduced by the C2 fix, caught by the stateful model

`issue_authority` checked revocation *before* its idempotent return, so asking again
for an authority that already existed raised instead of returning it. **Idempotence now
comes first**; only *minting a new* authority after revocation is forbidden.

## Attack coverage

| # | attack | result |
| --- | --- | --- |
| 1 | arrival-order permutation, official data (300 orders) | **0 breaches**; 14 distinct approved sets |
| 2 | approval count / set invariance | **falsified** — claim withdrawn |
| 3 | deferred step-up behind later approvals | held |
| 4 | three pending step-ups, all 6 resolution orders | held — 2 of 3 approved in every order |
| 5 | compositionality: individually safe, jointly unsafe | held |
| 6 | reverse-chronological resolution | held |
| 7 | **idempotent re-resolution** | **BROKE → fixed (C1)** |
| 8 | conflicting re-resolution | refused |
| 9 | window edge: exactly N days | allowed (half-open window `(t−N, t]`) |
| 10 | window edge: N days ± 1 second | held |
| 11 | ceiling − ε / exactly / + ε | 299.99 allow · 300.00 allow · 300.01 block |
| 12 | identical timestamps | held |
| 13 | FX rounding at the ceiling | held |
| 14 | backdating 30 days | held |
| 15 | straddling: no window ends at a purchase | held |
| 16 | duplicate authorization_id after resolution | idempotent replay, no double count |
| 17 | restart before *and* after every resolution | held |
| 18 | revocation with several step-ups pending | all three refused |
| 19 | **concurrent proposals, 20 ms widened RMW** | **BROKE 40/40 → fixed (C2), 0/40** |
| 20 | deadlock probe after the lock change | no deadlock |
| 21 | re-issuing an existing authority after revocation | **BROKE → fixed (C3)** |
| 22 | cost at 201 approved purchases | 2.2 ms per decision |

## What this is not

**This is empirical evidence, not a formal guarantee.** No proof was constructed. The
property is established by:

- exhaustive permutation of small constructed sets (24 orders × several shapes);
- 300 random permutations of the official SCEN0001 data;
- all 6 resolution orders of three interleaved pending step-ups;
- boundary cases enumerated by hand;
- a Hypothesis stateful model over the whole lifecycle.

A counterexample outside that coverage would not surprise me. In particular **nothing
here proves the peak-window computation correct for window shapes the official
vocabulary cannot express** (multiple overlapping period rules of different lengths
were not exercised on official data, only constructed).

## Exact results

| | |
| --- | --- |
| tests | **646 passed**, 0 failed |
| official replay | **45 events — 19 allow / 2 review / 24 block** (unchanged) |
| red-team corpus | 133 / 133 |
| adversarial matrix | 17 / 17 |
| fulfilment differential | 6 / CHF 1,787.40 |
| mutation check | reverting either fix fails exactly its own test |

## Is the mechanism still frozen?

**The window-containment mechanism is unchanged.** `peak_window_spend_chf` was not
touched. The three fixes are to its *callers* — when the override may run, what lock is
held around it, and the order of two checks inside `issue_authority`. No new module,
state, endpoint or dependency.

## Remaining limitations

1. **Order-dependence of the approved set is inherent and unfixed.** Who gets funded
   depends on who arrives first. Making it order-independent would require deferring
   admission until the window closes, which the protocol's 8-second deadline forbids.
2. **Empirical, not proven** — §"What this is not".
3. **Multiple overlapping period rules** of different lengths are supported by the code
   but now exercised: a 3,000-run campaign with three nested caps (CHF 200/1d, 300/7d, 1000/30d), randomized amounts and timestamps over 35 days and ~45% of purchases forced into step-ups resolved in random order found **0 breaches**, with the windows filling to 199.99 / 299.95 / 956.28 -- tight, not over-conservative.
4. **A cancelled or revoked purchase still consumes window budget.** The decision record
   stands; only payment authority dies. Arguably correct, certainly conservative,
   and not something the customer can undo.
5. The six standing limitations are unchanged: cross-run mandate reuse, account scope,
   process-local single-use, cancelled-retry, unverifiable merchant claims,
   unauthenticated step-up.
