# What we can prove

One line per product claim, with the test that fails if the property is removed. The
full classification, including the claims we removed, is in
`SENIOR_SECURITY_CLAIMS_AUDIT.md`.

| Claim | Evidence | Verdict |
| --- | --- | --- |
| We prevent authorization replay | `MockPSP.charge` consumes under an atomic compare-and-set before charging — `test_I4_I5_I6_*`, `attack_4_replay` | **proven, in one process** |
| We prevent merchant redirection | merchant compared against the stored decision — `test_I2_I3_*`, `attack_3` | **proven** |
| We enforce the customer's amount limit | the rule engine, and again at the execution boundary — `test_I2_I3_*`, `attack_1` | **proven** |
| **A rolling spending cap cannot be breached by proposal order or by a late human answer** | every window containing the purchase is checked, not just the one ending at it — `test_window_containment` (10 tests); 367/400 breaching orders → 0/400 | **proven** |
| We support human step-up | `resolve_authorization`, scoped to one authorization — `test_I8_*`, `attack_7` | **proven** |
| We support revocation, including for a purchase still awaiting an answer | run-level `_revoked_at` + sweep — `test_F1`, `test_F1b`, `test_F1c`, `attack_5` | **proven** |
| Merchant text cannot redefine policy | text yields only three narrowing derived facts — `test_I7_*` (6 payloads), `attack_2` | **proven** |
| A confirmed mandate cannot be widened | frozen rules, append-only, strictest governs — `test_I9_*`, `attack_8` | **proven** |
| Uncertainty never silently becomes approval | `fail > unknown > pass` — `test_I11_*` | **proven** |
| A restart does not resurrect a revoked or consumed authority | the lifecycle rides on the decision record — `attack_6`, `test_execution_durability` | **proven for the decision path** |
| A misstated FX conversion cannot understate CHF | recomputed against the published table — `test_I10_*` | **proven** |
| An external failure never becomes an approval | everything normalises to one catchable error; no approve-on-failure path exists — `test_failure_modes` (26) | **proven** |
| The audit trail cannot drift from the ledger | it is a pure projection — `test_the_audit_timeline_is_recomputed_not_stored` | **proven** |
| A one-shot job is performed once | derived from the ledger — `test_fulfilment_observer` (32) | **partially — within one run, and not in the decision path** |
| **The account monthly limit is protected** | — | **NO.** *Account-level monthly limit exists in the official data but is not enforced by this wallet.* It is displayed marked "not enforced". |
| **Exactly-once payment** | — | **NO.** At-most-once, per process. |
| **Total spending is capped** | — | **NO, and impossible** in the official rule format. |

See also `WHAT_WE_REFUSE_TO_CLAIM.md`.
