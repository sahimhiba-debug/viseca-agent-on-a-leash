# Economic delegation — what the customer actually hands over

<!-- snapshot -->
> **SNAPSHOT — written 18 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

The mission was to find out what a customer delegates *economically* when they
confirm a mandate, without assuming the answer is "a CHF budget", and without
building a second mutable budget ledger.

**The answer is that they delegate a rate, and believe they delegated a total.**

> The official rule vocabulary has exactly two scopes, `purchase` and `period`, and
> `technical_details.md` closes the set: *"No extra rule fields are allowed."* A
> `purchase` rule bounds one purchase. A `period` rule bounds a rate. Neither bounds
> a total, and there is no third scope, no mandate expiry a customer can set, and no
> way to say how many times a job may be done.
>
> **No mandate expressible in the official rule format can bound total economic
> delegation — including the one that looks like it does.**

Classification of the economic envelope, against the options the mission set:
**B + C — a derived explanation, surfaced as a pre-confirmation disclosure.**
Explicitly **not A**: it is strictly dominated as a mechanism (§5). **D is not
available**: a new rule field is forbidden by the official contract.

The mechanism gap that *was* real is closed by extending fulfilment, not by adding
money. One mechanism change, one disclosure correction, two self-inflicted errors
found and fixed.

---

## 1. The measurement

`python scripts/run_economic_envelope.py` — reproducible, and it does not touch the
decision path.

For each mandate, take the highest-value purchase the official replay **already
allowed** (policy-compliant by construction, not by our judgement) and repeat it,
spacing purchases just outside the 60-minute similar-purchase window. The agent
never has to be clever, only patient.

| Mandate | What the customer wrote | Shape | Policy engine alone | With derived fulfilment |
| --- | --- | --- | ---: | ---: |
| SCEN0000 | *"Buy **one** ordinary grocery item for CHF 20 or less"* | one-shot | 8,616 × CHF 20 = **172,320** | 1 = **20** |
| SCEN0001 | *"each order ≤ CHF 120, any seven days ≤ CHF 300"* | recurring | 104 = **12,480** | 104 = **12,480** |
| SCEN0002 | *"Replace my worn road-running shoes"* | one-shot | 8,616 = **1,542,264** | 1 = **179** |
| SCEN0003 | *"The agent may buy clothing … up to CHF 250 per order"* | standing | 8,616 = **2,128,152** | 8,616 = **2,128,152** |
| SCEN0004 | *"Buy **the** 27-inch monitor **I chose** … for CHF 400 or less"* | one-shot | 8,616 = **3,445,538** | 1 = **400** |
| | | | **CHF 7,300,754** | **CHF 2,141,231** |

Four of the five mandates approved **every single attempt** — 8,616 of 8,616.

**Two qualifications, both load-bearing, neither a footnote.**

1. These are **authorizations, not losses**. The wallet has no concept of a credit
   limit, so what finally stops the agent is not in the wallet.

   > **CORRECTED by the falsification pass.** This section originally said that
   > neither the wallet *nor the official schema* models a credit limit. That was
   > wrong. `accounts.csv` carries `per_transaction_limit_chf` and
   > `monthly_limit_chf` for all 31 accounts, and every scenario card resolves to
   > one: **CHF 3,200–5,000 a month**. The search that "verified" the absence looked
   > for `credit_limit` and `available_balance` and never opened `accounts.csv`.
   >
   > The finding survives; its magnitude does not. SCEN0004's CHF 3,445,538 is what
   > the WALLET would approve; the account's CHF 3,200 monthly limit caps it near
   > **CHF 38,400 a year** — still ~96× the CHF 400 the customer thinks they
   > delegated, but not 8,600×. See `SECURITY_OBJECT_FALSIFICATION.md`.

   The part that stands: **the customer's stated policy contributes nothing to the
   bound.** What bounds it is an account limit they did not set as part of this
   delegation and were never shown.
2. A year is an **illustration of a rate**, not a prediction. There is no horizon to
   predict with, which is the other half of the same finding.

## 2. Rate is not total — and this project had it wrong

The sharpest result came from falsifying our own prior work. `policy_compiler.py`
and `test_unbounded_policy_disclosure.py` both asserted that SCEN0001's rolling cap
left the agent *"blocked and stays blocked"*.

It does not. **The window rolls.**

```
week  0: 2 approved = CHF 240      week  6: 2 approved = CHF 240
week  1: 2 approved = CHF 240      ...
week  2: 2 approved = CHF 240      week 11: 2 approved = CHF 240
```

The earlier claim came from a 50-purchase probe that never advanced simulated time
past a single window. Steady state is CHF 240 per 7 days, indefinitely — and the
customer's own stated ceiling of CHF 300/week is **CHF 15,600 a year**.

The disclosure then compounded the error. It told the customer:

> ~~"Consider adding a total, such as *no more than CHF X across any 7 days*."~~

A rolling window **is the rate**. The advice named the thing the customer wanted and
handed them a construct that does not provide it — which is worse than silence,
because they stop looking. Both are now corrected and pinned by
`test_no_disclosure_advises_a_construct_that_does_not_bound_the_total`.

## 3. Are "transaction permitted" and "within what was delegated" the same question?

No, and the gap between them is the whole subject.

| | Asks | Bounded by | Official coverage |
| --- | --- | --- | --- |
| **Transaction permission** | is *this* purchase allowed? | the stated rules | every mandate |
| **Job fulfilment** | has this job already been done? | nothing in the vocabulary | 0 of 5 — derived by us |
| **Economic delegation** | is the total still what they meant? | rate × horizon | **0 of 5 — inexpressible** |

Every one of the 8,616 purchases above passes the first question. The wallet is
working correctly in every row of that table.

## 4. The mechanism gap that was real

`fulfilment_state` stayed silent whenever the mandate named no specific product,
on the reasoning that *"a category is not specific enough — counting against it
would make a basket of two different groceries look like the job done twice."*

That reasoning is sound about **units within one basket**. It had been wrongly
extended to **repetition across baskets**, and SCEN0000 is what the gap was worth:
*"buy **one** ordinary grocery item"* → **8,616 purchases, CHF 172,320**, unquestioned.

The fix counts **purchases, not units**, so it makes no claim about what belongs in
a single grocery basket — only that the job was already done once.

- **Cost on the official data: zero.** SCEN0000 has one approved purchase, so there
  is nothing to question. The differential is unchanged at 6 disagreements /
  CHF 1,787.40; the replay is unchanged at 19/2/24.
- **Value: CHF 172,320** of previously silent exposure, and it is the reason three
  one-shot mandates now collapse to exactly what was delegated (CHF 20 / 179 / 400).

## 5. Why a CHF envelope is not a security mechanism

The mission's constraint was explicit: *if a CHF envelope catches no attack that
fulfilment already catches, do not build it as a security mechanism.* It does not,
and it is strictly dominated:

| Attack | Derived CHF envelope | Derived fulfilment |
| --- | --- | --- |
| SCEN0004 repetition, 5 × monitor | catches (cap × 1 exceeded) | catches |
| SCEN0000 repetition, anchorless | catches | **catches (§4)** |
| **2 monitors, qty=2, CHF 398, cap CHF 400** | **MISSES — inside the money bound** | **catches — outside the job** |
| SCEN0001 recurring, CHF 15,600/yr | nothing to compare against | correctly silent |
| SCEN0003 standing | nothing to compare against | correctly silent |

The deeper reason it cannot be a mechanism: **to enforce a total you need a total,
and no official mandate states one.** The total is the missing quantity, not an
available one. An envelope built by inferring `cap × 1` for one-shot mandates is
just fulfilment counting denominated in francs — and the qty=2 row shows that
denomination is strictly weaker.

So money is the right **unit to explain in** and the wrong **thing to check**.

## 6. Audits

**Audit 1 — attack the change.** Found two things.

- **Fixed.** `"Buy one of each item on my shopping list"` classified as one-shot.
  "one of each" is a *distributive* quantity — how many of each thing, over a list
  whose length is not one. While anchorless mandates were silent this was free;
  once they count purchases it would interrupt a customer eight times for a
  nine-item list, and a control that cries wolf eight times trains them to dismiss
  the one interruption that matters. `"one of each|every"` and `"one per"` are now
  excluded.
- **Not fixed, pinned instead.** A first purchase that is approved and later
  cancelled makes a legitimate retry look like a repeat. Fixing it needs
  `related_authorization_id` on the authoritative `StoredDecision`, and this pass
  declined to widen the security core the previous pass had just shrunk. The verdict
  only *asks*, the customer can answer "the first one was cancelled", and the
  measured cost on official data is **zero rows** — `related_authorization_status`
  appears once, as `"declined"`, and a declined purchase never enters the count.
  `test_a_cancelled_first_purchase_is_a_known_blind_spot`.

**Audit 2 — attack the numbers.** The CHF 3.4M headline survives only with the
credit-limit qualification in §1, which is now written into the script's own
docstring rather than left to the reader. The 61-minute spacing is not a strawman:
the 60-minute window is explicit in `state._DUPLICATE_WINDOW`, and waiting is
available to any agent. The "per year" framing is an extrapolation of a rate and is
labelled as one everywhere it appears.

## 7. What the customer now sees before confirming

Disclosure only — `open_questions` create no rule and are read by no evaluation, so
this cannot move a decision.

> **SCEN0001** — *Your CHF 300 limit applies to each rolling 7-day window, so it
> paces spending rather than capping it: the window re-opens and the agent may spend
> up to that amount again, indefinitely. At that rate the delegation is worth about
> **CHF 15,600 a year**. There is no way to set an overall total or an end date, so
> if that figure is more than you intend to delegate, revoke or tighten this mandate
> when the job is done.*

> **SCEN0000/2/3/4** — *Your CHF 400 limit applies to each individual purchase, not
> to the total. The agent may make any number of purchases at that limit, so this
> mandate does not bound what you are delegating overall. Adding a rolling weekly
> limit would slow that down but would still not set a total — there is no way to
> state one. Revoke the mandate when the job is done.*

**The minimum a customer needs, and where it comes from:**

| Fact | Source | Available? |
| --- | --- | --- |
| ceiling per purchase | the mandate | ✅ authoritative |
| rate, if stated | the mandate | ✅ authoritative |
| is the job repeatable | derived from the instruction's shape | ✅ derived |
| performances so far | derived from the decision ledger | ✅ derived |
| **horizon** | — | ❌ **inexpressible** |
| **total delegated** | rate × horizon | ❌ **therefore inexpressible** |

Four of six are derivable from records we already hold authoritatively. The two that
are not are the two that determine the total — so the honest disclosure names the
rate, and tells the customer that revocation is the only instrument they have.

## 8. Claims, and their safe wording

| Claim | Evidence | Safe wording |
| --- | --- | --- |
| No official mandate bounds total delegation | the schema table + *"No extra rule fields are allowed"* | "The rule format can express a limit per purchase and a limit per rolling window. It cannot express a total or an end date." |
| A rolling cap is a rate | 12-week measurement | "The window re-opens. CHF 300 a week is CHF 15,600 a year." |
| 4 of 5 mandates approved every attempt | `run_economic_envelope.py` | "Four of the five mandates approved every one of 8,616 policy-compliant repeat purchases." |
| Fulfilment removes CHF 5.16M of silence | same script, both columns | "Deriving fulfilment collapses three one-shot mandates to exactly what was delegated." |
| We corrected our own error | git history + tests | "Our earlier disclosure told customers a rolling window was a total. It isn't, and we fixed it." |

**Must not say:** "we cap total spending" (we cannot — no total exists); "the agent
could steal CHF 3.4M" (those are authorizations the wallet would approve; the
account's own monthly limit caps the year near CHF 38,400);
"this blocks the attack" (fulfilment only ever asks); "we bound the delegation"
(only the customer's revocation does).

## 9. Verification

534 tests · official replay **45 / 19 allow / 2 review / 24 block** (unchanged) ·
corpus **133/133** · legacy matrix **17/17** · fulfilment differential **6
disagreements / CHF 1,787.40** (unchanged) · demo scenario OK · `fulfillment` still
absent from `decision_engine`, `rules` and `facts` · `main` untouched.

## 10. The result

Asked what the customer delegates economically, the honest answer is not a number.

**They delegate a rate, and no way to say when it stops.** The per-purchase cap they
wrote down — the number they think is their protection — bounds a single purchase
and nothing else. The rolling cap, which is the strongest control the official
vocabulary offers, converts "unbounded and immediate" into "unbounded but paced".
After the wallet has done everything a wallet can do, CHF 2,141,231 of the original
CHF 7,300,754 remains, and **not one franc of it is a rule violation.**

That residue is the delegation. The only instrument the customer has against it is
revocation — so the one thing the wallet owes them is to say so *before* they
confirm, in francs, without pretending a total is available.

The mission asked us not to build a CHF counter. The better reason not to build one
turned out to be that **there is nothing to count against.**
