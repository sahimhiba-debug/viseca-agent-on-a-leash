# Simplification log

Every deletion and move made during the senior review, with the evidence that it was
safe. After each one: full suite, official replay, corpus, matrix.

## The large move: runtime vs research

| | before | after |
| --- | ---: | ---: |
| `src/wallet_control` | 6,693 lines / 23 modules | **4,806 / 19** |
| `research/` (new) | — | 1,837 / 6 |

**Evidence it was safe:** an import-closure walk from the only two entry points
(`api`, `live_worker`) showed five modules were unreachable from either. They were not
"loosely coupled"; they were *not connected at all*.

| moved to `research/` | lines | why it is not runtime |
| --- | ---: | --- |
| `red_team_corpus.py` | 664 | 133 generated adversarial cases; a test harness |
| `attack matrix (red_team.py)` | 293 | 17 hand-written attacks; a test harness |
| `security_object.py` | 314 | eight competing models built to falsify each other |
| `fulfillment.py` | 291 | the job-capability derivation — *deliberately* not in the decision path |
| `demo_scenario.py` | 256 | an R&D walkthrough the product no longer calls |

Nothing was deleted: the results are cited throughout `docs/`, and a claim whose
experiment has been deleted is just an assertion. What changed is that the shipped
package now contains only code that runs in production.

**Made structural, not conventional** — `tests/test_runtime_boundary.py`:
1. every module in `src/wallet_control` must be reachable from an entry point;
2. no runtime module may import `research`.

The second matters most: without it, an experiment is one import away from changing a
customer's decision.

## Deletions

| removed | lines | evidence |
| --- | ---: | --- |
| `GET /api/rnd-demo` | ~35 | superseded by the Attacks tab, which demonstrates the same properties against the real engine rather than a pre-narrated walkthrough. Zero UI references. |
| `Mandate.replace_guidance()` | 8 | zero references in src, tests, scripts, research or UI |
| `VisecaClient.reference_data / authorization_history_csv / get_mandate / patch_mandate / events / team_reset` | ~24 | six HTTP wrappers for endpoints we never call, with no test. We read history from the vendored pack and never patch a mandate at runtime. An untested wrapper is a liability, not coverage. |

## Considered and deliberately kept

| candidate | why it stays |
| --- | --- |
| `intervention.py` (43), `viseca_mapping.py` (28), `money.py` (57) | each is one concept with one job: our decision vocabulary → the official wire value, and `Decimal`/FX handling. Folding them into callers would spread the official mapping across three files. |
| `drift.py` (94) | explanatory only and cannot gate a decision — but it is what the UI uses to show *how* a re-delivered authorization differs. Removing it would remove an explanation, not a check. |
| `LiveWorker.stop()` | flagged as unreferenced; it sets the `threading.Event` that ends the long-poll loop. A worker you cannot stop is worse than an unused method. |
| `PurchaseFacts` fields the rules never read | the record is the *canonical normalisation of the official event*. Trimming it to today's rules would make the next rule a schema change. |
| `attack_demo.py` (403) in the runtime | it is a product feature — the Attacks tab — not research. It must run against the real engine, and a test asserts it does. |

## False positives caught during the audit

An attribute-style scan for unused names flagged twelve `PurchaseFacts` fields,
`ChargeRecord.executed_at` and `duplicate_of` / `duplicate_reason`. All are used —
passed positionally or bound to locals. **Every candidate was checked by reading the
code before deletion; none of these was removed.** A deletion pass driven by grep alone
would have broken the engine.

## What was NOT simplified, and why

The two largest runtime modules are `state.py` (749) and `decision_engine.py` (672).
Both were deliberately left large:

- `state.py` is large *because* an earlier pass collapsed two records into one. Six
  vulnerabilities in this project came from a second record describing the same
  authorization. Splitting it again to reduce a line count would reintroduce the exact
  shape that caused them.
- `decision_engine.py` is one readable top-to-bottom path: run binding → platform status
  → replay → facts → rules → always-on safety → `_decide()`. Splitting it across files
  would make the decision path harder to trace, which is the opposite of the goal.

Neither is complex; both are long. That is the right trade here.

## Verification after every step

| | |
| --- | --- |
| tests | 622 passed |
| official replay | 45 / 19 allow / 2 review / 24 block — unchanged throughout |
| red-team corpus | 133 / 133 |
| adversarial matrix | 17 / 17 |
| fulfilment differential | 6 / CHF 1,787.40 |
| all 8 scripts | run clean |
