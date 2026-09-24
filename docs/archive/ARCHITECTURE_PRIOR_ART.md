# Prior art — what is ours and what is not

Written before any novelty claim, so the claim can be narrowed to what survives.

---

## Not ours: one-off vs recurring mandates

Payments has distinguished single-use from standing authorization for decades:

- **SEPA direct debit** mandate types: one-off vs recurring, carried in the scheme
  message itself.
- **Card-on-file / stored credential** frameworks: a single transaction versus a
  credential retained for later, with distinct scheme indicators.
- **Google AP2** separates an *Intent Mandate* from a *Cart Mandate* — intent
  being what the user authorized, cart being a specific purchase.
- **OpenAI's Agentic Commerce Protocol / Delegated Payment**: a single restricted
  token, amount- and expiry-bound.
- **Mastercard Agentic Tokens**, **Visa Trusted Agent Protocol**: bind a credential
  to an agent and a consent scope.

The *concept* that a delegation can be single-use is standard. We did not invent it.

## Not ours: derived state over an immutable log

Event sourcing, CQRS read models, and "derive, don't duplicate" are standard
distributed-systems practice. Linear/affine types and capability *consumption* are
standard in capability-security literature (KeyKOS, E, object-capability systems).
The principle that a capability is consumed by use is decades old.

## Not ours: least privilege / POLA

That a delegation should bound every dimension rather than the ones someone
happened to mention is the principle of least authority. Old and well known.

---

## What appears to be ours, narrowly

1. **Deriving delegation *shape* from a natural-language mandate.** The official
   challenge gives the customer free text and a rule vocabulary with no way to say
   "once". Classifying one-shot / recurring / standing from the customer's own
   words, with the evidence phrase reported for review, is the specific step we
   have not found elsewhere in agentic-commerce work.

2. **The measured observation that the challenge's rule vocabulary contains exactly
   one consumable resource.** Rolling spend is consumable; everything else is a
   stateless predicate. That asymmetry is what makes repeat fulfilment invisible,
   and it is a property of this challenge's own schema.

3. **The empirical differential on official data**: 6 approved purchases worth
   CHF 1,787.40 that are repeat performances of a job described once, with zero
   false positives on the two legitimately repeatable mandates.

4. **Applying the derive-don't-duplicate discipline to agentic authorization
   specifically**, with six documented vulnerabilities as the evidence that the
   alternative fails in practice rather than in theory.

---

## The defensible pitch

> Payments already distinguishes one-off from recurring authorization. Agentic
> wallets built from a transaction-predicate vocabulary lose that distinction,
> because a natural-language mandate has no field for it. We derive it from the
> customer's words, and we derive fulfilment from the decision ledger rather than
> tracking it — which is what makes it survive restart, human approval and replay.

Not: *"we invented one-shot mandates."*
Not: *"we invented derived state."*
