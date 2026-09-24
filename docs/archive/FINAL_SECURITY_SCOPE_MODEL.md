# The security scope model

> **A delegation is bounded only where an authoritative record exists at the same
> scope as the bound — and the scope of a bound is set by its authoritative
> definition, not by where the customer wrote it down.**

The second clause is new in this pass and was forced by a counterexample (§5).

---

## 1. The scopes, with the evidence that each is real

A scope counts only if it carries a **bound**. An identity is not a scope.

| scope | bound it carries | authoritative source | enforced by | status |
| --- | --- | --- | --- | --- |
| **authorization** | this purchase's amount, merchant, basket; money moves once | the decision ledger (`RunState._decisions`) | `MockPSP.charge()` | **built, holds** |
| **mandate** | how many times the delegated job may be performed | the customer's instruction + the decision ledger | derived `fulfilment_state` | **built, holds within a run only** (§4) |
| **account** | `monthly_limit_chf` across cards and runs | `accounts.csv` | — | **real, NOT enforceable** (§3) |

## 2. Candidate scopes examined and rejected

| candidate | why it is not a security scope | evidence |
| --- | --- | --- |
| **customer** | carries no bound at all — persona text only (`home_region`, `budget_style`, `travel_pattern`) | `customers.csv` has zero limit columns |
| **agent identity** | excluded by the challenge on purpose | *"The agent rows do not have `agent_id` … the challenge is about controlling delegated spending, not identifying a particular fictional AI provider."* |
| **authority** | real and time-bounded (`valid_from`/`valid_until`), but the platform pre-checks it and the pack says it is not ours | *"`scenario_authorities.csv` contains fixture customer/card authority identities and lifecycle dates only; **it is not a participant policy**."* Plus: `authority_status` is `active` throughout because every attempt has already passed the platform's pre-check. |
| **card** | its facts (`online_enabled`, `international_enabled`, `expires_on`, `status`) are uniform across all four scenario cards, and the event already carries the time-correct `card_status_at_attempt`. Reading `cards.csv` would substitute a stale snapshot for a live fact. | all four scenario cards: `active`, online+international enabled, expiring 2029–2030 |
| **device** | `customer_device_id` and `approved_device_transaction_count_before` feed a *signal* (session integrity), not a bound | no device limit exists anywhere |
| **merchant relationship** | `approved_merchant_transaction_count_before` feeds `merchant.familiar`, a signal | no merchant-scoped bound |
| **time period** | not a scope of its own — a *window* over the run, per the pack's own definition (§5) | `context_basis="run_decisions_and_scenario_timestamps"` |

## 3. The account scope: real, and not ours to enforce

Answering the questions this pass was set, from the pack rather than from intuition:

| question | answer | source |
| --- | --- | --- |
| Is it in the data? | yes, all 31 accounts | `accounts.csv` |
| Per account? | yes | keyed by `account_id` |
| Spans cards? | **yes** — 10 accounts carry 2 cards | `cards.csv` |
| Spans runs? | yes, economically | an account outlives any run |
| Calendar or rolling? | **unstated** | the pack never says |
| Does the API expose account spend? | **no** — there is no account endpoint | the full endpoint table |
| Is there a platform period counter? | yes, but **run-scoped only** | `context.approved_spend_in_period_chf` |
| Could an event carry prior spend? | `spend_in_period_before_chf` exists and is **null on every row** | *"Period tracking is deliberately left to your control layer."* |
| Is it declared as policy? | **no** | *"account attributes carried on the row for context"* |

**Classification: CONTEXT ONLY.** The bound is real and economically binding. The
official API provides no account-scoped spend, no account-scoped counter, and no
account endpoint. A wallet-side implementation would be guessing at the window
semantics and reading only its own runs — which is precisely the implementation that
was built in the previous pass and defeated three times (calendar boundary: CHF 8,800
against a CHF 4,500 limit in two days).

**We therefore do not implement it and do not claim it.**

## 4. The one place the model is not satisfied

The job capability is **mandate-scoped**: *"buy **the** monitor **I chose**"* is one
job whatever run it happens in. Our authoritative record is **run-scoped** — one
`RunState`, one checkpoint per `run_id`.

```
same mandate, run 1:  AU10  allow   fulfilment=first_fulfilment
same mandate, run 2:  AU20  allow   fulfilment=first_fulfilment   <-- the same job, again
```

This is reachable, not theoretical: `PATCH /v1/mandates/{id}` is documented as
*"Preserves or tightens an active mandate **for later runs**"*. An earlier audit
recorded this as *"not reachable: one mandate per run"* — that was our own demo
convention (`api.py` compiles a fresh mandate per run), not a guarantee of the
challenge, and `live_worker.register_run` will accept one mandate for two `run_id`s.

**The model predicted this failure.** A mandate-scoped bound enforced from run-scoped
state is exactly what T1 says cannot work. Pinned by
`test_the_one_shot_job_does_NOT_hold_ACROSS_runs`.

## 5. T1, sharpened by a counterexample

The rolling-period cap is written by the customer **in the mandate** and enforced by
us **from run state**. That looks like the same violation as §4, and is not:

> *"The live counter the platform maintains is `context.approved_spend_in_period_chf`,
> **recomputed from the decisions actually taken in the run**, as declared by
> `runtime.context_basis="run_decisions_and_scenario_timestamps"`."*

The platform **defines** the period as run-scoped. So the bound is not mandate-scoped
after all, and our run-scoped state is the right scope. Verified: our counter matches
that definition on all 45 official events, including the rule that a stepped-up
authorization stays out of approved spend until resolved.

**So T1 survives, in a sharper form: the scope of a bound is decided by where its
authoritative definition places it, not by where the customer wrote it.** Getting this
backwards would have made us "fix" a correct implementation.

## 6. Authoritative vs derived — the complete table

| fact | classification | scope | source |
| --- | --- | --- | --- |
| `authorization_id`, `card_id`, `mandate_id`, `timestamp` | **authoritative** | authorization | platform event |
| `authority_status`, `card_status_at_attempt` | **authoritative** | authorization | platform event (pre-checked) |
| `amount`, `currency`, `billing_amount_chf` | **authoritative, and cross-checked** | authorization | event + published FX table |
| `items[]`, `item_details` | authoritative *as text*, untrusted *as claims* | authorization | merchant, via the agent |
| stored decision (amount, merchant, basket key) | **authoritative** | authorization | ours, write-once |
| execution lifecycle (`revoked`, `consumed_at`) | **authoritative** | authorization | ours, monotonic |
| `mandate.hard_rules`, `status` | **authoritative** | mandate | platform, tighten-only |
| rolling period spend | **derived** | run *(= period, by definition)* | the ledger |
| fulfilment / job capability | **derived** | mandate *(recorded only at run scope — §4)* | the ledger |
| `merchant.familiar` | derived signal | card × merchant | history CSV |
| `session.integrity_risk` | derived signal | run × device | event + run history |
| `order_returnable`, return window, final sale | derived fact, **rule input** | authorization | `item_details` |
| `monthly_limit_chf`, `per_transaction_limit_chf` | **context only** | account | `accounts.csv` |
| `valid_from`/`valid_until` | **context only** — explicitly not participant policy | authority | `scenario_authorities.csv` |
| `spend_in_period_before_chf` | **unused** — null on every row | — | event |
| `customers.csv` columns | **explanatory only** | customer | persona text |
| `cards.csv` capability flags | **unused** — superseded by `card_status_at_attempt` | card | `cards.csv` |
| `approved_*_count_before`, `last_approved_at` | derived context | card | history CSV |

## 7. Invariants that survive

1. The decision ledger is write-once per `authorization_id`.
2. The execution lifecycle is monotonic: `issued → consumed | revoked`, both terminal, both persisted.
3. Execution validates against the ledger, at one point, re-read from live state, under an atomic compare-and-set.
4. No derived state gates an external side effect.
5. The agent never declares fulfilment; the wallet derives it.
6. A mandate can only be tightened, never widened.
7. `billing_amount_chf` is recomputed from `amount × fx_rates[currency]`, not trusted.
8. A stepped-up authorization does not enter approved spend until it is resolved.
9. **Within one run**, a one-shot job with an identifiable anchor is performed once.

Invariant 9 carries the scope qualifier that §4 forced onto it.
