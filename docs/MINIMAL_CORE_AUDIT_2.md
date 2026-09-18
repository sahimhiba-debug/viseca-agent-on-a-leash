# Minimal core — audit 2 (state integrity / distributed systems)

Deliberately not a replay of Audit 1, which attacked the logic. This one attacks
**persisted state**: compatibility, partial writes, concurrency, and what a second
worker sees.

**Result: the model held. One compatibility hazard found and pinned.**

---

## B1 — Old checkpoints  ·  HAZARD, FAILS CLOSED

A checkpoint written by the two-record build carries an `authorities` array and
decisions with no lifecycle fields. The new `from_snapshot` ignores the array and
defaults the fields to `None`.

So a restored legacy run has approved decisions with **no execution lifecycle** —
which is the V2 shape, and is refused at the payment boundary.

```
restored.get_authority("AU1") is None
charge(...) -> PaymentError: no payment authority on record
```

**Fails closed**, which is correct: a legacy run loses its authorities and must
re-issue rather than charging unconstrained. Pinned by
`test_an_old_checkpoint_without_lifecycle_fails_closed_rather_than_opening`.

Worth stating because the opposite default — treating a missing lifecycle as
unconstrained — is precisely the fail-open that V2 and V3 exploited.

## B2 — Can the lifecycle be persisted without its decision?  ·  IMPOSSIBLE

This is the class the merge exists to kill. V3 and V10 were both "decisions were
checkpointed, authorities were not."

The lifecycle is now a field of the decision, so `to_snapshot` writes both or
neither. There is no ordering in which one survives and the other does not.
Verified: the snapshot has no `authorities` key, and `decisions[0]["revoked"]` is
`true` after a revocation.

## B3 — Two workers from one checkpoint  ·  UNCHANGED

Both restore the same decisions and derive the same projection. Single-use across
processes remains unguaranteed — the long-standing V11 limitation, untouched by
this merge and still stated.

## B4 — Concurrency  ·  UNCHANGED

`issue_authority`, `revoke_authority`, `revoke_outstanding_authorities` and
`consume_authority` all take `_consume_lock`, as before. The compare-and-set that
closed V13/V14 now reads and writes `_decisions` instead of `_authorities`; the
atomicity argument is identical.

Re-verified by the existing atomicity suite: a revocation landing mid-charge is
refused, and 12 racing threads yield exactly one execution.

## B5 — Does anything still read a second copy?  ·  NO

`grep` for `_authorities` returns only a docstring reference. `RunState` has no
such attribute — asserted by `test_there_is_only_one_record_per_authorization`.

## Verdict

| Attack | Outcome |
| --- | --- |
| B1 legacy checkpoints | hazard, fails closed, pinned |
| B2 half-persisted lifecycle | **structurally impossible** |
| B3 two workers | unchanged limitation (V11) |
| B4 concurrency | unchanged; same lock, same CAS |
| B5 residual second copy | none |

Two audits, two real findings (Audit 1's `issued_at` defect, Audit 2's legacy
compatibility), neither of which invalidates the abstraction. The merge is
**security-neutral and structurally smaller** — which is the outcome the mission
asked for: simpler after attack, not more patched.
