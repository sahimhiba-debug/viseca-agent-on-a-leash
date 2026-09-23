# Here is what you authorised — and here is how much of it is real.

Two claims, and the second is the one nobody else will make.

> **A policy is not a list of rules. It is a set of purchases.**
> **And the set is drawn over facts — some of which the party being judged writes.**

The first makes a delegation countable. The second makes it honest. A wallet that
shows you the set without telling you which parts of its boundary are *enforced* and
which are merely *promised* has not told you what you authorised.

---

## What each rule is worth

*"Order our household groceries at or below CHF 120 from a shop I have used before,
only if the order is returnable within 14 days."* Four rules, on one screen, looking
equally solid:

```
●  billing amount chf    the agent cannot affect this
●  familiar              the agent cannot affect this
◐  category              the agent says this; the catalogue can refuse it
○  return window days    the seller says this; nothing can confirm it
```

> *1 of your 4 rules is checked against something the seller writes. Nothing
> independent can confirm it — a seller who states what you asked for satisfies
> that rule.*

**Measured, not asserted.** A violating purchase goes through the real engine, then is
talked into compliance **without changing the goods, the shop, the price or the
moment**. Only the description moves.

| | facts | |
| --- | --- | --- |
| **bound** | `merchant.familiar`, `session.integrity_risk`, `authorization.billing_amount_chf`, `authorization.timestamp` | the agent cannot author them |
| **refutable** | `merchant.category`, `item.category`, `item.unrequested_present` | it can, and official reference data refuses a mismatch |
| **advisory** | `item.name_contains`, `item.size`, `order.return_window_days` | it can, and nothing can contradict it |

**Two of those rows are corrections, and neither was found by the audit that produced
the table.** `authorization.timestamp` was in no row at all — the table was built from
the fields `rules.py` evaluates, and no rule names the clock, though every rolling
ceiling is measured in it. `merchant.category` sat under **bound** on a declaration
that read *"loaded from reference data, never from the proposal"*: the event
*builders* do that, and the engine read it straight out of the event. A `transport`
merchant relabelled `groceries` was **allowed** on a groceries-only mandate, with
`merchants.csv` open in the same process saying otherwise.

The probe agreed with the false declaration, because it attacked that fact by swapping
the merchant *id* — which changes the shop, and therefore the purchase — and never
relabelled the category of the **same** shop. *A test written from the same
misunderstanding as the code will confirm the code.* Both corrections came from sweeps
that do not know what the table says: `research/substitution.py` restates every field
of every official event with a value that field really takes elsewhere.

The clause about the purchase is what makes the criterion mean anything. The agent
writes `billing_amount_chf` too, and writing a smaller number *does* turn a BLOCK into
an ALLOW — for a smaller charge, because the number it names is the number taken. The
purchase changed. **Writing a fact is not forging it; forging it is getting the same
thing on better terms.**

`research/forgeable_facts.py` attacks every one of the nine declarations and fails the
build when a class does not survive. An anti-rot test requires each field `rules.py`
evaluates to carry both a declaration and a probe.

**This weakens our own apparent strength on purpose.** Three of nine rules are
promises. The limit was already disclosed — *"a plausible claim beats every realistic
threshold"* — at the bottom of a document, to a customer who will never read it. It is
now on the screen at the moment they write the rule.

### How it was found

By attacking the set framing with one question: *what information does the authority
depend on that it does not itself own?* `item.category` is the rule doing the most
work in all five official scenarios, and it arrives **in the event**:

```
a gift card labelled `gift_card`          BLOCK on a grocery mandate
the same gift card labelled `groceries`   ALLOW, "matches the rules you set"
```

CHF 100 of stored value on a mandate that says groceries, by writing a different word.
**The first fix was wrong**, and that was the useful part: escalating an unknown item
id closes the obvious bypass and a competent attacker just stops supplying a real id —
a defence that creates a bypass. The catalogue now **refutes and never confirms**,
which is its honest scope, and the hole it leaves is the `advisory` row above rather
than something papered over.

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

Live, at **47 ms**, as they type — median of nine calls with a fresh instruction
each time. (It was documented as *18 ms*. That figure was never true of the shipped
panel, and nothing checked it; there is now a test that fails if it drifts again.)
That set — call it **A** — is what was delegated.

### …and `|A|` is not a number, it is an interval

Those counts are at the catalogue's *typical* prices. **The seller picks the price**,
and every item in `items.csv` carries a published `min`/`typical`/`max`:

```
at the cheapest published prices    476 / 595      <- what was actually handed over
at typical prices                   116 / 595      <- what the panel used to show
at the dearest                       16 / 595
```

All 56 official purchase lines sit inside their band, and their median price is **CHF
16.50 below typical** — so `typical` is not even the middle of what really happens. The
panel was understating the delegation **fourfold**, in the one direction that costs a
customer something.

The fix is not a bigger number, it is the right one. The sets **nest** — a basket
affordable at `max` is affordable at `min`, and no rule but the ceiling reads price —
so the union across the band *is* the count at the cheapest end, and one figure can
honestly carry it. That nesting is checked, not argued, because a minimum-spend or
discount-threshold rule would break it and `authorised_upper` would quietly stop
meaning what it says.

**This is the same thesis one level down.** `|A|` depends on facts with different
authors, and the price is the *seller's*. The provenance panel says which rules rest
on what the seller writes; this says what that costs, counted in purchases.

### Five faces of one object

| face | the question | measured |
| --- | --- | --- |
| **size** | how much rope? | `|A|` = 116 of 595, and **how many times**: with no rolling rule, *unlimited* |
| **read-back** | which of my words did that? | each word deleted and the sentence recompiled; a word that changed no rule provably cannot change `|A|` |
| **ambiguity** | is the boundary of A even determined? | *"up to CHF 250 per week"* — **470 of 595** purchases judged differently by two defensible readings; the cheapest witness is three orders of CHF 87 |
| **silence** | can anything step into A from outside? | yes: a seller who publishes *nothing* beats one who publishes bad terms. 52 of 6,864 erasure pairs, **0 under `decline`** |
| **containment** | can the agent make A bigger? | no. Four brains — including one ranking baskets by a hash — plus an exhaustive prober trying all 595 in five orders: **0 escapes** |

Those five say how big A is and where its edge falls. **What each rule is worth** says
how much of that edge is load-bearing — the same object, asked what it rests on.

The containment row is the architecture, stated as set containment and checked by
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

## Saying less must never buy more

The sharpest result here is not a bug. It is a **property, attacked exhaustively**:

> For every event `E` and every field `f` in it,
> `permissiveness(decide(E \ f)) ≤ permissiveness(decide(E))`.

Erasing information must never help the party being judged. **8,124 erasures** over
the 45 official events — every field path, set to `null` and again removed entirely,
because `d.get(k)` cannot tell those apart and `k in d` can.

It also asked a second question of every one of those erasures: **did the wallet
answer at all?** It owes one of three answers inside eight seconds, and the official
worker outline makes validating the event *ours* — *"read the envelope's run ID and
validate its data event."* On the first run, **1,916 of 8,124 erasures made the
engine raise** rather than decide. Chasing that to **0** turned up three separate
root causes, two of them re-occurrences of classes this repository had already
"fixed" in other places: an absent field dereferenced unconditionally, `sorted()`
asked to compare `None` with a string in two places, and `all([])` being vacuously
true so `min([])` ran on an empty basket.

Six violations remain, and they are **two different things wearing one coat**:

| | what it is | what its absence means |
| --- | --- | --- |
| **requirement** | evidence *for* authority — a return window, a category, a ceiling | must never satisfy. Erasing turns `fail` into `unknown`: the seller who states *2 days* is refused, the seller who states **nothing** is not |
| **flag** | evidence *against*, raised by the wallet itself — text written at the machine | absence is the ordinary case. Erasing necessarily helps, and that is **not a defect**: you cannot be flagged for text you did not write |

The distinction is invisible in a field list because **one channel carries both**:
`item_details` holds the return window *and* the injection, so a seller who deletes
it erases one of each. A violation is therefore classified by **which reason
disappeared**, not by which field moved.

```
uncertainty_policy = decline    0 requirement-polarity violations
uncertainty_policy = ask        5
uncertainty_policy = approve    5
```

**There is exactly one setting in which saying less provably never buys more, and it
is the strictest one.** That is not a bug the engine can fix. `unknown` is the honest
outcome when a fact is missing, and what happens to an unknown is decided by the
customer's single dial — *one answer to a question that is really per-rule*. A
customer cannot say *"ask me about unknowns, but never let silence rescue a
refusal."* That is a gap in the official mandate format, measured rather than
asserted, and disclosed with the witness that produces it.

### The same boundary, from three directions

Erasing a fact is one way to say less. Restating it is another, and combining two
changes that each buy nothing is a third — and a single-field sweep is **structurally
blind** to the last one. All three were run over the official pack:

| sweep | what it varies | `decline` | `ask` |
| --- | --- | --- | --- |
| **erasure** | 8,124 field removals (`null` and absent) | **0** | 4 |
| **substitution** | 6,415 restatements with values that field really takes | **0** | — |
| **composition** | 4,068 pairs, each half individually useless | **0** | 6 |

The composition row found something the others could not. `SCEN0002 AU0014` requires
a return window, and that fact has **two** independent sources — the order-level flag
and the seller's text. Silencing either alone is useless, because the other still
refutes it; silence **both** and the fact becomes `unknown`, which is more permissive
than refuted.

**Two sources for one fact look like redundancy and are not.** They help only while
the attacker can reach just one of them, and each source masks the value of silencing
the other — which is precisely why it took a pairwise sweep to see.

So the property this repository can actually claim is one sentence:

> **Under `decline`, no erasure, no restatement, and no pair of individually-useless
> changes ever buys the same purchase a better answer.**

*Not claimed:* a theorem about the schema. This is exhaustive over the official
corpus and the paths those events contain, and the composition sweep is scoped to
ten fields rather than all of them.

---

## What the thesis got wrong

`A` is a set of **purchases**. A rolling ceiling is not a property of any purchase —
so three mandates that differ only in their rate have *identical* acceptance sets:

```
CHF 300 per 7 days    CHF 3000 per 7 days    CHF 300 per 30 days
    |A| = 145              |A| = 145              |A| = 145
```

Comparing 43 declared paraphrase relations as sets turned up three kinds of meaning
that live outside `A` entirely:

| what | why `A` cannot see it |
| --- | --- |
| **the rate** | a ceiling across a window is not a property of a single purchase |
| **what will be asked** | `A` counts approvals, so `ask → decline` — the strictest edit available — moves nothing in it |
| **what could not be expressed** | *"buy **one** grocery item"* and *"buy **twenty**"* compile identically; the rule format has no quantity field |

So the delegation is five things, and the thesis named one:

> **(approved, asked, per-window ceiling, pace, what could not be expressed)**

All five are now measured, and the last is why the compiler emits
`unsupported_restrictions` — a distinction it cannot enforce is one it must at least
admit to, and that admission blocks automatic confirmation.

**Where the corpus disagrees with the wallet, it is usually the *world* that is
silent, not the compiler.** `"Decline when unsure"` really is stricter than `"ask
me"` — but no basket in the grocery enumeration is ever `unknown`, so nothing
observes it. That is 9 of the 10 disagreements. The tenth is the quantity case above.
Conflating the two would be a false accusation against the compiler, so they are
counted apart.

### What "when unsure" costs, in purchases

The most consequential setting in a mandate is the least legible — *what should I do
when I cannot tell?*, asked once, in the abstract, about facts the customer has not
met yet. Measured on a mandate whose return window nothing can confirm:

```
decline      0 approved     0 asked    595 refused
ask          0 approved   116 asked    479 refused
approve    116 approved     0 asked    479 refused
```

`decline` is the **only** setting in which saying less never buys the proposer more —
measured over 8,124 erasures. This is what that costs: 116 purchases the customer
cannot have without being asked again. A dial with a security property on one side
and a price on the other is a choice; shown as one number it is a guess.

---

## The engineering idea

**Absence is not a value.** Fourteen instances of one mistake, at fourteen boundaries:
*something was missing, and something present was quietly put in its place*
([`ABSENCE.md`](ABSENCE.md)).

It connects to the first idea directly: **thirteen of the fourteen were a place where
A was secretly bigger than it looked.** A default that approves is the only kind of
bug that is quiet, because nothing complains.

The fourteenth is the exception, and it is the worst by consequence: the same
substitution in its *thrown* shape. Two lines of one product, one stating a return
window and one silent, made a basket fingerprint compare `None` with an int —
`POST /api/agent/propose` answered **HTTP 500**, and the protocol gives the wallet
three answers within eight seconds of which that is none. The basket is legal and
composed entirely by the untrusted party. We do not claim to know whether the
platform fails open or closed on it; the claim is that the party the wallet exists
to constrain could stop it answering.

The thirteenth is where a defence this repository had already built was overstating
itself: the Delegate tab told the customer the catalogue could refuse their category
rule, while an item id the catalogue had never seen was waved through — so the agent
chose whether that promise was true, and **saying less beat saying something false**.

Four of them were found by reading the organizers' own material rather than by
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
* **Not a proof, and the first version of this bullet was wrong.** It said `|A|` was
  *"not an artefact of the bound"*, on a measurement that widened the enumeration from
  one line to six and found `|A|` steady at 116 from the third line onward. That is
  true, and it checked the one axis that happened to be stable. **Price is the axis
  that was not.** `items.csv` gives every item a `min`/`typical`/`max`; the panel
  enumerated at `typical`; the median band spans **1.8× the typical price**. So the
  claim "the panel is not understating the delegation" was false by a factor of four,
  and it was found by attacking our own number rather than by the check written to
  defend it. What remains bounded, and is stated on the panel: one shop, the official
  catalogue, and up to five lines.
* **Not adversarially complete.** The silence channel is open by design and cannot be
  closed per-rule, because the official mandate format has one uncertainty dial for a
  question that is per-rule. That is a gap in the format, disclosed with a witness.
* **Not fully enforceable, and it says so.** Three of the nine facts the rule engine
  reads are `advisory`: the seller is the only source, so a plausible claim satisfies
  the rule. This cannot be closed from inside the wallet — it needs a second source
  (a merchant feed, a returns API) that the challenge data does not contain. What is
  built is the *disclosure*, at the moment the rule is written.
* **Not user-tested.** The claim that a concrete purchase is easier to answer than a
  rule list is the thesis behind four panels and rests on no study.

---

## The numbers, all checkable

```
official replay      45 events · 17 allow / 4 ask / 24 block · byte-identical ×3
tests                1,749 passed · 5 reported skips
mutation             39 mutants applied · 39 killed · 0 survived
adversarial corpus   133 / 133 held
planning benchmark   11 / 11   (pre-registered baseline 5/11)
intent corpus        90% recognised · 0 silently lost · 0 misinterpreted
fact provenance      9 declared · 9 measured through the real engine · 0 mismatches
authorship audit     0 violations
research modules     6 · byte-identical across runs
```
