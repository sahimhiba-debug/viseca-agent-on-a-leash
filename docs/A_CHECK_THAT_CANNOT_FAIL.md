# A check that cannot fail is not a check

`docs/ABSENCE.md` records one mistake found at seventeen boundaries in the *product*:
something was missing, and something present was quietly put in its place.

This document records a second class, found at **seven boundaries in the
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
that seven times today they could not, and that each was found by attacking the
instrument rather than by running it again.

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

## What is not claimed

That this is all of them. The instruments were audited because one of them was caught
lying, not because a sweep enumerated them — there is no sweep over sweeps. An eighth
is more likely than not, and the only defence that generalises is the one above: an
instrument must be shown to fail on a case it should fail on, before its passes mean
anything.
