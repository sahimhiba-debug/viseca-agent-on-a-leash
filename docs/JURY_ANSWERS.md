# Jury answers

Current as of the last commit on this branch. Each answer is one or two spoken
sentences. Under each one: what shows it, and where it stops being true. The older
flash cards (`FINAL_JUDGE_QA.md`) are a snapshot and are not maintained.

---

**What is the innovation?**
> "A spending limit asks *how much*. Our wallet also checks *what for*: which shop,
> which item, whether it can go back, whether it was already bought. It checks this
> against the sentence the customer wrote, and asks them when it can't tell."

*Shows it:* stage, key **S**. The same CHF 289 in eight variations: a card set as
tightly as a card can be says yes to all eight, the wallet says yes to one.
*Stops at:* a card MCC rule would catch a wrong *kind* of shop. It cannot catch a
wrong shop of the right kind, the wrong item, or a second purchase of the same thing.

**Where is the AI?**
> "In the agent, which can run on different brains, Apertus and OpenAI included. None
> of them has authority to pay. The wallet is deterministic, because the brief requires
> a predictable answer when a model is down."

*Shows it:* `research/brains.py`, `tests/test_runtime_boundary.py`.
*Stops at:* no language model sits in the decision path, and that is deliberate.

**What if the LLM is wrong?**
> "It can propose something wrong. The wallet judges the proposal on its own. In our
> benchmark, the models asked the customer unnecessarily and kept a sold-out item in
> the basket, and none of that got a forbidden purchase through."

*Shows it:* `docs/REAL_MODEL_PLANNER.md`, the failure table.

**What if the agent is malicious?**
> "Same boundary. It can propose, it cannot authorise. A deliberately hostile brain
> made 32 proposals: 23 were refused or put to the customer, and the 9 allowed ones
> broke no rule the customer wrote."

*Shows it:* `research/brains.py` (the adversarial row), and the stage's manipulated
agent run.
*Stops at:* purchases the customer's sentence *does* allow are allowed, whoever
proposes them. The leash (revoke) is the answer to that.

**Why not just a card limit?**
> "It controls the amount. In our same-price demonstration, eight purchases at the
> same acceptable amount differ in whether they are what the customer delegated.
> The card can't tell them apart. The wallet can."

*Shows it:* `GET /api/stage/same-price`. Both columns are computed, and a test
shows the card rule does refuse a US shop, CHF 401 or a grocer.

**Did you actually test real models?**
> "Yes. Apertus 1.5 70B on the Swisscom platform and OpenAI gpt-4.1-mini, both behind
> the same planner interface, against the same wallet, three runs each, in two
> experiments."

*Shows it:* `docs/REAL_MODEL_PLANNER.md`. Keys come from environment variables, and
none are in the repository.

**Which performed best?**
> "On our 11-episode benchmark: the deterministic planner 11/11 every run, and both
> models 7 to 8 on their own. The gap between the two models is smaller than their
> run-to-run variance, so we don't rank them. This is our benchmark, not a statement
> about the models."

**What if the model makes a bad decision?**
> "It never makes the decision. The wallet remains the authority. In our tests, the
> worst a real model did was ask the customer needlessly, or keep an item that had
> sold out in a basket the wallet then approved. The wallet can't see stock. None of
> them got through a purchase the sentence forbids."

**Can a seller talk the wallet into it?**
> "No, in 12,960 tries: 288 generated seller attacks against the 45 official
> purchases, and not one decision became more permissive. The customer is told a
> seller tried in about 70% of held-out cases."

*Stops at:* marketing-shaped pushes and most non-English instructions go unnamed,
though never obeyed. A seller can still *claim* the fact a rule checks, and that is a
known limit.

**Is it secure?**
> "Against what we attacked, and we say what we didn't close: spending windows are
> per run, single use is per process, the step-up channel has no authentication in
> the demo, and seller claims are unverifiable."

*Shows it:* `docs/FINAL_AUDIT_PACKAGE.md`, "Known vulnerabilities that remain".
We never say "fully secure".

**Does it work on the real platform?**
> "It ran on the Viseca sandbox with our team key: the one-off rule was accepted and
> only one monitor was approved. During our final checks the sandbox answered HTTP
> 500 to every new run. The stage says so on screen and falls back to the local
> replay of the same data."
