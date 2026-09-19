# Invariant register

Every security invariant this wallet enforces, with the test that fails if it is
removed. Mutation-verified where noted: reverting the mechanism makes the named test
fail.

## Authorization scope

| # | invariant | enforced in | test |
| --- | --- | --- | --- |
| I1 | The decision ledger is write-once per `authorization_id` | `state.record_decision` | `test_final_arbitration` |
| I2 | A re-delivery whose facts changed is a conflict, not a replay | `state.check_repeat_fingerprint` | `test_final_arbitration` (4) |
| I3 | An identical re-delivery is an idempotent replay and is counted once | same | `test_an_identical_redelivery_is_still_a_harmless_replay` |
| I4 | `billing_amount_chf` is recomputed from `amount × fx_rates[currency]`, never trusted | `decision_engine` always-on check | `test_I10_*` |
| I5 | `items_subtotal + delivery_fee` must equal `amount` | same | `test_I13_*` |
| I6 | The integrity tolerance is exactly 0.02 and pinned | same | `test_the_amount_integrity_tolerance_*` |

## Decision semantics

| # | invariant | enforced in | test |
| --- | --- | --- | --- |
| I7 | `fail > unknown > pass`; uncertainty never silently becomes approval | `_decide` | `test_I11_*` |
| I8 | A missing fact is reported unknown, never invented | `facts.py` | `test_I12_*` |
| I9 | Merchant text can only narrow; it can never widen policy | `facts.py` extractors | `test_I7_*` (6 payloads) |
| I10 | An **inapplicable** requirement escalates rather than passing | `rules.py` return-window | `test_return_window_not_applicable_escalates_*` |
| I11 | **Basket monotonicity** — adding a line never makes a decision more permissive | `rules.py` size; property | `test_basket_monotonicity_*` (fuzzed) |
| I12 | Negative evidence is decisive before silence | `rules.py` size ordering | `test_stating_nothing_is_never_better_*` |
| I13 | A period rule with no window length escalates | `rules.py` | `test_a_period_rule_with_no_period_length_*` |
| I14 | An unrecognised rule field escalates, never passes | `rules.py` | mutation-killed |

## Temporal scope

| # | invariant | enforced in | test |
| --- | --- | --- | --- |
| **I15** | **∀t : Σ{amount(p) : p approved, t−N < time(p) ≤ t} ≤ C** — every window *containing* a purchase, not the one ending at it | `state.peak_window_spend_chf` | `test_window_containment` (14) |
| I16 | A step-up resolved late cannot breach the window | `_period_rules_breached_now` | `test_a_step_up_resolved_late_*` |
| I17 | No randomized lifecycle trace breaches the window | both | `test_no_randomized_lifecycle_trace_*` |

## Mandate scope

| # | invariant | enforced in | test |
| --- | --- | --- | --- |
| I18 | A confirmed mandate can only be tightened | `mandate.py`, frozen rules | `test_I9_*` |
| I19 | A run keeps its original snapshot for RULES | `live_worker` | `test_mandate_lifecycle` |
| I20 | The platform's reported `mandate.status` is read **live** and may only narrow | `_run_binding_failures` | `test_a_mid_run_mandate_revocation_*` |
| I21 | An event must belong to this run (`card_id`, `mandate_id`) | same | `test_run_binding` |
| I37 | **A period-qualified amount compiles to a period rule, never a per-order ceiling** — "CHF 250 per week" is a budget, not an order limit | `policy_compiler._AMOUNT_THEN_PERIOD_RE` | `test_a_period_qualified_amount_is_a_budget_not_an_order_ceiling` |
| I38 | **Restrictive language that produced no rule is named back to the customer** — the compiler never treats an unrecognised restriction as silent permission | `policy_compiler._coverage_questions` | `test_a_quantity_the_vocabulary_cannot_express_is_named_back_to_the_customer` |
| I36 | **Every rule field the engine recognises has a DECLARED meaning for absence of its subject**, and `pass` is never it — the field list is discovered from `rules.py` by AST, so a new field with no decision fails the suite | `rules.py` (checked, not enforced) | `test_every_recognised_rule_field_has_a_declared_absence_case` |
| I35 | **An event's claim about itself is cross-checked wherever we hold an independent source** — velocity joins amount, parts and identity; `max`, so it can only raise risk | `state.observed_attempts_within` + `decision_engine` | `test_under_reporting_recent_attempts_no_longer_suppresses_session_risk` |
| I34 | **A rule evaluated over an empty collection is UNCHECKABLE, never satisfied** — emptying the basket must not buy a better answer than filling it | `decision_engine` basket check + `rules.py` item guard | `test_emptying_the_basket_is_never_more_permissive_than_filling_it` |
| I33 | **Deleting a required field never buys a more permissive decision than its strictest legal value** — a check must not be switchable off by omitting what it guards | `_reported_mandate_status`, `_platform_status_evaluations` | `test_omission_is_no_weaker_than_the_strictest_legal_value` |

## Execution scope

| # | invariant | enforced in | test |
| --- | --- | --- | --- |
| I22 | The execution lifecycle is monotonic: `issued → consumed \| revoked`, both terminal, both persisted | `state` | `test_authority_lifecycle` |
| I23 | Execution validates against the ledger at one point under an atomic compare-and-set | `payment.charge` | `test_execution_atomicity` |
| I24 | An approval cannot be redirected to another merchant or amount | same | `test_I2_I3_*` |
| I25 | Restart does not resurrect a consumed or revoked authorization | checkpoint | `test_execution_durability` |
| I26 | No derived state gates an external side effect | architecture | `test_runtime_boundary` |

## Human-in-the-loop

| # | invariant | enforced in | test |
| --- | --- | --- | --- |
| I27 | A human answer is final; a conflicting second answer is refused | `record_resolution` | `test_I8_*` |
| I28 | An identical re-submission is idempotent and does not double-count | same | `test_an_idempotent_re_resolution_*` |
| I29 | Concurrent answers cannot both be accepted | run lock | `test_F3_concurrent_*` |
| I30 | Revocation reaches a purchase still awaiting an answer | `_revoked_at` | `test_F1*` (3) |
| I31 | The customer's answer binds to the purchase they were shown | repeat fingerprint + stored decision | `test_the_answer_binds_to_the_purchase_the_customer_was_shown` |

## Concurrency

| # | invariant | enforced in | test |
| --- | --- | --- | --- |
| I32 | The decision path is atomic within one process | re-entrant run lock | `test_concurrent_proposals_*` (20 ms widened window) |

## Explicitly NOT invariants

- **Order independence of the approved set.** Retracted; greedy FCFS admission. `test_the_approved_set_is_NOT_order_invariant_*`.
- **Fairness.** No allocation policy is enforced, deliberately.
- **Exactly-once execution.** At-most-once, per process. `test_single_use_is_per_process_not_global`.
- **Cross-run period enforcement.** Per run by protocol definition. `test_the_rolling_cap_is_enforced_PER_RUN_*`.
