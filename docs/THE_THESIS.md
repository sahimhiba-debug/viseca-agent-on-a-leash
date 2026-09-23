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

Live, at 18 ms, as they type. That set — call it **A** — is what was delegated.

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

*Not claimed:* a theorem about the schema. This is exhaustive over the official
corpus and the paths those events contain.

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
* **Not a proof** — but not an artefact of the bound either, and that was measured
  rather than assumed. Widening the enumeration from one line to six grows the world
  from 35 baskets to 630 and leaves `|A|` at **116 from the third line onward**:
  every extra line only adds cost, and the CHF 120 cap bites first. So the panel is
  not understating the delegation. What it *is* bounded by is one shop and the
  official catalogue, and the convergence argument holds only for mandates that cap
  the amount — with no cap, `|A|` would grow with the bound and the number should be
  read as a lower bound.
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
tests                1,727 passed · 5 reported skips
mutation             39 mutants applied · 39 killed · 0 survived
adversarial corpus   133 / 133 held
planning benchmark   11 / 11   (pre-registered baseline 5/11)
intent corpus        90% recognised · 0 silently lost · 0 misinterpreted
fact provenance      9 declared · 9 measured through the real engine · 0 mismatches
authorship audit     0 violations
research modules     6 · byte-identical across runs
```
