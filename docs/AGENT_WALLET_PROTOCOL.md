# The agent/wallet protocol

Six objects. Each earns its place by carrying a boundary that would otherwise be a
convention. Nothing here is named for the sake of having a name.

---

## The one rule

> **Everything above the wallet may be wrong. Nothing above the wallet may decide.**

Every object below is classified by which side of that line it lives on.

## The objects

### 1. `Mission` — *what the customer wants, separate from any basket*

**Owner: customer. Above the line.**

The agent plans against the mission, not against the last basket it happened to
propose. Without it there is nothing to replan *toward* — which is exactly why the
earlier ladder-based agent could only shrink.

```
Mission(description, category, target_lines, merchants)
```

The mission is **not** the mandate. The customer's sentence produces both: a mission
(what to buy) for the agent, and a mandate (what is permitted) for the wallet. They
are deliberately different objects with different owners, and the agent never
receives the mandate.

### 2. `Proposal` — *a purchase the agent wants to make*

**Owner: agent. Above the line.**

```
Proposal(session_id, lines[]) -> one shop, plausible offers, well-formed
```

A proposal is a *request*, never an instruction. It carries no policy, no
instruction text, and no timestamp — three fields that used to be here and each of
which turned out to be a way for the agent to influence its own judgement.

### 3. `Decision` — *the wallet's answer*

**Owner: wallet. Below the line. The only authority in the system.**

`allow` · `block` · `step_up`. Derived from the confirmed mandate and authoritative
state, never from the proposal's claims about itself, and never from whoever is
planning above it.

### 4. `Feedback` — *what the agent is told about a refusal*

**Owner: wallet. Crosses the line, deliberately narrow.**

This is the interesting object, because it is the only place where the wallet gives
anything back. It must be enough to replan with and not enough to probe with.

| class | means | the agent's move |
| --- | --- | --- |
| `amount` | this single order is too large | propose a cheaper basket |
| `budget_window` | *the rolling allowance is used up* | fit the remainder, or wait |
| `merchant` | this shop is not acceptable | go elsewhere |
| `item` | wrong kind of thing | change the goods |
| `basket` | something unrequested is in it | remove it |
| `order_terms` | the seller's terms are not acceptable | different goods or seller |
| `session` | something about the agent's conduct | **stop. ask the customer** |
| `duplicate` | this looks like a repeat | **stop. ask the customer** |

`budget_window` is new in this phase and is the whole of Workstream 5. Previously a
per-order breach and a rolling-window breach were both `amount`, so the agent
answered them identically — and they call for different moves. Knowing a period rule
*exists* is the same class of information as `merchant` revealing that a merchant
rule exists. **No value, no remainder, no threshold.**

The last two classes are not shoppable. A constraint on the *purchase* is answered
by choosing differently; a constraint on the *agent* is not, and answering it with a
different basket is an agent rephrasing itself until the wallet stops noticing.

### 5. `Intervention` — *the customer is the decider*

**Owner: customer. Below the line.**

A `step_up` is a question, scoped to one purchase. The answer binds to that purchase
and nothing else: it cannot be flipped afterwards, cannot survive revocation, and
cannot breach a rolling window that filled up while it was waiting.

We do **not** claim to know who answered. There is no identity on this path.

### 6. `Authority` — *permission to move money, once*

**Owner: wallet. Below the line.**

Issued only for an approved decision, bounded by TTL, consumed at most once, and
killed by revocation while unspent. It lives **on** the decision record rather than
in a second object, because two records describing one authorization was the shape
that produced four separate vulnerabilities.

## The loop

```
  customer ──▶ Mission ──┐                       ┌── Mandate ──▶ wallet
                         ▼                       │
              ┌──────────────────┐               │
              │  BRAIN           │  observe      │
              │  det / model /   │  plan         │
              │  adversarial     │  evaluate     │
              └────────┬─────────┘               │
                       │ Proposal                │
                       ▼                         ▼
                  ┌─────────────────────────────────┐
                  │           WALLET                │
                  └──────┬──────────────┬───────────┘
                         │              │
              Feedback ◀─┘              └─▶ Decision ─▶ Authority ─▶ execution
                 │                                │
                 └──── replan, or hand back       └─ step_up ─▶ Intervention
```

The brain is replaceable. Everything below the wallet line is not.

## What the protocol does not promise

- No identity on the step-up path.
- No total-spend bound — `scope` is `purchase` or `period` and the spec closes the
  set.
- No cross-run aggregation: rolling spend is per run.
- No verification that a merchant stocks an item, or that its claims are true.
- No authentication on the demo API.
