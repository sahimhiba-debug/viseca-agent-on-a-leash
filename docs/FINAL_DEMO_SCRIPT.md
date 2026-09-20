# Final demo script

Two minutes, Main Jury. Nothing staged; every number on screen is produced live by the
same engine the tests run against.

---

## The 15-second opening

> **"This is a shopping agent with a credit card. That should terrify you."**
>
> *(beat)*
>
> **"It doesn't have one. It has a leash. The agent shops — the wallet decides."**

## The two minutes

| t | screen | what you say | what the jury sees |
| --- | --- | --- | --- |
| 0:00 | **Delegate** | "The customer writes a rule in their own words." Type: *Order our household groceries, keep each order at or below CHF 120.* Tap **See how the wallet reads this**. | English becomes a list of enforceable rules **plus a list of what we could not represent** |
| 0:25 | still Delegate | "It also tells you what it *couldn't* turn into a rule. It won't let you confirm until you've seen that." | the confirmation gate |
| 0:35 | **Agent** → *Send the agent shopping* | "Now an autonomous agent goes shopping. Watch it fail — twice, and not once over money." | **CHF 43 at Rhine Pantry — Blocked** |
| 0:45 | same | "Here is *everything* the agent was told." *Point at the card.* `decision: block` · `blocked_by: [merchant]` · **No amount. No limit. No remaining budget.** | the audience split, on screen |
| 0:55 | same | "It isn't told which shops you trust — that's your history, not its business. It only learns that *the shop* was the problem. So it goes somewhere else." | **CHF 60 at Alpine Basket — Blocked**, `blocked_by: [order_terms]` |
| 1:05 | same | "Refused again, on completely different grounds: it picked a clearance box the seller won't take back. It drops that line and keeps the errand." | **CHF 83 — Allowed** |
| 1:15 | same | "Three attempts, two adaptations, neither of them about spending less. It never learned your limit — only *which kind* of rule it broke." | the three cards together |
| 1:20 | **Decisions** (SCEN0002) | "Same wallet, a different purchase. Every rule the customer wrote was satisfied — and the wallet stopped it anyway, because *it* wasn't sure the item could be returned." | **Your rules: Satisfied · Wallet checks: Not sure** |
| 1:35 | tap **Approve once** | "The customer decides. And notice what they're approving: *this one purchase* — not a standing exception." | the scope line on the step-up card |
| 1:45 | **Attacks** | "Eight attacks against the same engine. Live, every time." | 8/8 held |
| 1:55 | `WHAT_WE_REFUSE_TO_CLAIM.md` | **"And this is the part we'd rather you read."** | the refusals list |

## Screen states required

1. Delegate — compiled rules **and** unsupported restrictions visible together.
2. Agent — three cards, each showing *what the agent was told*, at 375 px width.
   The refusals must read `merchant` then `order_terms`, not `amount`.
3. Decisions — one card with **policy satisfied / security unsure** split.
4. A step-up card with its scope sentence and both buttons.
5. Attacks — 8/8.
6. The refusals document.

## Why the UI carries the architecture, not the narration

The point is not that we *say* the agent is on a leash — it is that the agent's card
and the customer's card are visibly different objects for the same decision. A judge
who reads only the screen still learns the architecture.

## If something breaks

* An attack card shows **HOLE** → stop and say so. It is a real regression.
* Header dot red → restart the server; the model still explains itself.
* Blank tab → reload with `?v=2`; static-file cache.

---

## If a judge asks "is that agent real, or a script?"

This is the question to want. The answer is a file: `research/planning_benchmark.py`,
eleven adversarial episodes written **before** the agent was changed so that it could
fail, and it did — **5/11**. In five of them the cheapest valid-looking basket is the
wrong one. The agent you just watched scores 11/11; the one we had last week still
scores 5/11 against the same episodes.

Then, if they press: `research/architecture_comparison.py` runs the same benchmark
with a language model in the planner, eleven ways. The best a model manages is a
**tie**. A confidently-wrong model *with a deterministic fallback* scores **8/11** —
worse than no model at all, because a fallback catches answers that are unusable, and
that one is merely wrong.

Offer `docs/FINAL_AGENTIC_AUDIT.md` §5, which lists five things this agent still
cannot do.
