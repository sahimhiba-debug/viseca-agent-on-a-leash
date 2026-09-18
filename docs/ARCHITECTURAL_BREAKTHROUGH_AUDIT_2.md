# Audit 2 — second independent campaign, against the repaired model

Starts from Audit 1's result. Its working hypothesis was that Audit 1's fix — which
changed *what gets counted* — would have introduced a false positive, because
tightening a counting rule usually does.

**Result: the hypothesis was correct. One false positive found and fixed. The core
claim survived both audits.**

---

## B1 — Did Audit 1's fix actually hold?

Re-ran the quantity evasion against the repaired model.

```
2 pairs in one authorization  ->  over_fulfilled       ✓ caught
```

Holds.

---

## B2 — What did the fix break? (the real finding)

**Idea.** Audit 1 made the observer count units in the basket. A basket can contain
legitimate *non-job* lines. So buy exactly one pair of shoes and one shoe-care kit.

**Result: FALSE POSITIVE CONFIRMED.**

```
event : [ "Road-running shoes" x1 , "Shoe care kit" x1 ]   CHF 180
units counted: 2  ->  over_fulfilled  ->  the customer is asked
```

The customer bought **one** pair of shoes and an accessory, and was told they had
bought the shoes twice.

This matters more than its severity suggests. The module's entire safety argument is
"its worst failure is one unnecessary confirmation prompt" — which is only tolerable
while those prompts are rare and correct. **An observer that cries wolf is one the
customer learns to dismiss**, and a dismissed control is worth less than no control,
because it creates false assurance.

**Fix applied:** count only items matching the job's *specific* anchor
(`item.name_contains`). A care kit does not contain "road-running", so it is not the
job. Re-tested: `first_fulfilment`.

**Second-order fix.** Chasing B2 exposed a deeper question: what if the customer
named no specific product at all? "Buy **one ordinary grocery item**" is one-shot by
phrasing, but "grocery item" is a *kind*, not a job — two different groceries in one
basket would have looked like the job done twice. The observer now returns
`not_applicable` when no distinguishing phrase exists, rather than counting against
a category. Silence beats guessing.

---

## B3 — Can the agent disable the observer by influencing the instruction?

The classifier reads `mandate.instruction`. In the live path that arrives in the
platform's mandate block, the same channel as `authority_status`, `card_id` and the
timestamp — so this is the existing platform-trust boundary, not a new one.

Worth stating plainly regardless: **the observer is only as good as the instruction
text it is given.** `"Replace my shoes whenever needed"` classifies as STANDING,
which is arguably the correct reading of that sentence, and an empty instruction
classifies as UNCLEAR and is never questioned.

No new trust assumption. No fix.

---

## B4 — Does a refunded or revoked first fulfilment un-finish the job?

No — there is no refund or cancellation model. After a fulfilment, a second purchase
is questioned even if the first was reversed.

**Fails toward asking the customer**, never toward silent approval. Documented as a
limitation, not a defect: the customer answers "yes, the first was returned" and
proceeds.

---

## B5 — Is fulfilment state per-run?

Yes. Two runs under the same mandate each get a fresh fulfilment budget, exactly
like spend and every other ledger in this system. Same scope, same boundary, same
caveat as everywhere else — stated rather than implied.

---

## Verdict

| Attack | Outcome |
| --- | --- |
| B1 re-test of Audit 1's fix | holds |
| B2 accessory line in the basket | **real false positive**, fixed by anchor-scoped counting |
| B2b category-only mandates | second-order defect, fixed by staying silent |
| B3 instruction influence | existing platform boundary, no new assumption |
| B4 refunds | limitation, fails toward asking |
| B5 per-run scope | same scope as every other ledger |

Two audits, two real defects, both in the *counting rule* rather than in the
central claim:

> *a one-shot mandate can be finished, and further performances of a finished job
> should be put to the customer.*

That claim was attacked from both directions — evasion (Audit 1) and false alarm
(Audit 2) — and is intact. The differential against the official data is unchanged
at 6 purchases and CHF 1,787.40, with zero false positives on the two official
mandates that are legitimately repeatable.

**Recommendation: adopt as a parallel observer and demo artefact. Do not gate
official decisions with it** — see the main document for why.
