# External audit package

**Written to help you attack this, not to make it look good.** If you are auditing
this repository, start here.

| | |
| --- | --- |
| commit | see `git log -1` on `main` |
| branch | all work is on `main`. Earlier revisions of this page said `main` was untouched at `1aa3bac` and that the work lived on `rnd/productization`; that branch is gone and the statement was false by the time you read it |
| tests | 1840 collected, 5 reported skips (6 in a fresh clone — one needs the organisers' example fixture, which is in their repo, not ours) |
| official replay | **45 events — 17 allow / 4 review / 24 block**. THIS PAGE SAID 19/2/24 FOR TWO BOUNDARY MOVES: see "The number on this page was wrong" below |
| runtime | 5,112 code lines across 27 modules — 9,986 with the comments, which carry most of the reasoning · research apparatus separated into `research/` |
| dependencies | 4 runtime (fastapi, uvicorn, httpx, pydantic), 3 dev |

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"
python3 -m pytest -q                      # 1840 collected
python3 scripts/run_replay.py             # 45 / 17 / 4 / 24
python3 scripts/run_red_team_corpus.py    # 133/133
python3 scripts/run_red_team.py           # 17/17
python3 scripts/run_mutation_probe.py     # 41 mutants, 41 killed — breaks the core on purpose
uvicorn wallet_control.api:app --port 8420
```

## The number on this page was wrong

The replay split is the headline result of this project, and until this commit the
table above stated **19 allow / 2 review / 24 block** while the engine produced
**17 allow / 4 review / 24 block**. Two defects were fixed, each moved one event from
`allow` to `review`, and this page was not updated. An auditor who ran the command in
the box would have got a different answer from the table three lines above it.

<!-- superseded -->
There was a test against exactly this. `test_no_current_document_states_a_stale_replay_split`
names this file, runs the replay, and fails any "current" document that states a
different split. It passed throughout, because it searched for the spelling `19/2/24`
and this page writes the same fact as `19 allow / 2 review / 24 block`. **The guard
was blind to the spelling the drifting document actually used, and a search that
matched nothing was indistinguishable from a search that found everything correct.**

That is the same defect the repository names elsewhere as *a check that cannot fail is
not a check* (`docs/A_CHECK_THAT_CANNOT_FAIL.md`), found for the eighth time, in the
instrument built to prevent this precise drift. The guard now reads both spellings and
asserts how many statements it found, so going blind fails instead of passing.

Two things follow that are worth more than the corrected number:

* **Do not trust a figure in `docs/` because a test exists for it.** Ask what the test
  matched. Every headline number in this package can be re-derived with one command
  from the box above; prefer that to any table, including this one.
* **`docs/` is 133 files and most of them are historical.** Documents that record what
  was true at an earlier commit now say so in a banner at the top. The ones that claim
  to describe the present are `README.md`, `docs/BASELINE_CURRENT.md`, `docs/THE_THESIS.md`
  and this page, and only those four are covered by the guard.

## Where to attack first

Ranked by where I think you are most likely to find something:

1. **Cross-run state.** The period cap is enforced **per run**. One mandate across ten
   runs authorizes CHF 2,000 against a CHF 300/7-day cap. I argue this is the official
   period semantics and that the agent does not control run boundaries — *attack that
   argument.* `test_the_rolling_cap_is_enforced_PER_RUN_not_per_mandate`.
2. **Multi-process execution.** Two workers restoring one checkpoint each charge the
   same authorization. Reproduced, accepted, pinned.
   `test_single_use_is_per_process_not_global`.
3. **Merchant-claimed facts.** `order.return_window_days` and `item.size` have **no
   input other than merchant free text.** A plausible saturation claim ("returns
   accepted within 90 days") beats every realistic customer threshold with zero policy
   knowledge. Not fixable inside the official rule vocabulary.
4. **The peak-window computation.** `state.peak_window_spend_chf` is the newest
   security-critical code. Multiple overlapping period rules of different lengths are
   now exercised: a 3,000-run campaign with three nested caps (CHF 200/1d, 300/7d, 1000/30d), randomized amounts and timestamps over 35 days and ~45% of purchases forced into step-ups resolved in random order found **0 breaches**, with the windows filling to 199.99 / 299.95 / 956.28 -- tight, not over-conservative.
5. **Fields you can DELETE rather than forge.** Nothing here validates an incoming
   event against `authorization_event.schema.json`, and the engine reads it field by
   field. A check written `if value is not None and value != expected` is switched off
   by removing the field it guards. That was live: deleting `mandate.status`, or the
   whole `mandate` block, made a **revoked** mandate ALLOW, mint an authority and
   charge. Fixed, and the property is now asserted over the schema's own enums rather
   than for the one field that broke -- *find a required field I have not covered.*
   `test_omission_is_no_weaker_than_the_strictest_legal_value`.
6. **The step-up channel.** No authentication, no `resolved_by`. Anyone who can reach
   the demo port can answer a customer's question.
7. **The policy compiler, but only where it can reach.** `policy_compiler.py` is
   phrase patterns. It is **not in the live decision path** -- `from_event_mandate`
   takes `hard_rules` from the platform verbatim -- so it cannot mis-decide a live
   purchase. It does decide (a) what a customer is shown before they confirm a
   mandate, and (b) the rules used by the offline replay, which means **the whole
   replay split is conditional on our own reading of five English sentences.** Attack the parse:
   find an instruction whose compiled rules a reasonable customer would reject.
8. **Evidence semantics.** I audited 13 absent/inapplicable/conflicting cases and fixed
   two. A rule field added later would default to the wrong side; only the monotonicity
   fuzz would catch it.

## Claims, and how to falsify each

| claim | falsify by |
| --- | --- |
| No legal sequence breaches a stated window | find a transition sequence the lifecycle fuzz does not generate |
| Basket monotonicity | find a basket where adding a line relaxes the decision |
| Merchant text can only narrow | find text that widens a rule or raises a ceiling |
| Revocation reaches a pending step-up | find a path that mints authority after `_revoked_at` |
| The decision path is atomic in one process | widen a different race window than the one I widened |
| The test suite is not theatre | `python3 scripts/run_mutation_probe.py` breaks 39 security mechanisms one at a time and every one is caught. It is a targeted probe, not exhaustive — **find a mechanism I did not think to mutate.** It found one real gap on its first run (the rolling window's start boundary was unpinned) |
| Deleting a required field never helps an attacker | find a required field whose omission is more permissive than its strictest legal value |
| Every invariant in `FINAL_INVARIANTS.md` cites a real test | `test_every_test_the_register_cites_exists` — the register is machine-checked, so attack the MAPPING instead: find an invariant whose cited test does not actually exercise it |
| The 8s deadline is never at risk | measured, not assumed: EXACTLY quadratic in a run's approved purchases — ms/n² is flat at ~63e-6 once you remove window saturation — crossing 8,000 ms at **n ≈ 11,200 worst case**, against an official max of 12. This number took three passes and two of them were wrong (`tests/test_scale_limits.py` documents both). **Find a workload where n is large, or where the cost is worse than quadratic.** Find a workload where n is large or the cost is worse than quadratic (`tests/test_scale_limits.py`) |
| Official replay unchanged | `python3 scripts/run_replay.py` |

## Protocol assumptions I depend on

Each is a place where, if I am wrong about the protocol, a control is wrong:

1. **`authority_status`, `card_status_at_attempt`, `mandate.status`, `card_id` and
   `timestamp` are platform-supplied and not agent-forgeable.** If the agent can set
   them, several hard checks become advisory.
2. **The period counter is run-scoped** — *"recomputed from the decisions actually taken
   in the run"*. This is the justification for #1 in "where to attack".
3. **A paused purchase is not approved** until resolved. This is what creates the
   deferred-insertion problem the peak-window check exists to solve.
4. **Spending windows use simulated purchase time; deadlines use the real clock.**
5. **The platform rejects revoked mandates before queueing.** I no longer rely on this —
   `mandate.status` is now read live — but it is why that path is hard to reach.
6. **Events are schema-valid.** `minItems: 1`, `quantity ≥ 1`, `unit_price > 0`. I do
   **not** re-validate these, which the senior review classified as avoiding defensive
   theatre. If the platform does not validate, several "unreachable" findings become
   reachable.
7. **The agent does not receive our explanations.** Measured, and the reason the
   counterfactual-disclosure mechanism was rejected.

## Known vulnerabilities that REMAIN

Not softened:

1. Cross-run mandate reuse multiplies the period cap linearly.
2. Single-use is per process; two workers double-charge.
3. Two rule fields rest entirely on unverifiable merchant text, and saturation beats them.
4. The step-up channel is unauthenticated and records no identity.
5. A cancelled or revoked purchase still consumes window budget.
6. The approved **set** depends on arrival order (greedy FCFS). Safety is unaffected.
7. No mandate in the official rule format can bound **total** spending — `scope` is
   `purchase` or `period` and the spec closes the set.
8. The account's `monthly_limit_chf` is real data this wallet does **not** enforce.

## Design decisions and rejected alternatives

| decision | rejected alternative | why |
| --- | --- | --- |
| Two authoritative objects (mandate snapshot, decision ledger) | a separate payment-authority store | it caused four vulnerabilities; deleted |
| Job counting derived, **not** in the decision path | enforcing it | mandate-scoped bound, run-scoped ledger |
| No account-scope enforcement | implementing `monthly_limit_chf` | no account-scoped counter in the API; the naive version was defeated three ways |
| No counterfactual disclosure | authority-gated counterfactuals | the channel does not exist and saturation dominates inference |
| No fairness policy | max-min / reservation | the customer stated a bound, not an allocation policy |
| Deterministic compiler, no model at runtime | LLM intent extraction | determinism, and no failure mode on stage |

## Document map

`FINAL_INVARIANTS.md` (32 invariants + 4 explicit non-invariants) ·
`RESEARCH_LOG.md` (16 experiments, reproducible) ·
`SAFETY_FAIRNESS_LIVENESS.md` · `THREAT_SPACE_FINAL.md` ·
`FINAL_SECURITY_SCOPE_MODEL.md` · `SENIOR_SECURITY_CLAIMS_AUDIT.md` ·
`WHAT_WE_REFUSE_TO_CLAIM.md` · `RED_TEAM_FINAL_REPORT.md` ·
`C1_SECOND_ORDER_SECURITY_AUDIT.md` (a rejected mechanism, with the measurements) ·
`PRODUCT_ARCHITECTURE.md` · `CODEBASE_GUIDE.md` · `RUNBOOK.md`

## What I would tell you if we were in the room

The strongest result is **R2 in the research log**: following two requirements the
specification states plainly — a paused purchase is not approved, and windows use
simulated purchase time — produces a CHF 480 spend against a CHF 300 cap with every
individual decision correct. The natural implementation is wrong, and it passes every
ordinary test.

The weakest part is everything that depends on merchant free text. I can restate it
honestly, and I cannot fix it inside the official vocabulary.

The thing most likely to embarrass me is a cross-run or multi-process attack, because
both are documented rather than defended.
