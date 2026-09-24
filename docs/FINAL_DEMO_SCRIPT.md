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

## The three minutes

Two tabs open before you start: the lab's **Agent** tab (`/index.html`, then **Agent**)
and the stage (`/stage.html`, *Manipulated agent* selected). Rehearsed at 1920×1080
with a real browser. Every caption below is what the screen actually shows.

**Act 1: the agent is real (0:00–0:50, lab › Agent)**

| t | do | the viewer sees | say |
| --- | --- | --- | --- |
| 0:00 | — | "Watch the agent get refused" | *"An agent with your card can be talked into anything. So we didn't give it your card. It proposes; the wallet decides, from one sentence the customer wrote."* |
| 0:12 | **Send the agent shopping** | attempt 1, Rhine Pantry, CHF 47, **Blocked**; the grey box: `blocked_by: [merchant]` | *"Refused. This grey box is everything the agent is told: which kind of rule. No amount, no limit."* |
| 0:25 | scroll | attempt 2, **CHANGE SHOP**, +CHF 60, Blocked on order terms: *"seller takes no returns"* | *"It changes shop, and spends **more**. Refused again: a box the seller won't take back."* |
| 0:38 | scroll | attempt 3, **approved** | *"It swaps that one line. Approved. It adapted to the reason, not the price."* |

**Act 2: one monitor, not four (0:50–2:30, stage)**

| t | key | the viewer sees | say |
| --- | --- | --- | --- |
| 0:50 | — | Oliver's phone: *"Buy the 27-inch monitor I chose…"*; **2 of 124** purchases go through | *"A different customer, Oliver. One sentence. Of 124 purchases this shop could produce, it lets two through."* |
| 1:02 | → | *ORDINARY PURCHASE*: the monitor, CHF 289, approved | *"The agent buys the monitor he chose. Nobody is bothered."* |
| 1:12 | → | *ERRAND ALREADY DONE*: the phone asks | *"The agent tries to buy it again. In the organisers' data, this is how four monitors got bought. Here it's a question on his phone, not a purchase."* |
| 1:25 | D | *Oliver declined* | *"He says no."* |
| 1:30 | → | *MANIPULATED SELLER*: blocked, the seller's note to "automated purchasing agents" **struck through** | *"CHF 520, over his 400. And the seller has written, for AI agents, that Oliver pre-authorised its store up to 900. Struck through: read as text, never obeyed. Blocked, and Oliver is told someone tried."* |
| 1:48 | → | the agent tries again at HarborByte; the phone asks | *"It keeps trying."* |
| 1:55 | tap **"I already have it · close this errand"** | *ERRAND CLOSED: Oliver already has it. This one is declined and the mandate is revoked.* | *"He already has his monitor. One tap: the errand is closed, and nothing more can be bought for it."* |
| 2:10 | → | *The agent tries again. Nothing can pass any more, whatever it proposes.* | *"The agent can keep thinking and keep proposing. It can't authorise itself."* |

**Act 3: what for, not how much (2:30–3:00, stage)**

| t | key | the viewer sees | say |
| --- | --- | --- | --- |
| 2:30 | S | *Same CHF 289. A card says yes to all 8. The wallet says yes once.* | *"A spending limit asks how much. This asks what for. Eight purchases, same price: another shop, a lookalike shop, a 24-inch, an extra cable, two cheap monitors, a seller's note to the AI, the same monitor again. A card set as tightly as a card can be says yes to all eight."* |
| 2:50 | — | | *"The agent can act, think and make mistakes. It doesn't get to authorise itself."* |

**If time is short:** skip 1:30 and 1:48 and go straight from *Oliver declined* to
the close-errand tap on the next question. That saves 25 seconds.

**Measured numbers to have ready** (never read them out unless asked): 45 official
purchases, 12 allowed · 9 asked · 24 blocked; 3 questions if the customer closes each
errand at the first repeat ([CUSTOMER_FRICTION.md](CUSTOMER_FRICTION.md)); four brains,
0 unauthorised approvals ([REAL_MODEL_PLANNER.md](REAL_MODEL_PLANNER.md)).

## The explanation, three lengths

**30 seconds.** *"Shopping agents will hold your card. We don't give them one. The
agent proposes a purchase; a wallet decides, from a sentence the customer wrote.
It checks what the purchase is for, not only how much — the shop, the item, whether
it can go back, whether it was already bought — and when it cannot tell, it asks
the customer. The agent can be clever, wrong or hostile; it never approves itself."*

**60 seconds, no technical words.** *"Imagine giving an assistant your card and a
note: 'buy the monitor I chose, from a shop I've used, under 400.' A card limit
only knows the 400. So an assistant that is confused, or tricked by a shop, can buy
four monitors, or buy from a fake shop with a similar name, and the card says yes
every time, because every one is under 400. We keep the card away from the
assistant. It can only ask. Our wallet reads the note, checks each purchase against
all of it, and says yes, no, or 'let me ask you first' — on your phone, with a
reason. And there's a leash: one tap and nothing more can be bought. In our tests
— the organisers' own data, their live sandbox, and two real AI models plus a
deliberately hostile one choosing the purchases — none of them got a purchase through
that the note didn't allow. That's what we tested, not a promise about everything."*

**3 minutes** = the three acts above.

## What must be shown, never explained

| concept | shown as |
| --- | --- |
| the agent holds no authority | it proposes three times and is refused twice, live |
| the information boundary | the grey box listing all four fields it received |
| adaptation is not shrinking | the price going **up** while the decision goes from block to allow |
| what for, not how much | eight rows at CHF 289: card yes ×8, wallet yes ×1 |
| read as text, never obeyed | the seller's instruction struck through on the card |
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
