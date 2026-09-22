# Research log — 22 September 2026

Seventeen commits on `rnd/productization`. `main` untouched at `1aa3bac`.

---

## 1. What was discovered

### Withholding beats lying — at four different boundaries

A hard rule needs evidence. `order.return_window_days >= 14` is checked against a
window the **seller publishes**. Publish five days and the rule FAILS. Publish
nothing and it is UNKNOWN — not a failure — and goes to `uncertainty_policy`. The
party that picks the seller is the agent: the party the rule constrains.

```
a seller publishes a 5-day return window   ->  BLOCK
a seller publishes nothing                 ->  REVIEW, or ALLOW

an agent names a shop you have not used    ->  BLOCK
an agent names no shop at all              ->  ALLOW          (was a real bypass)

a customer writes "return within 14 days"  ->  a rule
a customer writes "send it back in 14 days" ->  nothing, silently
```

> **A rule is only as strong as the adversary's ability to avoid producing the
> evidence it needs.** If the party who chooses the evidence source is the party the
> rule constrains, the rule is advisory.

### Absence is not a value — nine instances of one mistake

Every vulnerability this project has found is the same mistake at a different
boundary: *something was missing, and something present was quietly put in its
place*. The failing shapes are **filled in**, **inferred**, and **thrown**.
`docs/ABSENCE.md` carries the table. Instance 7 was **predicted** by writing the
rule down and looking where the substitution is idiomatic; instance 9 came from the
official specification.

### The acceptance set — what the Apertus repository actually implies

`Swiss-ai-Weeks/optimized-apertus` is not an example of how to call Apertus. Its
subject is **speculative decoding**: an 8B draft proposes, a 70B target verifies, and
the guarantee is that the output distribution is the 70B's alone. A bad draft changes
the *speed*, never the *answer*. That is this architecture with a rigorous name, and
it supplies the object we had never named — the **acceptance set** is our output
distribution, and *acceptance rate* is the field's own figure of merit for a draft.

### Two tooling defects that cost more than any code defect

The mutation probe was editing source and not putting it back; and my own read-back
endpoint was quadratic. Both were found by attacking our own instruments.

---

## 2. What was changed

| area | change |
| --- | --- |
| **runtime** | `witness.py` (shared apparatus, one event builder), `silence.py`, `unconsumed.py`, `scope.py`, `disagreement.py`; `ambiguity.py` refactored onto the shared apparatus, output byte-identical |
| **API** | `POST /api/mandates/size`, `/read-back`, `/silence`; `/ambiguity` now reports a *count* |
| **UI** | three new Delegate panels — delegation size, read-back, silence — each silent when it has nothing to say |
| **engine** | `in`/`not_in` as membership on every field; an inapplicable rule is UNKNOWN, never an exception; `_requested_categories` and `_plain_reason` hardened against schema-legal values |
| **customer message** | an approval on *absence of evidence* now says so, on the fresh decision and the re-presented one |
| **agent boundary** | a missing `merchant` is a refusal, not `ME0001`; required fields checked for a *value*, not a key; unreadable numbers are 400s, not 500s |
| **checkpoints** | a partial execution lifecycle refuses to restore; a missing checkpoint warns loudly |
| **attack demo** | nine attacks, **one of which succeeds**, with the argument attached |
| **tooling** | the mutation probe is crash-safe, self-checking, and reads the tree it cuts |

---

## 3. What was disproved

- **"A card limit and this wallet approve different sets."** On the official grocery
  catalogue, for a mandate a card *can* express, they approve **exactly the same 116
  of 595 baskets** — and the agreement is a coincidence: the one unfamiliar grocery
  shop is also the one in Germany, so the card excludes it by *country* and the
  wallet by *familiarity*. The thesis survives only in its sharper form: the
  difference is not in how much or where, it is in **what was bought and on what
  terms**.
- **"`decline` closes the silence channel at no cost."** It closes it completely and,
  on groceries, buys nothing at all — 0 of 7 grocery items publish a return window.
  The control (clothing, 4 of 7 publishing) completes the same errand under the same
  setting for CHF 30 more. **Declining is not what costs. Requiring evidence nobody
  publishes is.**
- **"`blocked_by` enabled the silence attack."** My first reading. A blind variant
  with no wallet feedback at all arrives in *one* attempt instead of two. The hint
  saved a probe and enabled nothing.
- **"The suite passed with `_decide` neutered."** I wrote that, then measured it: the
  suite catches it on the thirteenth test. The corruption survived because of gate
  *ordering*, not weak tests.

---

## 4. What was experimentally validated

| claim | measurement |
| --- | --- |
| describing a purchase with less can make it more acceptable | 52 of 6,864 erasure pairs; **0 under `decline`** |
| an evasive agent moves real money | CHF 103 into unreturnable goods; **control**: same CHF 103, CHF 0 of harm when the goods really are returnable |
| `uncertainty_policy` is the only lever the format offers | no rule in the vocabulary can be made to FAIL by silence, over every field `rules.py` evaluates, read from its source |
| only two fields help when emptied | 657 single-field variants **and 15,763 pairs** where neither alone helped: 0 masked vacuities |
| the read-back measures the compiler, not English | three compilers, three different read-backs (2 / 6 / 11 words) |
| the read-back finds what vocabulary cannot | 19 of 20 silently-lost restrictions; **0 false alarms** on 33 well-formed sentences |
| no brain can enlarge the acceptance set | 4 brains, 337 proposals, including one ranking baskets by a hash: **0 escapes** |
| no legal rule crashes the engine | 1,344 field × operator × value × scope combinations |

---

## 5. What remains genuinely unresolved

- **No language model has been run.** `api.publicai.co/v1` answers 401 without a key;
  it was tried today. The seam is real and exercised by two hand-written compilers,
  and every claim about a model is about the *mechanism*, not a benchmark.
- **The silence channel is open by design** and cannot be closed per-rule: the
  official mandate format has one uncertainty dial for a question that is per-rule.
  That is a gap in the format, disclosed with a witness.
- **The read-back misses restriction-by-noun** ("Swiss shops preferred") and fires on
  restriction-flavoured remarks ("Do not worry about the weather"). Both are asserted
  as failures so they cannot be quietly deleted.
- **A witness has never been user-tested.** The claim that a concrete purchase is
  easier to answer than a rule list is the thesis behind three panels and rests on no
  study.
- **Nine absence instances and six sweeps are not a proof.** The ninth was found by
  reading the specification rather than by any sweep, which is the honest measure of
  how much they cover.

---

## 6. The strongest new differentiator

**A mandate is a set, and the set is countable.**

Every team will show a judge a rule list. This one answers the question a person
actually has — *how much rope did I just hand over?* — by putting all 595 purchases
the world can produce through the same engine that will judge the real ones, and
reporting the size of what comes back. Live, at 18 ms, as they type:

```
 595 / 595   "Order our household groceries."
 145 / 595   "...at or below CHF 120."                    -450
 116 / 595   "...from a shop I have used before."          -29
None without asking you — "...and only things I can return in 14 days."
```

It is hard to fake (the numbers come from the real engine), hard to reproduce
casually (it needs an enumerable world and a deterministic core), measurable, and it
makes "customer control" concrete rather than rhetorical. Directly beneath it sits
the read-back — **cause under consequence** — and a word that changed no rule
provably cannot change the size of the set.

---

## 7. What the final demo should prove

1. **You can see what you authorised.** 595 → 145 → 116, as you type.
2. **You can see what we understood.** Your own sentence, green for read, struck
   through for ignored, red where one word blocked a rule. Rewrite it and watch the
   clause turn green — *and the silence panel appear*, because the problem only
   exists once the rule does.
3. **A seller who says less gets further** — and the dial that closes it, which makes
   the panel fall silent.
4. **The agent is autonomous and the authority is not.** It is refused at an
   unfamiliar shop, changes shop, and is approved — for *more* money, because it
   fixed the problem rather than shrinking the basket.
5. **Eight of nine attacks stopped, and one is not** — with the exhaustive argument
   for why the format cannot express the defence.

What it must never claim: that a model was tested, that `decline` is free, that the
read-back finds every missed restriction, or that nine instances are a proof.
