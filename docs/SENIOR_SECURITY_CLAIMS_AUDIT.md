# Security claims audit

Every security claim the product makes, classified. A claim is **PROVEN** only if a
named test fails when the property is removed.

| # | Claim | Enforced where | Test | Verdict |
| --- | --- | --- | --- | --- |
| 1 | A confirmed mandate cannot be widened | `mandate.py` — `HardRule` frozen, `tighten_hard_rules` appends only; every rule must pass so the strictest governs | `test_product_invariants::test_I9_*`, `attack_8_policy_mutation` | **PROVEN** |
| 2 | Uncertainty never silently becomes approval | `decision_engine._decide` — `fail > unknown > pass`; `uncertainty_policy` governs unknowns only | `test_I11_*`, `test_failure_modes::test_under_a_decline_policy_*` | **PROVEN** |
| 3 | A missing fact is never invented | `facts.py` — three-valued derivation; `HistoryIndex.is_familiar` returns `None` when unavailable | `test_I12_*`, `test_history_being_unavailable_*` | **PROVEN** |
| 4 | Merchant text cannot change customer policy | `facts.py` — text yields only size / return window / final sale, each narrowing | `test_I7_*` (6 injection payloads × ceilings), `attack_2_merchant_prompt_injection` | **PROVEN** |
| 5 | An approval cannot be redirected to another merchant | `payment.py::charge` — merchant compared against `StoredDecision` | `test_I2_I3_*`, `attack_3_merchant_redirection` | **PROVEN** |
| 6 | An approval cannot be charged for more than approved | same | `test_I2_I3_*` | **PROVEN** |
| 7 | An authorization executes at most once | `state.consume_authority` — locked compare-and-set, consume before charge | `test_I4_I5_I6_*`, `test_execution_atomicity` | **PROVEN, in one process** |
| 8 | Revocation stops money that has not moved | `state._revoked_at` + sweep; `issue_authority` refuses after it; `_run_binding_failures` blocks new purchases | `test_resolution_escape_hatch::test_F1*` (3 tests) | **PROVEN** |
| 9 | A restart does not resurrect a revoked or consumed authorization | lifecycle rides on `StoredDecision`, both in one checkpoint record | `test_F1c_*`, `test_I4_I5_I6_*`, `test_execution_durability` | **PROVEN for the decision path** |
| 10 | A human answer is final; a conflicting second answer is refused | `state.record_resolution` under `_consume_lock` | `test_I8_*`, `test_F3_concurrent_*` | **PROVEN** |
| 11 | A step-up approved after revocation does not move money | `resolve_authorization` re-checks `state.is_revoked` | `test_F1_*` | **PROVEN** |
| 12 | A rolling ceiling is re-checked when the human answers | `resolve_authorization::_period_rules_breached_now` | `test_F2_*` | **PROVEN** |
| 13 | `billing_amount_chf` is verified, not trusted | `decision_engine` always-on `amount_integrity` vs the published FX table | `test_I10_*` (property, all 4 currencies) | **PROVEN** |
| 14 | The platform's `authority_status` / `card_status` are honoured | `decision_engine._platform_status_evaluations` | `test_platform_status` | **PROVEN** |
| 15 | A re-delivered `authorization_id` whose facts changed is a conflict, not a replay | `state.check_repeat_fingerprint` over the basket fingerprint | `test_final_arbitration` (4 tests) | **PROVEN** |
| 16 | An external dependency failure never becomes an approval | `viseca_client` normalises everything to `VisecaApiError`; no approve-on-failure path exists | `test_failure_modes` (26 tests) | **PROVEN** |
| 17 | The audit trail cannot drift from the ledger | `audit.py` is a pure projection, recomputed per call | `test_product_surface::test_the_audit_timeline_is_recomputed_not_stored` | **PROVEN** |
| 18 | The attack demonstrations run against the real engine | `attack_demo` imports the production entry points | `test_attack_demonstrations_use_the_real_engine` | **PROVEN** |
| 19 | A one-shot job is performed once | `research/fulfillment.py`, derived from the ledger | `test_fulfilment_observer` (32 tests) | **PARTIALLY PROVEN — within a run only, and NOT in the decision path** |
| 20 | Exactly-once payment | — | — | **NOT PROVEN.** At-most-once, per process. Two workers restoring one checkpoint can each consume once. |
| 21 | Total spending is capped | — | — | **NOT PROVEN — impossible.** `scope` is `purchase` or `period`; the spec closes the set. |
| 22 | The account's monthly limit is enforced | — | — | **OUTSIDE SYSTEM BOUNDARY.** Real data; no account-scoped counter exists in the official API. Displayed marked *not enforced*. |
| 23 | Merchant claims (size, return window, finality) are true | — | — | **OUTSIDE SYSTEM BOUNDARY.** Attacker-controlled text; we derive from it and cannot verify it. |
| 24 | The step-up channel authenticates the customer | — | — | **NOT PROVEN.** The demo API has no auth and records no `resolved_by`. Scoped as an event-day demo. |

## Claims removed during this review

- *"The customer confirms the compiled rules before anything runs"* — was stated in three
  places with **no confirm control in the UI**. A real confirm gate now exists and stamps
  the audit entry; the claim is true only because the gate was built.
- *"There is no code path from merchant text to a rule the wallet enforces"* — the narrow
  reading (text cannot *create* a rule) holds, but `order.return_window_days` and
  `item.size` have **no input other than merchant text**, so text decides their outcome.
  Reworded: text can never widen policy, and can only narrow a derived fact.
- *"Revocation stops authorized-but-unspent money"* — was **false for a purchase still
  awaiting the customer's answer** until F1 was fixed. Now true and tested.

## Concurrency boundary, stated precisely

- **Single process, multi-thread** — what we support and test. `RunState` guards the
  execution and consent transitions with one lock.
- **Multi-worker / distributed** — **not supported and not claimed.** Two processes
  restoring the same checkpoint can each consume the same authority once.
- `api.py` runs sync endpoints in Starlette's threadpool, so concurrent requests are real
  and are the reason both transitions are locked.
