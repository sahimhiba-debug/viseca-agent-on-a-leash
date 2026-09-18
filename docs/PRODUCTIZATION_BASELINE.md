# Productization baseline — observed, not reported

Everything below was re-run against the repository. Where the R&D report and the
repository disagreed, the repository wins. **They did not disagree.**

## Environment

| | |
| --- | --- |
| commit at baseline | `44b51e90b73e89bab4307f73ac76fadc139d34c4` (`44b51e9`) |
| branch | `rnd/productization`, cut from `rnd/verifiable-agentic-wallet` |
| `main` | `1aa3bac` — untouched |
| working tree | clean |
| Python | 3.13.9 (venv), macOS arm64 |
| Node | v26.4.0 — **not used**; the UI is a single static HTML file |
| server | `uvicorn wallet_control.api:app --port 8420` via `.claude/launch.json` |

## Verified results

| check | reported by R&D | **observed** | match |
| --- | --- | --- | --- |
| test suite | 556 | **556 passed** | ✅ |
| official replay | 45 / 19 / 2 / 24 | **45 events — 19 allow, 2 review, 24 block** | ✅ |
| red-team corpus | 133/133 | **133/133 held** | ✅ |
| adversarial matrix | 17/17 | **17/17 defeated** | ✅ |
| fulfilment differential | 6 / CHF 1,787.40 | **6 disagreements / CHF 1,787.40** | ✅ |

Per-scenario replay (the regression boundary, not a score):

| scenario | allow | review | block |
| --- | ---: | ---: | ---: |
| SCEN0000 | 1 | 0 | 0 |
| SCEN0001 | 5 | 0 | 5 |
| SCEN0002 | 3 | 1 | 8 |
| SCEN0003 | 5 | 0 | 6 |
| SCEN0004 | 5 | 1 | 5 |

All research scripts run clean: `run_offline_replay`, `run_red_team`,
`run_red_team_corpus`, `run_fulfilment_differential`, `run_demo_scenario`,
`run_economic_envelope`, `run_security_object_falsification`, `run_scope_falsification`.

## Existing API surface (8 routes)

`GET /api/scenarios` · `POST /api/mandates/compile` · `POST /api/scenarios/{id}/run` ·
`GET /api/rnd-demo` · `GET /api/runs/{run_id}` ·
`POST /api/runs/{run_id}/authorizations/{authorization_id}/resolve` ·
`POST /api/runs/{run_id}/revoke` · `POST /api/runs/{run_id}/rerun-check`

## Known gaps at baseline

These are the productization targets, not defects:

1. **The UI is a research prototype** — 261 lines, one page, three stacked panels. It
   exposes rule syntax rather than customer language, has no audit timeline, no
   attack demonstration, no judge-facing explanation, and no economic disclosure view.
2. **No health or reset endpoint** — nothing to check liveness or clear demo state.
3. **No deterministic attack demo** — the attacks live in scripts and tests, not in
   anything a judge can watch.
4. **No audit trail projection** — the decision ledger holds the facts; nothing renders
   them as a timeline.
5. **No runbook** — startup is tribal knowledge.
6. **External-failure behaviour is untested** — no coverage for timeouts, 401/403,
   malformed responses or corrupted checkpoints.

## Carried-forward architectural limitations (frozen, not to be "fixed" here)

1. The job capability is mandate-scoped; the ledger is run-scoped. The same mandate
   reused in a later run does not see the earlier run's fulfilment.
2. Account-scope (`monthly_limit_chf`) is real but unenforceable with the official API.
3. Single-use is per process.
4. A cancelled first purchase makes a legitimate retry look like a repeat.
