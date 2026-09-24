# Product architecture

```
   CUSTOMER  (phone)
      │
      │  "Buy the 27-inch monitor I chose, for CHF 400 or less. Ask me when uncertain."
      ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  POLICY COMPILER            deterministic, no model          │
   │  natural language ──► hard_rules  +  open_questions          │
   └─────────────────────────────────────────────────────────────┘
      │  customer confirms  ──►  MANDATE          [AUTHORITATIVE]
      │                          tighten-only, never widened
      ▼
                                          SHOPPING AGENT
                                          (untrusted, may be
                                           fully compromised)
                                               │
                                               │ purchase proposal
                                               ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  WALLET CONTROL ENGINE          decision_engine.py           │
   │                                                              │
   │   run binding ─► platform status ─► idempotent replay        │
   │        ─► canonical facts ─► rule evaluation                 │
   │        ─► always-on safety (FX integrity, positive amount)   │
   │        ─► _decide():   fail > unknown > pass                 │
   └─────────────────────────────────────────────────────────────┘
      │                │                 │
      ▼                ▼                 ▼
   ALLOW           STEP_UP            BLOCK
                      │
                      │  the customer answers — this one purchase only
                      ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  DECISION LEDGER   RunState._decisions      [AUTHORITATIVE]  │
   │  write-once per authorization_id                             │
   │  carries: decision · CHF · merchant · basket fingerprint     │
   │           · execution lifecycle (issued/consumed/revoked)    │
   │  checkpointed as one JSON record per run                     │
   └─────────────────────────────────────────────────────────────┘
      │
      ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  EXECUTION BOUNDARY   MockPSP.charge()   — ONE enforcement   │
   │  merchant binding · amount ceiling · authority must exist    │
   │  · atomic compare-and-set consume · then charge              │
   └─────────────────────────────────────────────────────────────┘
      │
      ▼
   SIMULATED PSP                    AUDIT TIMELINE  ── projection of
   (ours; the Viseca API            DELEGATION VIEW      the ledger,
    has no payment step)                                 never a second record
```

**The shopping agent is not part of this system.** It proposes; it never decides. Every
arrow into the engine carries data the agent may have chosen or corrupted; every arrow
out is a decision the agent cannot influence.

## Three scopes, three bounds

A delegation is bounded only where an authoritative record exists at the same scope as
the bound.

| scope | bound | record | status |
| --- | --- | --- | --- |
| **authorization** | this purchase's amount, merchant, basket; money moves once | the decision ledger | built, enforced |
| **mandate** | how many times the delegated job may be performed | derived from the ledger | built, **not in the decision path**; holds within a run |
| **account** | `monthly_limit_chf` across cards and runs | — | **real, not enforceable** — no account-scoped counter exists in the official API |

## Trust boundaries

| input | trust | why |
| --- | --- | --- |
| `mandate.hard_rules` | **trusted** | the customer confirmed it; tighten-only by construction |
| `authority_status`, `card_status_at_attempt`, `mandate.status`, `card_id`, `timestamp` | **trusted** | platform-supplied, pre-checked upstream |
| `amount`, `currency`, `billing_amount_chf` | **verified** | recomputed against the published FX table |
| merchant free text (`item_details`) | **untrusted** | yields only three narrow derived facts, each of which can only narrow |
| which purchases, in what order, how many | **attacker-controlled** | the core threat: individually-permitted purchases composing into an unintended outcome |

## What the agent cannot do

It cannot write to the ledger, widen the mandate, choose its own decision, re-point an
approval at another merchant or amount, charge twice, charge after revocation, resurrect
a consumed authority by restarting, or turn merchant text into policy.

## What it can still do

Spend the full envelope the customer actually authorised — which for four of the five
official mandates is unbounded in total, because the official rule format cannot express
a total or an end date. That is not a defect in this wallet; it is the delegation, and
the product's job is to say so before the customer confirms.
