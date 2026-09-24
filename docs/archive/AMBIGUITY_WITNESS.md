# Your sentence does not decide this one

**A policy is a hypothesis about what someone meant. This finds the experiment
that distinguishes two hypotheses — and the customer is the only instrument that
can read the result.**

```bash
python3 research/ambiguity_witness.py
```

---

## The problem with telling someone their sentence is ambiguous

The compiler already detects ambiguity and explains it, honestly, in prose:

> *"The instruction mentions more than one per-order amount; the smallest was used
> defensively. Please confirm the intended limit."*

Nobody audits prose about hypothetical purchases. They agree to it. The warning is
truthful and it protects nothing, because it asks the customer to imagine a
consequence they have no reason to imagine.

## The idea

**Do not describe the ambiguity. Find the purchase it changes.**

Compile the sentence twice — once as the compiler read it, once as the other
defensible reading — then search for a basket the two policies judge *differently*,
running both through the real engine. That basket is a **witness**: concrete proof
the sentence is underdetermined, and the only question a customer can actually
answer.

```
"Order groceries, under CHF 120."

    a basket costing exactly CHF 120.00
        read as "the amount itself is too much"  ->  BLOCK
        read as "the amount itself is fine"      ->  ALLOW
```

One rappen. That is the entire disagreement, and it is invisible in prose.

```
"Order groceries, up to CHF 250 per week."

    3 purchases of CHF 125.00
        read as "a rolling budget for the period" ->  BLOCK
        read as "a ceiling on each order"         ->  ALLOW
```

No *single* purchase can separate those two readings. The witness has to be a
**sequence**, which is why this is a search rather than a boundary check.

## The property that matters most is the silence

A disambiguator that fires on clear language teaches people to click through it,
and then it protects nobody. Measured over the corpus: **2 witnesses across 5
sentences**, and silence on the other three.

| sentence | witness? |
| --- | --- |
| "under CHF 120" | **yes** — CHF 120.00 exactly |
| "at or below CHF 120" | no — explicit |
| "up to CHF 250 per week" | **yes** — 3 × CHF 125 |
| "at or below CHF 120, from a shop I have used before" | no |
| "the 27-inch monitor, for CHF 400 or less" | no |

Two readings were written and then **deleted** for failing this test:

- *"Did naming the goods restrict what may be bought, or only describe it?"*
  produced a witness for **every** sentence. A hypothesis that separates everything
  separates nothing. "Order our household groceries" plainly restricts to groceries.
- The strictness question originally fired on *"at or below CHF 120"* too, which
  says plainly that CHF 120 is included. It is now gated to genuinely vague bounds.

`test_a_reading_that_fires_on_everything_is_not_a_reading` keeps that discipline.

## What it is not

- **Not a confidence score**, and not a model rating its own certainty. Both
  readings are *executed*. If no purchase separates them, the ambiguity is
  immaterial and the customer is never shown it.
- **Not a decision.** `wallet_control/ambiguity.py` decides nothing. It lives in the
  runtime for the same reason the compiler's open questions do: it is shown to the
  customer before they confirm.
- **Not exhaustive.** Two readings are implemented. A sentence can be ambiguous in
  ways this does not model, and silence is not proof of clarity.

## Where it sits

Between the compiled rules and the **Confirm** button — the one moment where
knowing changes what the customer does.

## The lineage

This is the same experimental form as the CHF 62 experiment, one level deeper.

| | held constant | varied | result |
| --- | --- | --- | --- |
| CHF 62 | amount, shop, card, second, goods | the customer's **intent** | three different verdicts |
| this | the customer's **sentence** | the **reading** of it | two different verdicts |

The first shows that a number cannot express an intent. The second shows where a
sentence stops expressing one — and hands that question back to the only party
entitled to answer it.
