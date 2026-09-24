# Jury Q&A

For each question there is a **short** answer (10–20 s), a **deeper** answer (30–45 s),
and what **not** to claim. Evidence is in brackets. The one-line versions are in
[JURY_ANSWERS.md](JURY_ANSWERS.md).

Lines to come back to: *The agent proposes. The wallet authorises.* · *The brain is
replaceable. The authority isn't.* · *Merchant text is evidence, not authorisation.* ·
*Customer intent defines the mandate. The wallet enforces it.* · *Ambiguity becomes a
question, not a guess.*

---

## Product and value

**1. Why do we need this if banks already have spending limits?**
- *Short:* A limit asks how much. An agent's mistakes are usually about *what*: the wrong
  shop, the wrong item, the same thing twice. All of them under the limit.
- *Deeper:* In the organisers' data, "buy the 27-inch monitor I chose, up to CHF 400"
  ended with four monitors, each under CHF 400. A limit can't see that. Our wallet
  checks each purchase against the customer's own sentence: the shop, the item, the
  return terms, whether it was already bought. [stage, key S; CUSTOMER_FRICTION.md]
- *Don't claim:* that limits are useless. They still cap the amount, and we use them.

**2. What is different from a normal card limit?**
- *Short:* Same CHF 289, eight versions of one purchase: a card set as tightly as a card
  can be says yes to all eight. The wallet says yes to one.
- *Deeper:* The card rule is written out: CHF 400 per purchase, electronics shops,
  Switzerland only. It *can* refuse: a US shop, CHF 401, a grocer. At CHF 289 in a
  Swiss electronics shop it has no reason to. The wallet refuses another shop, a
  lookalike shop, a 24-inch, an extra cable, and two cheap monitors, and it asks about
  a seller's note to the AI and a repeat. [`/api/stage/same-price`, tests/test_stage.py]
- *Don't claim:* "cards can't do X" beyond that defined card rule. A merchant-category
  code does catch the wrong *kind* of shop.

**3. Why can't the shopping agent simply implement these rules itself?**
- *Short:* Because then the thing being checked is the thing checking. If the agent is
  confused or manipulated, its rules go with it.
- *Deeper:* We tested exactly that case: a deliberately hostile brain made 32 proposals.
  23 were refused or put to the customer, and the 9 allowed broke no rule the customer
  wrote. The agent has no call that approves anything; that is enforced by a test on
  the code's imports. [research/brains.py, tests/test_runtime_boundary.py]
- *Don't claim:* that the agent is useless. It plans, and it adapts. It just doesn't
  authorise.

**4. What happens if the AI agent is compromised?**
- *Short:* It can propose anything. It can't approve anything. The customer's rules
  still apply, and the leash stops it.
- *Deeper:* The stage's official "manipulated agent" scenario is exactly that. It tries
  repeats, an overpriced order, a lookalike shop, a gift voucher. One monitor goes
  through; everything else is refused or asked. What a compromised agent *can* still do
  is buy things the sentence allows, which is why revocation is one tap.
- *Don't claim:* that a compromised agent can do nothing. It can spend within the mandate.

**5. Who is actually making the final decision?**
- *Short:* The wallet, from the customer's rules. When the rules don't settle it, the
  customer, for that one purchase.
- *Deeper:* Each rule gives pass, fail or unknown. Any fail means no. Any unknown means
  the customer's own choice for uncertainty, usually "ask me". Otherwise yes. The agent
  and any model are outside that path. [ARCHITECTURE_ONE_PAGER.md]
- *Don't claim:* "the AI decides". No model decides anything here.

**6. What happens when the customer changes their mind?**
- *Short:* They pull the leash: anything approved but unpaid is cancelled, open questions
  are answered no, everything after is blocked.
- *Deeper:* Revocation reaches a purchase that's waiting for the customer, on the stage
  and on the live sandbox: the open question is declined through the platform's
  `/resolve`. A customer can also tighten a mandate; loosening means confirming a new one.
  [tests/test_stage.py: leash during a question]
- *Don't claim:* that a charge already paid is reversed. Revocation stops what hasn't
  been paid.

**7. What happens if the customer wants to authorise an exception?**
- *Short:* When the wallet asks, "approve once" allows that one purchase. The rules don't change.
- *Deeper:* A question only arises when the rules can't settle the purchase. A purchase
  that clearly breaks a rule (over the limit, the wrong item) is refused without
  offering an exception: the customer changes the mandate instead. That stops a stream
  of "approve?" prompts from wearing the rules down.
- *Don't claim:* that any refusal can be overridden in one tap.

**8. Why do you ask the customer instead of just blocking?**
- *Short:* Because the wallet genuinely doesn't know. Was the first monitor delivered, or
  cancelled? If it was cancelled, he needs the second one.
- *Deeper:* A block would be guessing "no" on his behalf, and an approval would be
  guessing "yes". The customer chooses the policy in his own sentence: "ask me",
  "decline" or "approve when unsure". *Ambiguity becomes a question, not a guess.*
- *Don't claim:* that every question is necessary for every customer. Some would
  rather it declined, and they can say so.

**9. How do you avoid annoying the customer with too many questions?**
- *Short:* 9 questions in the 45 official purchases, and 3 if the customer taps "I
  already have it" once per errand.
- *Deeper:* All nine are justified by the customer's own sentence. Seven are the same
  question repeated as the agent retries. The close-errand tap turns five repeated
  questions into one. Measured, not estimated. [CUSTOMER_FRICTION.md, pinned by a test]
- *Don't claim:* zero friction. It went from 2 questions to 9 (or 3), in exchange for
  seven purchases that used to happen silently.

**10. What happens with unfamiliar merchants?**
- *Short:* An unfamiliar purchase isn't automatically forbidden. It's refused only if
  the customer said "from a shop I've used before".
- *Deeper:* Familiarity comes from the card's own history, including a replacement
  card's predecessor. A shop whose name imitates a known one (PixelHarbour for
  PixelHarbor) is named on screen as a lookalike.
- *Don't claim:* that we detect fraudulent merchants in general.

## Security

**11. What if the merchant tries prompt injection?**
- *Short:* It's read as text, never obeyed. And the customer is told a seller tried.
- *Deeper:* 288 generated seller attacks, appended to each of the 45 official purchases
  and compared against the same purchase without them: 0 of 12,960 decisions became
  more permissive. The customer was told in 67 of 96 held-out attempts that were aimed
  at the machine, with 0 false alarms on 156 honest descriptions. [GENERATED_CORPUS.md]
- *Don't claim:* "we detect every injection". About 30% go unnamed, though still never obeyed.

**12. Can merchant text influence the authorisation?**
- *Short:* It can't change the rules. But it's the only evidence for the return window,
  so a seller who claims "returns within 90 days" satisfies a return rule.
- *Deeper:* That's a known limit, pinned by a test so we can't forget it. There's no
  other source for that fact in the protocol. *Merchant text is evidence, not
  authorisation.* But evidence can lie. [LIMITATIONS.md]
- *Don't claim:* "merchant text can only narrow a decision". We used to, and it was false.

**13. What if the agent lies about what it wants to buy?**
- *Short:* The wallet judges the event the platform sends, not the agent's description of it.
- *Deeper:* The amount, the shop and the card come from the platform. "Already bought"
  comes from the wallet's own ledger, never from the event. A changed item id doesn't
  reset the errand. [tests/security/test_one_off_errand.py]
- *Don't claim:* that we verify the physical goods.

**14. What if the agent changes the amount after approval?**
- *Short:* An approval is a single-use authority for that shop and that amount. A larger
  charge is refused.
- *Deeper:* In the research demo, the approved CHF 299 goes through and a follow-up
  CHF 999 charge on the same authority is refused at the payment boundary. [research/demo_scenario.py]
- *Don't claim:* that this runs on real payment rails. The payment side is a mock.

**15. What happens if the same transaction is retried?**
- *Short:* Same answer. A redelivered authorisation id gets the decision it already had.
- *Deeper:* The live worker reconciles with the platform instead of deciding twice, and
  a restarted worker restores its ledger. [tests: redelivery, restart]
- *Don't claim:* exactly-once across several server processes. That's a documented limit.

**16. How do you handle duplicate purchases?**
- *Short:* Two ways. Same shop and basket within an hour is flagged. And for a one-off
  errand, any second purchase goes to the customer.
- *Deeper:* The one-off rule is compiled from the customer's wording ("the monitor I
  chose", "replace my shoes"). It counts approvals in the wallet's ledger, so a
  different shop, price or item name doesn't make a second one new.
- *Don't claim:* that it works across separate runs. The ledger is per run.

**17. What if the customer revokes while a transaction is pending?**
- *Short:* The pending question is answered no, and nothing after can pass.
- *Deeper:* We found that the stage used to keep waiting for an answer after the leash
  was pulled, and fixed it: in replay, and in live mode through `/resolve`. [tests/test_stage.py]
- *Don't claim:* anything about purchases already paid.

**18. What happens if the external LLM is unavailable?**
- *Short:* Nothing in the decision changes. There's no model in the wallet.
- *Deeper:* A model-driven planner with the deterministic search as fallback still scores
  11/11 when the model is down; that's measured with a stub that always fails.
  [research/architecture_comparison.py]
- *Don't claim:* that a model-only planner degrades gracefully. It doesn't.

**19. Can an LLM ever override the wallet?**
- *Short:* No path exists for it to. The model's output is a proposal; the wallet
  judges it like any other.
- *Deeper:* With four brains, real models included, 0 purchases were approved that break
  the customer's sentence, judged by an independent referee whose negative control finds
  23. [REAL_MODEL_PLANNER.md]
- *Don't claim:* that a model can't *propose* something harmful. It can; it just can't approve it.

**20. Why is the wallet deterministic?**
- *Short:* The brief requires a predictable answer even when a model is down. And
  authority you can't reproduce, you can't audit.
- *Deeper:* The same event gives the same decision, byte for byte. The official replay
  is identical across runs, which is what makes the tests, the mutation probe and the
  live comparison meaningful.
- *Don't claim:* that determinism makes it correct. It makes it checkable.

## AI and technical

**21. Why are you using an LLM at all?**
- *Short:* In the agent, not the wallet, to show the brain is replaceable, and to measure
  what a model adds.
- *Deeper:* A model is good at open-ended planning. We plugged Apertus and OpenAI into
  the same planner interface. The architecture doesn't need them, and it isn't
  endangered by them.
- *Don't claim:* that the product depends on an LLM.

**22. What does the LLM actually do?**
- *Short:* It chooses which basket to propose from the shop's offers.
- *Deeper:* It gets the errand, the offers, and which kind of rule refused the last
  attempt. It returns item ids as JSON. Anything unusable falls back or hands back.
- *Don't claim:* that it reads the customer's rules or limits. It never sees them.

**23. What happens if GPT or Apertus gives the wrong answer?**
- *Short:* The wallet refuses or asks. In our runs, the worst was asking needlessly, or
  keeping an item that had sold out.
- *Deeper:* On our benchmark the models escalated to the customer when a valid basket
  existed, and kept a sold-out item that the wallet then approved, since the wallet
  can't see stock. None of them got a forbidden purchase approved.
- *Don't claim:* "wrong answers are harmless". A sold-out item is a failed order.

**24. Why not let the LLM make the final decision?**
- *Short:* Because it can be talked into things, and its answers vary run to run. Authority shouldn't.
- *Deeper:* Our own runs at temperature 0 scored differently from run to run. A seller's
  text is one prompt away from a model's input. The decision has to be reproducible and
  immune to the text it reads.
- *Don't claim:* that models are bad. This is about where authority sits.

**25. How did you test the AI?**
- *Short:* Eleven shopping episodes, three runs, two experiments, same wallet, with an
  independent referee.
- *Deeper:* Planner scores: the search 11/11, Apertus 1.5 70B 7–8/11 alone and 8–9 with
  fallback, gpt-4.1-mini 7–8/11 alone and 9–10 with fallback. And across all of them, 0
  unauthorised approvals. [REAL_MODEL_PLANNER.md]
- *Don't claim:* a ranking of models. The gap is smaller than the run-to-run variance.

**26. Why did the deterministic planner perform better?**
- *Short:* On this benchmark, because it has an explicit objective and a search. The
  models guessed.
- *Deeper:* The episodes test specific moves: change shop, swap one line, notice an item
  that sold out. The search does these by construction. Eleven episodes is small, and a
  tuned prompt might close the gap.
- *Don't claim:* that search beats LLMs in general.

**27. What happens if you replace the model tomorrow?**
- *Short:* One adapter, about ten lines. Nothing below the planner interface changes.
- *Deeper:* Adding OpenAI next to Apertus needed only a new completer. The wallet, the
  rules and the tests didn't change. The same referee measures the new brain.
- *Don't claim:* that the new model will plan well.

**28. Can this architecture support another model?**
- *Short:* Yes, anything that answers two calls: an opening basket and the next step.
- *Deeper:* We ran a deterministic search, two hosted LLMs, and a hostile planner behind
  the same seam. *The brain is replaceable. The authority isn't.*

**29. How do you translate natural language into executable rules?**
- *Short:* A deterministic compiler: phrases become rules in the organisers' rule format,
  and it shows what it couldn't read.
- *Deeper:* "For CHF 400 or less" becomes a ceiling, "a seller I've bought from before" a
  familiarity rule, "the monitor I chose" a one-off rule. The customer sees the rules and
  the unread parts before confirming.
- *Don't claim:* that it understands any sentence.

**30. What happens when the customer uses an unsupported language?**
- *Short:* It's detected and flagged before confirmation, not read.
- *Deeper:* French, German and Italian are recognised as not English; the customer is
  told the restrictions in them were not read. Swiss amounts ("400.-", "1'200 CHF",
  "Fr. 400") are read.
- *Don't claim:* multilingual support.

**31. How do you handle ambiguity?**
- *Short:* At the rule level: unknown means ask. At the sentence level: the stricter
  reading, and a note to the customer.
- *Deeper:* "CHF 100, actually CHF 50" uses 50 and says so. One-off wording together with
  repeat wording ("a one-time thing… every week") is named, not guessed.

**32. How do you prevent a rule from being silently lost during compilation?**
- *Short:* Anything restrictive the compiler can't turn into a rule is shown before
  confirmation. We measured it on 840 generated sentences.
- *Deeper:* The expected meaning was drawn in code *before* a model phrased each sentence.
  The last blind measurement lost 3 of 200 restrictions silently; those are fixed, and
  the worst class was a weekly budget read as a per-order limit. [GENERATED_CORPUS.md]
- *Don't claim:* "never silently loses a rule". Zero on 840 is fitted.

## Scalability and real world

**33. Can this work across multiple banks?**
- *Short:* The mandate is data in the organisers' shared format, so in principle yes.
  We haven't shown it.
- *Don't claim:* interoperability we didn't build.

**34. Can this work across multiple merchants?**
- *Short:* Yes, and it has to: the rules are about the customer, not the shop. The
  official scenarios span several shops.

**35. Can this work with real payment networks?**
- *Short:* It ran on the Viseca sandbox API. Payment execution itself is a mock.
- *Deeper:* Production would need the issuer's authorisation hook and a real payment
  authority. The architecture separates decision from execution for that reason.
- *Don't claim:* production readiness.

**36. What happens across multiple devices or sessions?**
- *Short:* A new device mid-session is a question, if the customer asked for that
  ("pause anything that looks like someone other than me").
- *Deeper:* That's the official session-integrity scenario (AU0026). Cross-session
  history is the card's history; cross-run spending is not aggregated.

**37. How do you enforce spending limits across multiple transactions?**
- *Short:* Rolling windows ("CHF 300 across any 7 days") over the run's ledger, including
  purchases still waiting for the customer.
- *Deeper:* The tricky part was a pending purchase approved later, back-dated into a
  window. Our fix checks every window containing it. It's not aggregated across runs.
- *Don't claim:* a lifetime or cross-run total.

**38. What happens in a distributed deployment?**
- *Short:* That's not solved in this prototype. Single use is per process; production
  would need a shared ledger with an atomic claim.
- *Don't claim:* horizontal scalability.

**39. How would you authenticate the human approval?**
- *Short:* In the issuer's app, with its strong customer authentication. The demo has none.
- *Deeper:* Our answer endpoint is a stand-in. The platform's `/resolve` is authenticated
  with the team key, but whoever reaches our demo server can answer. [LIMITATIONS.md]

**40. What would you build next in production?**
- *Short:* A shared ledger across runs and processes, authenticated approvals in the bank
  app, and a verified source for return terms.
- *Deeper:* Those are exactly the three limits we document; each is outside what the
  hackathon protocol provides.

## Business *(hypotheses, not demonstrated)*

**41. Who is the customer?** A card issuer offering agent-safe cards to its cardholders.
**42. Who pays?** The issuer, as part of a premium or agentic-commerce card feature. We haven't validated pricing.
**43. Why would a bank want this?** Fewer disputes from agent mistakes, and a reason for customers to let agents use *its* card.
**44. Why would a card network want this?** A common mandate format makes agent purchases explainable across issuers. That's a hypothesis.
**45. Why would merchants accept this?** It asks nothing new of them; they see an ordinary authorisation. Honest merchants lose nothing.
**46. What is the market opportunity?** We didn't size it. Don't invent a number.
**47. What prevents Visa, Mastercard or banks from building this?** Nothing, and they might. Our contribution is the design and evidence of where authority must sit.
**48. What is your moat?** For a hackathon: a tested design and the evidence behind it, not a moat.

## Hackathon

**49. What is the hardest technical problem you solved?**
- *Short:* Rolling spending windows with purchases that wait for the customer.
- *Deeper:* A purchase approved later is dated when it was proposed, so it can land inside
  a window that's already full. Following the spec plainly produced CHF 480 against a CHF
  300 cap, with every individual decision correct. [FINAL_AUDIT_PACKAGE.md]

**50. What surprised you during development?**
- *Short:* How often our own claims were wrong. The four monitors were in the official data
  and our engine approved them; a guard on our numbers couldn't read one spelling; "merchant
  text can only narrow" turned out false.
- *Deeper:* So every number now comes with the command that reproduces it.

**51. What did you deliberately NOT build?**
- *Short:* An LLM in the decision, account-level limit enforcement, and multilingual
  compilation.
- *Deeper:* Each would have made the demo look smarter and the authority less predictable.

**52. What would you do with another month?**
- *Short:* The three production limits (shared ledger, authenticated approvals, verified
  return terms), then a study with real customers on how often they want to be asked.
