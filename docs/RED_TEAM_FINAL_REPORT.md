# Red team — final report

Every adversarial result against the final build, and the vulnerabilities found in it.

## Standing suites

| suite | result | what it is |
| --- | --- | --- |
| adversarial matrix | **17 / 17 defeated** | hand-written attacks: injection, basket tampering, replay, resolution abuse, mandate widening |
| generated corpus | **133 / 133 held** | attack primitives crossed with contexts — identities, merchant text, timestamps, statuses, replay, races, mid-flight crashes |
| attack demonstrations | **8 / 8 held** | the judge-facing eight, run live against the real engine |
| property invariants | **12 invariants**, 60 generated cases each | I1–I12, each named after a product claim |
| stateful model | passes | a `RuleBasedStateMachine` over authorize / resolve / revoke / charge / restart |
| failure modes | **26 / 26** | transport failures, 401/403/429/500/503, malformed bodies, missing fields, corrupted checkpoints, late human answers |

## Vulnerabilities found in the final build

An independent security researcher was given the code, the official spec and the data —
and deliberately *not* our conclusions — and asked to reconstruct the threat model and
attack. They found four real defects. All are fixed and pinned.

### F1 — CRITICAL. Revocation did not reach a purchase awaiting the customer

**Attack.** The customer hits the emergency brake while a purchase is waiting for their
answer, then answers the question already on their screen.

**Why it worked.** Revocation was a point-in-time *sweep* over existing records. A
pending review carries no execution lifecycle, so there was nothing to sweep — and
resolving it afterwards minted a fresh, unrevoked authority.

**Impact.** Reproduced end to end through the HTTP API: **CHF 175 charged after the
customer revoked.** This invalidated a claim the product makes in its own UI.

**Fix.** Revocation is now run-level state (`RunState._revoked_at`), persisted in the
checkpoint. `issue_authority` refuses after it, and a resolution arriving afterwards is
recorded as a **block** — revocation is the customer's later and stronger instruction.
*A sweep cannot cover a record that does not exist yet.*

**Second gap, found immediately by the stateful model while fixing the first:** a *new*
purchase after revocation reached `issue_authority` and raised, crashing the engine
rather than declining. Revocation now blocks new authorizations too.

### F2 — HIGH. The rolling ceiling was never re-checked at human resolution

**Attack.** The agent chooses what gets asked. By re-proposing a basket inside the
similar-purchase window it forces purchases into the queue, then lets the customer
approve each on its own merits — each individually reasonable.

**Impact.** **CHF 2,400 approved against a CHF 500 / 7-day cap.**

**Fix.** `resolve_authorization` re-derives the period ceilings from live state before
accepting an approval.

### F3 — Concurrent answers to one step-up were both accepted

The payment transition was a locked compare-and-set; the **consent** transition next to
it was bare. Two concurrent answers both landed, last writer won, and a purchase the
customer *declined* could end holding a live payment authority. Reproduced in 75/4000
uninstrumented trials. **Fix:** `record_resolution` now runs under the same lock.

### F4 — A non-JSON error body escaped the worker's only handler

Found by our own failure-mode tests, not the audit. An HTML page from a proxy on a 502
raised `JSONDecodeError`, which is not a `VisecaApiError`, so it escaped
`live_worker`'s single handler and would have killed the poll loop. **Fix:** both the
error and success paths normalise to `VisecaApiError`.

### Root cause

Four of five findings were **one defect**: `resolve_authorization` was the single place
in the codebase that did not re-derive from authoritative state. It checked one flag —
`was_reviewed`, set minutes or hours earlier — and then converted a pending review into
an approval plus a fresh authority, re-validating neither revocation, nor the customer's
own ceiling, nor a concurrent answer.

That is this project's own governing discipline turned on itself: *lifecycle state kept
beside the record it describes will diverge from it.* Here the thing that diverged was
**time**.

## What the audit could NOT break

Stated because it is load-bearing:

- **Authorization binding.** Amount inflation, merchant redirection, and pointing a
  charge at a different pending authorization are all refused with specific errors. An
  approval cannot be re-pointed.
- **In-process double execution.** `consume_authority` is a genuine locked
  compare-and-set; expiry is judged on the boundary's own clock, not the caller's; a
  stale captured authority cannot resurrect a revoked one.
- **`charge_id` semantics.** An exact retry is idempotent; reuse for a different
  authorization, amount or merchant is a conflict.
- **Prompt injection into policy.** No path found. Merchant text reaches only three
  narrow whitelisted extractors, NFKC-normalised with invisible characters stripped.
- **Sequential double resolution.** An identical re-submission is idempotent; a
  conflicting one raises.

## Residual risk the audit named, and we accept

| risk | why it stands |
| --- | --- |
| Two rule fields are decided entirely by merchant text (`order.return_window_days`, `item.size`) | not fixable inside the official rule vocabulary; the 3,650-day bound excludes absurd values without excluding the attack |
| Single-use is not durable across processes | the persist hook exists but no production path wires one |
| The step-up channel is unauthenticated and records no `resolved_by` | closing it needs an identity on the resolution — new authoritative state |
| `mandate.status` is read from the run's frozen snapshot, not the live event | the platform pre-checks it, so a non-active status may never arrive; the check has no live source |
| Fulfilment is not in the decision path | deliberate; 50 proposals can draw CHF 20,000 breaking no rule, and the wallet would only ever *ask* |
