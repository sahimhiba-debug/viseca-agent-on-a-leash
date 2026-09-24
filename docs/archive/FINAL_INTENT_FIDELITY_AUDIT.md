# Final intent-fidelity audit

**The question:** does the wallet enforce what the customer asked for, or what our
policy compiler *thinks* they asked for?

**The answer:** it enforced what the compiler heard, and the compiler was
mishearing — in one case inverting a restriction into a weaker one and then telling
the customer that weaker reading was theirs. Six defects, all upstream of everything
this project had been testing. **Conclusion B**, moving to **A** after the fixes,
with one boundary that cannot be closed and is now stated rather than implied.

---

## 1. Current compiler architecture, traced not assumed

```
customer text
   → policy_compiler.compile_instruction()     ← the ONLY natural-language step
   → hard_rules + uncertainty_policy + guidance + open_questions
   → POST /v1/mandates  (draft)   ← OUR rules are what the platform stores
   → confirm
   → platform echoes `mandate.hard_rules` on every event
   → MandateSnapshot.from_event_mandate()      ← read back verbatim
   → rules.py → decision_engine → decision
```

Answering Phase 0's questions precisely:

| question | component |
| --- | --- |
| interprets natural language | `policy_compiler` — **alone**, and only once, at mandate creation |
| validates the interpretation | **the customer**, via `guidance` + `open_questions`, before confirming |
| decides whether the interpretation is complete | `_coverage_questions` (added by this audit) |
| decides scope, temporal semantics, negation | `policy_compiler` regexes |
| can silently discard information | `policy_compiler` — **this was the defect** |
| can invent a rule | `policy_compiler` (it did: a per-order ceiling nobody wrote) |
| can weaken a rule | `policy_compiler` only; `mandate.tighten_hard_rules` forbids widening afterwards |
| can turn unknown into allow | `decision_engine._decide`, under `uncertainty_policy` only |

**The nuance that matters.** A previous campaign concluded "the compiler is not in
the live decision path", because `from_event_mandate` reads the platform's rules.
That is true and it was misleading: **the platform's rules are our compiler's
output.** A compiler error is baked in at mandate creation and then enforced
faithfully, forever. Not being re-run per event makes it *harder* to catch, not
safer.

**And the stated mitigation is a no-op on one path.** `scripts/run_live_worker.py`
compiles, drafts, and then calls `confirm_mandate` immediately — its own comment says
*"In a real product this pauses for the customer's explicit confirmation."* The
confirmation that justifies trusting the compiler exists in the API/UI path and not
in the event-day script. Recorded in §24 rather than fixed, because on event day the
operator reads the logged rules and open questions.

## 2. The five official mandates, decomposed

Every proposition, and whether a rule reaches the engine. **Bold = was lost.**

| mandate | proposition | rule | enforced |
| --- | --- | --- | --- |
| **SCEN0000** | **"one" item** | — | **no — now disclosed** |
| | grocery item | `item.category in [groceries]` | yes |
| | CHF 20 or less | `billing_amount_chf <= 20 purchase` | yes |
| | shop I use regularly | `merchant.familiar = true` | yes |
| | ask when uncertain | `uncertainty_policy=ask` | yes |
| **SCEN0001** | each order ≤ CHF 120 | `<= 120 purchase` | yes |
| | total across any 7 days ≤ CHF 300 | `<= 300 period/7` | yes (per run — §9 of the deep R&D report) |
| | household groceries | `item.category in [groceries]` | yes |
| **SCEN0002** | **"replace" (one pair)** | — | **no — now disclosed** |
| | road-running | `item.name_contains = road-running` | yes |
| | size 43 | `item.size = 43` | yes |
| | only specialist sports retailer | `merchant.category in [sporting_goods]` | yes |
| | only if returnable ≥ 14 days | `order.return_window_days >= 14` | yes |
| | ≤ CHF 200 | `<= 200 purchase` | yes |
| **SCEN0003** | ≤ CHF 250 per order | `<= 250 purchase` | yes |
| | shops used before | `merchant.familiar = true` | yes |
| | pause if not me | `session.integrity_risk = false` | yes |
| **SCEN0004** | **"the monitor I chose" (one, specific)** | partial — variant only | **quantity disclosed** |
| | 27-inch | `item.name_contains = 27-inch` | yes |
| | seller bought from before | `merchant.familiar = true` | yes |
| | ≤ CHF 400 | `<= 400 purchase` | yes |
| | no unrequested items | `item.unrequested_present = false` | yes |

**Three of five official mandates contain a singular/quantity proposition, and none
of them was represented.**

## 3–4. Coverage matrix and information loss

| concept | expressible by customer | parsed | represented | enforced | status |
| --- | --- | --- | --- | --- | --- |
| per-order amount | yes | yes | yes | yes | ok |
| rolling-window amount | yes | **was broken** | yes | yes | **fixed** |
| overall total | yes | yes | **never** | no | **disclosed** (vocabulary cannot express it) |
| end date / deadline | yes | yes | **never** | no | **disclosed** |
| quantity / "one" | yes | yes | **never** | no | **disclosed** |
| strict vs inclusive limit | yes | **was conflated** | yes | yes | **fixed** |
| merchant familiarity | yes | partial | yes | yes | **broadened + disclosed** |
| merchant category | yes | lexicon | yes | yes | ok, lexicon-bounded |
| item category | yes | lexicon | yes | yes | ok, lexicon-bounded |
| item variant / size | yes | yes | yes | yes | ok |
| return window | yes | yes | yes | yes | ok |
| no unrequested items | yes | partial | yes | yes | **broadened + disclosed** |
| session integrity | yes | yes | yes | yes | ok |
| uncertainty policy | yes | yes | yes | yes | ok |

## 5–10. Results by attack class

**Negation** — "Do not spend more than CHF 50", "Never spend over CHF 50" produce no
ceiling. Not silent: the missing-ceiling question fires.

**Quantifiers** — "one", "exactly one", "at most one", "up to three" are all
unrepresentable. `scope` is `purchase` or `period` and the spec closes the set, so
there is no "this many items" and no "this many orders". **Representational
limitation, not a compiler bug**, and now named back to the customer.

**Scope — the worst finding.** `"up to CHF 250 per week"` compiled to
`billing_amount_chf <= 250 scope=purchase`. A weekly budget became a per-order
ceiling: CHF 250 *every order*, indefinitely. The guidance then said *"Each order
must total CHF 250 or less"* — asserting a scope the customer never wrote — and the
open question advised them to *"consider adding a rolling weekly limit"*, which is
what they had just written. Same inversion for `"in total"`. **Both fixed.**

**Temporal** — week/month/day/fortnight/year now map to period rules; explicit day
counts use the customer's number. `_ROLLING_RE`'s existing "across any N days" form
is unchanged.

**Conditionals / unknown** — the two uncertainty layers are distinct and must stay
so. *Interpretation* uncertainty → `open_questions`, resolved by the customer before
confirming, affects no decision. *Evidence* uncertainty → `unknown`, resolved by
`uncertainty_policy` at decision time. Collapsing them would let a parse failure be
auto-approved under `uncertainty_policy=approve`. It does not: an unparsed phrase
creates no rule and no `unknown`.

## 11–14. Empirical results

| campaign | before | after |
| --- | --- | --- |
| adversarial optimiser, 4,800 generated instructions | **7,392 silent losses** (4,032 quantity · 2,400 temporal · 960 familiarity) | **0** |
| falsification probe, 15 constructed sentences | 3 silent | **0** |
| metamorphic, 95 cases over 5 mandates | whitespace lost the ceiling in **5/5** | **0** |
| paraphrase corpus, 43 declared relations | 15 unmet | 9 unmet, **8 of them my harness's blind spots** (§22) |

## 15. Human interpretation differential

**Not performed.** No human evaluation was run, and none is fabricated. The expected
relation for each paraphrase was annotated by me before running the compiler, with
the reason recorded in `research/paraphrase_corpus.py`, and the compiler's own output
was never used to define the expectation. That is a documented annotation set, not a
human study, and it carries the obvious limitation: **the same author wrote the
expectations and the fixes.**

## 16–17. Verification mechanisms considered

| candidate | verdict |
| --- | --- |
| **coverage check** (restrictive language with no rule is named back) | **ADOPTED** — deterministic, creates no rule, changes no decision, needs no infrastructure |
| independent second parser + agreement gate | rejected — two regex parsers sharing a lexicon share their blind spots; the disagreement signal would be near-zero |
| LLM as interpreter or verifier | rejected — the brief forbids it, `technical_details.md` requires a predictable response when a model is unavailable, and a model cannot be the sole authority for proving its own interpretation |
| confidence scoring | rejected — a number invented by the same patterns that failed |
| restricted grammar (forms-only input) | rejected — solves fidelity by removing natural language, which is Objective #1 |
| policy diff on re-compile | already present: compilation is deterministic, asserted |

The adopted mechanism is deliberately the weakest thing that works. It does not try
to understand the phrase. It notices that the customer used restrictive language of
a KIND for which no rule exists, and says so before they confirm. Broadening patterns
fixes the wordings someone thought of and nothing else; there are indefinitely many
ways to write a restriction, and guessing at one is how the "per week" inversion
happened.

## 18–21. Defects, fixes, invariants, mutation

| # | defect | severity | fix |
| --- | --- | --- | --- |
| 1 | `"CHF 250 per week"` → per-**order** ceiling | **high — inversion, stated to the customer as fact** | period rule |
| 2 | `"CHF 50 in total"` → per-order ceiling | **high — same inversion** | no rule + disclosure |
| 3 | quantity never represented (50 purchases for "buy one"; `quantity: 50` approved) | medium | disclosure |
| 4 | 5/8 no-add-ons and 2/8 familiarity paraphrases dropped silently | medium | synonyms + coverage check |
| 5 | **doubling spaces lost the ceiling in all five mandates** | **high** | normalise whitespace |
| 6 | `"under CHF 50"` admitted exactly CHF 50 | low | strict operators |

New invariants **I37** (a period-qualified amount is a budget, never an order
ceiling) and **I38** (restrictive language with no rule is named back to the
customer). Mutation probe **21 → 26, all killed**.

## 22. Failed experiments and corrected conclusions

* **My harness had three blind spots**, and they mattered: no probe produced an
  `unknown`, so `uncertainty_policy` differences were invisible; each probe ran in a
  fresh state, so period rules could never bind; and `item.category` masked
  `item.unrequested_present`. The third meant the paraphrase corpus **passed** cases
  that were genuinely broken. Two are fixed; the remaining 9 unmet expectations are
  honestly reported as probe-coverage limits, not as compiler defects.
* **My optimiser inflated its own result.** Its quantity marker was a bare `"one" in
  text`, which fired 192 times on *"a shop that is one I have used before"* — a
  phrase with no quantity intent. A measurement whose marker is looser than the
  concept it measures is not a measurement.
* **I introduced a regression and the replay did not catch it.** The first
  strict-inequality pattern failed to exclude "at or below", flipping SCEN0001's rule
  from `<=` to `<`. Nothing failed, because no official purchase is exactly CHF
  120.00, and the guarding test compared value and scope but not the **operator**.
  Found by reading compiled rules. The test now pins operators.
* **The mutation probe caught me leaving disclosure unasserted.** Reverting the
  overall-total fix passed the whole suite, because I had fixed and disclosed the
  behaviour without pinning it.

## 23. Remaining limitations

1. **The compiler is the trust boundary, and it is phrase patterns.** Coverage is
   checked; *correctness of a recognised phrase* is not. A pattern that matches the
   wrong thing still produces a wrong rule silently.
2. **Two lexicons bound what is expressible** — item categories and retailer types.
   Outside them, an open question, never a guess.
3. **Three concepts are inexpressible in the official vocabulary**: an overall total,
   an end date, and any quantity. All three are now disclosed; none is enforced.
4. **Confirmation is the mitigation, and it is a no-op in the live worker script.**
5. **The annotation set has one author**, who also wrote the fixes.

## 24. What we refuse to claim

* **NOT** that the wallet enforces the customer's intent. It enforces the compiled
  policy, and shows the customer that policy plus what it could not represent.
* **NOT** that the compiler understands natural language. It matches phrase patterns.
* **NOT** that the coverage check finds every lost restriction. It detects the KINDS
  it knows; a restriction of an unanticipated kind is still lost silently.
* **NOT** that "no silent weakening" is proved. It is measured — 4,800 generated
  instructions, 95 metamorphic cases, 43 annotated paraphrases, 15 falsification
  sentences — and measurement over a corpus is not a proof over a language.
* **NOT** that any of this was validated by a human other than its author.

## 25. Conclusion

**B at the start, A at the end, with a boundary that stays open.**

The audit began at **B — a material unresolved weakness**: a restriction the
customer wrote was silently inverted into a weaker one, and the weaker reading was
reported back as if it were theirs. That is the worst available failure of an intent
layer, because the disclosure mechanism that is supposed to catch a mistake was
repeating it.

It ends at **A — adequately bounded**, on the evidence above, for the kinds of
restriction the compiler knows about. The bound is not "the compiler is right". It is
narrower and testable: *restrictive language that produced no rule of its kind is
named back to the customer before they confirm*, and *a period-qualified amount is
never compiled as an order ceiling*.

**C was considered and refused.** No new verification mechanism is justified. Every
candidate stronger than the coverage check either needs a model in the money path,
or invents a confidence number from the same patterns that failed, or verifies the
interpretation using the thing that produced it.

The honest summary is the sentence the brief anticipated, and it is now earned rather
than assumed:

> The compiler is the remaining trust boundary. Under the current challenge protocol
> we cannot verify natural-language intent, so we bound that claim explicitly, name
> what we could not represent, and make the customer confirm the structured policy
> before it has any authority.

What changed is that this sentence used to be true only in aspiration. Six defects
stood between it and the code, and the largest of them was reporting a restriction
the customer never wrote.
