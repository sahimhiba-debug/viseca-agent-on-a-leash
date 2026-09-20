# Judge Q&A — flash cards

Twenty cards. Each answer is ten to twenty seconds spoken, in the voice of an
engineer answering a colleague, not a pitch. Evidence and limitation on every one,
because a jury that catches an unqualified claim discounts everything after it.

The long-form versions are in `FINAL_JURY_AUDIT.md`.

---

**1 · Where is the AI?**
> "Outside the money path, on purpose. The agent does the reasoning — it searches
> baskets against an explicit objective and learns from refusals. The wallet decides
> deterministically, because the spec requires a predictable answer when the model is
> down."

*Evidence:* `research/shopping_agent.py`, `tests/test_runtime_boundary.py`.
*Limitation:* no language model anywhere in the judged path.

---

**2 · Why is this an agent and not a workflow?**
> "We wrote eleven adversarial episodes before touching the agent, so it could fail,
> and it did — five out of eleven. In five of them the cheapest valid basket is the
> wrong one. It scores eleven now. The old one still scores five."

*Evidence:* `research/planning_benchmark.py`, `tests/test_planning_benchmark.py`.
*Limitation:* eleven synthetic worlds is a diagnostic sample, not representative.

---

**3 · What does the agent actually decide?**
> "Which goods, from which shop, in what combination, and when to stop and ask you.
> Nothing about money moving. Watch it: it changes shop, then swaps one line, and
> the approved basket costs a franc more than the refused one."

*Limitation:* its objective counts lines bought — a thin proxy for a shopping list.

---

**4 · Why no LLM?**
> "We measured it rather than assumed. A model planner at the same seam ties at
> eleven out of eleven for twenty-one network calls. A confidently-wrong model with a
> deterministic fallback scores eight — worse than no model, because the fallback
> catches unusable answers and that one is merely wrong."

*Evidence:* `research/architecture_comparison.py`.
*Limitation:* those are stubs. No API was called; we did not benchmark an LLM.

---

**5 · Isn't this just a policy engine?**
> "A policy engine answers 'does this match the rules'. There's one decision in the
> official data where every rule the customer wrote passed and the wallet stopped it
> anyway. A policy engine can't produce that — the policy said yes."

*Evidence:* `GET /api/scenarios/security-override` → SCEN0004/AU0036.
*Limitation:* the policy half genuinely is a simple rules engine.

---

**6 · Why not just use a card spending limit?**
> "A limit answers 'can this card spend'. It can't say 'from a seller I've used
> before' or 'only if returnable in fourteen days', and it can't tell the agent why
> it was refused without telling it the number. Two of our three refusals are things
> a limit cannot express."

*Limitation:* for the amount rule alone, a card limit is equivalent. We say so.

---

**7 · What if the agent is malicious?**
> "It proposes, it never decides. We test planners worse than a compromised one —
> one asking for a hundred and fifty thousand francs, one hallucinating items, one
> that crashes. No approval, no money, every time."

*Evidence:* `tests/security/test_agent_planner_boundary.py`.
*Limitation:* the wallet cannot verify a merchant stocks an item. An agent lying
about its own basket gets a truthful evaluation of a false description.

---

**8 · What if the model hallucinates?**
> "There's no model in the path, so the real answer is about the seam: a
> hallucinating planner returns ids that don't exist, the parse fails closed, and the
> deterministic search takes over. Nothing unusable ever widens an errand."

*Limitation:* a model that is confidently *wrong* in well-formed JSON is the case a
fallback cannot catch. That's the eight-out-of-eleven number.

---

**9 · Can the agent learn my spending limit?**
> "Slowly and expensively — about twelve probes and five hundred francs of purchases
> it has to keep, for one ceiling. Ours doesn't, because its objective spends as
> little as it can, so it walks away from the limit rather than toward it. Seven
> francs fifty against a hidden one-thirty-seven."

*Limitation:* that's a property of our planner, not the interface. A different
planner behind the same seam could probe.

---

**10 · So the agent never sees the limit?**
> "The *wallet* never tells it one — that's provable. But the errand is your own
> sentence and your sentence says 'CHF 120', so the number is in its possession. Our
> planner never reads the instruction; it uses the category and how many lines count
> as done. A model planner would read it straight out of the prompt."

*Evidence:* `test_the_SHIPPED_planner_never_reads_the_instruction_at_all`.

---

**11 · Why trust merchant evidence?**
> "You shouldn't, and we don't. Return windows and sizes are merchant claims from
> text we can't verify. The rule is that merchant text can only ever narrow a
> decision, never widen one, and we test that against injection in the description."

*Limitation:* a plausible lie beats us. 'Returns accepted within 90 days' satisfies
any realistic threshold. It's on the refuse list with no fix inside this protocol.

---

**12 · What happens after revocation?**
> "Nothing is authorised, including a purchase already waiting for you. That was a
> real vulnerability — revoke, then answer the pending step-up, and a hundred
> seventy-five francs was charged. Revocation was a sweep over records, and a waiting
> purchase had no record yet. It's run-scoped state now."

*Limitation:* within one process.

---

**13 · What about across sessions?**
> "The rolling cap is per run, matching the platform's own scope. Ten runs put three
> thousand eight hundred francs through a stated three-hundred-a-week cap. We
> disclose that to the customer at confirmation. We do not enforce it."

*Limitation:* and we corrected ourselves — we used to call that a protocol limit.
It's a choice under uncertainty. A ledger prototype lost writes under concurrency.

---

**14 · Double spending?**
> "At most once, within one process, by construction — the execution lifecycle lives
> on the decision record rather than in a second object. Two records describing one
> authorization was the shape that produced four separate vulnerabilities. Eight
> concurrent charges give one charge."

*Limitation:* not exactly-once, not across processes. It's on the refuse list.

---

**15 · What if the wallet is down?**
> "Nothing is authorised. The agent holds no authority to fall back on, so it fails
> closed by construction rather than by a check."

*Limitation:* we don't know what the platform does on a missed deadline. The spec
doesn't say. If silence approves, our failure mode is wrong and it's the first thing
we'd change.

---

**16 · What's actually novel?**
> "Not the rules engine, and not one-shot mandates — SEPA and Google's AP2 intent
> mandates are prior art and we cite them. What we haven't found prior art for is
> refusing an agent in a form it can act on while withholding everything it could
> probe with, and pricing the leak that's left in francs."

*Limitation:* 'we didn't find prior art' is not 'there is none'.

---

**17 · Who pays for this?**
> "The card issuer. They carry the loss when an agent spends wrongly, they're already
> in the authorization path, and they already hold the purchase history the
> familiarity rule needs."

*Limitation:* no customer discovery, no pilot, and we have no market-size number.

---

**18 · What's reproducible?**
> "All of it, offline. The replay is byte-identical run to run. The benchmark and the
> architecture comparison are byte-identical. We ran the demo forty times across two
> server restarts plus eight concurrent sessions — same trace every time."

*Limitation:* 19/2/24 is a regression boundary, not a score. The dataset says
`contains_expected_decisions: false`.

---

**19 · What are you not claiming?**
> "There's a document for it and it's the one I'd rather you read. Exactly-once
> payment. Capping total spend. Cross-session enforcement. Detecting merchant lies.
> Understanding intent. Formal proof of anything."

*This is the strongest card. Play it before being asked.*

---

**20 · Did you find anything wrong with your own work?**
> "Several, this week. The demo was quoting real item ids with fabricated names — a
> hotel room on screen as pantry restock. A pending step-up told the customer it was
> approved. And the customer view sat under `/api/agent/` keyed on an id the agent
> chooses, so an agent could read the whole policy in one GET instead of twelve
> probes. All three are fixed, tested and written up."

*Why answer this fully: a team that can name its own defects precisely is the one
whose remaining claims are worth believing.*
