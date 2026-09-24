# Independent adversarial security audit

<!-- snapshot -->
> **SNAPSHOT — written 19 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

Audit of the wallet-control system at `0f9af11`. Evidence is the repository, the
official specification and schemas, and runtime behaviour I exercised myself. Prior
research conclusions were read only after forming my own, and are cited only where I
verified or contradicted them.

**Declared conflict of interest.** I am the same agent that performed the earlier
campaigns on this repository. My independence is structural, not genuine. I
compensated by re-deriving evidence rather than citing it, and by constructing
corpora deliberately *not* drawn from the system's own vocabulary — which is how the
principal finding below was reached. A reader should weigh this section accordingly;
it is the most important limitation of this report.

---

## 1. Executive summary

**No CRITICAL finding. One HIGH.**

The security core is genuinely hard. I swept every leaf field of an authorization
event with ten mutation classes each (920 mutations), attacked the ledger, the
execution boundary, the step-up path, the concurrency model and the platform payload,
and found no way for a compromised *agent* to obtain spending authority beyond the
compiled policy. Everything documented as fixed, I re-tested and found fixed.

The HIGH finding is not in the security core. It is upstream of it, and it needs no
compromised agent at all:

> **A customer writing "Buy groceries but never spend more than CHF 40 on any single
> order" gets a mandate with no spending ceiling.** I measured a **54% recognition
> rate** (19 of 35) across ordinary English phrasings of a per-order limit. A single
> CHF 25,000 purchase was approved against that stated CHF 40 limit.

This is *disclosed* — the compiler emits "No per-order spending ceiling was
recognized" every time — so it is not a silent weakening, and the system's safety
property holds. But the prior audit's headline evidence (**"4,800 generated
instructions, 0 silent losses"**) was generated from phrasings the compiler already
recognises, so it measured the compiler against its own vocabulary and could not have
discovered this. That methodological point is the most useful thing in this report.

## 2. Baseline (observed, not quoted)

| | |
| --- | --- |
| commit | `0f9af11`, clean tree, 86 commits ahead of `main` |
| `main` | `1aa3bac`, untouched |
| suite | 877 passed, 5 skipped |
| official replay | 45 events — 19 allow / 2 review / 24 block |
| runtime | 5,484 lines across 19 modules |

## 3. Attack surface as I mapped it

Three entry points (`api`, `live_worker`, `offline_replay`); two most-depended-on
modules (`mandate`, `state`); one execution point (`MockPSP.charge`). Externally
supplied surface: the authorization event (92 leaf fields), the resolve endpoint, the
customer's instruction text, and the platform's echoed `mandate` block.

## 4. Findings by severity

### HIGH — F1. Ordinary restrictive English compiles to no ceiling

**Component:** `policy_compiler._AMOUNT_RE`.
**Reproduction:**

```python
from wallet_control.policy_compiler import compile_instruction
c = compile_instruction("Buy groceries but never spend more than CHF 40 "
                        "on any single order. Ask me when uncertain.")
[r.field for r in c.hard_rules]       # ['item.category'] -- no ceiling
```

Six distinct-basket purchases against that mandate: CHF 10, 250, 999, 4 999, 9 999,
**25 000** — **all ALLOWED**, CHF 41 257 total, against a stated CHF 40 per-order limit.

**Measured coverage**, corpus written without consulting the compiler's patterns:

| | |
| --- | --- |
| recognised | 19/35 (54%) |
| not recognised | 16/35 — `never more than`, `nothing over`, `capped at`, `limited to`, `do not exceed`, `not exceeding`, `no higher than`, `a CHF 40 cap`, `CHF 40 ceiling`, `within CHF 40`, `max CHF 40`, … |
| **not recognised AND not flagged** | **0** |

**Exploit preconditions:** none. A customer writes ordinary English.
**Security impact:** unbounded per-order spending against an explicit stated limit,
*if the mandate is confirmed despite the warning*. Under `uncertainty_policy=ask`
unrecognised mandates escalate everything (safe, but the product does not function);
under `approve`, CHF 5 000 is approved outright.
**Aggravating factor:** `scripts/run_live_worker.py` compiles, drafts and **confirms
automatically** — its own comment says *"In a real product this pauses for the
customer's explicit confirmation."* On that path nobody reads the warning.
**Reachable in the official challenge?** The five official instructions all use
recognised phrasings, so the replay is unaffected. Any customer-authored mandate is
exposed.
**Changes official replay?** No.
**Minimal fix:** extend `_AMOUNT_RE` with the negation and noun forms above, and add
a coverage marker for "an amount appears in the text but no ceiling rule was created"
(today the generic no-ceiling question carries this, which is why nothing is silent).
**Regression test:** the 35-phrase corpus, asserting recognition or an explicit flag.
**Second-order risk:** broadening an amount regex risks matching amounts that are not
ceilings (e.g. "I spent CHF 40 last week"). The flag-don't-guess default is safer and
should remain for anything ambiguous.

### MEDIUM — F2. `authorization_id` uniqueness is load-bearing and undocumented

**Component:** `state.RunState` ledger keying + `decision_engine` repeat fingerprint.
**Reproduction:** five genuinely distinct CHF 100 orders sharing `authorization_id=""`
with identical baskets, under a CHF 300 / 7-day cap:

```
order 1 -> allow (replay=False)      window counted: CHF 100
order 2 -> allow (replay=True)       real orders:    CHF 500
order 3 -> allow (replay=True)       cap:            CHF 300
order 4 -> allow (replay=True)
order 5 -> allow (replay=True)       -> under-counted by CHF 400
```

Control with unique ids: `allow, allow, allow, block, block`, window CHF 300.

**The asymmetry is the finding.** A colliding id with a *different* fingerprint fails
**closed** (`authorization_id_conflict` → block, verified). A colliding id with the
*same* fingerprint fails **open** — it is indistinguishable from a legitimate retry,
so the purchase is approved and not counted.
**Preconditions:** the platform issues duplicate ids within a run. Not agent-reachable.
**Official relevance:** `technical_details.md` implies uniqueness ("stays the same
within a run but changes between runs"); all 45 official ids are unique.
**Why it is a finding anyway:** `docs/FINAL_AUDIT_PACKAGE.md` lists seven "Protocol
assumptions I depend on" — including schema validity, run-scoped counters and clock
domains — and **does not list id uniqueness**, which is the only one whose violation
fails open rather than closed.
**Minimal fix:** documentation (add assumption #8). Optionally reject a non-empty-
string id, which closes the degenerate cases without touching the retry path.

### MEDIUM — F3. The worker adopts the platform's echoed policy unverified

**Component:** `live_worker._handle_envelope` → `MandateSnapshot.from_event_mandate`.
**Reproduction:** the first event of a run carrying a widened `mandate.hard_rules`:

```
drafted  : billing_amount_chf <= 400, merchant.familiar, item.category, item.name_contains
adopted  : billing_amount_chf <= 10000
CHF 9,000 gold bar at an unknown seller -> drafted BLOCK / adopted ALLOW
```

`scripts/run_live_worker.py` holds `compiled.hard_rules` and never compares them to
what comes back. The tighten-only invariant protects the `Mandate` object, **not this
path**.
**Preconditions:** the platform or the transport alters the rules. Not agent-reachable.
**Minimal fix:** pass the drafted rules to `LiveWorker` and refuse a run whose first
event echoes anything wider. Cheap, because both values are already in hand.
**Second-order risk:** the platform legitimately adds `customer_id`/`card_id`/
`profile_id` at run start, so the comparison must cover `hard_rules` and
`uncertainty_policy` only.

### LOW — F4. Payment-authority TTL is pinned by nothing

Found by my own mutation set. Changing `DEFAULT_AUTHORITY_TTL` from 15 minutes to
**3 650 days** passes the entire suite. Expiry *is* enforced (a charge a year later is
refused), and issue/consume are consistently on the real clock — I verified both — but
no test asserts that an authority expires or at what horizon, while the architecture
documents "a narrow, expiring, inspectable payment authority". **Minimal fix:** one
test pinning the horizon.

### LOW — F5. Per-process budget multiplication is an unstated corollary

Two workers restored from one checkpoint each enforce the CHF 300 window
independently: **CHF 600 approved against a CHF 300 cap**. The refusals document
double-*charging* ("at-most-once, per process") and cross-*run* resetting, but not the
third combination — the *budget* multiplying per process within one run. Same root
cause, not a new vulnerability; stated here because a reader of the refusals would not
derive it.

### INFORMATIONAL — F6. `evidence[0]` can read `[pass]` on a blocked decision

On AU0007/AU0008 the per-purchase rule passed while the period rule failed, so the
first evidence line of a BLOCK says `[pass]`. `evidence` is a technical field by
design; noted only because a judge scanning it could misread the outcome.

## 5–9. Impact summary

Nothing I found lets a compromised **agent** exceed the compiled policy. F1 is an
*intent* failure reachable by an ordinary customer; F2 and F3 require the platform to
misbehave; F4 and F5 are coverage and documentation gaps.

## 10. Concurrency

Verified independently: within one process the decision path is atomic and
`charge()` is a genuine compare-and-set (8 concurrent charges → exactly 1 succeeded).
Across processes, both documented failures reproduce, plus F5. **The missing primitive
is precise: a shared atomic store with compare-and-set on the decision ledger.** The
protocol exposes none — the documented endpoints are bootstrap, reference-data,
mandates GET/PATCH/DELETE and team/reset, and none returns or updates accumulated
spend. I agree with the prior conclusion that this is a protocol limit, having
re-derived it.

## 11. Lifecycle

`revoke → resolve`, `resolve → revoke`, `resolve → retry ×5`, `revoke → revoke`,
malformed/null/list/wrong-case resolve payloads, unknown ids: all fail closed or are
idempotent. Tightening mid-run correctly does not apply (`technical_details.md`:
*"Changes affect later runs"*). Restart does not resurrect a consumed authority.

## 12. API / platform path

I reconstructed the submitted payload for all 45 official decisions and scanned
`customer_message` for engine internals (outcome vocabulary, list reprs, dotted field
names, variable dumps): **0 leaks**. Messages are prose and correctly distinguish a
rolling-window breach from an oversized order. `reason_codes` and `evidence` are
technical by design and the spec sanctions that.

## 13. UI

At 375×812, 390×844 and 412×915 with a 123-character merchant name,
CHF 1'234'567'890.99, 25 line items and six simultaneous reasons: no horizontal
overflow, no clipped element inside a decision card, no interactive element below the
44px touch target. The step-up card states its own scope. **The basket shown to the
customer carries name/quantity/category only — no per-line prices** — which
incidentally closes the one integrity gap I looked for there (`unit_price` is never
reconciled against `items_subtotal`, but is also never displayed).

## 14. Evidence

Withholding evidence does not buy permissiveness: with a maximal mandate, deleting or
nulling `item_details`, `item_name`, `merchant_category` or `order_returnable` all
move the decision away from ALLOW. Quantity remains unrepresentable and unchecked —
confirmed independently, and correctly documented as a vocabulary limit.

## 15. Human approval

The answer binds to the stored decision. Amount, merchant and basket swaps during the
step-up window are rejected as conflicts; only the shown amount and merchant can be
charged. Five identical resolves are idempotent (4 approvals, CHF 687.00 either way).

## 16. Compiler

See F1. Separately verified: whitespace and case are inert; multiple amounts take the
smaller and flag; `at or below` is `<=` while `under` is `<`; per-order and per-week
are distinguished; negation forms are unparsed but flagged.

## 17. Test-suite weaknesses

I wrote an independent mutation set targeting constants the project's own probe does
not touch — duplicate window, velocity window, integrity tolerance, FX rate,
`is_revoked`, empty-basket path, authority TTL. **7 applied, 1 survived** (F4). That
is a strong result for a suite tested with mutants it was not written against.

The real weakness is not in the tests but in the **corpus that validates the
compiler**: it is generated from the compiler's own vocabulary, so its "0 silent
losses over 4,800 instructions" cannot detect an unrecognised phrasing. F1 lives
entirely in that blind spot.

## 18. Claims audit

I could not find an overbroad claim in the user-facing surfaces. The UI's
"exactly-once" string is inside its *"What we do not claim"* list; the demo script
carries a *"What NOT to say"* section that pre-empts the four most dangerous claims.
The prior conclusion *"A — adequately bounded"* is narrowly worded ("for the kinds of
restriction the compiler knows about") and is not false — but its headline number
invites a reader to infer near-complete coverage where the measured figure is 54%.
**Recommend restating it with that number.**

## 19. Strongest unresolved attack

F1, in its most damaging form: a customer writes a clear limit in an unrecognised
phrasing, the mandate is confirmed on the auto-confirming worker path where the
warning is never read, and the wallet enforces no ceiling. No agent compromise
required.

## 20. What held under attack

920 field mutations; id collision with differing fingerprint; step-up binding under
three swap classes; repeated and concurrent resolution; revocation orderings; restart;
the execution compare-and-set; platform payload hygiene; the two-verdict relation
(`decision == stricter(policy, security)`, **0 violations in 2 000 randomized
decisions**, re-derived); and six of my seven independent mutants.

## 21. Could not be verified

* Behaviour against the **hosted API** — everything here is offline.
* What the **platform** does on a missed deadline; undocumented and unobserved.
* Whether the platform **enforces `authorization_id` uniqueness** (F2 assumes it does).
* **My own independence**, as declared above.

## 22–23. Recommended fixes, in priority order

1. **F1** — extend the amount vocabulary and add an "amount present but no ceiling
   created" marker. *Highest value: it is the only finding reachable without a
   platform fault.*
2. **F1a** — make `run_live_worker.py` refuse to auto-confirm a mandate carrying a
   no-ceiling warning, or require an explicit flag. Small change, removes the
   aggravating factor.
3. **F3** — compare drafted rules against the first event's echo; refuse anything wider.
4. **F2** — document id uniqueness as protocol assumption #8; optionally reject an
   empty id.
5. **F4** — pin the authority TTL with one test.
6. **F5** — add one sentence to the refusals.
7. **F6** — no action required.

No fix was applied. This is an audit.
