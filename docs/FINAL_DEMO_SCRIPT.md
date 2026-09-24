# Final demo script

Two minutes. One story, not a tour of the UI. Every number on screen is produced
live by the same engine the tests run against.

**The story:** a human delegates → the agent shops → the wallet refuses → the agent
adapts → the wallet allows → and then the wallet overrules a policy that passed.

---

## The 15-second opening

Three candidates were written and tested against the three juries in
`FINAL_JURY_AUDIT.md`. **Use C.**

### A — the incumbent (the one we had)

> "This is a shopping agent with a credit card. That should terrify you.
> It doesn't have one. It has a leash. The agent shops. The wallet decides."

Strong rhythm, and "it has a leash" lands. Two problems. *"That should terrify you"*
tells a senior jury how to feel before showing them anything, and they resist it on
reflex. And "leash" is the project's name, so the line explains the title rather than
the architecture.

### B — the question

> "Your agent found a better price at a shop you've never used.
> Should it buy? Every system here answers yes or no.
> This one answers *who decides* — and it isn't the agent."

Accurate and it frames the real contribution. But it takes ten seconds before
anything concrete appears, and "who decides" is abstract until they see a screen.

### C — the one to use ✅

> "An agent with your card can be talked into anything.
> So we didn't give it your card.
> It proposes. The wallet decides — from rules you wrote in your own words.
> Watch it get refused twice, and neither time is about money."

Why this one. It states the threat model in one clause without instructing anyone to
be afraid. *"So we didn't give it your card"* is the architecture, in seven words.
*"Rules you wrote in your own words"* is the UX differentiator. And the last line
sets a falsifiable expectation the next forty seconds deliver — which converts a
sceptical jury into one that is *checking*, the best state they can be in.

---

## The two minutes

| t | screen | action | what you say | what the jury takes away |
| --- | --- | --- | --- | --- |
| 0:00 | **Home** | — | *"An agent with your card can be talked into anything. So we didn't give it your card. It proposes — the wallet decides, from rules you wrote in your own words. Watch it get refused twice, and neither time is about money."* | the thesis, and a promise to check |
| 0:15 | **Delegate** | the instruction is already in the box | *"The customer writes this. Groceries, from a shop I've used before, under CHF 120, only if I can send it back."* Tap **See how the wallet reads this**. | plain English is the input |
| 0:25 | still Delegate | compiled rules appear | *"Four enforceable rules — and a list of what it could **not** turn into a rule. You can't confirm until you've seen that list."* | honesty is a feature, and it is a gate |
| 0:35 | **Agent** | tap **Send the agent shopping** | *"Now an autonomous agent goes shopping. It has never been told your rules."* | the agent is a separate client |
| 0:42 | Agent | first card lands | *"CHF 47 at Rhine Pantry. Refused."* Point at the grey box. *"This is **everything** it was told: blocked, merchant. No amount. No limit. No remaining budget."* | the information boundary, visible |
| 0:52 | Agent | second card | *"It can't fix that by spending less. So it changes shop — and the basket goes **up** sixty francs."* | **strategy change 1**, and not price |
| 1:02 | Agent | second refusal | *"Refused again, different reason: order terms. Look at the basket — a clearance box the seller won't take back."* | the agent reads the world |
| 1:10 | Agent | third card | *"It swaps that one line. One franc **more** — and allowed. It didn't shrink the basket, it fixed the problem."* | **strategy change 2**; this kills "it just deletes the expensive item" |
| 1:22 | **Decisions** | tap **Run** (already on *Manipulated agent*) | *"Different errand, same wallet. A 27-inch monitor, CHF 289, from a seller they've used before."* | generality |
| 1:32 | Decisions | the **Needs you** card | *"Every rule the customer wrote was satisfied."* Point: **Your rules — Satisfied. Wallet checks — Not sure.** *"The wallet stopped it anyway. It looks like an order you already placed."* | **policy ≠ security**, the whole idea |
| 1:42 | Decisions | point at the scope line | *"And when the customer approves, they're approving **this one purchase** — CHF 289 at PixelHarbor. Not a standing exception."* | bounded consent |
| 1:50 | `WHAT_WE_REFUSE_TO_CLAIM.md` | open it | *"This is the part we'd rather you read. Everything we don't claim, and why."* | credibility, deliberately last |

**Total: 1:55.** Five seconds of slack, deliberately.

---

## The two moments that must land

**1. The agent is not "remove the expensive item".** This is the single hardest
thing about this project to believe, so the screen says it rather than the presenter:
each card carries a strategy chip — `CHANGE SHOP`, then `CHANGE THE GOODS` — and the
price delta beside it, reading **"+CHF 60.00 — it did not spend less"** and
**"+CHF 1.00 — it did not spend less"**. The basket is itemised and the offending
line is marked *"seller takes no returns"*.

If a jury remembers one thing, it should be that **the approved basket cost more
than the refused one.**

**2. Policy satisfied, security not.** The page asks
`GET /api/scenarios/security-override`, which runs the scenarios and returns
whichever contains a decision where `policy_verdict: allow` and
`security_verdict != allow`. Since the one-off errand rule none does: the two
candidates (SCEN0004 AU0036, AU0040) are also repeat monitors, so the customer's own
rule asks as well, and the endpoint says so rather than pointing at a stale id. Show
the distinction on the stage instead: AU0040's card carries the seller's instruction
struck through beside the errand question.

---

## What must be shown, never explained

| concept | shown as |
| --- | --- |
| the agent holds no authority | it proposes three times and is refused twice, live |
| the information boundary | the grey box listing all four fields it received |
| adaptation is not shrinking | the price going **up** while the decision goes from block to allow |
| policy vs security | two labelled verdicts on one card, disagreeing |
| bounded consent | *"this one purchase — CHF 289 at PixelHarbor"* |
| we know our limits | the refusals document, on screen |

---

## Reproducibility

The agent loop was run 40 times across two server lifetimes and 8 concurrent
sessions during this campaign; every run produced the identical trace
(CHF 47 → 107 → 108, `merchant` → `order_terms` → allow). The official replay is
byte-identical across runs. No network, no key, no model.

`tests/test_demo_data_is_real.py` fails if the demo stops taking three attempts,
stops changing shop once and goods once, or ends on a basket *cheaper* than the one
refused before it — so a future price edit cannot quietly turn this back into "it
removed the expensive item" while this script still promises otherwise.

---

## If something breaks

* An attack card shows **HOLE** → stop and say so. It is a real regression.
* Header dot red → the replay drifted. Say that too; it is the honest failure.
* The Agent tab approves on attempt 1 → the mandate on **Delegate** was confirmed
  and is looser than the built-in one. The line under the button says which mandate
  is running. Either narrate it or reload.
* Stale page → should no longer happen; the page is served `no-store`. If it does,
  the server is not the one you think it is.

---

## What to do with the remaining two minutes of Q&A

Lead with the question you want: *"Ask me whether the agent is real."* Then
`research/planning_benchmark.py` — eleven episodes written before the agent was
changed so it could fail, and it did, 5/11. Flash cards in `FINAL_JUDGE_QA.md`.
