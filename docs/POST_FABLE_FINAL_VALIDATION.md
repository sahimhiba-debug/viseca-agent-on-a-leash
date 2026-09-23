# Post-remediation final validation

<!-- snapshot -->
> **SNAPSHOT — written 20 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Focused verification that the four findings of `docs/FABLE_INDEPENDENT_AUDIT.md`,
remediated in `0e6e17e`, are actually closed. Invariants were re-derived from source
and then attacked; the remediation report was not taken as evidence.

---

## 1. Executive result

| finding | status |
| --- | --- |
| 1 — unsupported restrictive intent | **CLOSED** (one latent bypass found and fixed during this pass) |
| 2 — authorization identity / idempotency | **CLOSED**, with a protocol caveat recorded |
| 3 — echoed mandate trust | **CLOSED** |
| 4 — TTL coverage | **CLOSED** |

**One code change was made**, and only after the audit found a genuine bypass: a
compiling caller that did not carry `unsupported_restrictions` into
`Mandate.draft()`, so the confirmation gate could not fire for it.

## 2. Finding 1 — unsupported restrictive intent — **CLOSED**

**Invariant.** *Every unsupported restrictive intent must be explicitly acknowledged
before confirmation.*

### The three categories, verified independently

| category | probe | observed |
| --- | --- | --- |
| **supported** | 93 of the 103-phrase corpus | rule created, confirms normally |
| **unsupported** | `"Buy one grocery item, no more than CHF 20 in total, and stop after Friday."` → 4 detected | confirmation refused until each is named back |
| **harmless unknown** | three ordinary mandates incl. *"Thanks very much."* | 0 detected, confirms normally |

The third row is the one that would be easy to get wrong in the safe-looking
direction: a gate that fired on ordinary prose would make every mandate unconfirmable
and would be routed around.

### Attacks on the acknowledgement

| attack | expected | observed |
| --- | --- | --- |
| no acknowledgement | refuse | refused |
| empty list | refuse | refused |
| partial (first only / all but one) | refuse | refused |
| wrong content | refuse | refused |
| right count, wrong items | refuse | refused |
| `None` | refuse | refused (`TypeError`) |
| bare string instead of a list | refuse | refused |
| substring of a real item | refuse | refused |
| all items, duplicated | **accept** | accepted |
| all items | **accept** | accepted |

### Complete path audit — every drafter/confirmer in the repository

Enumerated by AST, not by reading.

| path | compiles? | carries the field? |
| --- | --- | --- |
| `offline_replay.compile_and_confirm_mandate_for_scenario` | yes | **yes**, acknowledged explicitly |
| `api` (`/api/scenarios/{id}/run`) | via the above | yes |
| `scripts/run_live_worker.py` | yes | **yes** — exits unless `--acknowledge-unsupported` |
| `research/demo_scenario.py` | yes | **NO — the bypass found in this pass** |
| `attack_demo.py`, `research/red_team*.py`, `tests/helpers.py` | no — raw `HardRule`s | n/a, no compiled policy exists |

`/api/mandates/compile` is preview-only; there is no API endpoint that confirms a
customer-authored mandate.

### The bypass, and the fix

`Mandate.draft()` defaults `unsupported_restrictions` to `None`, so a caller that
compiles an instruction and forgets to pass it gets an empty list and confirms
freely. No tampering — just an omission. `research/demo_scenario.py:100` drafted with
five positional arguments and did exactly that.

**Not exploitable as it stood**: its instruction carries zero unsupported
restrictions, and `research/` is never imported by the runtime (asserted by an
existing test). But a gate that depends on every caller remembering will eventually
be forgotten, and the invariant is stated without exception.

*Fix:* one call site plumbed and acknowledged explicitly, matching `offline_replay`.
*Regression test:* `test_every_compiling_drafter_plumbs_unsupported_restrictions`
re-enumerates by AST and fails on any omission.
*Demonstrated to kill the defect:* reverting the plumbing fails the test with
`['research/demo_scenario.py:100']`.

### Post-compilation tampering — informational, not a finding

Clearing `draft.unsupported_restrictions` or the `CompiledPolicy` in memory before
confirming does confirm. Both require Python-level access to our own objects inside
the process, which is not a boundary this gate can defend; an attacker there has
already won. Recorded, not fixed.

**Mutation evidence:** `unsupported restrictive intent no longer blocks confirmation`
→ killed by `test_unsupported_restrictive_intent_blocks_confirmation`; `a drafted
mandate silently drops the unsupported restrictions` → killed by the same test.

## 3. Finding 2 — authorization identity — **CLOSED**, with a caveat

**Is `authorization_id` structurally unique per purchase?** **Yes.** It is a resource
address — `POST /v1/authorizations/{authorization_id}/decision` and `/resolve` — so
two purchases sharing one would be mutually unaddressable. Schema: `minLength: 1`. The
worker outline treats it as *the* key. It "stays the same within a run but changes
between runs".

### The behaviour matrix

| variation | observed | spend |
| --- | --- | --- |
| A–E all identical | **retry (replay)**, allow | CHF 100, counted once |
| timestamp +1 day | conflict → block | CHF 100 |
| timestamp +1 second | conflict → block | CHF 100 |
| basket differs | conflict → block | CHF 100 |
| amount differs | conflict → block | CHF 100 |
| merchant differs | conflict → block | CHF 100 |
| id empty / blank / null / int / list | block | — |

### The caveat, stated because the brief asked me not to assume

`technical_details.md` says *"Recognize repeated delivery by its live purchase ID"*
and frames duplicates as a problem of *different* IDs. Read strictly, same ID = repeat
delivery, and the timestamp component of the fingerprint is a **divergence from the
letter of the protocol** in a case the protocol says cannot occur.

Two things make it defensible rather than reckless:

* The divergence predates this remediation. Comparing merchant/basket/amount already
  refused a same-ID-different-facts delivery instead of replaying it; the timestamp
  only extends an already-accepted decision to the identical-facts case.
* **It is inert on the judged path.** All 45 official ids are distinct and no id
  appears with two timestamps, so the official corpus contains no re-delivery at all.

**Residual risk, honestly:** if the hosted platform ever re-delivered a purchase with
a jittered timestamp, this would refuse a legitimate retry — a *liveness* failure, not
a safety one. Unobservable offline. Recorded in §9.

**Mutation evidence:** `two economic transactions under one id read as a retry again`
→ killed by `test_one_id_cannot_carry_two_economic_transactions`; `a null or empty
authorization_id is accepted again` → killed by `test_a_malformed_authorization_id_is_refused`.

## 4. Finding 3 — echoed mandate — **CLOSED**

**Invariant.** *The platform echo is data to validate, never an authority over
customer policy.*

| # | echo | expected | observed |
| --- | --- | --- | --- |
| 1 | identical | accept | **accepted** |
| 11 | same rules, reversed order | accept | **accepted** |
| 11b | same rules, shuffled | accept | **accepted** |
| 2 | tightened (rule added) | fail closed | failed closed |
| 3 | widened amount ceiling | fail closed | failed closed |
| 4 | widened merchant scope (rule removed) | fail closed | failed closed |
| 5 | widened time window (7 → 90 days) | fail closed | failed closed |
| 6 | removed rule | fail closed | failed closed |
| 7 | changed operator (`<=` → `<`) | fail closed | failed closed |
| 8 | changed currency (CHF → EUR) | fail closed | failed closed |
| 10 | all rules missing | fail closed | failed closed |
| — | uncertainty policy widened | fail closed | failed closed |
| 9 | malformed block (`hard_rules` not a list / empty / `None`) | raise | `TypeError` / `KeyError` |

Rows 11 and 11b are the trap the brief warned about: the comparison is over a **set of
normalised rule tuples**, so JSON ordering cannot cause a false rejection. Every
failure names each added and missing rule.

**Mutation evidence:** `a widened platform echo silently becomes the policy again` →
killed by `test_any_echoed_difference_fails_closed`.

## 5. Finding 4 — TTL — **CLOSED**

Expiry was not redesigned; this is coverage verification only.

| probe | observed |
| --- | --- |
| horizon = `issued_at + DEFAULT_AUTHORITY_TTL` | true |
| 1s before expiry | consumed |
| **exactly at expiry** | **consumed** — the contract is `now > expires_at` |
| 1s after expiry | refused |
| 1 year after | refused |
| very short TTL (1s) | horizon honoured; refused just after |
| long TTL (30 days) | horizon honoured; refused just after |

**Mutation evidence:** `a payment authority never effectively expires`
(15 min → 3,650 days) → killed by
`test_the_expiry_comparison_uses_the_same_clock_the_horizon_was_set_on`. This is the
mutant that **survived** the independent audit; it no longer does.

## 6. Test-the-tests

Every remediation has a mutant that removes it and a named test that catches it.

| mutant | killed by |
| --- | --- |
| unsupported intent no longer blocks confirmation | `test_unsupported_restrictive_intent_blocks_confirmation` |
| a drafted mandate silently drops the restrictions | same |
| two transactions under one id read as a retry | `test_one_id_cannot_carry_two_economic_transactions` |
| a null/empty authorization_id is accepted | `test_a_malformed_authorization_id_is_refused` |
| a widened platform echo becomes the policy | `test_any_echoed_difference_fails_closed` |
| an authority never effectively expires | `test_the_expiry_comparison_uses_the_same_clock…` |
| *(by direct demonstration)* plumbing reverted in `demo_scenario.py` | `test_every_compiling_drafter_plumbs_unsupported_restrictions` |

**35 mutants applied, 35 killed, 0 survived.**

## 7. Regression results

| gate | required | observed |
| --- | --- | --- |
| full suite | green | **934 passed, 5 skipped** (939 collected) |
| official replay | 45 · 19/2/24 | **45 · 19 allow / 2 review / 24 block** |
| adversarial corpus | 133/133 | **133/133** |
| attack matrix | 17/17 | **17/17** |
| mutation probe | ≥ 34/34 | **35/35** |
| independent corpus | 103 · 93 · 10 · 0 · 0 | **103 · 93 · 10 · 0 · 0** |

No expected result was adjusted to make anything pass.

## 8. New findings

| # | finding | severity | action |
| --- | --- | --- | --- |
| N1 | `research/demo_scenario.py` omitted `unsupported_restrictions`, so the gate could not fire for it | **low** (latent; research-only, instruction carries none) | **fixed + AST regression test** |
| N2 | In-process attribute tampering defeats the gate | informational | recorded, not fixed — not a boundary this can defend |
| N3 | The timestamp fingerprint diverges from the letter of *"recognize repeated delivery by its live purchase ID"*; a jittered re-delivery would be refused | low, liveness-only, inert on the judged path | recorded as an open limitation |
| N4 | The echo check is opt-in; offline and test callers supply no confirmed policy | informational, by design | recorded |

None is a freeze blocker. N3 is the one a future pass should revisit if the hosted
platform is ever observed re-delivering.

## 9. Freeze recommendation

**Freeze: YES.**

All four findings are CLOSED. The regression gate passes at or above every required
threshold. One genuine bypass was found during this pass and fixed with the smallest
change that closes it — one call site plus a test that makes the same omission fail
the suite rather than pass silently.

What this validation does **not** establish: that the compiler understands language
(90% of one person's corpus is not a language), that a *recognised* phrase is
interpreted correctly, or that the hosted platform behaves as the specification
describes. Those remain in `WHAT_WE_REFUSE_TO_CLAIM.md`.
