# A check that cannot fail is not a check

`docs/ABSENCE.md` records one mistake found at seventeen boundaries in the *product*:
something was missing, and something present was quietly put in its place.

This document records a second class, found at **eight boundaries in the
instruments** — the probes, sweeps, corpora and gates this project uses to decide
whether the product is sound. Every one of them reported success it had not earned,
and in every case the output was **indistinguishable from the real thing**.

That is what makes the class dangerous. A failing test tells you something. A test
that passes because it could not have failed tells you the same thing a working test
tells you, and everything you decide afterwards rests on it.

| # | the instrument | what it reported | what it had actually done |
| --- | --- | --- | --- |
| 1 | the mutation probe | `41 mutants applied, 41 killed, 0 survived` | examined **2**, then been interrupted. It printed the length of the mutant list |
| 2 | the mutation probe | a clean working tree | left a **live mutant** in `decision_engine.py` — its cleanup did not survive `SIGTERM`, and my own check grepped for one mutant *shape* out of a dozen |
| 3 | `docker compose --profile verify` | a clean pre-demo gate | run **no tests**: `tests/` was not in the image, and `pytest` with nothing to collect exits **0** |
| 4 | the research-module gate | every module runs | tailed each module's output instead of checking its exit code, so `lost_state.py` — the module reproducing the CHF 900 finding — sat **broken** after a rename |
| 5 | the synthetic-event corpus | `0 escapes under decline` | judged 120 events whose baselines were **all `block`**, and so could not have observed an erasure moving a decision away from `allow` |
| 6 | the instruction fuzzer's oracle | `nothing moved` | been unable to distinguish `CHF 120 per order` from **`CHF 1200 per order`** — it measured at the price band's floor, where neither ceiling binds |
| 7 | the forgeable-facts probe | `merchant.category` is **bound**, matching its declaration | attacked that fact by swapping the merchant *id*, which changes the shop and therefore the purchase, and never relabelled the category of the **same** shop |
| 8 | the stale-figure guard | every current document states the engine's real replay split | searched for the spelling `19/2/24`. `docs/FINAL_AUDIT_PACKAGE.md` — the page written for an external auditor — writes it `19 allow / 2 review / 24 block`, and had been **wrong by two events in two categories** across two boundary moves |

Plus one that is not an instrument failing but the same lesson: `paraphrase_corpus.py`
declared the expected relation for **43 rewordings**, each with a reason, written so
as not to be circular — and for four days, **nothing asserted any of it**. A corpus of
claims with nothing checking them is a document.

## The one that is worst, and why

**Seven is a false accusation against the code.** Instrument 7 did not merely fail to
find the defect; it *agreed with the false declaration*. `provenance.py` said
`merchant.category` was "loaded from reference data, never from the proposal" — true
of the event builders, false of the engine, which read it straight out of the event.
A `transport` merchant relabelled `groceries` was **allowed** on a groceries-only
mandate, with `merchants.csv` open in the same process.

The probe was written from the same misunderstanding as the code, so running it more
often could never have helped. That is the limit of self-testing, and the only escape
is an instrument that does not know what the answer is supposed to be —
`research/substitution.py`, which restates every field of every official event with a
value that field really takes elsewhere, and found it on its first run.

## What each fix looks like

Every repair has the same shape: **make the instrument prove it could have failed.**

| | |
| --- | --- |
| the probe | counts what ran, marks a short run `*** INCOMPLETE: nothing here is a pass ***`, returns non-zero, and restores on `SIGTERM`/`SIGINT`/`SIGHUP` |
| the verify profile | asserts a plausible collection count *before* trusting the suite; checked both ways — passes with tests, refuses in an empty directory |
| the module gate | runs each module in a subprocess and requires exit 0 |
| the corpus | asserts its baselines actually **move** (1,054 erasures made a decision stricter), so a corpus that could not fail cannot pass |
| the oracle | has a self-test that feeds it a ten-times-larger ceiling and requires it to notice |
| the probe (7) | attacks the same shop, and a test asserts the safety-field list is **derived** from the engine's own constants rather than copied |
| the corpus of claims | 43 declared relations are now compared as **sets of purchases decided by the real engine** — an oracle the compiler does not author |

## Why this is in the judge-facing set

Most submissions can show that their tests pass. The question a hostile reader should
ask next is *how do you know your tests can fail?* — and the honest answer here is
that eight times they could not, and that each was found by attacking the instrument
rather than by running it again.

Eight is also the interesting one, because the instrument that failed was the one
built to prevent exactly the drift it missed, and it failed in the way this whole
document is about: **a search that matches nothing is indistinguishable from a search
that finds everything correct.**

## Which were inherited and which were mine

Worth being exact, because "seven instruments lied" reads better than the truth and
the truth is more useful.

**Three were inherited**, and had been trusted across several campaigns: the mutation
probe's two failures (added 19 September) and the verify profile's (21 September).
Those are the ones that matter most — they had been quoted as evidence, repeatedly,
in documents that are still in this repository.

**Four I wrote the same day**, and caught within hours by attacking them: the
research-module gate, the synthetic corpus, the instruction fuzzer's oracle, and the
forgeable-facts probe. That is not a smaller failure. A new instrument is *more*
likely to be wrong than an old one and *less* likely to be doubted, because it was
written by someone who had just finished convincing themselves of the thing it
checks. Every one of the four was written to check a finding I had just made.

So the lesson `ABSENCE.md` ends on — a fix is a new place for the mistake to live —
turns out to be true of the tools as well as the code, and more true of them.

## The sweep over sweeps

An earlier version of this page ended: *"there is no sweep over sweeps. An eighth is
more likely than not."* The eighth arrived, and it suggested what the sweep should
measure.

Every instrument in the table above failed the same way: it reported on something it
had not examined. That is measurable without knowing anything about what any of them
were *for*. Run the suite under `coverage`, cross the executed lines against every
`assert` in `tests/`, and an assertion inside a test that ran, on a line that never
executed, is a claim this repository makes and does not check. A green tick says an
assertion did not fail. It does not say it ran.

`scripts/run_vacuity_audit.py` does that. On roughly 1,800 tests it found **seven**:

| where | the assertion | why it never ran |
| --- | --- | --- |
| `test_F3_concurrent_answers_to_one_step_up…` | a **declined** purchase holds no live payment authority | guarded by `if stored.decision == "block"`. Measured over 150 races, the declining thread won **once** — whichever thread starts second wins ~99% of the time |
| `test_baselines_are_captured_once_before_any_mutation` | the mutant loop takes no baseline from disk | `ast.walk` descends into nested functions, so "the first loop in `main` that writes a file" found the **signal handler's** restore loop. It had been inspecting the wrong function since that handler was added |
| `test_the_dockerfile_and_compose_exist_and_bake_no_secrets` | no credential is baked into the image | matched lines containing `API_KEY` **and** `=`. Compose passes keys through as YAML — `ANTHROPIC_API_KEY: "${…}"` — a colon, no equals. The scan examined **zero lines** |
| `test_the_agents_proposals_do_not_depend_on_the_secret_limit` | every revision matches while the wallet's answers match | compared CHF 60 against CHF 200, whose answers diverge at attempt **zero**, so the loop broke on its first iteration every time |
| `test_property_compile_instruction_never_crashes…` | every compiled rule is well-formed | Hypothesis' arbitrary text essentially never compiles to a rule, so the loop was empty on all 200 examples |
| `test_a_per_item_ceiling_is_not_confused_with…` | the extracted ceiling is 100.0 | guarded by `if ceiling is not None`, and the compiler correctly extracts nothing |
| `test_negative_sounding_amount_phrase…` | the extracted ceiling is ≥ 0 | same shape, same reason |

None were failing. All reported success about something they had not looked at. Two
of them — the concurrency invariant and the secret scan — are the kind a judge would
reasonably expect to be real.

All seven are fixed, and the fixes are not "add an assertion": the race now runs both
start orders and **fails if it does not observe both outcomes**; the secret scan reads
both file syntaxes, has five negative controls proving it catches a baked key, and
asserts it examined at least two lines; the agent test uses ceiling pairs whose
answers agree for several revisions and asserts it compared at least eight. The audit
now reports **0**.

`tests/security/test_vacuity_audit.py` is the audit's own negative control: a
synthetic tree with one assertion that ran and one that did not, and a synthetic
coverage record, so the instrument is shown to fire before its zero means anything.

## What is not claimed

That this is all of them. The vacuity sweep catches one shape — an assertion never
reached — and it is blind to the rest. An assertion that runs on data too weak to
falsify it looks identical to a working one from the outside; instruments 5, 6 and 7
in the table above were all of that kind, and none of them would be caught by the
sweep that now exists. A ninth is more likely than not.

The defence that generalises is still the one above: **an instrument must be shown to
fail on a case it should fail on, before its passes mean anything.** What changed is
that this repository now does that for its own instruments too, and says so where a
judge can check it.
