# Deep weakness campaign — report

Plan and pre-registered falsifiers: `docs/archive/DEEP_WEAKNESS_ATTACK_PLAN.md`.

**Thesis under test:** *"A delegation is bounded only where an authoritative record
exists at the same scope as the bound."*

---

## 1. Executive summary

**The thesis is necessary but not sufficient, and the campaign found the case that
shows it.** For the cross-run bound an authoritative record at the right scope
*plausibly does exist* in the protocol — and the delegation is still unbounded,
because the record's *shape* is undocumented. Existence is not enough; the record
must also be reliably readable. That refinement is the campaign's main conceptual
result.

Two falsifiers fired:

* **F1 — an authoritative cross-run record is reachable.** `POST /v1/team/reset` is
  documented to clear *"your team's mandates, runs, decisions, and event"* state, so
  the platform holds decisions **team-scoped, spanning runs**. The justification
  previously recorded — *"a protocol limit, not a preference"* — was **overstated**
  and has been corrected.
* **F4 — a restrictive instruction was silently weakened.** *"at most CHF 200 but
  never over CHF 100"* enforced **CHF 200**, unflagged. Found by a 204-phrase semantic
  corpus. **Fixed.**

F2, F3, F5 and F6 did not fire. Two code changes were made, both in the compiler;
one of them introduced a crash which the corpus caught minutes later and which is
also fixed and pinned.

## 2. Attack 1 — cross-run / scope escape

**Status: DOCUMENTED LIMITATION (exposure) + REAL CLAIM DEFECT (justification, corrected).**

| question | answer |
| --- | --- |
| Reachable by the *agent*? | **No.** `POST /v1/scenario-runs` is called only by our operator script and demo API. The agent proposes purchases; it cannot create runs. **F2 did not fire.** |
| Authoritative mandate identity across runs? | `mandate_id`. `PATCH` is documented *"for later runs"* — the protocol expects reuse. |
| Authoritative identity of the rolling window? | **This is the gap.** The platform's own `context` is run-scoped, but the underlying *decisions* are team-scoped. |
| Can the existing ledger carry the bound? | **Yes** — by keying worker state on `mandate_id` rather than `run_id`. That is a re-scoping of an existing object, **not a new security object.** |
| Would it violate protocol semantics? | No. Rules stay per-run (`"A run uses a snapshot"`); only the *spend ledger* would widen. |
| Is the run boundary a real security boundary? | **No — it is an implementation artifact.** Nothing in the customer's sentence "CHF 300 across any seven days" refers to a session. |

**Strongest adversarial trace (reproduced).** Customer: CHF 150/order, CHF 300 per
7 days. Ten runs under one mandate, every purchase inside **one** seven-day window,
each run stopping at CHF 299.90:

```
run  1: CHF 299.90   cumulative 299.90     each run believes it is at 299.90 / 300
run  2: CHF 299.90   cumulative 599.80
...
run 10: CHF 299.90   cumulative 2999.00    -> 10.0x the stated cap
```

Every individual decision is correct under run-scoped semantics. No forged field, no
malformed input, nothing to detect.

**Why it is not fixed in this campaign.** It is not agent-reachable, so it is an
operator-controlled exposure rather than an attack. Re-scoping run state touches
checkpointing (`_checkpoint_path` is keyed by `run_id`), and doing that during a
freeze is the kind of change that trades a documented limitation for an undocumented
one. **Recommended as the next phase**, with the design already established above.

**What was fixed:** the claim. `WHAT_WE_REFUSE_TO_CLAIM.md` now states that an
authoritative cross-run record plausibly exists, its shape is under-documented, we
cannot verify it offline, and we *chose* not to rely on it — which is what our own
`reconcile_run` docstring has said all along (*"isn't documented well enough to trust
a reconstructed amount/timestamp"*).

## 3. Attack 2 — step-up identity

**Status: SAFE, with one OUT OF SCOPE.**

| attack | result |
| --- | --- |
| wrong human | **OUT OF SCOPE** — `POST /resolve` carries no resolver identity. A protocol absence, not an implementation defect. |
| stale approval (`resolved_at` 30 days before the purchase) | **SAFE** — spend is placed at the *purchase* timestamp (`state.py:435`), so a backdated approval cannot move the rolling window |
| approval after revocation | SAFE — block |
| approval for another authorization | SAFE — refused |
| mismatched amount (100 → 9 000) | SAFE — stored CHF 100, the shown amount |
| replayed approval | SAFE — idempotent, counted once |
| double approval, flipped | SAFE — refused |
| approval copied between authorizations | SAFE — the other stays `review` |
| approval before the step-up existed | SAFE — refused |
| resolving an auto-decided purchase | SAFE — refused |
| approval after tightening | SAFE — the human override is per-purchase; tightening applies to later runs by spec |

UI authentication was not counted as a protection anywhere above.

## 4. Attack 3 — semantic intent compiler

**Status: REAL VULNERABILITY → FIXED.**

204 phrases, 15 classes, written by enumerating how people speak.

| | before | after |
| --- | --- | --- |
| 1 correctly represented | 104 | 104 |
| 2 correctly unsupported (flagged) | 98 | 98 |
| **3 silently weakened** | 0 | **0** |
| **4 incorrectly strengthened** | 0 | **0** |
| 5 incorrectly interpreted, unflagged | **2** | **0** |
| 6 looser than stated, named back | — | 2 |

**The finding.** *"Buy groceries at most CHF 200 but never over CHF 100"* enforced
**CHF 200** — the looser bound — and said nothing.

*Root cause:* the defensive `min()` compares only amounts the compiler **parsed**. A
stricter bound phrased unrecognisably is invisible to it, and the multi-amount
ambiguity question needs two *parsed* figures to fire, so every existing guard missed
it.

*Fix, and why it discloses rather than guesses:* every CHF figure in the text is now
compared against the figures used in rules, and any unused one is named back. Taking
the minimum of all figures would "fix" this case and break *"I spent CHF 40 last
week"*. The notice is **advisory, never blocking** — making a sentence containing a
number unconfirmable would destroy the *harmless unknown language* category the
confirmation gate exists to protect.

*Attack against the fix, which succeeded:* the first pattern `CHF\s*([\d.,]+)`
matched the `chf.` in *"max 200 chf."*, captured the full stop alone, and
`_parse_amount(".")` **crashed `compile_instruction`** — a denial of service on the
mandate-creation path, reachable by a customer ending a sentence with the currency.
Caught by re-running the corpus against the fix minutes after writing it. Fixed
(`\d[\d.,]*`) and pinned with four regression cases.

**Multi-sentence precedence** behaves as the compiler documents: later clauses do not
override earlier ones; all parsed figures are collected and the smallest is used
defensively, with the ambiguity named.

## 5. Attack 4 — evidence provenance

**Status: DOCUMENTED LIMITATION, bounded more precisely than before.**

The decisive question — *can an attacker cause an ALLOW by manipulating only a
non-authoritative fact?* — is **yes, within a bounded set.**

| fact | source | can it cause ALLOW? |
| --- | --- | --- |
| `order.return_window_days` | **merchant free text** | **yes** — REVIEW → ALLOW |
| `item.size` | **merchant free text** | **yes** — REVIEW → ALLOW |
| `billing_amount_chf` | platform, recomputed from `amount × fx` | no |
| `merchant.familiar` | derived from authorization history | no |
| `authority_status`, `card_status`, `mandate.status` | platform | no |
| `recent_attempt_count_10m` | platform, cross-checked against our own log | no |
| basket contents, quantity | agent | no (quantity is unrepresentable) |

**Reproduced:** a mandate requiring size 43 and a 14-day return window goes
REVIEW → ALLOW purely on merchant-declared text, including an implausible
*"returns accepted within 999 days"*.

**Bounded, and this is the useful part:** merchant text can only satisfy rules *about
merchant-declared facts*. It cannot raise a ceiling, fake familiarity, or override a
platform status — verified: merchant text claiming `authority_status=active` against
a platform `revoked` still blocks. The exposure is exactly the two fields whose only
source is the merchant.

## 6. Attack 5 — autonomy vs friction

**Status: PROVEN SAFE on the measured corpus.**

| | official corpus (45) |
| --- | --- |
| ALLOW | 19 (42.2%) |
| REVIEW | 2 (4.4%) |
| BLOCK | 24 (53.3%) |
| **human interventions per legitimate purchase** | **0.095** (2 of 21) |

**Block attribution: 33 customer-policy violations, 0 wallet safety checks.** The
wallet adds no friction of its own on the official corpus — every block is the
customer's own rule firing.

The two REVIEWs are a genuinely unstated return window and a genuine duplicate
suspicion. **No false friction found.** The candidate *false autonomy* is repeated
purchase against an inexpressible quantity ("buy **one**"), which is the documented
vocabulary limit and now blocks confirmation until acknowledged.

## 7. Second-order attacks

Twelve multi-dimensional traces over the seven named interactions. **All held**, and
one was my own error worth recording:

* cross-run × fulfilment, × quantity, × window stacking — all reproduce the *same*
  single root cause (run-scoping), not separate weaknesses. Four runs stacked in one
  window: CHF 1 192 against CHF 300.
* ambiguity → step-up → human allow: counted once.
* late human approval into a filling window: CHF 250, cap held.
* near-duplicate escalates rather than doubling; revoke-then-charge refused; charge
  redirected to another merchant refused; step-up resolved against another run's
  state refused.
* **Corrected:** I initially recorded "revoke, then a new run allows". That was a
  test error — I revoked the *run state* and left the mandate active. Mandate-level
  revocation does propagate: a new run under a revoked mandate **blocks**.

## 8. Exploitable vulnerabilities

| # | vulnerability | agent-reachable | fixed |
| --- | --- | --- | --- |
| W2 | silent weakening on contradictory instructions | no (customer-authored) | **yes** |
| W3 | crash on `"…chf."` — DoS on mandate creation, introduced by the W2 fix | no | **yes** |

**No agent-reachable vulnerability was found in this campaign.**

## 9. Architectural gaps

**G1 — the run boundary is an implementation artifact standing in for a security
boundary.** The customer's bound is temporal ("any seven days"); enforcement is
sessional. The existing ledger can express the correct scope; nothing architectural
prevents it. **This is the one genuine architectural gap**, and it is not fixed.

**G2 — the evidence model has no notion of unverifiable authority.** Two fields are
merchant-declared with no corroboration, and the engine treats a satisfied rule
identically regardless of who supplied the fact. A provenance-aware engine could
refuse to let a merchant-only fact *upgrade* a decision. Not attempted: it would
change decisions on the official corpus and is a redesign, not a fix.

## 10–11. Fixes proposed and implemented

| fix | implemented |
| --- | --- |
| Name back every stated CHF figure not used in a rule (advisory) | **yes** |
| Require a digit in the currency scan | **yes** (defect introduced by the above) |
| Correct the cross-run refusal to state a choice, not a protocol limit | **yes** (documentation) |
| Key worker state on `mandate_id` to close G1 | **no** — next phase, reasoning in §2 |
| Provenance-aware evidence authority (G2) | **no** — redesign, out of scope |

## 12. Remaining limitations

1. **G1 cross-run** — 10× measured, operator-controlled, design established, unfixed.
2. **G2 merchant-declared evidence** — two fields, bounded, unfixable in the vocabulary.
3. **Quantity, overall total, end date** — inexpressible; disclosed and blocking at confirmation.
4. **Step-up resolver identity** — the protocol carries none.
5. **Per-process budget** — two workers each enforce the window independently.
6. **N3 timestamp-sensitive idempotence** — unchanged from the previous campaign.

## 13. Claims we can safely make

* No agent-reachable way to exceed the compiled policy was found in this campaign.
* Across 204 restrictive phrasings: **0 silently weakened, 0 incorrectly strengthened**.
* On the official corpus, **every block is the customer's own rule**; the wallet adds
  no friction of its own, at 0.095 interventions per legitimate purchase.
* A backdated approval cannot move a purchase in the rolling window.
* Merchant text cannot raise a ceiling, fake familiarity, or override a platform status.

## 14. Claims we must NOT make

* **NOT** that cross-run enforcement is impossible under the protocol. It is
  *under-documented*, which is a different and weaker statement.
* **NOT** that the compiler understands language. 204 phrases from one author is not a language.
* **NOT** that merchant-declared facts are verified. Two can flip REVIEW → ALLOW.
* **NOT** that the step-up channel authenticates anyone.
* **NOT** that 0.095 interventions generalises beyond the official corpus.

## 15. Recommended next phase

Close **G1** by keying worker run state on `mandate_id`, with checkpoint migration —
the design is established and it needs no new security object. Then re-attack it for
the failure modes that killed the earlier file-based prototype: TOCTOU across
processes, and a lost ledger reading as a fresh mandate.

---

## Weakness table

| Weakness | Reproduced | Judged-path | Severity | Fixed | Residual risk |
| --- | --- | --- | --- | --- | --- |
| G1 cross-run multiplication | **yes**, 10.0× | operator-controlled, not agent | **high (intent)** | **no** | a mandate reused across sessions multiplies the stated window |
| W2 silent weakening on contradiction | **yes** | customer-authored | **high (intent)** | **yes** | phrasings outside the corpus |
| W3 crash on `"…chf."` | **yes** | customer-authored | medium | **yes** | none known |
| Claim defect: "protocol limit" | **yes** | n/a | medium (honesty) | **yes** (doc) | none |
| G2 merchant-declared evidence | **yes** | yes | medium | no | 2 fields can flip REVIEW → ALLOW |
| Step-up resolver identity | n/a | yes | medium | no | protocol carries no identity |
| Per-process budget | yes (earlier) | single-worker model | low | no | documented |

---

## The question that matters most

> **After this campaign, what is the strongest remaining way an intelligent autonomous
> shopping agent could extract more economic value than the customer intended while
> still appearing compliant?**

**Nothing the agent controls on its own.** It cannot create runs, forge platform
fields, beat the window inside a run, bypass the ledger, or move a purchase in time.
Every second-order trace collapsed to a root cause the agent does not hold.

The strongest remaining extraction, ranked honestly:

1. **Spend at the cap, forever.** No rule in the official vocabulary bounds a total.
   A perfectly compliant agent draws the ceiling every order, indefinitely. This is
   not an exploit — it is the delegation the customer actually granted, and the only
   defence is telling them so before they confirm. **It remains the largest gap
   between what a customer believes they have limited and what they have.**
2. **Merchant-declared evidence, if the agent can influence the merchant's item
   text.** Claiming a 999-day return window and the requested size converts REVIEW →
   ALLOW on facts nothing can verify. Requires merchant collusion, which is outside
   the stated threat model — but it is the only channel where an unverifiable claim
   moves a decision toward permissive.
3. **Session multiplication, if the agent can induce a new run.** It cannot in the
   judged protocol. In a product where an agent could ask for a new shopping session,
   G1 becomes directly agent-reachable and 10× is immediate. **That is the reason G1
   should be closed even though it is not exploitable today.**

The honest one-line answer: *the agent's best remaining move is not to break the
wallet but to use the delegation exactly as written, because the customer's own
vocabulary cannot express the bound they think they set.*
