# The CHF 62 experiment

**Four purchases. One amount. One shop. One card. Three different answers.**

The thesis artifact. Everything else in this repository exists to make this
credible; this is the thing itself.

```bash
python3 research/same_amount_experiment.py
```

---

## The argument it defeats

"A spending limit already does that."

The unspoken model behind that sentence is that a bad purchase is an **expensive**
purchase, so a well-set limit catches it. The cleanest refutation is to hold the
amount constant and vary only the intent.

## What is held constant — everything a card can see

| | |
| --- | --- |
| amount | **CHF 62.00 exactly**, every case |
| merchant | **ME0001 Alpine Basket**, every case |
| country | CH | 
| MCC | 5411, a grocer |
| card | CA0001 |
| time | every case is the **first decision of its own fresh session** |
| catalogue | every id, name and category from `data/official/items.csv`, every price inside its published band |

**On every input a card control can observe, all four are the same purchase.**

## The result

| purchase | card | wallet | why |
| --- | --- | --- | --- |
| exactly what was asked for | YES | **YES** | — |
| the same basket, seller silent on returns | YES | **ASK** | `order_terms` |
| a line the seller will not take back | YES | **NO** | `order_terms` |
| something the customer never asked for | YES | **NO** | `item` |

Rows 1 and 2 are the **identical basket** — same items, same prices, same shop,
same total. The only difference is what the seller said about returns. One is
approved; the other asks the customer.

A card says yes four times out of four, and it is not being careless: CHF 62 at a
Swiss grocer is, on the only evidence it has, an ordinary purchase.

## Every alternative explanation, eliminated

| confounder | how it is killed |
| --- | --- |
| **the amount explains it** | each refused basket is **re-judged against a mandate with every money rule deleted** — no ceiling, no window, nothing about money. Every refusal persists. |
| duplicate detection | each case is the first decision of its own fresh session; no verdict may cite `duplicate` |
| rolling-window state | same — a fresh session has an empty window |
| session ordering | **20 shuffled orderings**, identical results |
| previous decisions | nothing precedes any case |
| merchant / category coincidence | one shop, one MCC, one country, all four |
| hidden amount differences | exact equality asserted, not approximate |
| different card state | one card throughout |
| fabricated catalogue | every id, name, category and price band checked against the official CSVs |
| security, not policy | every refusal traces to a rule compiled from the **customer's own sentence** |
| UI-only verdicts | the page submits live; the generated file is grepped for verdict words |

The first row is the decisive one. If a refusal were secretly about the amount, it
would vanish when the money rules are removed. None does.

## Two cases held out, and why

Both are real refusals. Neither is in the headline.

**The rolling allowance.** A rolling window bounds a *sum of amounts* — and a card
with a periodic cap bounds one too. An earlier version used this as a fifth case
under the claim "none of these refusals is about the amount", which was false. The
test written to catch that missed it, because it grepped for the literal string
`amount` after the class had been renamed to `budget_window`. **A rename hid the
problem from the test written to find it.**

**The unfamiliar shop.** "A shop I have used before" is the most intuitive
constraint here and is genuinely inexpressible on a card. It is still not airtight
*as an isolated experiment*: in the official data card CA0001 has paid **every
Swiss grocer**, and the only grocer it has never paid — ME0005 Rhine Pantry — is in
**Germany**. A card with a country allow-list would refuse it too, for a reason
unrelated to intent. The dimension that cannot be held constant is the country, and
the cause is the shape of the official data, not a choice we made.

Removing them costs one row each and buys an argument with no way in.

## What this proves, exactly

That **an amount-only control cannot encode these intent constraints.**

Not that it prevents fraud. Not that it is universally better — it answers two
questions we cannot (spend this month, merchant country). Not that card controls
are badly designed. A card asks *how much, where, and what kind of shop*, and
answers those well.

> **A limit is a number. Intent is a sentence.**
> **You cannot enforce a sentence with a number.**
