# Submission baseline

This file is the single human-readable baseline for the submission. It describes the final delivery on **24 September 2026** and deliberately separates reproduced facts from claims about correctness.

| | |
| --- | --- |
| submission commit | `3bb934acafa82755ad43c2df3d13bd6e5dd9d8cb` |
| freeze commit | `7b164df50412b50b39cdee966ce748e49f85c751` |
| freeze date | 24 September 2026 |
| principle | a fresh run on the submitted commit overrides stale documentation |

## Reproduced at the freeze

| check | command | recorded result |
| --- | --- | --- |
| tests | `python3 -m pytest -q` | **2000 passed, 6 skipped, 2006 collected** |
| official replay | `python3 scripts/run_replay.py` | **45 events — 12 allow / 9 review / 24 block** |
| adversarial corpus | `python3 scripts/run_red_team_corpus.py` | **133/133 held** |
| attack matrix | `python3 scripts/run_red_team.py` | **17/17 defeated** |
| mutation probe | `python3 scripts/run_mutation_probe.py` | **45 applied, 45 killed, 0 survived** |

The final delivery commit immediately follows the freeze and packages the jury-facing delivery. Before presenting, rerun the gate in [RUNBOOK.md](../RUNBOOK.md). If any result differs, investigate the difference instead of repeating the number in this file.

## Official replay by scenario

| scenario | events | allow | review | block |
| --- | ---: | ---: | ---: | ---: |
| SCEN0000 | 1 | 1 | 0 | 0 |
| SCEN0001 | 10 | 5 | 0 | 5 |
| SCEN0002 | 12 | 1 | 3 | 8 |
| SCEN0003 | 11 | 4 | 1 | 6 |
| SCEN0004 | 11 | 1 | 5 | 5 |
| **Total** | **45** | **12** | **9** | **24** |

These totals are a **regression boundary, not a correctness score**. The official synthetic pack contains no expected decision labels.

## What the baseline establishes

It establishes that, at the recorded freeze, the shipped test suite passed, the replay was stable at the documented boundary, the two adversarial suites produced their recorded outcomes, and every targeted mutation in the probe was detected.

It does **not** establish that the suite is exhaustive, that every replay decision is objectively correct, that the system is production-ready, or that the documented limitations have disappeared. Those boundaries are explicit in [LIMITATIONS.md](LIMITATIONS.md) and [FINAL_CLAIMS_REGISTER.md](FINAL_CLAIMS_REGISTER.md).

## Runtime shape

The judged architecture has one decision engine shared by three drivers:

```
offline replay ─┐
demo API/UI ─────┼──► decision engine ──► allow / review / block
live worker ─────┘
```

The planner proposes; it does not own the authorization path. Research code is evidence around that boundary, not an alternate wallet implementation.

## Fresh-check rule

For a release or demo machine, do not infer health from this document. Run:

```bash
python3 -m pytest -q
python3 scripts/run_replay.py
python3 scripts/run_mutation_probe.py
python3 scripts/run_red_team_corpus.py
python3 scripts/run_red_team.py
```

Then verify `/api/health` reports `matches_regression_boundary: true`. The output of those commands is the current truth.
