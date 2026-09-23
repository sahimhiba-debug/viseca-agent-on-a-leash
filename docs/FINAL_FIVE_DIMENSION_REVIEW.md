# Final five-dimension review

<!-- snapshot -->
> **SNAPSHOT — written 23 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

No score, no overall verdict. Per dimension: strongest evidence, weakest evidence,
missing evidence, highest-leverage improvement, and whether it is safe before freeze.

---

## 1. Technical functionality and AI

**Strongest.** 981 tests; 39 mutation kills; deterministic replay at 45 · 19/2/24
unchanged across every campaign; byte-identical agent episode; no network, no key, no
model needed to run anything.

**Weakest.** "AI" in the conventional sense is absent by choice. A jury scanning for a
model will not find one.

**Missing.** Evidence that a model-based planner *would* work here. We built the seam
and tested it against five hostile planners; we never filled it.

**Improvement.** A model-backed `Planner` behind the existing seam, off the judged path.
**Safe before freeze? No** — it adds a network dependency to the only dimension we
currently win outright.

## 2. User experience

**Strongest.** Mobile-first at 375/390/412 with hostile content — 123-character
merchant names, CHF 1'234'567'890.99, 25 line items, six simultaneous reasons: no
overflow, no clipping, no target under 44 px. Plain-language reasons. Every step-up
card states its own scope: *"this one purchase only — not a standing exception."*

**Weakest.** Six tabs is a lot for a 2-minute demo; a judge left alone might not find
the Agent tab.

**Missing.** Any test with a person who has not seen it before.

**Improvement.** Make Agent the landing tab for the demo build.
**Safe before freeze? Yes** — one attribute. Not done: it would diverge the demo build
from the reproducible one, and the script already routes there at 0:35.

## 3. Agentic depth

**Strongest.** An agent that plans against an explicit mission, is refused three times,
substitutes rather than merely shrinking, and succeeds on the merits — as an **external
HTTP client**, with the wallet unable to import it (AST-enforced). Nine adversarial
episodes: five replanned, four correctly escalated.

**Weakest.** The ladder is four rules. It is a planner, not a reasoner.

**Missing.** Tool use; semantic substitution ("oat milk for whole milk"); multi-merchant
comparison on anything but price.

**Improvement.** The same model-backed planner as §1.
**Safe before freeze? No**, for the same reason.

## 4. Uniqueness / creativity / fun

**Strongest.** Two audiences for one decision, side by side on screen: the customer sees
CHF 120, the agent sees `blocked_by: [amount]`. Plus a probe that breaks the wallet on
purpose, and a document titled *what we refuse to claim*.

**Weakest.** "Fun" is thin. It is a serious demo about refusal; there is no delight
moment beyond watching the agent fail and recover.

**Missing.** A single image a judge remembers 20 demos later.

**Improvement.** The opening line does that work: *"This is a shopping agent with a
credit card. That should terrify you."* **Safe: yes, already in the script.**

## 5. Potential / market impact

**Strongest.** The problem is real and imminent, and the framing is one issuers do not
yet have an answer to: the danger is not fraud, it is **misreading**. Our measured
numbers support it — CHF 2,999 through a CHF 300 cap across sessions; 12 probes to
learn a ceiling; 204 phrasings with zero silent weakenings.

**Weakest.** No integration with a real issuer stack; `MockPSP` is ours and simulated.

**Missing.** Any evidence of customer demand beyond argument.

**Improvement.** None available in the time; overclaiming here is the easiest way to
lose a payments judge.

---

## Deliberate non-improvements

| candidate | why not |
| --- | --- |
| model-backed planner in the judged path | costs reproducibility, the one criterion we win outright |
| Agent as landing tab | diverges demo build from reproducible build |
| enforcing cross-session limits | not agent-reachable; touches checkpointing during a freeze |
| more tests | 981 is not the constraint; mutation coverage is, and it is at 41/41 |
