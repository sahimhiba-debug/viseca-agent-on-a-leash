# Architecture on one page

```
   customer ──"Buy the 27-inch monitor I chose, from a seller I've used, CHF 400 or less.
      │        Ask me when uncertain."
      ▼
 ┌────────────────────┐   rules it could read, and what it could NOT read,
 │  sentence compiler │── shown before the customer confirms
 └────────────────────┘
      │ mandate: rules + "ask me / decline / approve when unsure"
      ▼
 ┌────────────────────┐        proposes         ┌─────────────────────────┐
 │       WALLET       │ ◀────────────────────── │  AGENT (any brain):     │
 │  decision engine   │ ──── yes / no / ask ──▶ │  search · Apertus ·     │
 │  (deterministic)   │   + which KIND of rule  │  OpenAI · hostile       │
 └────────────────────┘     refused, no more    └─────────────────────────┘
      │  facts: platform event · purchase history · the wallet's own ledger
      │         · seller text (read as evidence, never obeyed)
      ▼
   yes ─▶ a single-use authority for that one purchase
   ask ─▶ the customer's phone: approve once · decline · "I already have it"
   no  ─▶ refused, with the reason in plain words
      │
   the leash: revoke ─▶ unspent approvals cancelled, open questions answered no,
                        everything after blocked
```

**The one design decision.** Deciding and proposing are different programs. The agent
has no call that approves anything. It can only submit a proposal. So a better or
worse brain changes *what is proposed*, never *what is allowed*
(`tests/test_runtime_boundary.py`; `research/brains.py` measures it with four brains).

**How a decision is made.** Each rule gives `pass`, `fail` or `unknown`. Any `fail`
means **no**. Otherwise any `unknown` means the customer's own choice for uncertainty,
usually **ask**. Otherwise **yes**. Uncertainty never silently becomes approval.

**Where the facts come from, and who can lie about them.** The amount, the shop and
the card come from the platform. "A shop you have used before" comes from the card's
history. "Already bought once" comes from the wallet's own ledger, never from the
event. The return window and the size come from the seller's text: the one place a
seller can mislead ([LIMITATIONS](LIMITATIONS.md)).

**What the agent learns when refused.** The kind of rule ("merchant", "order terms"),
never the limit or the remaining budget. It can adapt without probing the wallet.

**Two modes, one engine.** *Replay* runs the organisers' 45 official purchases locally.
*Live* runs them on the Viseca sandbox, with the customer's answers sent through the
platform's `/resolve`. The same `evaluate_authorization` decides both.

| module | role |
| --- | --- |
| `policy_compiler.py` | sentence → rules, and the list of what it could not read |
| `decision_engine.py`, `rules.py`, `facts.py` | the decision: facts, each rule's outcome, the verdict |
| `state.py` | the run's ledger: approvals, windows, revocation, history |
| `live_worker.py`, `viseca_client.py` | the live integration with the platform |
| `stage.py`, `ui/stage.html` | the demo: the customer's phone beside the agent's purchases |
| `research/` | the agents, benchmarks and corpora; never imported by the wallet |
