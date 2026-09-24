# 840 generated instructions, aimed at silent semantic loss

**Status: SUPPORTED BY EXPERIMENT.** A sample of the restriction kinds we thought to
generate, phrased by one model. It is not an independent oracle and not a proof.

## The question

When a customer states a restriction, does the wallet either **enforce** it or **say**
that it cannot? The failure is losing a restriction without a word, or weakening one
(a weekly budget turned into a per-order ceiling). Each constraint of each instruction
is graded into one of these:

| grade | meaning |
| --- | --- |
| ENFORCED | a rule at least as strict as the customer asked |
| DISCLOSED | no such rule, and a warning *about that kind of restriction* is shown before confirmation |
| SILENT_LOSS | no rule and no relevant warning |
| ENFORCED_LOOSER | a weaker rule (a higher amount, per-order instead of per-week) and no relevant warning |
| STRENGTHENED | a rule the customer did not ask for, or a stricter value |

## Where the expected meaning comes from

The expected meaning is **not from the model.** `research/generated_corpus.py` first draws
each instruction's meaning in code: the amount and its Swiss notation, the limit word,
the scope (per order, per week, any 7 days, per month, in total), the familiar shop, the
return terms, one-off or recurring, the language, and the uncertainty policy. OpenAI
`gpt-4.1` is then asked only to phrase that spec as a customer would. The model is a
paraphraser, graded against a spec it did not write. Where it changed the meaning
while phrasing, the case is listed as `PARAPHRASE_DRIFT` after a person read it (2 of
840). It is never counted as a pass.

## What each corpus found BEFORE the fixes it prompted

Each corpus is measured once, reported as found, and only then used to fix the
compiler. The honest numbers are the "found" column. The zeros at the end were fitted.

| corpus | style | generated | found | then fixed |
| --- | --- | --- | --- | --- |
| tuning, 240 | natural | first | **111 silent losses, 12 weakenings** (lenient grader) | Swiss periods, familiar-shop paraphrases, refundable / final sale, one-time purchase, bare amounts, "total" |
| holdout, 200 | terse notes | after round 1 | **11 silent, 9 weakened** (lenient) | `CHF 120/month`, `/wk`, short German and Italian, "places I've shopped", "1-time" |
| blind, 200 | chatty | after round 2 | 0 under the lenient grader; **9 silent, 2 weakened** once the grader was made strict | one-off wording ("that jacket I picked out", "just one", "1x"), "for the week", "any 7 days", "same shop as before" |
| final, 200 | formal email | after round 3 | **3 instructions** (5 constraints) lost, all real: "a shop where I have made previous purchases" (twice), and a formal Italian email that contained none of the listed foreign words | a vocabulary-free language signal (share of English function words), "made previous purchases" |

After round 4, all four corpora (840 instructions) grade **0 SILENT_LOSS, 0
ENFORCED_LOOSER, 0 STRENGTHENED**. Of 157 English instructions whose every constraint
is enforced, 2 still carry a warning. Both are texts where the paraphraser added "one
every week", a count the wallet really cannot hold. `tests/security/test_generated_corpus.py`
holds all of this offline, with a negative control showing that the grader catches a
compiler that returns nothing.

**The last measurement made before any fix is 3 in 200 (1.5%).** Quote that number,
not the zeros.

## The worst class it found

This is the **scope inversion**: "no more than CHF 400 within any seven-day period",
"40 CHF weekly" and "max 120 CHF/month" each compiled to a **per-order** ceiling. So a
weekly budget let the agent spend that amount on every order, forever, and the customer
was not told. The compiler's own comments already name this as its most damaging
failure mode, and it came back through three new spellings. Every rolling-limit
spelling now either compiles to a rolling rule or triggers the period warning.

## What it does not show

* **The kinds are ours.** The generator only produces the restriction kinds this
  file asks for. A kind nobody thought of ("nothing made in X", "not before payday")
  is not measured here. `unconsumed.py` is the causal detector for those, and it
  still misses "Keep it cheap."
* **Other languages are detected, not read.** A French instruction gets a warning,
  not rules.
* **The grader's relevance check is keyword-based.** A warning counts as relevant
  when it names the kind of restriction lost. That is stricter than "any warning",
  but it is not a semantic check.
* **It says nothing about the decision engine.** This is about the compiler, which
  sits before confirmation. It is not in the live decision path, where the platform
  supplies the rules.

Cost: 840 generations with `gpt-4.1`, under 2 USD of the organisers' credit.

```bash
python3 research/generated_corpus.py            # tuning corpus, offline
python3 research/generated_corpus.py --holdout  # --blind, --final likewise
OPENAI_API_KEY=... python3 research/generated_corpus.py --final --generate 200
```
