# Audit 1 — independent attack on the fulfilment model

Conducted as an independent reviewer with no stake in the design. The instruction
was to attack the **model**, not hunt for coding errors, and to assume the attacker
knows exactly how it works.

**Result: one real evasion found. The core claim survived; the counting rule did
not.**

---

## What the model claims

> A mandate carries a *shape*. A ONE_SHOT mandate describes a job that can be
> finished. Once fulfilled, a further purchase performing the same job is put to
> the customer rather than silently approved.

---

## A1 — Dodge the job key by proposing something outside the anchors

**Idea.** The fulfilment key is built from the customer's compiled item anchors. So
propose something that does not match them, and the observer has nothing to match
against.

**Result: FAILED (the model holds).** A `Trail-running shoes` line against a
mandate anchored on `road-running` is **blocked by the ordinary rule engine** before
fulfilment is ever consulted.

This is the strongest structural property the design has, and it is worth stating
precisely: the fulfilment key is derived from *the same anchors the policy engine
enforces*. To evade the fulfilment check the agent must propose something the policy
check rejects, and to satisfy the policy check it must propose something the
fulfilment check recognises. **The two checks are mutually reinforcing rather than
independent layers.** An attacker cannot be outside both at once.

---

## A2 — Perform the whole job in a single purchase

**Idea.** The observer counts *purchases*. So do the job twice inside one
authorization: two pairs of shoes, one event.

**Result: EVASION CONFIRMED.**

```
mandate : "Replace my worn road-running shoes in size 43."  (cap CHF 200)
event   : 1 authorization, item "Road-running shoes", quantity 2, CHF 198
engine  : allow            observer: first_fulfilment
```

CHF 198 sits under the CHF 200 cap, it is one authorization, and the customer asked
to replace **one** pair. The observer said nothing.

This is a defect in the model, not in its implementation: "how many times has this
job been performed" was being measured in the wrong unit. Counting purchases is a
proxy for counting fulfilments, and proxies are exactly what an optimising attacker
attacks.

**Fix applied:** count *units of the job*, not purchases — the quantity of items
matching the job's anchor. Re-tested: `over_fulfilled`.

---

## A3 — Confuse the classifier with a compound instruction

**Idea.** Write a mandate containing both a one-shot job and a recurring one.

**Result: WEAKNESS CONFIRMED, accepted rather than fixed.**

| Instruction | Classified | Assessment |
| --- | --- | --- |
| "Replace my worn shoes **and** order our household groceries weekly." | RECURRING | the one-shot half is unprotected |
| "The agent **may buy** the monitor I chose." | STANDING | correct — an explicit open grant that names an item is still an open grant |
| "Buy one item. You **may buy** more later if needed." | STANDING | correct |

Precedence (standing > recurring > one-shot) resolves compounds toward the more
permissive reading, so a mixed mandate loses its one-shot protection.

**Not fixed, deliberately.** The failure mode is **silence** — the observer declines
to raise a concern it might have raised. That is exactly the behaviour of the
architecture without this module at all, so the compound case is never *worse* than
today. Resolving it properly requires clause-level parsing, which trades a large
amount of machinery and a new class of misparse for a case that does not appear in
the official data. Recorded as a known limitation.

---

## Verdict

| Attack | Outcome |
| --- | --- |
| A1 anchor dodging | model holds — evasion costs the attacker the policy check |
| A2 quantity evasion | **real defect**, fixed by counting units of the job |
| A3 compound instructions | real weakness, fails toward silence, accepted and documented |

The core claim survives. One counting rule was wrong and is now right. Audit 2
should assume the repaired version and look for what this audit's fix broke — a
fix that changes a counting rule is exactly the kind that introduces false
positives.
