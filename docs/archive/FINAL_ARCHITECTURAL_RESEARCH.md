# Final architectural research — the minimal trusted core

The mission: find the smallest set of authoritative facts and atomic transitions
that stops a compromised agent turning one delegation into more economic outcome
than was authorized.

**Answer, measured:**

```
mandate snapshot  +  decision ledger  +  one atomic transition
```

Three things. Everything else in the wallet is derived, explanatory, or
presentation — and this pass proved it by deleting the largest counterexample and
watching nothing break.

**Decision: B — remove unnecessary mechanisms.** Not "already minimal": a whole
duplicate record was still there.

---

## 1. What was found

A survey of every `PaymentAuthority` field across production source:

| Field | Reads in `src/` |
| --- | --- |
| `expires_at`, `revoked`, `consumed_at` | 2, 2, 3 |
| `merchant_id` | 1 (only to feed a check against the decision record) |
| `amount_ceiling_chf`, `basket_fingerprint`, `policy_version`, `currency`, `issued_at`, `evidence_ref`, `mandate_id` | **0** |

**Seven of twelve fields were never read.** The object's entire security content
was three lifecycle facts about a decision that already existed in another record.

So the second record was deleted. `RunState._authorities` is gone; the lifecycle
rides on `StoredDecision`; `PaymentAuthority` is a projection built on demand.

**Net −26 lines in `state.py`, one source file changed, zero behavioural
difference on every gate.**

## 2. Gates, before and after the merge

| | Before | After |
| --- | --- | --- |
| Tests | 517 | **528** (+11 pinning the merge) |
| Official replay | 19 / 2 / 24 | **19 / 2 / 24** |
| Adversarial corpus | 133/133 | **133/133** |
| Legacy matrix | 17/17 | **17/17** |
| Fulfilment differential | 6 / CHF 1,787.40 | **6 / CHF 1,787.40** |
| Demo (API, step-up, revocation) | works | verified end to end |

## 3. What the merge structurally buys

V3 and V10 were both *"decisions were checkpointed, authorities were not."* The
lifecycle is now a field of the decision, so the snapshot writes both or neither.
**There is no ordering in which one survives and the other does not.**

The projection is rebuilt on every call, so it cannot hold a stale copy.

## 4. What it costs — stated, not hidden

`StoredDecision` is no longer wholly immutable; the lifecycle mutates in place.
That is a real new risk surface, now a mutation-verified guard: no lifecycle
transition may alter the decision, amount, merchant, basket or timestamp.

And it does **not** make the V2 shape impossible — a caller can still fail to
issue a lifecycle. It stays fail-closed. The claim is narrowed accordingly: the
merge removes the *persistence* divergence class, not the *issuance* one.

## 5. The discipline, and its boundary

Audit 1 found the merge violating the very principle it implemented: `issued_at`
was reconstructed as `expires_at - DEFAULT_AUTHORITY_TTL` — a derivation resting
on a **program constant** rather than on authoritative state. Changing the
constant would silently rewrite history.

That gives the discipline its domain of validity, which Phase 9 asked for:

> A fact about **what happened** must be recorded.
> Only a fact that is a **function of recorded facts** may be derived.
> A "derivation" that depends on a mutable program constant is neither — it is a
> second source of truth wearing a derivation's clothes.

`issued_at` is now recorded. The discipline caught a violation of the discipline.

## 6. Economic delegation — unchanged by this pass

| Shape | Maximum for a compromised agent |
| --- | --- |
| standing | per-transaction cap × ∞ — the customer granted it |
| recurring | cap × ∞, or the rolling cap |
| **one-shot** | cap × ∞ today (measured CHF 1,729 against CHF 400 delegated); cap × 1 with derived fulfilment |
| ambiguous | cap × ∞, observer silent |

The minimal core constrains the **transaction**; only the derived fulfilment view
constrains the **job**; nothing observable constrains the **outcome in the world**.

## 7. The twelve stop-condition questions

1. **Minimal trusted core** — mandate snapshot + decision ledger + atomic transition.
2. **Truly authoritative** — the decision content (write-once) and the execution lifecycle (monotonic).
3. **Purely derived** — `PaymentAuthority`, rolling spend, fulfilment, drift, verdict split, facts.
4. **Never safely duplicated** — the execution lifecycle. Six vulnerabilities were one duplication.
5. **A compromised agent can still** — spend the full policy envelope (unbounded for standing/recurring), burn a one-shot job with a decoy, lie about `item.size`, exploit multi-process single-use.
6. **Economic outcome** — §6.
7. **Attack prevented** — five monitors for a job delegated once: CHF 1,729 against CHF 400.
8. **Why** — fulfilment derived from the ledger, anchored on the customer's own compiled anchor, so evading it costs the agent the policy check.
9. **Outside our control** — outcomes in the world, merchant truth about size, compound instructions, multi-process single-use, the platform's honesty.
10. **Differentiated** — *adding security state can make a wallet less secure.* Six of this project's vulnerabilities were duplicate state drifting from the record that already determined it. We deleted an entire security object and the invariants got stronger.
11. **Two audits** — yes; Audit 1 found a real defect in the merge, Audit 2 a compatibility hazard. Neither invalidated the abstraction.
12. **Under three minutes** — yes (§8).

## 8. Demo

1. *"You said buy **the** monitor. The agent bought five. Every one passed your rules."* — CHF 1,729 against CHF 400 delegated.
2. *"Nothing catches it: the duplicate window is 60 minutes; these are days apart."*
3. *"It isn't tracked — it's derived from the decision ledger. That's why it survives a restart and counts the one you approved at step-up."*
4. *"And we deleted the object that used to hold that state. Six of our vulnerabilities were a second copy of it."*

## 9. Claims

| Claim | Evidence | Safe wording |
| --- | --- | --- |
| 7 of 12 authority fields were never read | grep over `src/` | "Its security content was three lifecycle fields." |
| Deleting the second record changed nothing | 528 tests, all gates | "Security behaviour is identical; the structure is one record smaller." |
| Half-persistence is impossible | snapshot shape + test | "The lifecycle cannot be checkpointed without its decision." |
| 6 purchases repeat a job described once | differential | "Six approved purchases worth CHF 1,787 repeat a job the customer described once." |

**Must not say:** exactly-once; universal intent understanding; universal merchant
truth; multi-process guarantees; that we secure an official Viseca payment
endpoint (there is none); that the merge made V2 impossible (it did not).

## 10. Next mission, self-selected

Not another mechanism. The remaining gap with real economic weight is **the
unbounded dimensions** — 4 of 5 official mandates have no total cap and the
customer is only told at confirmation time. The honest next step is product, not
security: make the delegation envelope visible *before* confirmation, in CHF, and
let the customer close it. That needs a designer more than a researcher.
