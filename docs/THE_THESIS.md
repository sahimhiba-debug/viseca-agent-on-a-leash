# A policy is not a list of rules. It is a set of purchases.

This repository had nine headline ideas, which is the same as having none. They are
not nine ideas. They are **two**, and every mechanism in the product is a face of the
first.

---

## The product idea

A customer writes a sentence. Every wallet, every card, every agent framework answers
by showing them **rules**:

> Maximum per purchase — CHF 120
> Merchant — must be familiar
> When unsure — ask you

All true, and none of it answers the question a person actually has, which is *how
much did I just hand over?* So answer it. Enumerate every purchase this world can
produce, put each one through **the same engine that will judge the real ones**, and
report the set that comes back.

```
 595 / 595   "Order our household groceries."
 145 / 595   "…at or below CHF 120."                       −450
 116 / 595   "…from a shop I have used before."             −29
  28 / 595   "…at or below CHF 60…"                         −88
```

Live, at 18 ms, as they type. That set — call it **A** — is what was delegated.

### Five faces of one object

| face | the question | measured |
| --- | --- | --- |
| **size** | how much rope? | `|A|` = 116 of 595, and **how many times**: with no rolling rule, *unlimited* |
| **read-back** | which of my words did that? | each word deleted and the sentence recompiled; a word that changed no rule provably cannot change `|A|` |
| **ambiguity** | is the boundary of A even determined? | *"up to CHF 250 per week"* — **470 of 595** purchases judged differently by two defensible readings; the cheapest witness is three orders of CHF 87 |
| **silence** | can anything step into A from outside? | yes: a seller who publishes *nothing* beats one who publishes bad terms. 52 of 6,864 erasure pairs, **0 under `decline`** |
| **containment** | can the agent make A bigger? | no. Four brains — including one ranking baskets by a hash — plus an exhaustive prober trying all 595 in five orders: **0 escapes** |

That last row is the architecture, stated as set containment and checked by
enumeration rather than asserted in a docstring. It is also the guarantee
[speculative decoding](https://github.com/Swiss-ai-Weeks/optimized-apertus) gives a
draft model: an untrusted fast proposer changes the **speed**, never the
**distribution**. The wallet is the verifier. The agent is the draft. **A is the
distribution.**

### Why a card cannot do this

Measured, both ways, and the first answer is the inconvenient one:

| the customer's sentence | a card limit | this wallet |
| --- | --- | --- |
| *"…at or below CHF 120 from a shop I have used before"* | 116 of 595 | **116 of 595 — identical** |
| *"…only if returnable within 14 days"* | 116 of 595 | **0**, and 116 put to the customer |

On this catalogue the two controls agree *exactly* for a mandate a card can express —
and the agreement is a coincidence: the one unfamiliar grocery shop is also the one in
Germany, so the card excludes it by **country** and the wallet by **familiarity**.
Same answer, different question.

The difference is not how much, or where. It is **what was bought and on what terms** —
and neither control can obtain the missing fact. Only one of them can tell you it is
missing.

---

## The engineering idea

**Absence is not a value.** Twelve instances of one mistake, at twelve boundaries:
*something was missing, and something present was quietly put in its place*
([`ABSENCE.md`](ABSENCE.md)).

It connects to the first idea directly: **every one of those twelve was a place where
A was secretly bigger than it looked.** A default that approves is the only kind of
bug that is quiet, because nothing complains.

Four of the twelve were found by reading the organizers' own material rather than by
any sweep we built — and they produced three sentences a card cannot say:

> *"…it would take you over the CHF 300 you allowed across any 7-day period.*
> ***You could order this again on Monday 17 August at 09:12.***"
>
> *"…because **this purchase came from a device that has not been used earlier in
> this session**."*
>
> *"…because **this seller's product description contains instructions aimed at an
> automated buyer, not at you**."*

None of the three *fails* a rule. Each returns `unknown` and goes to the customer's
own `uncertainty_policy` — none is evidence the purchase is bad, and that is exactly
what the third value is for.

---

## What this is not

* **Not an LLM product.** No model has been run: the public Apertus endpoint answers
  401 and the CLI's OAuth will not refresh for a subprocess. Both verified today. The
  seam is built and exercised by two deliberately different hand-written compilers,
  and every claim about a model is about the *mechanism*, not a benchmark.
* **Not a proof.** `|A| = 116` is a function of the enumeration's bound — one shop, up
  to five lines, the official catalogue. What carries meaning is how it **moves**.
* **Not adversarially complete.** The silence channel is open by design and cannot be
  closed per-rule, because the official mandate format has one uncertainty dial for a
  question that is per-rule. That is a gap in the format, disclosed with a witness.
* **Not user-tested.** The claim that a concrete purchase is easier to answer than a
  rule list is the thesis behind four panels and rests on no study.

---

## The numbers, all checkable

```
official replay      45 events · 17 allow / 4 ask / 24 block · byte-identical ×3
tests                1,663 passed · 5 reported skips
mutation             39 mutants applied · 39 killed · 0 survived
adversarial corpus   133 / 133 held
planning benchmark   11 / 11   (pre-registered baseline 5/11)
intent corpus        90% recognised · 0 silently lost · 0 misinterpreted
authorship audit     0 violations
research modules     6 · byte-identical across runs
```
