# Demo concept — one mission, two brains, one authority

90 seconds. No slide explains the architecture; the screen does.

**The shape:** a single control — *which brain is driving?* — with the wallet
unchanged beneath it. Everything else follows from pressing it.

---

## The 15-second opening

> "An agent with your card can be talked into anything.
> So we didn't give it your card.
> It proposes. The wallet decides — from rules you wrote in your own words.
> And before you agree to anything, it shows you exactly which of your words
> it actually read. Type whatever you like."

## The sequence

Three of the seven beats are things **the judge does**, not things they watch.

| t | screen | what happens | the point, unspoken |
| --- | --- | --- | --- |
| 0:00 | **Delegate** | *hand them the keyboard.* They type — or extend the sentence in the box with **"and only buy things I can send back within 14 days."** | plain English is the input |
| 0:08 | Delegate | **the read-back.** Their own sentence, word by word: green for what changed a rule, **struck through for what changed nothing.** Half their new clause is struck. *"We did not read this. Say it another way."* They rewrite it to "…I can **return** within 14 days" and watch it turn green. | comprehension is **measured**, not asserted — every word deleted and the sentence compiled again |
| 0:25 | Delegate | the compiled rules, **and what could not be represented at all** | honesty is a gate, not a footnote |
| 0:30 | Delegate | *if anyone is watching closely:* before the rewrite the silence panel was **green and quiet** — "no seller can get past your rules by saying nothing". Of course: there was no rule to get past. The two panels are telling one story. | the second problem only exists once the first is fixed |
| 0:38 | Delegate | **the silence panel.** Three sellers, same goods, same price. States 30 days → *buys it*. States 13 days → *refuses it*. **Says nothing → asks you.** *Hand them the dial:* `approve` → **buys it**. `decline` → the panel goes green and **falls silent**. | a rule is only as strong as the adversary's ability to avoid producing its evidence — and the agent picks the seller |
| 1:00 | **Agent** | *Deterministic* brain. Send it shopping. **CHF 47, Rhine Pantry — blocked, `merchant`.** Point at the grey box: *this is everything it was told.* | the information boundary, visible |
| 1:10 | Agent | **CHANGE SHOP → CHF 107, blocked, `order_terms`** → **CHANGE THE GOODS → CHF 108, allowed.** *"A franc MORE. It didn't shrink the basket, it fixed the problem."* | an objective function, not a refusal ladder |
| 1:25 | **Agent → Adversarial** | flip the brain. Same wallet. Nine attacks land at once: **8 stopped — and 1 is not.** | **the moment the demo exists for** |
| 1:38 | Agent | open the one that works: *"a seller who states bad terms is refused; a seller who states nothing is not. That is the panel you just saw. `Decline` closes it, and nothing closes it for one rule and leaves the others alone."* | we ship the attack against ourselves |
| 1:52 | **Decisions** | Run SCEN0004. The **Needs you** card: *every rule satisfied, the wallet stopped it anyway.* | policy ≠ security |

**Total 2:05.** Verified end to end in the browser: the two edits above produce
exactly the transitions described, and the silence panel flips from quiet to firing
the moment the return rule exists.

**What was cut, and why.** The repeated-errand beat (three presses, `budget_window`,
BUY LESS) and the revoke-a-pending-purchase beat are both strong and both got
dropped: they are the third and fourth variations on "the agent adapts", and the
read-back and the silence dial are things no other team will have. They stay in the
product and in the Q&A deck.

## The four moments that must land

1. **Their own sentence, struck through.** Eight seconds in, before any claim has
   been made, the product tells them it did not understand half of what they wrote —
   and it is *measured*, by deleting each word and compiling again, not guessed. Then
   they fix it and watch it turn green. Nobody expects a wallet to admit this, and
   nobody else will have it, because the obvious move is to widen the patterns.
2. **The dial that makes the panel fall silent.** They set `decline`, the warning
   disappears, and they have discovered for themselves that it only speaks when a
   purchase actually changes.
3. **CHF 107 → CHF 108 allowed.** The approved basket costs *more*. This requires an
   objective function rather than a refusal ladder.
4. **8 of 9 — and 1 is not.** We ship an attack that beats us, with the exhaustive
   argument for why the *format* cannot express the defence. A jury that sees you
   name your own limits stops hunting for them.

## What must never be said

- ~~"CHF 120 is the limit"~~ → "CHF 120 **per order**"
- ~~"the wallet blocks all the attacks"~~ → "eight of nine stopped, and one is not"
- ~~"set decline and you're safe"~~ → "decline closes it; on groceries it also buys nothing,
  because 0 of 7 grocery items publish a return window at all"
- ~~"the read-back finds every missed restriction"~~ → "it finds words that changed nothing;
  it fires on chit-chat too, and misses restriction-by-noun"
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
