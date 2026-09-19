# Breakthrough proof — window containment

## The mechanism

> A purchase may be approved only if, **after** admitting it, no rolling window of the
> customer's stated length contains more than the customer's stated amount — evaluated
> over **every window that contains** the purchase, not the one that **ends** at it.

## The invariant

> For every approved set *S* and every period rule *(N days, cap C)*:
> **∀t : Σ{ amount(p) : p ∈ S, t−N < time(p) ≤ t } ≤ C**

The previous check enforced this only for *t* = the timestamp of the purchase being
judged. It must hold for **all** *t*, including instants that become reachable only
after a later insertion.

## Where it is enforced

`RunState.peak_window_spend_chf` — a pure function over `_approved_spend`, which is
already authoritative and already checkpointed. Called from two places: the rule
evaluation path (`_projected_period_spend`) and the human-resolution path
(`_period_rules_breached_now`). **No new state, modules, endpoints or dependencies.**

## The attacks it stops

### Attack 1 — deferred step-up, strictly chronological, no reordering

```
T+0h   AU1 CHF 180  -> REVIEW   paused; correctly NOT in approved spend
T+2h   AU2 CHF 150  -> ALLOW    checked against a window that cannot see AU1
T+4h   AU3 CHF 150  -> ALLOW    spend reaches exactly the CHF 300 cap
       customer approves AU1    it enters at its ORIGINAL timestamp
       ---------------------------------------------------------------
       the 7-day window now holds CHF 480 against a CHF 300 limit
```

Every decision is locally correct. Both halves are required by the specification:

> *"A purchase waiting for a human answer is not yet approved."*
> *"Use simulated purchase time for spending windows."*

**Being careful is what creates the hole.** The pause is the vulnerability.

*After the fix:* the resolution is refused — `period_limit_exceeded: approving it would
put CHF 480.0 into a 7-day window against a CHF 300 ceiling` — and the window stays at
CHF 300.

### Attack 2 — arrival reordering

The agent chooses what to propose when. On SCEN0001's own data:

| | before | after |
| --- | --- | --- |
| random orders breaching the cap | **367 / 400** | **0 / 400** |
| worst 7-day window | **CHF 389.00** | CHF 300.00 |
| approvals across orderings | **5 … 7** | **5 … 5** |
| approved spend | CHF 387.50 → 477.00 | unchanged |

The last row is the stronger property: **the outcome no longer depends on an ordering
the agent controls.**

## What would happen without it

The customer's rolling cap — the only economic control the official rule vocabulary
actually enforces — is exceedable by up to 60% while the wallet reports full
compliance on every individual decision.

## Why the official replay is unchanged

For a run whose decisions arrive in chronological order with nothing deferred, the peak
containing window and the window ending at the purchase are the same number. The fix
bites only where the old check was wrong. Verified: all five scenarios identical,
45 / 19 / 2 / 24.

*Corollary, stated plainly: the official fixtures do not exercise this. We demonstrate
it on constructed inputs that use only official semantics, and we say so.*

## Adversarial review of the mechanism itself

| attack | result |
| --- | --- |
| backdate a purchase 30 days to dodge the window | held — worst window CHF 300 |
| straddle: place purchases so no window ends at one | held — the middle purchase is refused |
| idempotent re-delivery (×3) | held — CHF 200 counted once |
| two threads racing the same remaining budget, 2000 trials | 0 double-allows, 0 breaches |
| restart between purchases | held — refused after checkpoint round-trip |
| cost at 201 approved purchases | 2.2 ms per decision |

The period check remains a read-modify-write outside the consume lock (documented as
F4). The new test does not change that and is not reachable through the single-threaded
`LiveWorker`.

## What is actually ours

Finding that **the specification's own two requirements combine to induce the
violation**, and that the natural implementation passes every ordinary test while being
wrong. The question that found it is reproducible by anyone: *same transactions, same
rules, different order — can the security meaning differ?*

## What is NOT ours

- **Not** the algorithm. Evaluating every containing window is textbook sliding-window-log
  rate limiting.
- **Not** the observation that out-of-order events break window aggregation. That is well
  studied in stream processing, with patents.
- **Not** a claim that other teams will have this bug. `COMPETITOR_SIMULATION.md` is
  scenario analysis, not prediction.
- **Not** a fix for any of the six standing limitations. Account scope, cross-run mandate
  reuse and process-local single-use are all unchanged.
