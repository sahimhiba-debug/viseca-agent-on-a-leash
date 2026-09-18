# The architecture model

Derived from the code as it stands, not from intent.

---

## 1. The security object

**Corrected by the falsification pass.** This section used to name one object. A
security object is only fundamental relative to a SCOPE, and this delegation has
three — see `SECURITY_OBJECT_FALSIFICATION.md`:

| scope | object | bounds | status |
| --- | --- | --- | --- |
| an authorization | **the decision ledger** | money moves once, correctly, and stops on revocation | built |
| a mandate | **the derived job capability** | how many times the delegated job is performed | built |
| an account | account-scoped rolling spend | total francs | **not built** |

Protecting the ledger perfectly leaves 4 of the 5 official mandates economically
unbounded, so it is fundamental at the scope of an authorization and nowhere else.
The rest of this section describes that scope, which is where it does hold.

**The run's persisted decision ledger** — `RunState._decisions`, a map from
`authorization_id` to an immutable `StoredDecision`, checkpointed with the run.

Everything else at THIS scope is either *derived from it* or *enforced against it*:

| Thing | Status |
| --- | --- |
| `StoredDecision` | **authoritative.** Write-once per id (`record_decision` returns the existing entry rather than overwriting). Carries merchant, CHF amount, fingerprinted basket, simulated timestamp |
| `PaymentAuthority` lifecycle (`revoked`, `consumed_at`) | authoritative for execution, persisted, monotonic |
| `PaymentAuthority.merchant_id`, `amount_ceiling_chf`, `basket_fingerprint`, `policy_version` | **copies.** `charge()` enforces against `StoredDecision`, never against these |
| rolling spend | derived from the ledger |
| fulfilment | derived from the ledger (pure function) |
| drift, verdict split | derived, explanatory, cannot gate |

## 2. Minimum trusted security state

```
mandate snapshot   (fixed at run start, from the platform)
        +
decision ledger    (append-only per id, checkpointed)
        +
authority lifecycle (monotonic: issued → consumed | revoked)
```

That is the whole trusted computing base inside the wallet. Delete any one and a
guarantee falls; add anything else and it becomes a candidate for drift.

## 3. The governing discipline

> **Every security-relevant fact is either authoritative-and-immutable, or derived
> from something that is. Never a third thing that can drift.**

This is not a design preference. It is the generalisation of every vulnerability
this project found:

| | Parallel record | Drift |
| --- | --- | --- |
| V2 | payment authority | human-approved step-up minted none |
| V3 | payment authority | restart lost it |
| V8 / V10 | consumption flag | restart lost it |
| V13 / V14 | consumption flag | concurrent transition overwrote it |
| A8 | fulfilment tally | human-approved step-up never reached it |
| A12 | fulfilment tally | restart reset it |

Six instances. One mistake. The fix that finally worked was not better
synchronisation or more persistence — it was **removing the second record**.

## 4. What the compromised agent controls

| Controls | Does not control |
| --- | --- |
| which purchases to propose, in what order, how many | the decision ledger |
| all merchant free text | the mandate text (platform-supplied) |
| retries, replays, races, crashes | `authority_status`, `card_status`, `mandate.status`, `card_id`, `timestamp` |
| which purchases to route through human step-up | whether a fulfilment is recorded (derived, not declared) |

The last row is the one that matters most for fulfilment: **the agent never
declares completion.** The wallet derives it from its own records, which removes
the claim-of-fulfilment and evidence-manipulation attack classes by construction
rather than by checking for them.

## 5. Bounded and unbounded dimensions

A delegation is a multi-dimensional envelope. The wallet enforces exactly the
dimensions the customer expressed; every unexpressed dimension is unbounded.

| Dimension | Bounded by | Official coverage |
| --- | --- | --- |
| amount per transaction | the cap the customer stated | 4 of 5 mandates |
| rate of spend | a `scope="period"` rule | 1 of 5 |
| **total amount** | **nothing in the vocabulary** | **0 of 5** |
| **horizon / end date** | **nothing the customer can set** (the platform may expire a mandate; they cannot) | **0 of 5** |
| counterparty | merchant rules | 3 of 5 |
| product | item rules | 3 of 5 |
| **performances of the job** | **nothing in the vocabulary** | **0 of 5** |

The bold rows are the project's economic findings. None is a rule violation; all
are dimensions the customer never bounded and was never told about.

The `total amount` row was corrected by the economic-delegation pass, which had
previously been credited to the `scope="period"` rule. A rolling window bounds a
RATE: it re-opens, and CHF 300 a week is CHF 15,600 a year. Since `total` and
`horizon` are both inexpressible — `technical_details.md`: *"No extra rule fields
are allowed"* — total economic delegation cannot be bounded by any mandate written
in the official format. See `ECONOMIC_DELEGATION_RESEARCH.md`.

## 6. Derived economic exposure

For a one-shot mandate the total bound is derivable: one performance at the stated
cap.

| Mandate | Shape | Delegated | Authorized | Excess |
| --- | --- | ---: | ---: | ---: |
| SCEN0000 | one-shot | 20.00 | 20.00 | — |
| SCEN0002 | one-shot | 200.00 | 512.00 | **312.00** |
| SCEN0004 | one-shot | 400.00 | 1,729.40 | **1,329.40** |
| SCEN0001 | recurring | 300 / 7d | 387.50 over 10d | — (window, not excess) |
| SCEN0003 | standing | unbounded | 841.05 | — (correctly) |

**CHF 600 delegated across the two one-shot jobs; CHF 2,241.40 authorized.**

## 7. A candidate considered and rejected

Expressing the delegation as a derived CHF budget is a better *presentation* — it
speaks the customer's unit. It was tested as a possible *replacement* for
fulfilment counting and **does not subsume it**:

```
2 monitors, qty=2, CHF 398, cap CHF 400
  derived budget   -> within budget (MISSES)
  fulfilment count -> over_fulfilled
```

Two monitors for the price of one delegated monitor sit inside the money bound and
outside the job. So budget is adopted as the headline metric and **not** built as a
separate mechanism — it would be a second check earning nothing.
