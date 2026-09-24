# Differentiator proof — two verdicts from one pass

## What is the mechanism?

Every check the wallet runs is tagged with the **authority it comes from**:

- `source="customer"` — a rule the customer wrote in their own instruction
- `source="safety"` — a control-layer integrity check they never opted into
  (FX/amount arithmetic, platform authority and card status, run binding,
  similar-purchase detection)

One evaluation pass therefore yields **two verdicts**, not one:

```
policy_verdict    what the customer's own rules concluded
security_verdict  what the wallet's integrity checks concluded
```

## Why does it matter?

A single-verdict engine can only say *permitted* or *not*. It cannot represent:

> **"Every rule you wrote was satisfied. I stopped this anyway."**

That is the honest description of a step-up caused by something the customer never
asked about. Told only "declined", a customer cannot tell whether to change their
rules or to distrust the purchase. **The remedy is completely different.**

## What security invariant does it enforce?

**None — and that is deliberate and tested.** The split is *explanatory*. `_decide()`
reads rule **outcomes** and never their `source`.

The invariant is the negative one:

> Re-tagging every evaluation must not change a single decision.

`test_the_two_verdicts_are_explanatory_and_cannot_change_a_decision` monkeypatches
`_decide` to swap every `customer` tag for `safety` and back, re-runs all 45 official
events, and asserts the counts are identical. If a tag could alter a decision, the
replay would move.

## Where is it enforced?

`decision_engine.py` — every `RuleEvaluation` is constructed with its `source`. The
customer's compiled rules default to `customer`; the always-on checks pass
`source="safety"` explicitly. The API reconstructs the split for a decision read back
from the ledger (`_verdict_split`). **The UI renders it and computes nothing.**

## What is the authoritative source?

The same `RuleEvaluation` list that produces the decision. There is no second record,
no separate classifier, and nothing persisted that could drift.

## What attack does it stop?

**By itself, none** — and we say so rather than dressing it up. The attack it *exposes*
is one the wallet already stops: an agent that satisfies every stated rule and is
escalated anyway.

`tests/security/test_verdict_split.py::test_a_safety_check_alone_can_escalate_a_policy_clean_purchase`
constructs it: a purchase inside the customer's limit, at a familiar merchant, for the
right item — repeated inside the similar-purchase window. `policy_verdict=allow`,
`security_verdict=review`.

## What would happen without it?

The decision would be identical. The customer would be told "needs your confirmation"
with a reason, and would have no way to know that **their own policy had nothing to do
with it**. The wallet would look arbitrary in exactly the case where it is being most
careful.

## How is it shown to the judge?

On the decision card, at phone width:

```
NEEDS YOU
CHF 289.00
PixelHarbor
1× 27-inch computer monitor

WHY THE WALLET IS ASKING
Every rule you wrote was satisfied. The wallet stopped this anyway:
 • This looks like an order you already placed. The wallet cannot
   tell whether you meant to order it twice.

┌─────────────────┬──────────────────┐
│ YOUR RULES      │ WALLET CHECKS    │
│ Satisfied       │ Not sure         │
└─────────────────┴──────────────────┘
```

Deterministic, from the official 45-event data, on SCEN0004. No scenario IDs in the
engine, no hidden state, no manual step.

## What is actually novel about our implementation?

- Both verdicts fall out of **one** evaluation pass, because authority is a property of
  every check rather than a separate classification step.
- The split **survives the ledger**: a decision read back after a restart or a step-up
  still reports which authority stopped it.
- The customer is shown it, in their own language.
- It is proven **explanatory** by a mutation test rather than asserted.

## What is NOT novel

- **The concept is standard industry practice.** Card networks and EMVCo already separate
  a limit decline from a fraud/risk decline with distinct reason codes. 3-D Secure has
  risk-driven step-up.
- **Google AP2** separates Intent, Cart and Payment mandates — a related separation, but
  of mandate types, not verdict provenance.
- **Visa TAP / Mastercard Agentic Tokens** authenticate the agent; we do not, and the
  challenge explicitly excludes agent identity.

**We do not claim this is an industry first.** We claim our implementation of it.

## Limitations

1. **It changes no decision.** If you remove it, the wallet behaves identically.
2. **The split is reconstructed from reason codes on the refetch path**, using a fixed set
   of safety field names. A new safety check must be added to that set or it will be
   attributed to the customer. The fresh evaluation path has no such duplication.
3. **It occurs once in 45 official events.** Genuinely rare in the provided data — the
   demo depends on that one case, and we construct a second in the tests rather than
   pretending the corpus is rich in them.
4. **"Wallet checks: not sure" is not a risk score.** It means one integrity check could
   not establish a fact, nothing more.
