# Pre-registration — written before any prototype of this pass

The thesis under test:

> **T1** A delegation is bounded only where an authoritative record exists at the
> same scope as the bound.
>
> **T2** The scopes are exactly three: mandate (job capability), authorization
> (decision ledger), account (rolling spend, unimplemented).

## What would falsify T2 (the scope count)

| # | Falsifier | Decided by |
| --- | --- | --- |
| **B1** | An official field that creates a *binding* constraint at a scope other than the three | field map + a rule that would change a decision |
| **B2** | An attack that cannot be *expressed* as a violation at any of the three scopes | attack battery |
| **B3** | Two individually-valid authorizations that jointly violate an official or customer constraint belonging to a fourth scope | constructed pair |
| **B4** | A lifecycle property that cannot be safely attached to any of the three objects | state/lifecycle audit |
| **B5** | A cross-field invariant (e.g. amount × FX = billing_amount_chf) that no scope currently owns | consistency probe |

A candidate scope counts only with (1) official challenge semantics, (2) official
data, or (3) an experimentally demonstrated security requirement. **Theoretical
possibility is not evidence.** A field that exists but is uniform across the data,
enforced upstream, or documented as non-policy does NOT establish a scope.

## What would falsify T1 (the same-scope principle)

| # | Falsifier | Decided by |
| --- | --- | --- |
| **C1** | A bound at scope A that is *safely and completely* enforced using only authoritative state at a lower scope B | constructed counterexample |
| **C2** | Conversely: a case where lower-scope state is used for a higher-scope bound and is demonstrably safe because the higher scope cannot fan out | official data cardinality |

C2 is the dangerous one for us: if the official data has 1:1 cardinality between
scopes, our three-scope model may be *untestable* on the official corpus rather than
*true*. **If that is what we find, we must say so and not claim confirmation.**

## Decision rule, fixed now

- **CONFIRMED** requires: no B-falsifier fires, and every surviving invariant is
  pinned by a test.
- **FALSIFIED** requires naming the failed invariant, the missing scope, and why
  existing state cannot provide it.
- If a scope is real but **unenforceable with the information the official API
  provides**, the honest verdict is CONFIRMED-WITH-DOCUMENTED-LIMIT, not confirmed
  and not falsified. That outcome must be reported as prominently as either.
- **No mechanism is built unless a B-falsifier fires.** Reducing uncertainty is the
  deliverable; code is not.

## Mechanical corrections log

Any correction to these criteria after seeing results is recorded here.

- *(none yet)*
