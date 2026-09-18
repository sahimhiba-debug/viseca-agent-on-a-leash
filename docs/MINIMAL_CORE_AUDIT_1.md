# Minimal core — audit 1 (security researcher)

Attacking the merged model as someone who did not design it. The question is not
"do the tests pass" but "what did collapsing two records into one give away?"

**Result: one real defect found in the merge itself, and fixed.**

---

## A1 — Is the projection ever stale?  ·  HELD

`get_authority()` builds a `PaymentAuthority` on every call from the current
decision. Two consecutive calls return equal-but-distinct objects. There is no
cached instance, so the stale-copy attack that V13/B5 relied on has nothing to
hold.

## A2 — Can a lifecycle transition corrupt the decision?  ·  REAL NEW RISK

The merge makes `StoredDecision` partly mutable. `revoke_authority`,
`consume_authority` and `issue_authority` all call `replace()` on the record that
also holds the decision, the amount, the merchant and the basket.

No current code path does this, but nothing prevented it. Converted into a guard:
`test_no_lifecycle_transition_alters_the_decision_content` runs all four
transitions and asserts the decision core is byte-identical. Mutation-verified —
corrupting `billing_amount_chf` during a revocation fails it.

**This is a genuine cost of the merge and is recorded as such, not as a win.**

## A3 — `issued_at` derived from a constant  ·  REAL DEFECT, FIXED

The first version of the merge reconstructed `issued_at` as
`execution_expires_at - DEFAULT_AUTHORITY_TTL`.

That is a derivation resting on a **program constant**, not on authoritative
state. Changing `DEFAULT_AUTHORITY_TTL` would silently shift the reported issue
time of every historical authority.

The project's own discipline says a derivation must rest on authoritative state.
The merge violated it while implementing it. Fixed by recording
`execution_issued_at`.

The lesson generalises: *"derive, don't store"* is not unconditional. A fact about
**what happened** must be recorded. Only a fact that is a **function of recorded
facts** may be derived. §Phase 9 of the mission asked for the discipline's domain
of validity — this is its boundary.

## A4 — Does the V2 shape become impossible?  ·  NO

A decision can still exist with no lifecycle if a caller fails to issue one —
exactly V2's shape. The merge relocates the `None`; it does not eliminate it.
Behaviour stays fail-closed and is pinned.

**Claimed narrowly for this reason.** The merge removes the *persistence*
divergence class (V3/V10), not the *issuance* one (V2).

## Verdict

| Attack | Outcome |
| --- | --- |
| A1 stale projection | held — nothing is cached |
| A2 lifecycle corrupting the decision | real new risk, now a mutation-verified guard |
| A3 `issued_at` from a constant | **real defect, fixed** |
| A4 V2 shape | not eliminated; fail-closed, pinned, claim narrowed |

The abstraction is sound. One implementation defect and one new risk surface,
both closed. Audit 2 should come at it from state integrity rather than logic.
