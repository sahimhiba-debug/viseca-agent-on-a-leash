# Verified baseline

Only facts re-verified by running the thing, on this commit. Where old documentation
disagreed with the code, the code won and the document was corrected.

| | |
| --- | --- |
| branch | `rnd/productization` |
| HEAD at baseline | `4fec029` |
| `main` | `1aa3bac` — **untouched**, 71 commits behind, never written to |
| working tree | clean |

## Suites, all re-run

| suite | command | result |
| --- | --- | --- |
| tests | `python3 -m pytest -q` | **862 pass, 5 reported skips** (867 collected) |
| official replay | `python3 scripts/run_replay.py` | **45 events — 19 allow / 2 review / 24 block** |
| adversarial corpus | `python3 scripts/run_red_team_corpus.py` | **133/133** across 10 categories |
| attack matrix | `python3 scripts/run_red_team.py` | **17/17** |
| mutation probe | `python3 scripts/run_mutation_probe.py` | **26 applied, 26 killed, 0 survived** |

`/api/health` reports `matches_regression_boundary: true`.

## Runtime dependency graph (derived by AST, not by reading imports by eye)

12 modules in `src/wallet_control/` import something internal; 19 modules total.

```
api ──────────────► attack_demo, audit, csv_data, decision_engine, mandate, …
live_worker ──────► decision_engine, mandate, state, viseca_client, viseca_mapping
offline_replay ───► csv_data, decision_engine, mandate, policy_compiler, state
decision_engine ──► drift, facts, intervention, mandate, money, rules, state
rules ────────────► facts, mandate
payment ──────────► state
```

Most depended on: **`mandate` (8)** and **`state` (8)**, then `decision_engine` (4).
There are exactly three entry points — `api`, `live_worker`, `offline_replay` — and
nothing imports them. That shape matches the claimed architecture: one policy object,
one security object, one engine, three drivers.

## Product surface

16 routes. The UI is a single 31 KB file with a viewport meta and three safe-area
insets. No framework, no build step.

## What this baseline does NOT establish

* That the suites are *sufficient* — only that they pass. The mutation probe is the
  evidence for sufficiency, and it is targeted rather than exhaustive.
* That the replay counts are *correct* — the official pack ships no expected
  decisions. 19/2/24 is a regression boundary.
* Anything about the hosted API. Every number here is offline.
