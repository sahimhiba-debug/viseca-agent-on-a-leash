# Research queue

Live priority list. Reprioritised whenever evidence changes.

---

## Done in this campaign

| # | hypothesis | status | evidence |
| --- | --- | --- | --- |
| R1 | the defects we keep finding are one defect | **CONFIRMED** | six instances, one pattern; `AUTHORSHIP.md` |
| R2 | that pattern can be checked statically | **CONFIRMED** | `run_authorship_audit.py`; all six replayed and caught |
| R3 | `LiveWorker` silently skips echo verification | **CONFIRMED, FIXED** | fails closed; CHF 9,000 exposure on record |
| R4 | the rule can be made interactive for a jury | **BUILT** | `POST /api/authorship/propose-field` |

## Open, ranked

| # | hypothesis | why it matters | next attack |
| --- | --- | --- | --- |
| **R5** | **L8 intent expressiveness is the largest unexplored surface** | a silently-weakened restriction is the worst possible failure: the customer believes they said something the wallet never enforces | build an INDEPENDENT corpus (not derived from the compiler's vocabulary), classify every phrase EXACT / PARTIAL-SAFE / UNSUPPORTED-SAFE / **SILENTLY-WEAKENED** / **INCORRECTLY-STRENGTHENED**, and metamorphic-test paraphrase equivalence |
| R6 | authorship applies to *facts in flight*, not only request fields | the static rule reasons about names; a fact can change author mid-flow | taint-style trace: follow `mandate`, `spend`, `confirmed_*` from entry to decision and assert the author never changes |
| R7 | the six-defect pattern predicts a seventh | the rule covers request models and defaults; other surfaces exist | audit checkpoint restore, the platform event payload, and `to_snapshot`/`from_snapshot` for author confusion |
| R8 | cross-feature attacks find what single-feature ones cannot | every campaign so far tested one axis | randomised traces combining tightening × pending step-up × restart × concurrency |
| R9 | the agent can maximise exposure without violating any single rule | "policy-permitted but customer-surprising" is the real economic risk | adversarial planner that optimises total moved under honest per-transaction compliance |
| R10 | a real model changes the benchmark | unknown, and cheap to answer if a key appears | `ANTHROPIC_API_KEY=... python3 research/architecture_comparison.py` |

## Killed

| hypothesis | why |
| --- | --- |
| aggregate spend across runs via a shared ledger | prototype lost writes under concurrency; a missing file is indistinguishable from a mandate that never spent |
| re-order the objective when the allowance binds | bought one CHF 30 line where two lines for CHF 62 also fit; the candidate filter already handles fitting |
| split the demo into wallet/agent/PSP containers | implies a process boundary that does not exist; the agent is a browser client |
| classify all eight adversarial attacks as "blocked" | three are not; `neutralised` and `paced` are the honest categories |
