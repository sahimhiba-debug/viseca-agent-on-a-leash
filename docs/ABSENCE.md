# Absence is not a value

Every vulnerability this project has found is the same mistake.

Not a similar mistake — the same one, at six different boundaries, in six different
vocabularies, found by six different methods over several campaigns. It took the
sixth to see it.

> **Something was missing, and something present was quietly put in its place.**

---

## The six

| # | where | what was absent | what filled the hole | how it was found |
| --- | --- | --- | --- | --- |
| 1 | the request schema | who is entitled to write this field | whoever sent it | the authorship audit, after six separate fixes |
| 2 | `customer_message` | which *kind* of approval this was | "matches the rules you set" | asking what an approval SAYS, which 1,480 tests never did |
| 3 | `rules.py` | evidence for an `item.*` rule | `pass` — vacuous truth over an empty basket | an adversarial audit |
| 4 | the seller's listing | a published return window | `UNKNOWN`, routed to `uncertainty_policy` | erasure monotonicity: 6,864 pairs, 52 violations |
| 5 | the customer's sentence | a phrase the compiler knows | no rule, and no trace of one | causal read-back: 20 of 20 ordinary phrasings lost |
| 6 | `/api/agent/propose` | the basket's merchant | `or "ME0001"` — a familiar shop | emptying every field of the event, one at a time |

Number 6 is worth reading twice. Three lines above the expression that did it sat a
comment saying exactly why it was wrong:

> *"Quietly re-attributing it to a default merchant would hand the engine a truthful
> evaluation of a false description — the same defect that let an earlier agent be
> 'approved' while holding goods from a shop the customer had excluded."*

The reasoning was correct, written down, and contradicted by the code beneath it.
That is how this class survives: not through ignorance, but because a default is
invisible at the site where it is taken.

---

## Why it is always the permissive direction

A default that blocks gets found on the first honest purchase. A default that
approves is found by nobody, because nothing complains. Selection pressure does the
rest: the defaults that survive are the ones that let things through.

So the class is not merely common. It is **the only kind of bug that is quiet**, and
quiet bugs are the ones that reach production.

---

## Withholding beats lying

Numbers 4, 5 and 6 are the same attack at three different boundaries, and in each
one the adversary is the party who controls whether the fact exists:

```
    a seller publishes a 5-day return window   ->  BLOCK
    a seller publishes nothing                 ->  REVIEW, or ALLOW

    an agent names a shop you have not used    ->  BLOCK
    an agent names no shop at all              ->  ALLOW        (fixed)

    a customer writes "return within 14 days"  ->  a rule
    a customer writes "send it back in 14 days" ->  nothing, silently  (now visible)
```

**A rule is only as strong as the adversary's ability to avoid producing the evidence
it needs.** If the party who chooses the evidence source is the party the rule
constrains, the rule is advisory. That is not a flaw in this engine; it is a property
of delegated authority, and the only honest responses are to close it where the
format allows, to show it where it cannot be closed, and to say which is which.

---

## The rule that follows

> **A missing fact must be represented as missing, and routed to whoever can supply
> it. Never filled in, never inferred, never thrown.**

The three failure modes, and the fix in each case:

| failing shape | what it looks like | what it must be |
| --- | --- | --- |
| **filled in** | `l.get("merchant") or "ME0001"` | a refusal that names the missing field |
| **inferred** | an empty basket satisfies "nothing unrequested" | `unknown`, routed to `uncertainty_policy` |
| **thrown** | `float(None)` out of the handler | a refusal that names the unreadable value |

The engine's three-valued outcome — `pass` / `fail` / **`unknown`** — is this rule
expressed in the type system. `unknown` is not "missing data". It is *the
representation of an unauthored fact*, and `uncertainty_policy` is the customer
pre-authoring what to do about one. Every fix to number 3 was the same edit: stop
answering a question we were not authorized to answer, and return `unknown` instead.

### The one absence that is a fact

A validator that refuses every empty value would pass every test above and destroy
the point. **A seller who publishes no return window is a real fact about a real
offer** — the customer must still be able to decide what to do about it. So
`return_days: null` is legal and reaches `uncertainty_policy`; `merchant: null` is
malformed and is refused. The difference is whether the absence is *about the world*
or *about the message*, and `_NULL_MEANS_UNSTATED` in `api.py` is exactly one field
long.

---

## How it is checked, not asserted

| check | scope | result |
| --- | --- | --- |
| `scripts/run_authorship_audit.py` | every caller-controlled field | 0 undeclared authors; fails the build otherwise |
| `research/silence_channel.py` part 1 | 6,864 (purchase, erasure) pairs | 52 violations, 0 under `decline` |
| `research/silence_channel.py` part 3 | every field `rules.py` evaluates, read from its source | no rule can be made to FAIL by silence |
| `research/silence_channel.py` part 4 | 657 field-emptying variants | exactly 2 fields help, both documented |
| ...and its own second-order attack | 15,763 PAIRS where neither field alone helped | 0 masked vacuities |
| `research/unconsumed_intent.py` | 20 ordinary phrasings + 33 well-formed sentences | 19/20 detected, 0 false positives |
| `tests/security/test_absent_fields_are_not_values.py` | the agent's own boundary | 17 assertions, including the absences that must stay legal |

---

## What this does not claim

* **It is not a proof.** Six instances and five sweeps over *this* engine. A seventh
  boundary may exist; every sweep is bounded by the fields it enumerates, and each
  one says so. The field sweep was first-order until it was attacked for being
  first-order — 15,763 pairs later it still holds, which is evidence and not a
  theorem. Nothing here rules out a third- or higher-order vacuity.
* **It does not close the seller channel.** `uncertainty_policy = decline` closes it
  completely and closes nothing else selectively, because the official mandate format
  has one uncertainty dial for a question that is per-rule. That is a gap in the
  format, disclosed with a witness rather than patched around.
* **It does not catch restriction-by-noun.** "Swiss shops preferred" restricts
  without a single closed-class word, and the read-back misses all five such cases in
  its own corpus.
* **`unknown` is not free.** Routing more facts to `unknown` moves work onto the
  customer, and a wallet that asks about everything is a wallet nobody reads. The
  witness panels exist to spend that budget where a purchase actually changes.
* **And the defence has a measured price.** On the official catalogue, **0 of 7**
  grocery items publish a return window, so `uncertainty_policy = decline` turns
  "only buy what I can send back" into an agent that buys nothing at all. The
  control — clothing, where 4 of 7 publish — completes the same errand under the
  same setting, for CHF 30 more. So the expensive thing is not declining; it is
  **requiring evidence nobody publishes**, and the wallet's job is to show the
  customer that before they confirm rather than to choose for them.
