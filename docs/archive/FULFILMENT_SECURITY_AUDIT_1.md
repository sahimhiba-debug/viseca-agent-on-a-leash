# Fulfilment audit 1 — attacking the stateful observer

Independent attack on the *concept*, assuming the attacker knows the design.
Attack classes drawn from the brief's list of 22; only the ones with a plausible
mechanism were built.

**Result: two attacks succeeded. Both killed the abstraction, not the idea.**

---

## A8 — Human step-up laundering  ·  SUCCEEDED

**Hypothesis.** The observer is fed from *engine* ALLOWs. A step-up rewrites the
*stored decision* instead. If the agent gets every purchase reviewed and approved,
the tally never advances.

**Construction.** Mandate with `merchant.familiar` at a merchant with no history,
so the purchase is reviewed; the customer approves it.

**Observed.**
```
AU1 -> review
human approves AU1 -> stored decision is now 'allow'
observer on the NEXT monitor -> first_fulfilment
```

**Survived? No.** The job is invisibly unfulfilled forever.

The sting is that this attack *looks like more oversight*: the customer is asked
about every purchase and approves each one on its own merits. Nothing in the
interface says "this is the fifth time." It is the same shape as V2, where a
human-approved step-up minted no payment authority and so escaped revocation.

---

## A12 — Restart  ·  SUCCEEDED

**Hypothesis.** The tally is an attribute of a Python object. If it is not in the
checkpoint, a restart resets the job.

**Observed.**
```
before restart -> already_fulfilled
fulfilment state present in the RunState snapshot? False
after restart  -> first_fulfilment
```

**Survived? No.** Identical to V3, V8 and V10.

---

## Attacks that failed (the model held)

| Class | Construction | Result |
| --- | --- | --- |
| Substitution / SKU | `Trail-running shoes` against a `road-running` anchor | **blocked by the rule engine** before fulfilment is consulted |
| Merchant switch | same item, different seller | caught — the anchor is merchant-independent |
| Batch (class 3) | qty=2 in one authorization | caught by the earlier unit-counting fix |
| Multi-job / cross-customer | — | not reachable: one mandate per run |

The substitution result is the model's best structural property: the fulfilment
key is the customer's *own compiled anchor*, so evading fulfilment means failing
the policy check. An attacker cannot be outside both.

---

## Is the abstraction wrong?

Per Phase 9, the question before patching.

Both successful attacks share one cause: **the tally is a second record, kept
beside the decision ledger and free to drift from it.** Patching would mean adding
persistence (for A12) and a second feed from resolutions (for A8) — which is
exactly what was done for `PaymentAuthority`, twice, before the same class of bug
appeared again here.

**Verdict: the abstraction is wrong.** A stateful observer is the defect. The
concept — a one-shot job can be finished — is untouched by either attack.

**Recommendation: rebuild as a derivation over the persisted ledger.** Do not
patch. Audit 2 should attack the rebuild as a different attacker.
