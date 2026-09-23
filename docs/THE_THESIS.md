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
| **bound** | `merchant.familiar`, `merchant.category`, `session.integrity_risk`, `authorization.billing_amount_chf` | the agent cannot author them |
| **refutable** | `item.category`, `item.unrequested_present` | it can, and the official catalogue refuses a mismatch |
| **advisory** | `item.name_contains`, `item.size`, `order.return_window_days` | it can, and nothing can contradict it |

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
* **Not a proof.** `|A| = 116` is a function of the enumeration's bound — one shop, up
  to five lines, the official catalogue. What carries meaning is how it **moves**.
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
tests                1,678 passed · 5 reported skips
mutation             39 mutants applied · 39 killed · 0 survived
adversarial corpus   133 / 133 held
planning benchmark   11 / 11   (pre-registered baseline 5/11)
intent corpus        90% recognised · 0 silently lost · 0 misinterpreted
fact provenance      9 declared · 9 measured through the real engine · 0 mismatches
authorship audit     0 violations
research modules     6 · byte-identical across runs
```
