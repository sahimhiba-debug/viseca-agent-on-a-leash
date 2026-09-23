# The minimal security core

<!-- snapshot -->
> **SNAPSHOT — written 18 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Measured, not asserted. Every classification below was derived by grepping the
production source for reads, then by deleting the thing and running the gates.

---

## 1. The core

```
mandate snapshot          fixed at run start, from the platform
        +
decision ledger           one immutable-core record per authorization_id,
                          carrying a monotonic execution lifecycle
        +
atomic transition         the compare-and-set that spends it
```

That is all of it. Three things. Everything else in the wallet is derived,
explanatory, cached, or presentation.

## 2. Classification of every security-relevant object

| Object | Class | Evidence |
| --- | --- | --- |
| `StoredDecision` (decision, amount, merchant, basket, timestamp) | **AUTHORITATIVE, write-once** | `record_decision` returns the existing entry rather than overwriting |
| execution lifecycle (`execution_issued_at/expires_at`, `revoked`, `consumed_at`) | **AUTHORITATIVE, monotonic** | the only mutable security state in the system |
| `PaymentAuthority` | **DERIVED** (projection) | built on demand by `project()`; 7 of its 12 fields were read zero times before the merge |
| rolling spend | DERIVED | summed from the ledger |
| fulfilment | DERIVED | pure function of the ledger |
| `AuthorizationDrift` | PRESENTATION | computed after `_decide()`, never read by it |
| `policy_verdict` / `security_verdict` | PRESENTATION | the same evaluations re-scoped |
| compiled policy | DERIVED from the mandate, then frozen into the snapshot |
| facts | DERIVED per event, never stored |
| platform statuses, timestamps, ids | **EXTERNAL**, trusted, unverifiable |
| merchant text | **UNTRUSTED**; reaches facts through 3 whitelist extractors |
| `ChargeRecord` | SIDE EFFECT, one construction site |

## 3. What was deleted, and what broke

| Deleted | Result |
| --- | --- |
| `RunState._authorities` (the second dict) | **nothing broke.** 528 tests, replay 19/2/24, corpus 133/133, differential unchanged |
| the `authorities` snapshot array | nothing broke; the lifecycle rides with its decision |
| 7 never-read authority fields as *stored* data | nothing broke; they are derived for display |
| `PaymentAuthority.is_valid()` (earlier pass) | nothing broke — it was never called |
| `charge_via_authority`'s ceiling check (earlier pass) | nothing broke — provably identical to `charge()`'s |

Net: **−26 lines in `state.py`**, one file changed, zero behavioural difference on
every gate.

## 4. What cannot be deleted, and the invariant that proves it

| Kept | Invariant that breaks without it |
| --- | --- |
| the decision ledger | everything |
| `execution_expires_at` | an approval never stops being spendable |
| `revoked` | the customer's brake does nothing |
| `consumed_at` | one approval executes many times |
| the atomic compare-and-set | a revocation landing mid-charge is overwritten (V13); two threads both spend (V14) |
| `mandate.status` / platform status checks | a revoked mandate keeps authorizing (V12) |
| the run-binding check | an event borrows another card's history (V5) |

## 5. The one thing that may never be duplicated

**The execution lifecycle.** Six vulnerabilities in this project were one mistake:
a second mutable record describing an authorization that already had one.

| | Second record | How it drifted |
| --- | --- | --- |
| V2 | payment authority | never minted for a human-approved step-up |
| V3, V8, V10 | authority / consumption | lost on restart while decisions persisted |
| V13, V14 | consumption | overwritten by a concurrent transition |
| A8, A12 | fulfilment tally | missed human approvals; reset on restart |

The merge removes the possibility for the authority case; deriving removes it for
fulfilment.

## 6. The cost, stated

`StoredDecision` is no longer wholly immutable — the lifecycle mutates in place.
That is a real new risk surface, converted into a mutation-verified guard: no
lifecycle transition may alter the decision, amount, merchant, basket or
timestamp (`test_no_lifecycle_transition_alters_the_decision_content`).

And collapsing the records does **not** make the V2 shape impossible — a caller
can still fail to issue a lifecycle. It stays fail-closed, and that is pinned.
