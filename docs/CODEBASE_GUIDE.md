# Codebase guide — the ten files that matter

A senior engineer should be able to understand this product by reading these ten
files in this order. Everything else is either research apparatus (`research/`),
fixtures, or a script.

## The decision path, in order

| # | file | purpose | authoritative? |
| --- | --- | --- | --- |
| 1 | `src/wallet_control/mandate.py` | The customer's policy: `Mandate`, `HardRule`, the lifecycle (draft → confirm → tighten-only → revoke). `HardRule` is frozen and `tighten_hard_rules` only appends, so a confirmed mandate cannot be widened by anyone. | **authoritative** |
| 2 | `src/wallet_control/policy_compiler.py` | Natural language → executable `hard_rules`, deterministically, with no model. Anything it cannot map becomes a visible `open_question`, never a guessed rule. | derives the mandate |
| 3 | `src/wallet_control/facts.py` | The official event → one canonical `PurchaseFacts` record. The only place merchant text is turned into narrow derived facts (size, return window, final sale). | derived, immutable |
| 4 | `src/wallet_control/rules.py` | Evaluates one `HardRule` against `PurchaseFacts` → `pass` / `fail` / `unknown`. Pure. | pure function |
| 5 | **`src/wallet_control/decision_engine.py`** | **The core.** Run binding, platform status, idempotent replay, always-on safety checks (amount integrity, positive amount), rule evaluation, and `_decide()`: `fail > unknown > pass`. Also `resolve_authorization`, the human path. | orchestrates |
| 6 | **`src/wallet_control/state.py`** | **The security object.** `RunState._decisions` — write-once per `authorization_id`, carrying the money, merchant, basket fingerprint *and* the execution lifecycle. Plus rolling spend, duplicate detection, run-level revocation, and the JSON checkpoint. | **authoritative** |
| 7 | `src/wallet_control/payment.py` | The execution boundary. `MockPSP.charge()` is the single enforcement point: merchant binding, amount ceiling, authority must exist, then an atomic compare-and-set consume. | enforces against #6 |

## The surfaces

| # | file | purpose |
| --- | --- | --- |
| 8 | `src/wallet_control/api.py` | The demo backend. Compile, run a scenario, resolve a step-up, revoke, health, attacks, audit. Reuses the exact engine — there is no demo-only decision path. |
| 9 | `src/wallet_control/live_worker.py` | The real Viseca integration: one `RunState` per `run_id`, checkpointed after every decision, reconciliation on restart. |
| 10 | `ui/index.html` | The whole customer experience, mobile-first, no build step and no dependencies. It renders decisions; it never computes them. |

## Reading order for a specific question

| question | file |
| --- | --- |
| What is authoritative? | `state.py` — `StoredDecision` and `RunState._decisions` |
| Where is the decision made? | `decision_engine.py::evaluate_authorization`, ending at `_decide()` |
| Where is money validated? | `payment.py::MockPSP.charge` — one function, one enforcement point |
| Where is revocation enforced? | `state.py::revoke_outstanding_authorities` + `_revoked_at`, `decision_engine::_run_binding_failures` |
| Where is step-up handled? | `decision_engine.py::resolve_authorization` |
| What happens if the agent lies? | `decision_engine` idempotency + `state.check_repeat_fingerprint` (basket fingerprint) |
| What if merchant text is an injection? | `facts.py` — text produces only a few narrow derived facts and is never obeyed; a claimed return window is still believed (known vulnerability 3) |
| What is NOT guaranteed? | `docs/WHAT_WE_REFUSE_TO_CLAIM.md` |

## Everything else

- `money.py` (57) — `Decimal` handling and the fixed FX table.
- `intervention.py` (43) — maps a decision to the official `approve`/`decline`/`step_up` wire value.
- `viseca_mapping.py` (28) — our decision vocabulary → the official one.
- `csv_data.py` (88) — read-only loaders for the vendored data pack.
- `offline_replay.py` (212) — builds schema-valid events from the CSV fixtures. The regression boundary.
- `drift.py` (94) — explanatory only: describes how a re-delivered authorization differs. Cannot gate a decision.
- `audit.py` (192) — the audit timeline and delegation summary, both pure projections.
- `attack_demo.py` (403) — the eight judge-facing attacks, run against the real engine.
- `viseca_client.py` (214) — the HTTP client, covering exactly the endpoints we call.

`research/` (1,837 lines) is apparatus: the fulfilment derivation, the 17-attack
matrix, the 133-case corpus, eight competing security-object models, and the R&D
walkthrough. A test asserts the runtime never imports it.
