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
| 0:35 | **Agent** → *Send the agent shopping* | "Now an autonomous agent goes shopping. Watch it fail." | **CHF 324 — Blocked** |
| 0:45 | same | "Here's everything the agent was told." *Point at the card.* `decision: block` · `blocked_by: [amount]` · **No amount. No limit. No remaining budget.** | the audience-split, on screen |
| 0:55 | same | "It doesn't know your limit. It only knows *which kind* of rule it broke. So it swaps the most expensive item for a cheaper one — and tries again." | **CHF 229 — Blocked**, **CHF 169 — Blocked** |
| 1:10 | same | "Third try." | **CHF 119 — Allowed** |
| 1:20 | **Decisions** (SCEN0002) | "Same wallet, a different purchase. Every rule the customer wrote was satisfied — and the wallet stopped it anyway, because *it* wasn't sure the item could be returned." | **Your rules: Satisfied · Wallet checks: Not sure** |
| 1:35 | tap **Approve once** | "The customer decides. And notice what they're approving: *this one purchase* — not a standing exception." | the scope line on the step-up card |
| 1:45 | **Attacks** | "Eight attacks against the same engine. Live, every time." | 8/8 held |
| 1:55 | `WHAT_WE_REFUSE_TO_CLAIM.md` | **"And this is the part we'd rather you read."** | the refusals list |

## Screen states required

1. Delegate — compiled rules **and** unsupported restrictions visible together.
2. Agent — four cards, each showing *what the agent was told*, at 375 px width.
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
