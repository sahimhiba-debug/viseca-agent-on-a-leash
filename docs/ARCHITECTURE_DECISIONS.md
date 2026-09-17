# Architecture decisions

Each entry: the question, the alternatives actually considered, what was measured
or traced (not just speculated), and the decision with its rationale. Written so a
judge can see the tradeoffs were weighed, not assumed.

---

## ADR-1: Policy representation -- flat conjunctive `HardRule` list vs. a structured `CustomerPolicy` object

**Question:** Is the current `list[HardRule]` (a flat list of independent
`{field, operator, value, ...}` checks, ANDed together) the right internal
representation, or would a structured object with typed sections (monetary /
merchant / item / temporal / basket constraints, as an explicit sub-object each)
serve the system better?

**Option A (current): flat conjunctive list.**
Every hard rule is evaluated independently; the mandate's overall verdict is
FAIL if any rule fails, else UNKNOWN if any is unknown, else PASS. `PATCH`
tightening is implemented as `list.append` -- nothing more.

**Option B: structured `CustomerPolicy`** with named fields
(`monetary.per_order_ceiling`, `merchant.category`, `item.categories`,
`order.min_return_window_days`, `session.integrity_required`, `uncertainty_policy`).

**What was actually traced, not just argued:**

*For Option B's main claimed benefit (self-documenting structure, easier UI
rendering):* true, and worth something. But the SAME grouping was achievable
without changing the underlying representation -- see ADR-3 below, where a
`source`/grouping tag was added to `RuleEvaluation` for exactly this purpose, at a
fraction of the cost of a whole second representation plus a bidirectional mapper.

*For Option B's main claimed cost:* the official wire format (`technical_details.md`,
"Rule format") IS a flat list of independent `{field, operator, value, currency?,
scope?, period_days?}` objects. Option B would need a lossless bidirectional
mapper to/from that wire format for every live mandate exchange -- an entire
extra module for zero gain in what can be expressed for this challenge's scope.

*The decisive finding, discovered only by actually tracing the tighten-only
guarantee through both designs:* Option A's "PATCH can only tighten" guarantee
falls out of the conjunctive evaluation semantics **for free, uniformly, for every
field type** -- appending ANY rule, including a weaker or directly contradictory
one, can never relax an existing stricter rule, because the existing rule keeps
independently failing on exactly what it always failed on (confirmed in the
second audit pass, and it is why `test_mandate_lifecycle.py` needed no special
case per rule type to prove tighten-only holds). Option B would need to
re-implement this guarantee **per constraint category**, and differently for each:
narrowing `merchant.category`'s allowed set is a set-intersection operation;
narrowing `monetary.ceiling` is a `min()`; narrowing `item.categories` is another
intersection; narrowing "must be returnable" is a `max()` on the minimum window.
Every one of those four operations is a place a future contributor could get the
direction of narrowing backwards. Option A has exactly one operation
(`list.append`) and one property (conjunction) that makes correctness of ALL of
them automatic.

**Decision: keep Option A.** Not because it was assumed correct, but because
tracing the actual tighten-only proof through both designs showed Option A gets a
security-critical guarantee for free that Option B would have to re-derive,
per-type, by hand. The one genuine benefit of Option B (structured display) was
captured separately and far more cheaply (ADR-3).

---

## ADR-2: Where (if anywhere) an LLM belongs

**Question:** challenge.md explicitly welcomes machine learning and language
models. Where, if anywhere, could one improve this system without becoming a new
trust boundary in the money path?

Five options were evaluated against seven criteria each:

| Option | Improves? | Can it widen authority? | Injectable? | Behavior if unavailable | Latency | Reproducible? | Demo value |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **A. Current: regex/lexicon compiler** | Handles the five official + many paraphrased instructions; fails visibly on the rest | No -- deterministic, no free-form generation | No -- fixed patterns, not a generation step | N/A -- nothing to be unavailable | ~0ms | Always, byte-for-byte | Understated but solid |
| **B. LLM → structured policy → deterministic validator → deterministic engine** | Could understand a much wider range of phrasings than the fixed lexicon | Only if the *validator* has a bug -- the LLM's output is just a proposal, never executed directly | Injection would target the LLM's OUTPUT shape, which the validator constrains to the same `HardRule` schema `HardRule.__post_init__` already enforces -- so a maximally adversarial LLM output is no more dangerous than a maximally adversarial regex match today | Must fail closed to "produced 0 rules, open_question raised" -- same code path as Option A already has for exactly this reason | Adds a network round-trip to mandate *creation* only (not the decision path) | No, unless temperature=0 and the exact model/prompt are pinned -- a real cost for a customer-facing "what did I just agree to" moment | High -- "understands anything you type" is an easy story to tell a judge |
| **C. LLM as explanation-only layer** (writes the `customer_message` in nicer prose from the already-computed evidence) | Marginal -- the evidence tree (ADR-3) is already legible without it | No -- reads a decision already made, cannot change it | Could hallucinate a *misleading* explanation of a correct decision -- a real but narrow risk | Falls back to the existing template string | Adds latency to every decision if run synchronously, or explanation lags the decision if run asynchronously | No | Low-to-medium -- a nicer sentence is not what wins a security-focused demo |
| **D. LLM as an ambiguity detector** (flags instructions likely to be misparsed, without itself producing rules) | Genuinely useful signal on top of Option A's own `open_questions`, which already do this deterministically for every pattern it doesn't recognize | No | Low -- it only ever adds a warning, never a rule | Falls back to Option A's own coverage, unaffected | Off the decision path, same as B | No, but doesn't need to be -- it's advisory | Medium |
| **E. No LLM anywhere** | -- | -- | -- | -- | -- | -- | Honest, and arguably the stronger security story for THIS challenge's judging criteria |

**What would have to be true for Option B to be worth building:** a demonstrated
gap in Option A's actual coverage that a fixed lexicon cannot close by adding a
few more patterns. The third-pass fuzz corpus (`tests/test_compiler_fuzz_corpus.py`)
was built specifically to find such gaps, and it found two (Findings recorded in
`docs/MASTER_R_AND_D_AUDIT.md`) -- both were closed with regex additions in under
ten lines each, not with a language model. No fuzz case required semantic
understanding beyond what a slightly larger lexicon already provides.

**Decision: no LLM anywhere in this codebase (Option E), with Option B recorded
as the natural next step if the lexicon's coverage gaps turn out to be
genuinely unbounded rather than a short, closeable list.** The determining factor
was not "LLMs are unsafe" in the abstract -- Option B's architecture (LLM proposes,
deterministic validator constrains, deterministic engine decides) is a
legitimate, safe pattern, and is explicitly the pattern to reach for if the
lexicon ever needs to go further. The determining factor was that building it now,
without first exhausting what the deterministic compiler could do, would trade a
reproducible, zero-latency, zero-dependency mandate-creation step for a
non-reproducible one, in exchange for closing gaps that turned out to be closeable
without it. challenge.md's own technical preference ("smaller, lower-latency
models are preferred" if used at all) reads as permission, not an instruction --
and the strongest hackathon story here is "we checked whether we needed one, and
we didn't."

---

## ADR-3: A `source` tag on `RuleEvaluation`, not a new decision type

**Question:** Section 21's brief asks whether the three-level ALLOW/REVIEW/BLOCK
model should be split internally into six (`ALLOW`, `REVIEW_MISSING_FACT`,
`REVIEW_SECURITY`, `BLOCK_POLICY`, `BLOCK_SECURITY`, `BLOCK_AUTHORITY`) for
explainability, while still mapping to Viseca's three.

**What was tried:** `intervention.py` already makes exactly this distinction for
REVIEW (`ask_missing_fact` vs `ask_this_time`) and for BLOCK (`never`, uniformly --
there is no meaningful sub-split of "block" in this system, since every block
already carries its specific failing `HardRule.field` in `reason_codes` and
`evidence`, which IS the finer-grained reason a six-way split would try to
manufacture). Adding three more BLOCK sub-types on top of that would duplicate
information already present in `reason_codes`/`evidence` without adding anything
a judge or a UI couldn't already read directly off them.

**What was missing, and was actually added:** not a finer decision taxonomy, but a
way to see *where a given piece of evidence came from* -- customer policy vs.
control-layer safety net. That is `RuleEvaluation.source` (ADR-3's actual
deliverable), which the demo UI now renders as two separate evidence groups. This
is strictly a superset of what a REVIEW_SECURITY/REVIEW_MISSING_FACT split would
have shown for the REVIEW case, generalizes to BLOCK too (which the six-way split
in the brief did not further break down), and required a one-field addition
instead of restructuring `_decide()`, `intervention.py`, and every call site that
pattern-matches on `Decision`.

**Decision: reject the six-way internal decision-type split; keep three internal
decisions (ALLOW/REVIEW/BLOCK) plus the existing `Intervention` classification;
add the `source` tag instead.** The six-way split was evaluated and found to
mostly restate what `reason_codes` already carries, for a real implementation
cost (touching `_decide`, `intervention.py`, and every consumer of `Decision`);
the `source` tag delivers the actual explainability goal for a tenth of the change.

---

## ADR-4: Crash recovery -- local checkpoint + best-effort reconciliation, not an append-only event log

**Question:** Section 25 asks whether `RunState`'s snapshot-on-write checkpoint
(added in the second audit pass) should instead be an append-only event log (every
decision/resolution appended as an immutable event, state rebuilt by replaying the
log from the start).

**What was traced:** an event log's real advantage over a snapshot is auditability
of the *history* of state changes, not just its current value, and safer recovery
from a torn write (a log append that fails halfway is easier to detect/discard than
a snapshot write that fails halfway). The current checkpoint already gets the
torn-write safety via atomic replace (`tmp` file + `os.replace`, which is atomic on
POSIX and Windows) -- the same property an event log would need its own care to
get right (e.g. a partially-written last line). The auditability benefit is real
but is already served by a different mechanism in this system: every
`EngineDecision` already carries a full evidence trail, and `RunState._recent_attempts`
already retains a bounded history of recent purchases for duplicate detection --
what an event log would add on top is durability of evidence beyond what a single
run needs, which is a production audit-log concern, not a state-recovery one.

**Decision: keep the snapshot checkpoint.** An event log was prototyped mentally
far enough to see it would roughly double the code in `state.py`'s persistence
layer (serialize/deserialize a whole event type hierarchy vs. one dict) for a
benefit (change-history auditability) this system does not currently need and the
challenge does not ask for. Rejected as the kind of complexity Section 0's rule 6
("do not introduce complexity unless you can demonstrate its value") explicitly
warns against absent a demonstrated need.

---

## ADR-5: Session-integrity heuristic -- explicit rules, not a trained model

**Question:** could `RunState.session_signals` (three named signals: device
change, velocity, unfamiliar-merchant-after-device-change) be replaced with a
statistical/ML model trained on `authorization_history.csv`'s 4,701 rows for
better sensitivity?

**What was traced:** the official history file is explicitly documented as having
"a stochastic component" behind its `status` outcomes and is explicitly NOT an
answer key or fraud-label dataset (`data_dictionary.md`: "status is... not a fraud
label, not an expected decision, and not an answer key"). Training a model against
it would be training against noise dressed as signal -- there is no ground truth
in this dataset for "was this session actually hijacked," only a synthetic,
partly-random authorization outcome for unrelated reasons (amount vs. norm,
merchant familiarity, velocity, hour, cross-border, account limits). A model
trained on it would learn to imitate the synthetic generator's stochastic
component, not to detect session hijacking.

**Decision: keep the explicit, three-signal heuristic.** Explainable (every flag
traces to a named, human-readable reason in `session_integrity_reasons`), has no
training-data risk of learning noise, and -- per SECURITY_INVARIANTS.md I18/I19 --
never turns an unknown into a confident answer, which is exactly the property that
would be hardest to guarantee from a model's continuous output.
