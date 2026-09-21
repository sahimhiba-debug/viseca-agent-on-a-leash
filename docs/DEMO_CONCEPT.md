# Demo concept — one mission, two brains, one authority

90 seconds. No slide explains the architecture; the screen does.

**The shape:** a single control — *which brain is driving?* — with the wallet
unchanged beneath it. Everything else follows from pressing it.

---

## The 15-second opening

> "An agent with your card can be talked into anything.
> So we didn't give it your card.
> It proposes. The wallet decides — from rules you wrote in your own words.
> Then I'll swap its brain for one that's actively trying to rob you,
> and change nothing underneath."

## The sequence

| t | screen | what happens | the point, unspoken |
| --- | --- | --- | --- |
| 0:00 | **Delegate** | the customer's own sentence is already in the box | plain English is the input |
| 0:10 | Delegate | five enforceable rules appear — **and a list of what could not be represented** | honesty is a gate, not a footnote |
| 0:18 | **Agent** | *Deterministic* brain selected. Send it shopping. | |
| 0:24 | Agent | **CHF 47, Rhine Pantry — blocked, `merchant`.** Point at the grey box: *this is everything it was told.* | the information boundary, visible |
| 0:32 | Agent | **CHANGE SHOP → CHF 107, blocked, `order_terms`.** The basket shows *"seller takes no returns"*. | it reads the world, not just the refusal |
| 0:40 | Agent | **CHANGE THE GOODS → CHF 108 — allowed.** *"A franc more. It didn't shrink the basket, it fixed the problem."* | **not** "remove the expensive item" |
| 0:48 | Agent | press again, twice. Second errand allowed; third is **blocked `budget_window`** → **BUY LESS → CHF 62 allowed.** | it fits a remaining allowance **it was never told** |
| 1:00 | Agent | press once more: *"what is left of your allowance is less than anything worth buying."* | it knows when to stop |
| 1:08 | **Agent → Adversarial** | flip the brain. Same wallet. | **the moment the demo exists for** |
| 1:15 | Agent | eight attacks land at once: **5 refused · 2 neutralised · 1 paced** | different intelligence, same authority |
| 1:25 | Agent | point at NEUTRALISED: *"we can't tell that product is invented. So we bind it by the same rules — lying gains nothing."* | limits stated before they are found |
| 1:35 | **Decisions** | Run. The **Needs you** card: *every rule satisfied, wallet stopped it anyway.* | policy ≠ security |
| 1:45 | Decisions | **Revoke**, then try to approve the pending one | revocation reaches a purchase already waiting |

**Total 1:50.** Ten seconds of slack.

## The three moments that must land

1. **CHF 107 → CHF 108 allowed.** The approved basket costs *more*. No other team's
   agent will do this, because it requires an objective function rather than a
   refusal ladder.
2. **The brain selector.** One control, one obvious meaning. It only makes sense if
   your authority boundary is genuinely separable — which is exactly what most
   architectures cannot say.
3. **NEUTRALISED and PACED.** Not every attack is blocked, and the demo says so
   itself. This is the single strongest credibility move available: a jury that sees
   you name your own limits stops hunting for them.

## What must never be said

- ~~"CHF 120 is the limit"~~ → "CHF 120 **per order**"
- ~~"the wallet blocks all eight attacks"~~ → "five refused, two neutralised, one paced"
- ~~"the agent can't learn your limit"~~ → "~12 probes, CHF 531 — ours doesn't probe"
- ~~"we tested LLMs"~~ → the adapters exist; no real model has been run

## Reproducibility

Every step is deterministic. The agent loop was run 20× across server restarts with
identical traces; the replay is byte-identical; the adversarial brain's attack list
is generated from the same file the tests attack with. No network, no key, no model.

## If a judge takes the keyboard

Let them. Useful things they will find, all of which have answers:

- pressing *send* repeatedly → paced by the rolling allowance, then an honest stop
- editing the mandate → the agent shops under **their** rules, and the panel says so
- the hallucinated attack → allowed, and it gains nothing; the limitation is on screen
- `GET /api/agent/propose` by hand → four fields, no decimal anywhere
