# Is the decision ledger the fundamental security object?

<!-- snapshot -->
> **SNAPSHOT — written 18 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

**No. It is the fundamental security object of *execution*, and this project
over-claimed it as the security object of *delegation*.**

That claim is not a change of mind. It is the result of measuring eight candidate
objects against criteria fixed before any of them was built, and it is reproducible:
`python scripts/run_security_object_falsification.py`.

> **The result in one line.** Delegation spans three scopes — an authorization, a
> mandate, an account — and **no single object can bound a quantity scoped larger
> than itself.** A run-scoped ledger cannot bound account-scoped exposure no matter
> how perfectly it is protected. The architectural error was never the choice of
> object; it was the belief that one object could be enough.

---

## 1. Pre-registered criteria

Fixed before the first prototype, so the outcome is forced by measurement:

| | Test | Decided by |
| --- | --- | --- |
| **F1** | Protect it perfectly — is the unintended economic outcome bounded? | the repetition attack |
| **F2** | Can it be computed from authoritative recorded facts at all? | the official corpus |
| **F3** | Does protecting it require escalating almost everything? | escalation rate on 45 events |
| **F4** | Is there an attack that ONLY this object catches? | the attack matrix |

Also fixed in advance: *if two survive, they are both fundamental and the
architecture must name both layers.* Three did.

## 2. The candidates

M1 transaction · M2 decision ledger *(this project's claim)* · M3 mandate ·
M4C capability in francs · M4N capability in performances · M5 job ·
M6 consent · M7 irreversible commitment · M8 account envelope

M4N was **deleted during the pass**: a 4,000-run randomized differential found zero
inputs on which it and M5 disagree. *"Job"* and *"capability whose unit is a
performance"* are one object — **the unit is the job.** That is a real result, and
it also removes the temptation to present two.

## 3. F1 — sufficiency

CHF a policy-compliant compromised agent extracts in 365 simulated days if the named
object were protected perfectly:

| object | SCEN0000 | 0001 | 0002 | 0003 | 0004 |
| --- | ---: | ---: | ---: | ---: | ---: |
| M1 transaction | UNBOUNDED | 12,480 | UNBOUNDED | UNBOUNDED | UNBOUNDED |
| **M2 ledger** | **UNBOUNDED** | **12,480** | **UNBOUNDED** | **UNBOUNDED** | **UNBOUNDED** |
| M3 mandate | UNBOUNDED | 12,480 | UNBOUNDED | UNBOUNDED | UNBOUNDED |
| M4C capability (CHF) | UNBOUNDED | 12,480 | UNBOUNDED | UNBOUNDED | UNBOUNDED |
| M5 job | 20 | 12,480 | 179 | **UNBOUNDED** | 400 |
| M6 consent | 0 | 0 | 0 | 0 | 0 |
| M7 irreversibility | UNBOUNDED | 12,480 | UNBOUNDED | UNBOUNDED | UNBOUNDED |
| **M8 account** | **4,500** | **12,480** | **4,833** | **3,952** | **3,199** |

**The ledger — the thing this project called its fundamental security object —
bounds nothing.** Protect it perfectly and four of five mandates remain unbounded.
It is not a weak object; it is an object of a different domain (§5).

M6 bounds everything at CHF 0 by escalating all 19 approved purchases. It fixes the
degenerate end of the scale and fails F3.

## 4. F2 and F3 — two candidates die outright

**M4C (francs) fails F2.** 45 of 45 events return `unknown`. It asks how much of the
delegated total remains, and no official mandate states a total, because `scope` is
`purchase` or `period` and `technical_details.md` closes the set. *The model everyone
reaches for first cannot be evaluated even once.*

**M6 (consent) fails F3.** 19 of 19 approved purchases escalated. Trivially safe,
trivially useless.

## 5. F4 — the attack matrix, and why it splits in two

| attack | M1 | M2 | M3 | M4C | M5 | M6 | M7 | M8 |
| --- | :-: | :-: | :-: | :-: | :-: | :-: | :-: | :-: |
| A1 repeat a one-shot job | · | · | · | · | **YES** | YES | · | · |
| A2 batch qty=2 under the cap | · | · | · | · | **YES** | YES | · | · |
| A3 repeat after a human step-up | · | · | · | · | **YES** | YES | · | · |
| A8 second FINAL-SALE purchase | · | · | · | · | · | YES | **YES** | · |
| A9 second RETURNABLE purchase *(control)* | · | · | · | · | · | YES | · | · |
| A10 repeated FINAL-SALE, STANDING mandate | · | · | · | · | · | YES | **YES** | · |
| A11 first FINAL-SALE purchase *(control)* | · | · | · | · | · | YES | · | · |

| execution attack | result |
| --- | --- |
| E1 charge the same authorization twice | held |
| E2 charge after revocation | held |
| E3 revoke, crash, restart, charge | held |
| E4 redirect the charge to another merchant | held |
| E5 charge above the approved amount | held |

**M5, M7 and M8 have no opinion on E1–E5 at all.** They assess a proposed purchase;
they cannot speak about whether money moves once. That is the measurement that
splits the question: *these objects are not competing. They govern different domains,
and the project had been treating one domain's answer as the whole answer.*

## 6. M7 — a candidate that looked strong and was subsumed

Irreversibility is the one axis on which every other model is blind: 8,616 returnable
purchases are an afternoon of administration, 8,616 final-sale purchases are a loss,
and francs, performances and ledger entries treat those sequences as identical.
A10 is uniquely M7's — a *standing* mandate, where repetition is legitimate but
unbounded unrecoverable commitment is not.

It still loses, on evidence:

- **Zero of the 19 approved purchases in the official corpus are irreversible.** Every
  one is `returnable` or `not stated`.
- The corpus contains exactly **one** final-sale authorization, AU0014, and it was
  already **blocked by an ordinary hard rule** the customer wrote:
  `order.return_window_days >= 14`.

So irreversibility is real, and it is already governed — by the rule engine, in the
existing vocabulary, whenever the customer states a return-window rule. M7 is a
**rule input, not a security object**. A10 remains constructible and unexercised;
that is worth knowing, not worth building on.

## 7. M8 — the bound that already existed, and that we had denied

`accounts.csv` carries `per_transaction_limit_chf` and `monthly_limit_chf` for all
31 accounts. Every scenario card resolves to one:

| | card | per-txn | monthly | ×12 | binding constraint |
| --- | --- | ---: | ---: | ---: | --- |
| SCEN0000/1 | CA0001 | 1,200 | 4,500 | 54,000 | the mandate cap |
| SCEN0002 | CA0011 | 1,400 | 5,000 | 60,000 | the mandate cap |
| SCEN0003 | CA0023 | 1,000 | 4,000 | 48,000 | the mandate cap |
| SCEN0004 | CA0039 | 900 | 3,200 | 38,400 | the mandate cap |

**This falsifies a claim this project committed one pass earlier** — that "neither
this wallet nor the official schema models a credit limit". The wallet does not; the
schema does. The search that "verified" the absence looked for `credit_limit` and
`available_balance` and never opened `accounts.csv`. Corrected in
`ECONOMIC_DELEGATION_RESEARCH.md` §1 and in `run_economic_envelope.py`.

The economic finding survives; its magnitude does not. SCEN0004's **CHF 3,445,538** is
what the *wallet* would approve; the account's monthly limit caps the year near
**CHF 38,400** — still ~96× the CHF 400 the customer believes they delegated, but not
8,600×.

`data_dictionary.md` calls these *"account attributes carried on the row for
context"* and tells the control layer to *"aggregate `billing_amount_chf` over
approved rows yourself with the window your control layer needs"* — so this is not an
invented mechanism. It is one the data anticipates and the wallet never built.

**Then M8 was attacked, and the implementation lost three times:**

1. **The per-transaction limit never binds.** The customer's own cap (CHF 20–400) is
   always below the account's (CHF 900–1,400). Half the envelope is dead weight.
2. **A calendar month is not a rolling window.** Spend the limit on 31 January and
   again on 1 February: **CHF 8,800 against a CHF 4,500 limit, in two days.**
3. **Three of five accounts carry two cards.** `RunState` is scoped to one run and one
   card; the bound is scoped to an account. Two mandates on two cards of one account
   each believe they have the whole limit.

The **bound** is real, authoritative and unforgeable by the agent. This **reading** of
it is not, and a correct one needs account-scoped rolling state that `RunState` cannot
express. That is not a bug to patch — it is the scope mismatch that is the result.

## 8. What survives

| domain | object | scoped to | bounds | evidence |
| --- | --- | --- | --- | --- |
| **Execution integrity** | the decision ledger | one authorization | money moves once, to the right merchant, for the right amount, and stops on revocation | E1–E5 held; nothing else speaks here |
| **Delegation scope** | the job capability | one mandate | how many times the delegated job is performed | A1–A3; 6 questions / CHF 1,787.40 on the corpus, 0 false positives |
| **Loss exposure** | the account envelope | one account, over time | total francs | the only object bounding a standing mandate (F1) |

Non-overlapping, and proven so: no attack caught by one is caught by another, except
by the degenerate M6.

**The decision rule fixed in advance said that if two survived, both are fundamental
and the architecture must name both layers.** Three survived, and the third is one we
do not currently implement.

## 9. The defensible architecture

Not "the ledger is the security object", which the F1 table refutes. Instead:

> **A delegation is bounded only where an authoritative record exists at the same
> scope as the bound.** Three scopes, three records. We hold two of them.
>
> | scope | record | status |
> | --- | --- | --- |
> | authorization | the decision ledger | **built, attacked, holds** |
> | mandate | the derived job capability | **built, attacked, holds** |
> | account | account-scoped rolling spend | **not built** — the data exists, the state abstraction does not |

This is defensible by falsification rather than preference because every alternative
was measured and failed for a stated reason: M1 and M3 catch nothing uniquely, M4C
cannot be computed, M4N is M5, M6 is degenerate, M7 is a rule input, and M2 alone
leaves four of five mandates unbounded.

## 10. What this pass did NOT do

It did not build the account envelope. Three reasons, in order of weight:

1. **The correct version is not a feature, it is a scope change.** It needs spend
   aggregated per account over a rolling window, crossing runs and cards — new
   authoritative state, which is exactly what the minimisation pass spent its effort
   removing. Adding it on the strength of one pass's measurement would be the
   feature-factory move this project has repeatedly refused.
2. **Whether the issuer already enforces it is unknown.** The pack says these are
   attributes "for context" and does not say the platform enforces them. If it does,
   a wallet-side copy protects nothing and only duplicates a control that already
   binds.
3. **The wrong version is worse than none.** The one built here was defeated three
   times in an hour, and a limit that reports "within" while CHF 8,800 leaves against
   a CHF 4,500 ceiling is an assurance the customer would be right to resent.

What it did do: name the scope, measure the bound, correct the false claim about it,
and pin all three in tests.

## 11. Claims, and their safe wording

| Claim | Evidence | Safe wording |
| --- | --- | --- |
| The ledger is not the object of delegation | F1: 4 of 5 unbounded | "Our ledger guarantees money moves once and correctly. It says nothing about how many times." |
| Three objects, three scopes | the attack matrix | "Delegation spans an authorization, a mandate and an account. Each needs its own record." |
| The schema carries a total bound | `accounts.csv`, 31 rows | "A total limit does exist — on the account, not the mandate, and the customer never chose it for this delegation." |
| We corrected our own error | the diff | "We previously said no credit limit existed in the schema. It does; we had not looked in the right file." |
| M4C cannot be computed | 45/45 unknown | "A franc budget cannot be evaluated even once, because no mandate states a total." |

**Must not say:** "we bound total exposure" (we do not — the account does, and we do
not read it); "the account limit protects the customer" (unverified whether the
platform enforces it); "irreversibility is our security model" (it is a rule input,
and the corpus exercises it once); "three layers are implemented" (two are).

## 12. Verification

547 tests · official replay **45 / 19 allow / 2 review / 24 block** (unchanged) ·
corpus 133/133 · legacy matrix 17/17 · fulfilment differential 6 / CHF 1,787.40 ·
`security_object` absent from `decision_engine`, `rules` and `facts` (asserted by
test) · `main` untouched.

## 13. Honest closing

The pass was asked whether the fundamental security object had been correctly
identified. It had not — but the error was subtler than picking the wrong thing.

The ledger is genuinely fundamental, and everything previously proved about it still
holds. What was wrong was the word *the*. **A security object is only fundamental
relative to a scope, and this delegation has three.** The ledger is fundamental at
the scope of an authorization, which is why protecting it perfectly still leaves a
compromised agent free to repeat a finished job several thousand times.

The most uncomfortable finding is the smallest: a total spending bound was sitting in
`accounts.csv` the whole time, and the previous pass asserted its absence after a
grep that never opened the file. The measurement that would have caught it — open the
data, not the prose — took under a minute.
