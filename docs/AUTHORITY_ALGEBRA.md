# Authority algebra — attacking the claim word by word

The claim under test:

> *"An approval is a **single-use**, **time-boxed**, **merchant-** and
> **amount-bound** authorization to execute **one specific purchase**, **revocable
> until spent**, **re-verified against persisted state** at the only point money
> moves."*

Each emphasised phrase is a predicate. Each was attacked. Two did not survive as
written and are restated below.

---

## 1. The predicate table

| Predicate | Represented by | Created | Stored | Enforced at | Bypass attempted | Result |
| --- | --- | --- | --- | --- | --- | --- |
| SINGLE_USE | `PaymentAuthority.consumed_at` | `MockPSP.charge` | `RunState._authorities`, checkpointed | `charge()` | charge twice; crash between; two workers | **weakened** — see §3 |
| TIME_BOUNDED | `expires_at = issued_at + 15min` | `issue_authority` | same | `charge()` via `MockPSP._clock` | supply `now=` at issue time | holds (V4 fixed) |
| MERCHANT_BOUND | `stored.merchant_id` | `record_decision` | `RunState._decisions` | `charge()` | swap merchant; reuse charge_id with another merchant | holds (V9 fixed) |
| AMOUNT_BOUND | `stored.billing_amount_chf` | `record_decision` | same | `charge()` | charge more; charge CHF 0.001 more | **imprecise** — see §2 |
| REVOCABLE | `revoked` + `mandate.status` + `authority_status` | `revoke_*`, platform fields | same | `charge()` and the engine | revoke then charge / restart / replay / resolve | holds (V2, V3, V7, V12 fixed) |
| PERSISTED | `to_snapshot` / `from_snapshot` | `live_worker._save_checkpoint`, `persist` hook | JSON checkpoint | restore | crash at each transition | conditional — see §3 |
| REVERIFIED | every check reads `self._state` | — | — | `charge()` | pass a stale authority object | holds |
| SPECIFIC_PURCHASE | `authorization_id` + fingerprint | `_basket_key`, `record_decision` | same | engine (not the boundary) | see §4 | holds, but not where you'd expect |

---

## 2. AMOUNT_BOUND is really AMOUNT_CEILINGED

`charge()` enforces `amount_chf <= stored.billing_amount_chf`, not equality. So the
set of transactions one authority admits is not a point but a segment:

```
VALID(A, t) ⟺  t.authorization_id = A.authorization_id
            ∧  t.merchant_id      = stored[A].merchant_id
            ∧  0 < t.amount       ≤ stored[A].billing_amount_chf
            ∧  A.consumed_at is None ∧ ¬A.revoked ∧ clock() ≤ A.expires_at
```

Measured: an approval for CHF 100 will execute a charge of CHF 1.00. Nothing
escalates — the customer pays less than approved — and the spend ledger still
records the *approved* CHF 100, which is the conservative direction. But "amount-
bound" overstates it, and the honest word is **ceilinged**. Under-charging is a
legitimate partial capture in real card systems, so this is a correct design; only
the wording was wrong.

---

## 3. SINGLE_USE and PERSISTED are conditional

Two measured failures, both reproduced before being fixed or scoped:

**V10 — durability.** `consumed_at` was written to memory only. Nothing calls
`_save_checkpoint` after a charge; checkpoints follow *decisions* and
*resolutions*. So the last checkpoint on disk predates any charge, and restoring
it resurrected a spendable authority: **CHF 200 against an approved CHF 100.**

Fixed by ordering: **consume → persist → then create the charge record.** Dying
between consumption and persistence, or between persistence and the record, leaves
a dead authority and no money — a legitimate purchase fails to complete, which is
the safe direction for a wallet. The opposite order is what produced the double
execution.

The fix is conditional on an injected `persist` hook. Without one, single-use holds
within the process and not across a crash. That condition is pinned by a test
rather than implied.

**V11 — scope.** `consumed_at` lives in one `RunState`. Two workers restoring the
same checkpoint each hold their own copy and each execute once: **CHF 200 again.**
Closing this requires a single shared store with an atomic compare-and-set on
consumption, which this prototype deliberately does not build. Pinned by
`test_single_use_does_not_hold_across_two_independent_run_states`.

So the honest predicate is:

> SINGLE_USE holds **within one run state, in one process**, and **durably across a
> crash iff the executor is given a persist hook**.

---

## 4. Can A1 ≠ A2 exist with VALID(A1, t₂) where t₂ was not what A1 authorized?

This is the mission's central question. Working through the conjunction above:

- **Different `authorization_id`** → `charge()` looks up `stored[t.authorization_id]`
  and the authority is fetched by that same id. An authority for AU1 cannot be
  pointed at AU2; measured directly (probe H6: charging via AU1's authority executed
  AU1 and left AU2 untouched).
- **Different merchant** → compared against `stored`, not against the passed object,
  so even a forged authority fails. Also now compared on `charge_id` reuse (V9).
- **Higher amount** → refused at `Decimal` precision; CHF 0.001 over is refused.
- **Lower amount** → *admitted*, by design (§2).
- **Different basket** → not visible at the boundary at all (§5).
- **Same transaction, twice** → **this is the one that worked**, via V10 and V11.

**Conclusion.** Within one run state and one process, with a persist hook, no
counterexample was found: authority A cannot be turned into payment for a
*different* transaction. The counterexamples that did exist were all of the form
"the *same* transaction executed *twice*" — which is a violation of SINGLE_USE, not
of non-transferability. One is fixed; the other (two run states) is a stated,
tested boundary.

---

## 5. Where "one specific purchase" is actually enforced

Not at the payment boundary. `charge()` receives an amount and a merchant — **it
never sees a basket.** The purchase is pinned one layer earlier, by the
repeat-delivery fingerprint:

```
(merchant_id, billing_amount_chf,
 [(item_id, item_name, quantity, return_window_days, final_sale, stated_size), …])
```

The charge references `authorization_id`, and that id's facts are frozen by
`authorization_id_conflict`, so the binding reaches the boundary *transitively*
rather than directly. This is why `basket_fingerprint` on the authority is
provenance and not an enforced binding: there is nothing at the boundary to compare
it against.

**Should the boundary bind the basket directly?** No, on the evidence. It would
duplicate a check that already exists one layer up, require passing a basket into a
function whose entire job is money, and — the real argument — create false
confidence that the boundary validates goods when it validates payment. The layer
that can see baskets should check baskets.

---

## 6. What an authority actually authorizes, stated exactly

> **Pay at most the approved amount, to the approved merchant, for this one
> authorization id, once, within fifteen real-clock minutes, while the mandate
> behind it is ACTIVE and neither the authority nor the platform has revoked it.**

It does **not** authorize "the customer-authorized purchase" in the sense of goods:
`mandate_id`, `policy_version` and `basket_fingerprint` are recorded on the grant
and are not consulted at execution. Those are provenance for the audit trail. The
goods-level binding lives in the decision layer, where it is enforceable.
