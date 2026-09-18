# State machine & adversarial sequences

*(This covers both deliverables the brief lists separately — the state-machine
model and the adversarial sequence generator. They are the same artefact here:
the model IS the generator. A second document would have restated it.)*

---

## Why sequences, not requests

Of the twelve vulnerabilities found across five passes, almost none were reachable
by exercising one field of one request:

| Vulnerability | Sequence needed to reach it |
| --- | --- |
| V2 | authorize → step-up → **human approves** → revoke → charge |
| V3 | authorize → revoke → **crash** → restart → charge |
| V7 | authorize → **re-deliver with a revoked status** → charge |
| V8 | authorize → charge → **restart** → charge |
| V10 | authorize → **checkpoint** → charge → crash → restart → charge |
| V11 | authorize → checkpoint → **two workers** → charge, charge |

Every one is a composition of individually-correct operations. Fixed test cases
find these only if someone already imagined the ordering — which is precisely what
failed for four consecutive passes.

---

## The model

`tests/security/test_state_machine.py` drives the **real** engine, run state and
payment boundary. Nothing is mocked except the clock.

**Operations:** `authorize`, `redeliver_possibly_mutated`, `human_resolves`,
`customer_revokes`, `agent_attempts_charge`, `time_passes`, `crash_and_restart`.

**One detail is load-bearing.** `crash_and_restart` restores from the checkpoint
the model actually maintained — written after each decision and resolution, and
through the payment boundary's `persist` hook after consumption — **not** from a
fresh `to_snapshot()` taken at the moment of the restart. That shortcut is exactly
what hid V10: the previous pass's crash test snapshotted *after* charging, which no
production sequence does, so it proved a property the system did not have.

**Invariants, asserted after every single step:**

1. no authorization is charged beyond its approved amount
2. only `allow` decisions are ever charged
3. consumption is monotonic — including across a restart
4. revocation is monotonic
5. a revoked or consumed authority is never chargeable (probed live, not inferred)
6. an authority exists only for an `allow`
7. approved spend equals the sum of counted approvals
8. every charge went to the approved merchant

Checking after *every* step, rather than at the end, attributes a violation to the
operation that caused it and lets Hypothesis shrink to a minimal reproduction.

---

## Impossible states searched for

| Impossible state | How it would appear | Result |
| --- | --- | --- |
| REVOKED + CHARGEABLE | invariant 5 | not found |
| CONSUMED + CHARGEABLE | invariant 5 | not found |
| EXPIRED + CHARGEABLE | clock advance then charge | not found |
| EXECUTED + UNCONSUMED | invariant 3, after restart | not found (was V8/V10) |
| CHARGED + NOT-ALLOW | invariant 2 | not found |
| AUTHORITY + NO-ALLOW | invariant 6 | not found |
| HUMAN-APPROVED + DIFFERENT-TRANSACTION | invariants 1 and 8 | not found |
| SPEND ≠ Σ APPROVALS | invariant 7 | not found |

---

## Results

| Sweep | Operations | Charges executed | Restarts | Revocations | Violations |
| --- | ---: | ---: | ---: | ---: | ---: |
| Uniform random, 4,000 sequences | ~50,000 | 175 | 8,631 | 8,622 | **0** |
| Charge-biased, 6,000 sequences | ~47,000 | **4,353** | 11,843 | 9,266 | **0** |
| Hypothesis, 300 examples × 30 steps | ~9,000 | — | — | — | **0** |

The second sweep exists because the first was not good enough evidence: only 175
of ~5,000 charge attempts succeeded, so the consume/restart/revoke interleaving —
where V8, V10 and V11 all lived — was barely exercised. Biasing toward *valid*
charges (correct merchant, amount within the approval) raised successful executions
25-fold and hammered exactly that path.

---

## What this does and does not establish

**Establishes:** across roughly 100,000 operations in adversarial orderings —
including crashes at arbitrary points, revocations interleaved with charges, human
resolutions on mutated authorizations, and re-deliveries carrying dead platform
statuses — no invariant was violated in the configuration the model represents
(one run state, one process, persist hook wired).

**Does not establish:** correctness. The model shares the implementation's own
notion of state, so a misconception present in both would be invisible to it. It
also cannot reach what it cannot express — V11 (two run states) is outside the
model by construction, which is why it is pinned by a separate explicit test rather
than left to the search.

A model that finds nothing is evidence about the orderings it explored, not a
proof. The orderings it explored are listed above so that claim can be checked.
