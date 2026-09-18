# Claim audit

Every security-flavoured claim in this repository, classified. The categories are
the brief's: **PROVEN BY CODE** (structural, checkable by reading), **SUPPORTED BY
TEST**, **ASSUMPTION** (true only under a stated precondition), **DEMO-ONLY**, and
**NOT TRUE** (found false and corrected).

The point of this document is that the last category is not empty.

---

## NOT TRUE — claims this project made and later disproved

| Claim, as it was written | Where | What was actually true |
| --- | --- | --- |
| "I29 — revoking the mandate revokes every outstanding payment authority" | pass 4 | False. A human-approved step-up minted **no** authority, so there was nothing to revoke; it charged CHF 175 after revocation (V2) |
| "an authorization with no authority still charges normally" (asserted as *safe*) | pass 4 | False and load-bearing: this fail-open default is what let V2 and V3 move money (V10's ancestor) |
| "I26 — a payment authority is single-use … expiry is independently re-checked" | pass 4 | Expiry was judged by a **caller-supplied clock** (V4) |
| "single use … persisted, so a restart does not reset it" | pass 5 | False. Consumption was memory-only; a real crash gave CHF 200 against an approved CHF 100 (V10). The pass's own test snapshotted *after* charging — a sequence production never performs |
| "I1 — no authority exists without a valid customer-confirmed mandate" | pass 2 | False for four passes. Nothing re-checked that the mandate was *still* ACTIVE, so a **revoked mandate kept authorizing** (V12) |
| "merchant text can never make a decision more permissive" | pass 4 | Overstated in one direction, understated in another — see the corrected statement below |

Six disproved claims, five of them made by earlier passes of this same project.
That is the base rate this document exists to record.

---

## PROVEN BY CODE — structural, checkable by reading

| Claim | Structure that proves it |
| --- | --- |
| Exactly one place moves money | `ChargeRecord` constructed at one line; `_charges` written on the next; verified by grep |
| Only the wallet mints authority | `RunState.issue_authority` is the sole constructor, gated on `allow` |
| Merchant text cannot become policy | the compiler is never imported by the engine or facts; asserted by source inspection, not behaviour |
| No LLM in the decision path | no model client is imported anywhere in `decision_engine`/`rules`/`facts` |
| A resolution cannot be re-priced | `record_resolution` takes no amount and no merchant — not "checks" them, *cannot receive* them |
| Explanation cannot change outcome | drift and the verdict split are computed after `_decide()` and never read by it |

---

## SUPPORTED BY TEST

| Claim | Evidence |
| --- | --- |
| An approval cannot be redirected to a different authorization, merchant, or a higher amount | 15 mutation families × 3 contexts; probe H6; `test_properties.py` |
| A revoked/expired authority, blocked card, or non-ACTIVE mandate cannot be paid | `test_platform_status.py`, `test_mandate_status.py`, corpus `F02` |
| Revocation reaches human-approved step-ups, and survives a restart | `test_revocation_end_to_end.py`, corpus `N01` |
| A security-relevant re-delivery cannot inherit the approval; a cosmetic one does not fork a retry | mutation fuzzer, both directions, mutation-verified |
| An event for another card or mandate is rejected before anything is decided | `test_run_binding.py` |
| ~100,000 adversarial operations violate no invariant | `test_state_machine.py` + two sweeps |

---

## ASSUMPTION — true only under a stated precondition

These are the claims that must always be spoken **with** their condition.

| Claim | Precondition |
| --- | --- |
| Single-use is durable across a crash | the executor is constructed with a `persist` hook |
| Single-use holds at all | one `RunState`, one process. Two workers from one checkpoint each execute once (V11) |
| Single execution under concurrency | the GIL and a small check-then-act window. Not synchronised; not designed |
| Rolling-window limits hold | `authorization.timestamp` is truthful. Platform-supplied, unverifiable by us, and the contract requires us to key on it |
| A charge retry after restart is safe | it fails closed rather than returning the original record — safe, not idempotent |

---

## Corrected statements

Where a claim was overstated, the replacement — not a deletion.

**On merchant text.** Not *"merchant text can never make a decision more
permissive"*, and not *"a merchant can lie about return terms"* either. Measured:

- platform says not returnable + merchant claims 30 days → **BLOCK**
- platform says unknown + merchant claims 30 days → **REVIEW**
- platform says returnable + merchant admits final sale → **BLOCK**
- platform says returnable + merchant claims 30 days → **ALLOW**

So: **merchant text can narrow a day-count within a returnability the platform has
already asserted, and can make any outcome stricter. It cannot create
returnability and cannot turn unknown into known.** `item.size` is the weaker case:
no platform field backs it, so there the merchant is the sole source.

**On the amount.** Not "amount-bound" but **amount-ceilinged**: `charge()` enforces
`≤`, not `=`, so an approval for CHF 100 will execute CHF 1. That is a legitimate
partial capture and never an escalation, but the word matters.

**On the payment boundary.** `MockPSP` guards a *simulated* execution. Neither
`api.py` nor `live_worker.py` ever calls it, because the official challenge has no
payment-execution endpoint. "No unauthorized EXECUTED" is a true statement about
our mock and says nothing about the hosted challenge, whose output is a decision.

---

## DEMO-ONLY — not security, marked to prevent confusion

| Thing | What it actually is |
| --- | --- |
| `AuthorizationDrift` | a field diff computed after the decision; explains, never gates |
| `policy_verdict` / `security_verdict` | the same evaluations re-scoped for display |
| `PaymentAuthority.policy_version`, `basket_fingerprint`, `mandate_id` | provenance on the grant, not enforced bindings |
| The demo UI | a viewer over the engine; no decision logic |
| The 17-case red-team matrix | a readable demo artefact; the 133-case corpus is the real one |

---

## Words we do not use

**"Secure."** Unqualified, about the system.
**"Tamper-proof."** Nothing here is.
**"Cryptographically verified."** No keys, no signatures, no verifier.
**"Non-transferable"** without its scope — it is non-transferable *across
transactions*, and was twice transferable *across executions of the same one*.
**"Proven."** The state machine explored orderings; it did not prove correctness.
**"Understands intent."** It matches compiled anchors.
