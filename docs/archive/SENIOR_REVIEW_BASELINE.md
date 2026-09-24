# Senior review baseline

<!-- snapshot -->
> **SNAPSHOT — written 18 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Recorded before the review's simplification pass. Every figure re-run, not quoted.

| | |
| --- | --- |
| commit at baseline | `e6a955d` |
| `main` | `1aa3bac` — untouched throughout |
| Python | 3.13.9 (venv), macOS arm64 |
| Node | not used — the UI is one static HTML file |
| tests | **621 passed**, 0 failed |
| official replay | **45 events — 19 allow / 2 review / 24 block** |
| red-team corpus | **133 / 133 held** |
| adversarial matrix | **17 / 17 defeated** |
| fulfilment differential | **6 disagreements / CHF 1,787.40** |
| attack demonstrations | **8 / 8 held** |
| mobile | 0 px horizontal overflow, 0 clipped elements, 0 touch targets < 44 px at 375×812, 390×844, 412×915 |

## Code size at baseline

| | lines | modules |
| --- | ---: | ---: |
| `src/wallet_control` | 6,693 | 23 |
| tests | 6,425 | — |
| `ui/index.html` | 543 | 1 |

## Entry points

1. `uvicorn wallet_control.api:app` — the demo backend + static UI (what the demo runs).
2. `scripts/run_live_worker.py` → `live_worker.LiveWorker` — the real Viseca integration.
3. `scripts/run_replay.py` — the offline regression boundary.

Both (1) and (2) call the *same* `decision_engine`. There is no demo-only decision path.

## Critical invariants at baseline

1. The decision ledger is write-once per `authorization_id`.
2. The execution lifecycle is monotonic: `issued → consumed | revoked`, both terminal, both persisted.
3. Execution validates against the ledger at exactly one point, under an atomic compare-and-set.
4. No derived state gates an external side effect.
5. A confirmed mandate can only be tightened.
6. `fail > unknown > pass`; `uncertainty_policy` governs unknowns only.
7. `billing_amount_chf` is recomputed from `amount × fx_rates[currency]`, never trusted.
8. A stepped-up authorization does not enter approved spend until resolved.
9. Revocation stops money that has not moved, including for a purchase still awaiting the customer.
10. Within one run, a one-shot job with an identifiable anchor is performed once *(research module, not in the decision path)*.

## Known limitations carried into the review

1. The job capability is mandate-scoped; the ledger is run-scoped. One mandate reused across runs does not see the earlier run's fulfilment.
2. Account scope (`monthly_limit_chf`) is real and **not enforceable** with the official API.
3. Single-use is **per process**. Two workers restoring one checkpoint can each consume once.
4. A cancelled first purchase makes a legitimate retry look like a repeat (0 instances in the corpus).
5. Merchant claims — size, return window, finality — are attacker-controlled text we cannot verify.
6. The demo API has no authentication and records no `resolved_by`.

## Intentional simplifications (not defects)

- **In-memory demo state.** `api.py` keeps runs in a dict. This is an event-day tool for one team, not a service.
- **No database.** The live worker checkpoints to one JSON file per `run_id`.
- **No model at runtime.** The policy compiler is a deterministic lexicon + regexes, so the customer sees identical rules on every retry and the demo cannot fail because an API is down.
- **Simulated payment boundary.** The official API has no payment step; `MockPSP` is ours and labelled as such.
- **One static HTML file.** No build step, no framework, no dependency to break on stage.
