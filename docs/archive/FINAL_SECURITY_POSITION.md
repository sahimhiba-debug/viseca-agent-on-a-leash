# Final security position

The answer to the question the proof mission asked:

> **Can a compromised shopping agent turn an authorization for transaction A into
> payment for transaction B?**

**No counterexample was found for a *different* transaction B.** Four
counterexamples were found where B was *the same transaction executed twice*. Three
are fixed; one is a stated, tested boundary.

That distinction is the whole result, so it is worth being exact about it.

---

## 1. What an authority authorizes

```
VALID(A, t) ⟺  t.authorization_id = A.authorization_id
            ∧  t.merchant_id      = stored[A].merchant_id
            ∧  0 < t.amount       ≤ stored[A].billing_amount_chf
            ∧  A.consumed_at is None
            ∧  ¬A.revoked
            ∧  clock() ≤ A.expires_at
            ∧  mandate.status = ACTIVE
            ∧  authority_status = active ∧ card_status = active
```

Read off the code, not the intent. Three consequences:

- **The id is pinned.** The authority names its own `authorization_id`, and
  `charge()` resolves the stored decision by that same id. There is no parameter
  that could point it elsewhere. Measured: charging via AU1's authority executes AU1
  and leaves AU2 untouched.
- **The amount is ceilinged, not pinned.** `≤`, not `=`. An approval for CHF 100
  will execute CHF 1 — a partial capture, never an escalation.
- **The basket is not at the boundary at all.** `charge()` receives an amount and a
  merchant and never sees goods. The purchase is pinned one layer earlier by the
  repeat-delivery fingerprint, and reaches the boundary transitively through the id.

---

## 2. The four counterexamples, all "same transaction, twice"

| | Sequence | Result before fix |
| --- | --- | --- |
| V8 | charge → restart → charge | CHF 200 vs approved CHF 100 |
| V10 | checkpoint → charge → **crash** → restart → charge | CHF 200. V8's fix was incomplete; its test snapshotted *after* charging, which production never does |
| V11 | checkpoint → two workers → charge, charge | CHF 200. Scoped, not fixed |
| V12 | revoke mandate → authorize → charge | CHF 400 under a **revoked mandate** |

V10 and V12 are the two that matter most, for opposite reasons. V10 is a case where
a previous pass's *test* was generous enough to hide the bug it was written to
catch. V12 is a case where a whole class of audit — "enumerate schema fields" —
was run once, found the largest bug in the project, and was then not re-run over
nested objects, where its twin was waiting for four more passes.

---

## 3. All twelve vulnerabilities

| | Severity | Falsified a prior claim? |
| --- | --- | --- |
| V1 platform `authority_status`/`card_status` ignored | CRITICAL | — |
| V2 human-approved step-ups escaped revocation | HIGH | yes — I29 |
| V3 revocation lost across restart | HIGH | — |
| V4 expiry judged by caller's clock | MED | yes — I26 |
| V5 events not bound to run (card-history borrowing) | MED | — |
| V6 duplicate detection evaded by one centime | LOW-MED | — |
| V7 revocation on re-delivery ignored | HIGH | — |
| V8 double execution across restart | HIGH | — |
| V9 `charge_id` reuse ignored merchant | MED | — |
| V10 consumption never persisted | HIGH | yes — V8's own fix |
| V11 single-use is per-run-state | HIGH | scoped, not fixed |
| V12 **revoked mandate still authorized** | CRITICAL | yes — I1 |

Five of twelve falsified a claim a previous pass of this project had explicitly
made and tested.

---

## 4. Where the guarantee rests on someone else

Named, because a guarantee with an unnamed precondition is not a guarantee.

| Assumption | Consequence if false |
| --- | --- |
| `authorization.timestamp` is truthful | every rolling-window limit is defeatable. Platform-supplied; the agent has no channel to author it; the contract requires us to key on it |
| One `RunState`, one process | two workers each execute once (V11) |
| A `persist` hook is wired into the executor | single-use is not durable across a crash |
| The platform is honest | every fact originates from its event stream |
| `item.size` is truthfully stated by the merchant | no platform field backs it — unlike returnability, which the platform gates |

---

## 5. The strongest transaction a compromised agent can still execute

Assuming a malicious agent, a malicious merchant, an unreliable network, restarts,
revocation and full replay of everything seen — but **no channel to platform-
authoritative fields**:

> **A purchase that is fully inside the customer's own mandate, at a merchant the
> mandate permits, for an amount the mandate permits — where the merchant has
> overstated the size or the length of the return window.**

That is not an authorization bypass. It is the customer's policy being satisfied by
a merchant who lied about the one or two facts the wallet has no independent source
for. The wallet's answer is correct given its inputs; the inputs were false.

Everything stronger was tried and refused: a different merchant, a larger amount, a
different basket, a different card, a different mandate, a revoked mandate, a
revoked authority, a blocked card, an expired authority, a replayed approval, a
mutated re-delivery, a human approval re-pointed at other facts, and ~100,000
adversarial operation sequences.

---

## 6. Answers to the mission's questions

**Is `PaymentAuthority` actually non-transferable?** Across transactions, yes —
the id is structurally pinned. Across *executions of the same transaction*, it was
transferable twice (V8/V10) and remains so across two run states (V11).

**Is revocation actually enforced?** Now yes, at four levels: the authority
(`revoked`), the mandate (`mandate.status`), the platform's authority/card status,
and durably across a restart. Before this pass it was enforced only when revocation
came through our own demo endpoint.

**Is human approval transaction-specific?** Yes, structurally: `record_resolution`
cannot receive an amount or a merchant.

**Does restart preserve security?** With a persist hook, yes. Without one, no —
and that is now pinned by a test rather than assumed.

**Does concurrency preserve security?** Within one process, incidentally (the GIL,
not synchronisation). Across processes, **no** — V11.

**Is the official schema fully consumed?** Yes: 42 fields, 26 read, 16 unread each
with a written reason, 0 unclassified.

**Can merchant facts create policy bypasses?** Only within a returnability the
platform already asserted, and for `item.size`, which no platform field backs.

---

## 7. What we can and cannot say

**Defensible in front of a payment engineer:**

> An approval is a single-use, time-boxed, merchant-bound, amount-ceilinged
> authorization to execute one specific authorization id — revocable until spent at
> four independent levels, and re-verified against persisted run state at the single
> point where money moves. Single-use holds within one run state and one process,
> durably across a crash when the executor is given a persist hook.

**Not defensible, and not to be said:** "secure", "tamper-proof",
"cryptographically verified", "non-transferable" without its scope, "proven", or
anything about the hosted challenge inferred from `MockPSP` — which guards a
simulated execution the official integration never triggers.

---

## 8. Honest closing

Twelve vulnerabilities across five passes; five falsified a claim this project had
already made and tested. The most valuable finding of this pass — V12 — was found
by re-running an audit that had already found the largest bug in the project, in a
place that audit had not looked.

So the useful statement is not that the wallet is secure. It is that the security
model is now written down precisely enough to be attacked, the places it depends on
trusting someone else are named, and the one remaining execution-level gap (V11) is
pinned by a test rather than hidden by one.
