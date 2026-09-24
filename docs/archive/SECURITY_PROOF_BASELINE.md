# Security proof — frozen baseline

<!-- snapshot -->
> **SNAPSHOT — written 18 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Recorded before the proof-breaking pass touched anything. Every number here was
measured, not remembered.

| | |
| --- | --- |
| Branch | `rnd/verifiable-agentic-wallet` |
| Commit | `ccacffd` |
| Working tree | clean |
| `main` | untouched at `1aa3bac` |
| Tests | **463 passed** |
| Official replay | **45 events — 19 allow / 2 review / 24 block** |
| Adversarial corpus | **133/133 held**, 10 categories |
| Legacy red-team matrix | **17/17** |
| Vulnerabilities fixed to date | 8 (V1–V8), passes 4–5 |

## `PaymentAuthority` as frozen

```
authorization_id : str
mandate_id       : str            <- provenance, not enforced
merchant_id      : str
amount_ceiling_chf : Decimal
currency         : str
issued_at        : datetime       <- real clock
expires_at       : datetime
basket_fingerprint : BasketKey    <- provenance, not enforced
policy_version   : str            <- provenance, not enforced
evidence_ref     : str
revoked          : bool
consumed_at      : datetime | None
```

## The payment boundary as frozen

`MockPSP.charge(charge_id, authorization_id, amount_chf, merchant_id, now=None)`,
the only constructor of `ChargeRecord` in the repository, in order:

1. `charge_id` seen before → compare `authorization_id` and `amount`; return the
   existing record if both match, else refuse.
2. `amount_chf > 0`
3. stored decision exists for `authorization_id`
4. stored decision is `allow`
5. `merchant_id == stored.merchant_id`
6. `amount_chf <= stored.billing_amount_chf`
7. authority exists (fail-closed since V2/V3)
8. authority not consumed
9. authority not revoked
10. authority not expired, judged by `MockPSP._clock`

## The claim under test

> *"An approval is a single-use, time-boxed, merchant- and amount-bound
> authorization to execute one specific purchase, revocable until spent,
> re-verified against persisted state at the only point money moves."*

Every word of that sentence is a predicate to be attacked in
`docs/archive/AUTHORITY_ALGEBRA.md`. The findings of this pass are in
`docs/archive/FINAL_SECURITY_POSITION.md`.
