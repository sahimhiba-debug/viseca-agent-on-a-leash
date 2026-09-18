# Autonomous security research — the final architectural position

Written from first principles, not from the previous narrative. Where earlier
conclusions of this project survive, they survive because they were re-derived;
where they do not, they are marked.

The headline result is not a vulnerability. It is a reframing:

> **The wallet's guarantee is confinement to the customer's policy envelope. The
> size of that envelope is the customer's choice — and four of the five official
> mandates define an envelope with no total bound at all.**

---

## 1. The security problem

Not spend limits. Not intent fidelity. Not agent identity.

The problem that appears *specifically* because an AI agent acts for a customer is
that **authority outlives the intent that created it.** A human at a checkout makes
a decision and acts on it in one motion. An agent receives a grant and holds it —
across retries, crashes, restarts, workers, and the customer changing their mind.

So every question that matters is about the *lifecycle of a grant*, not about the
correctness of a decision:

- can the grant be re-pointed at something else? (transferability)
- can it be used twice? (replay / double execution)
- does it die when the customer says so? (revocation)
- does it survive things it should not? (crash, restart, concurrency)

Every one of the fourteen vulnerabilities found across three passes is in that
list. **None** was a policy-evaluation bug. The decision engine has been correct
since the second pass; the grant lifecycle took three more passes to get right.

---

## 2. Attacker model

Fully compromised agent: knows the mandate, every prior authorization, every
identifier, every response and error. May propose anything, retry anything, replay
anything, race anything, and crash the process at any point. Malicious merchant:
controls all free text. Unreliable network. Multiple workers.

**Cannot** forge platform-authoritative fields — `authorization.timestamp`,
`authority_status`, `card_status_at_attempt`, `mandate.status`, `card_id` — because
they arrive inside `envelope["data"]` from `/v1/decision-requests/next` and the
agent has no channel that writes them. This is the single load-bearing assumption
of the whole model, and it is an assumption about the *architecture*, not about the
agent's good behaviour.

---

## 3. Trust model

| Component | Trusted for | If it lies |
| --- | --- | --- |
| Customer | the policy itself | nothing to defend; it is their money |
| Platform event stream | timestamps, statuses, ids, amounts | **total compromise** — every window, every revocation signal, every identity binding is theirs |
| Wallet code + persisted state | the decision and the grant lifecycle | total compromise |
| Clock (payment boundary's own) | expiry | expiry becomes advisory (was V4) |
| Persistence layer | durability of consumption | double execution across a crash (was V10) |
| Human approval channel | one answer for one authorization | approval becomes re-pointable |
| Merchant text | **nothing** | can satisfy `item.size`, and narrow a return window the platform already asserted — nothing else |
| Shopping agent | **nothing** | this is the threat model |
| PSP | that a capture happens at most once per idempotency key | see §15 |

The five-tier model from earlier passes survives re-derivation, with one
correction: the platform is not merely "trusted", it is **the root of trust**. Every
other guarantee is downstream of it.

---

## 4. The true security object

**It is not `PaymentAuthority`.** That was the previous passes' answer and it does
not survive inspection.

Derive it from what `charge()` actually validates against:

```python
stored = self._state.get_stored_decision(authorization_id)
if stored.decision != "allow":            ...   # ← stored
if merchant_id != stored.merchant_id:     ...   # ← stored
if amount_chf > stored.billing_amount_chf:...   # ← stored
authority = self._state.get_authority(authorization_id)
if authority.consumed_at / .revoked / expiry:   # ← authority
```

Merchant and amount are enforced against **`StoredDecision`**, never against the
authority — even though the authority carries `merchant_id` and
`amount_ceiling_chf` copies of exactly those fields. Those copies are decorative,
like `policy_version` and `basket_fingerprint` before them.

So the real object is a **pair**:

```
GRANT = ( immutable decision record , monotonic lifecycle state )

  record    = StoredDecision: authorization_id, merchant, amount, fingerprinted
              basket, timestamp. Written once, never mutated. `record_decision`
              returns the existing entry rather than overwriting.

  lifecycle = issued ──▶ consumed        (terminal)
                    └──▶ revoked         (terminal)
              monotonic, persisted, and now transitioned by an atomic
              compare-and-set.
```

`PaymentAuthority` is the *name we gave the lifecycle half*, carrying redundant
copies of the record half. That is why it kept generating vulnerabilities: three
passes tried to secure a thing whose security content lives somewhere else.

**Testing the object against the mission's questions:**

| Can it be… | Answer |
| --- | --- |
| copied? | the record can; copying it grants nothing, because the lifecycle is keyed by `authorization_id` in one store |
| replayed? | no — `consumed_at` is terminal and persisted |
| modified? | the record is write-once; a re-delivery with different facts is a conflict |
| confused with another? | no — the lifecycle is looked up by the same id the record is |
| survive revocation? | no, at four levels (authority, mandate status, platform authority status, card status) |
| survive restart? | no, given a persist hook |
| cross workers/processes? | **yes — this is the one real remaining gap (§11)** |
| be manufactured by the agent? | no — `issue_authority` is the sole constructor and requires an `allow` |
| be influenced by the merchant? | only `item.size` and a return-window narrowing |

---

## 5–6. Authority semantics and transaction identity

```
VALID(grant, t) ⟺ t.authorization_id = record.authorization_id
                ∧ t.merchant_id      = record.merchant_id
                ∧ 0 < t.amount       ≤ record.billing_amount_chf
                ∧ lifecycle = issued
                ∧ clock() ≤ expires_at
                ∧ mandate.status = ACTIVE ∧ platform statuses active
```

Transaction identity at the *decision* layer is the fingerprint
`(merchant, CHF total, [(item_id, item_name, qty, return_window, final_sale, size)])`
— facts derived from merchant text, never the text itself, so a fact-moving edit is
a conflict while cosmetic noise is a retry.

Transaction identity at the *payment* layer is only `(authorization_id, merchant,
amount ≤ ceiling)`. **The basket is not visible at the boundary.** These are
different identities, joined by `authorization_id`. That join is the whole
architecture: goods are pinned where goods are visible, money where money is.

---

## 7–9. State machine, lineage, side effects

The lifecycle is three states and two terminal transitions; every impossible
combination (`REVOKED+CHARGEABLE`, `CONSUMED+CHARGEABLE`, `EXPIRED+CHARGEABLE`,
`EXECUTED+UNCONSUMED`) was searched for over ~100,000 generated operation
sequences and not found — see `STATE_MACHINE_SECURITY.md`.

**Lineage, the one case worth naming:** merchant text → three whitelist extractors
→ derived facts → fingerprint → conflict detection. Untrusted data becomes a
*fingerprint input* but never an *authority input*. The platform gates whether the
fact is claimable at all: with `order_returnable=false`, a merchant claiming "30
days" is **blocked**; with `unknown`, it is **reviewed**. Merchant text can narrow,
never create. `item.size` is the exception — no platform field backs it.

**Side effects.** See §15. The wallet performs `check → state change → side
effect`, in that order, deliberately.

---

## 10. The strongest attack found

Not a bypass. **The policy envelope itself.**

A fully compromised agent, proposing only purchases that satisfy the customer's
own confirmed mandate, extracts:

| Mandate | Shape | 50 attempts |
| --- | --- | --- |
| SCEN0001 | CHF 120/order **and CHF 300 / 7 days** | **CHF 300**, then blocked, permanently |
| SCEN0000 | CHF 20 / purchase, no total | **CHF 1,000** — and unbounded in attempts |

Both are the wallet behaving correctly. A per-purchase cap bounds each purchase and
bounds nothing in total. **Four of the five official mandates have the unbounded
shape**, and the compiler never said so — so the customer could not have known the
policy they confirmed had no ceiling on total exposure.

This is the most important finding of the three passes, and it is not a bug in the
wallet. It is the difference between *"the agent cannot exceed your rules"* and
*"the agent cannot spend more than X"*. Only the second is what a customer hears.

**Fixed** by disclosing it at compile time, before confirmation — advisory text,
read by no rule, changing no decision, so the replay is untouched.

---

## 11. Counterexamples found this pass

**V13 — revocation lost to a check-then-act window.** `charge()` validated the
authority, then called `consume_authority`, which re-read and wrote `consumed_at`
**without re-validating**. A revocation landing in between was overwritten: money
moved on an authority the customer had already revoked, leaving it both revoked and
consumed. Reproduced by widening the window to what a real external capture costs.

**V14 — double execution through the same window.** Two threads both passed the
`consumed_at is None` check and both consumed: CHF 200 against an approved CHF 100.

Neither was reachable by the earlier 24-thread test, which raced identical calls
through a window a few bytecodes wide that the GIL closed by luck. That is exactly
the reasoning this project criticised when it was applied to concurrency, and it was
still load-bearing here.

**Fix:** validation moved *into* the state transition, which is now an atomic
compare-and-set under a lock. The lock is **proven** load-bearing: removing it while
widening the read-modify-write window reproduces the double execution; restoring it
fixes it. (An earlier mutation that removed the lock without widening the right
window passed — recorded because it would have let me claim the lock mattered
without evidence.)

**V11 — still open, by decision.** Single-use is per-`RunState`. Two *real OS
processes* restoring the same checkpoint each cross the boundary: CHF 200. Closing
it needs a shared store with an atomic CAS (§15). Pinned by a test, not hidden.

---

## 12. Invariants that actually matter

Reduced from thirty-odd to the six that carry the architecture. Each is close to
machine-checkable and each has a test.

1. **Only an `allow` mints a grant, and only the wallet mints one.**
2. **The record is write-once.** A re-delivery with different security-relevant
   facts is a conflict, never an inherited approval.
3. **The lifecycle is monotonic.** `issued → consumed | revoked`, both terminal,
   both persisted, transitioned atomically.
4. **Execution validates against the record, at one point, re-read from live
   state.** Not against any object the caller supplies.
5. **A non-ACTIVE mandate, a dead platform status, or a blocked card authorizes
   nothing** — checked before anything else is decided.
6. **Untrusted data never becomes an authority input.** It may become a fingerprint
   input; the platform gates whether a fact is claimable at all.

Everything previously written as a separate invariant is a corollary of one of
these, or is presentation.

---

## 13. Fixes this pass

| | Fix | Mutation-verified |
| --- | --- | --- |
| V13 | validation moved into an atomic compare-and-set at the transition | yes |
| V14 | same fix; lock proven load-bearing by widening the true window | yes |
| — | unbounded-policy disclosure at compile time | yes (test fails without it) |

---

## 14. Remaining assumptions

| Assumption | If false |
| --- | --- |
| The platform's event stream is honest | everything collapses; it is the root of trust |
| One `RunState`, one process | two workers each execute once (V11) |
| A persist hook is wired to the executor | consumption is not durable across a crash |
| `item.size` as stated by the merchant | no platform field backs it |
| The PSP is idempotent on a stable key | see §15 |

---

## 15. The payment boundary — what the wallet proves and what it cannot

`MockPSP` has no external side effect; a "capture" constructs a Python object. To
reason about a real processor, this pass built a failure-injecting `ExternalPSP`
whose capture has a side effect that outlives the process and whose response can be
lost. Measured:

| Ordering | Crash after the side effect | Result |
| --- | --- | --- |
| **consume → persist → capture** (current) | response lost | PSP captured once; wallet refuses to retry. **CHF 100. Safe.** |
| capture → consume | crash before consume | retry captures again. **CHF 200. Unsafe.** |

So the current ordering is right, and the guarantee it provides is precisely:

> **At-most-once, not exactly-once.**

The wallet guarantees money never moves twice. It does **not** guarantee money
moves at all: if the capture succeeds and the response is lost, the authority is
already consumed and the wallet will never retry. That is a deliberate trade —
availability for safety — and it is the correct trade for a wallet. It must not be
described as exactly-once.

**What a real PSP must provide** for exactly-once:

1. **Idempotent capture keyed on a stable key.** Measured: replaying the same key
   moves money once. A *fresh* `charge_id` per retry defeats this entirely — so the
   key must be derived from the authorization, not generated per attempt. Our
   `charge_id` is caller-supplied and arbitrary; that is a documented requirement on
   the caller, not something the wallet enforces.
2. **A status lookup** so the wallet can resolve "did it happen?" after a lost
   response. Without it, at-most-once is the ceiling.
3. **Atomic compare-and-set on consumption** if more than one worker may execute —
   this is the same primitive that would close V11. For a single host, an
   `O_EXCL` marker file is sufficient; nothing distributed is required.

---

## 16–17. What the wallet guarantees, and what it does not

**Guarantees** (within one run state, one process, persist hook wired):

- a grant cannot be re-pointed at a different authorization, merchant, or a higher
  amount
- a grant executes at most once, durably
- revocation stops it — at the authority, the mandate, and both platform statuses
- a security-relevant change to the purchase invalidates the approval; a cosmetic
  one does not
- a human approval applies to exactly the reviewed facts and cannot be re-priced
- no untrusted input becomes an authority input
- malformed input, NaN/∞ money, network failure and crashes never become approval

**Does not guarantee:**

- that money moved (at-most-once, §15)
- single-use across processes (V11)
- anything if the platform lies
- that the merchant told the truth about `item.size`
- **any bound on total spend beyond what the customer's policy states** — the
  finding of §10

---

## 18. Final minimal architecture

```
CUSTOMER INSTRUCTION ──compiler──▶ RULES + open_questions ("no total limit")
                                        │
PLATFORM EVENT (root of trust) ─────────┤
                                        ▼
                        ┌──────────────────────────────┐
                        │ DECISION ENGINE              │  fail > unknown > pass
                        │ + always-on safety checks    │  uncertainty_policy
                        └──────────────────────────────┘
                                        │
                        ALLOW ──▶ GRANT = (record, lifecycle)
                                   record:    write-once
                                   lifecycle: issued ▶ consumed | revoked
                                        │
                        ┌──────────────────────────────┐
                        │ PAYMENT BOUNDARY             │  validates vs RECORD
                        │ atomic CAS on the lifecycle  │  one point, live state
                        └──────────────────────────────┘
                                        ▼
                                   AT-MOST-ONCE
```

**Recommended simplification, not performed:** `PaymentAuthority` should shed
`merchant_id`, `amount_ceiling_chf`, `basket_fingerprint` and `policy_version` —
all four are copies of `StoredDecision` fields that nothing enforces against. What
remains (`issued_at`, `expires_at`, `revoked`, `consumed_at`) *is* the lifecycle,
and naming it so would end three passes' worth of confusion about which object is
load-bearing. Not done here because it touches the API and UI surface for zero
behavioural gain, and the demo is imminent — but it is the right next change, and
the fields are documented as provenance in the meantime.

---

## 19–20. Demo implications and final claims

The strongest honest demo beat is no longer a bypass — it is §10. *"Your policy caps
each purchase at CHF 20. A compromised agent stays inside it and spends CHF 1,000.
Here is the wallet telling you that before you confirm."* That is a real problem
customers have, it is demonstrable in one screen, and it is true.

**Defensible:**

> Within one run state and one process, a grant is a write-once decision record
> plus a monotonic, persisted lifecycle. It cannot be re-pointed at another
> transaction, executes at most once, and dies on revocation, expiry, a non-active
> mandate, or a dead platform status — validated at a single point against live
> state by an atomic compare-and-set. Total exposure is bounded by the customer's
> policy and by nothing else.

**Not defensible, and not to be said:** "secure", "exactly-once", "tamper-proof",
"cryptographic", "production-ready", "non-transferable" without its scope, or any
claim about the hosted challenge derived from `MockPSP`.

**The answer to the mission's final question — maximum damage from a fully
compromised agent:** the customer's policy envelope, exactly. Measured at CHF 300
for the one official mandate with a rolling cap, and **unbounded** for the four
without one. The wallet's job is confinement to that envelope; the envelope's size
is a product decision, and until this pass the customer was never told which shape
theirs was.
