# Final deep R&D report

<!-- snapshot -->
> **SNAPSHOT — written 22 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

**The question:** given everything already proven and everything explicitly refused,
is there still a fundamental weakness, missing abstraction, or architectural
opportunity that would materially improve this wallet?

**The answer, in one line:** no missing abstraction — but two real security defects,
both instances of a single class the project had been fixing one at a time without
noticing it was a class.

---

## 1. Executive conclusion

| | |
| --- | --- |
| **Architecture** | **SATURATED UNDER CURRENT PROTOCOL CONSTRAINTS** |
| **Implementation** | **was not saturated** — two exploitable defects found and fixed |
| Major new mechanism adopted | **none.** The one serious candidate was built, measured, attacked and rejected |

Both of the brief's outcomes occurred, and they are not in tension. The *shape* of
the system — one policy object, one write-once security object, one execution point,
`fail > unknown > pass` — absorbed every attack this campaign produced without
needing a new concept. The *mapping from inputs into that shape* had a systematic
bias that had already produced four defects, two of which were still live.

The class: **a claim is believed because its refutation is absent.** It is now
self-policing rather than fixed a fifth time.

## 2. Verified baseline

Re-run, not taken from the brief (`docs/BASELINE_CURRENT.md`). Start: `4fec029`,
`main` untouched at `1aa3bac`, clean tree, 700 collected, replay 45 at 19/2/24,
corpus 133/133, matrix 17/17, probe 18/18. Every figure confirmed.

## 3. Research questions

1. Is the run the right scope for the rolling window, or inherited from a misreading?
2. Is there an abstraction the system needs but does not represent?
3. Do the invariants hold in *combination*, not just individually?
4. Does the engine believe anything it holds independent evidence about?
5. Can an optimiser that actually tries beat the stated bounds?

## 4–5. Hypotheses and cross-invariant findings

Full register in `docs/RESEARCH_LOG.md`, R17–R29. The load-bearing ones:

| # | hypothesis | result |
| --- | --- | --- |
| H1 | The window should be seeded from the card's prior spend | **rejected on measurement** — agent-initiated spend in the 7 days before every scenario is **zero**; nearest is 15+ days prior. Changes nothing. Also wrong in principle: a mandate bounds the delegate, not the principal |
| H2 | `source_authorization_id` enables cross-run dedupe | **rejected** — it is a simulation artefact (it locates a CSV row), and our state is run-scoped anyway |
| H3 | Cancellation should release window budget | **rejected** — `_approved_spend` is append-only with two write sites and no removal. Releasing would permit cancel-and-rebuy past the cap. Conservative is the right direction |
| H4 | A mandate-scoped ledger fixes cross-run exposure | **built, worked, then lost to its own attacks** — §9 |
| H5 | Empty collections are read as satisfaction | **CONFIRMED — defect** — §7 |
| H6 | The event is trusted about its own velocity | **CONFIRMED — defect** — §7 |
| H7 | Mandate tightening should reach a pending decision | **rejected** — spec: *"Changes affect later runs. An existing run keeps its original snapshot."* Revocation is the in-flight brake and has I30 |
| H8 | We invented rule field names the vocabulary forbids | **rejected** — `field` is *"A nonempty string naming the fact to check"*; names are not enumerated. *"No extra rule fields"* constrains the rule object's keys, not field names |

Cross-invariant pairings attacked this campaign: **V** authority expiry × retry,
**W** authority expiry × concurrent execution (8 threads → exactly 1 charge),
**O** fulfilment × cancellation, **Q** fulfilment × merchant substitution,
**Y** decision ledger × malformed event. Four held; **Y found a real defect.**
Nine further pairings held in the previous campaign (R17).

## 6. Architecture findings

**No missing abstraction was found.** Candidates evaluated against the brief's test —
*does it collapse several independent problems?*

| candidate | verdict |
| --- | --- |
| settlement vs authorization | real distinction, but releasing budget on settlement failure *opens* cancel-and-rebuy. The conservative direction is already taken |
| mandate-scoped delegation ledger | §9 — falsified against a protocol limit |
| evidence provenance object | the need was real; it resolved to **semantics**, not an object — §7. Adding a provenance type would have been ceremony around a two-line rule |
| run identity as a security object | the run already *is* the scope of everything. Naming it changes nothing |

The one genuine structural addition is not an abstraction but a **constraint**:
every rule field must declare what absence of its subject means, checked by parsing
`rules.py` with AST (I36).

## 7. Security findings — two defects, one class

**D1 — an empty basket satisfied every item rule it could not check.**
Every `item.*` branch reasons over a list and read an empty list as agreement:
nothing is outside the requested category, no name fails to match, nothing
unrequested is present. A CHF 400 purchase carrying **no items** satisfied four item
restrictions at once, and with no `item.size` rule — four of the five official
scenarios — it was **ALLOWED under every uncertainty policy, `decline` included.**
The strictest setting a customer can choose was not stricter; that asymmetry is the
tell that the problem is structural rather than uncertain.
*Fixed in two layers* (engine: structural hard failure; `rules.py`: `unknown`), so
deleting either leaves the other refusing to answer "pass" to a question whose
subject it cannot see.

**D2 — the event was trusted about how suspicious it was.**
`session.integrity_risk` is driven by `recent_attempt_count_10m`, a claim the event
carries about itself. Four attempts inside one minute with a device change halfway:

| reported | decisions |
| --- | --- |
| honest `0,1,2,3` | allow, allow, **block**, **block** |
| tampered `0,0,0,0` | allow, allow, allow, allow |

Two blocks became approvals — while this run's own attempt log, the one duplicate
detection already depends on, held all four. *Fixed* by `max(reported, observed)`:
`max` because the platform legitimately sees attempts we cannot (one official event
reports 3 where we observe 2), monotone so it can only raise risk.

**The class.** With the earlier `mandate.status` omission and the
`order_returnable: not_applicable` fix, that is **four instances of one defect**,
found and fixed separately. `fail > unknown > pass` is right; the bias is in the
mapping *into* it. Absence lands on `pass` unless whoever wrote the branch remembered
the `unknown` case, and nothing required them to. Now nothing has to remember:
`test_absence_semantics.py` discovers the field list from source and fails on any
field without a declared absence case. Verified non-vacuous.

## 8. Distributed / concurrency findings

The honest guarantee is unchanged and now re-tested: **at-most-once per process**,
enforced at one point by an atomic compare-and-set (8 concurrent charges → exactly 1
succeeded, 7 refused). Two workers restoring one checkpoint can each charge once.
The missing primitive is a shared atomic store; the protocol offers none.

## 9. Cross-run findings — the candidate mechanism, and why it died

Measured exposure: SCEN0001 approves **CHF 387.50 per run** against a stated
CHF 300 / 7 days. Ten runs → **CHF 3,875**, 12.9× the customer's sentence.

`research/mandate_ledger_prototype.py` — append-only, monotone, deliberately not the
shared *mutable* record a previous decision rejected — **held ten runs to CHF 387.50
with a worst window of CHF 299.50.** It worked. Then:

| attack | result |
| --- | --- |
| **A1 TOCTOU** | two concurrent sessions both approved against the same remaining budget, and **the losing write vanished** — the ledger recorded CHF 200 of CHF 400 approved. Record wrong as well as decision |
| **A2 missing ledger** | indistinguishable from a mandate that has never spent. Full budget, silently |
| A3 cross-mandate | held — a foreign `mandate_id` is refused |
| **A4 scale** | 301 ms at 3,000 entries; this is exactly the "ledger scale" where O(n²) was documented as *not* fine |

A1 and A2 need the same thing: an authoritative mandate-scoped spend counter with a
cross-process compare-and-set. **The protocol has none** — the documented endpoints
are bootstrap, reference-data, mandates GET/PATCH/DELETE, team/reset, and GET returns
the stored mandate, never its spend. The mechanism would replace an honest run-scoped
bound with a *claimed* global one that breaks under exactly the conditions motivating
it. **Rejected**, and the limitation is now proven to be protocol-level rather than
asserted to be.

Run-scoping is not our invention: `technical_details.md` scopes the platform's own
context to the run, and its spend field ships **null on all 45 rows**.

**What shipped instead:** the half of the truth a customer cannot guess — that the
window is counted per shopping session and starts at zero when the agent runs again.

## 10. Evidence / provenance findings

Modelled as authoritative / platform-derived / merchant-declared / inferred /
unknown. The sweep (§7) asked, for all ten recognised fields, whether absence yields
`pass`. **One did** (D2). Merchant-declared text remains the largest exposure and is
unfixable inside the vocabulary — `order.return_window_days` and `item.size` have no
input but merchant free text. No provenance *object* was added: the need resolved to
rule semantics.

## 11. Human-consent findings

I31 — *"the customer's answer binds to the purchase they were shown"* — was the only
security invariant in the register citing a research campaign rather than a test.
Attacked with three swaps during the step-up window (amount CHF 100 → 900, merchant,
basket). All rejected as conflicts; the stored decision keeps the shown facts; at the
execution boundary only the shown amount **and** merchant can be charged. Now four
tests, asserting the outcome rather than either mechanism.

## 12. Economic optimiser findings

`scripts/run_economic_optimizer.py` — the agent controls amount, timing, merchant,
basket, quantity, item text, device, claimed velocity and step-up resolution order.
9 strategies × 200 trials = **1,800 trials, 0 window breaches**, window filling to
exactly **300.00** against a CHF 300 cap. Tight, not over-conservative — an
enforcement that never approaches its bound has not been shown to work.

Best totals reach CHF 1,559 and that is **not** a breach: no rule the official
vocabulary can express bounds the total. The script says so in its own output.

## 13. Prior-art findings

Nothing here is novel and the report does not claim otherwise. Capability attenuation
(macaroons, IETF `draft-niyikiza-oauth-attenuating-agent-tokens`, DeepMind delegation
tokens), sliding-window log rate limiting, transactional-outbox idempotency, and
counterfactual explanation are all prior art. The sliding-window containment fix is
textbook once the protocol is understood; the contribution was *finding that the
protocol induces the bug*, not inventing the algorithm.

## 14–16. Mechanisms considered, rejected, selected

Considered: mandate-scoped ledger (§9), history-seeded windows (H1), cross-run dedupe
via `source_authorization_id` (H2), settlement-based release (H3), a provenance
object (§10), a wallet-imposed total cap.

The last deserves its own line: a total bound the customer never stated would be the
wallet inventing policy. Disclosure is the honest answer and is already implemented.

**Selected: none.** Under the brief's twelve criteria no candidate survived. The
correct conclusion is that the architecture is saturated under current protocol
constraints, and inventing a mechanism to avoid an anticlimax would be the one
outcome worse than saying so.

## 17–20. Changes, invariants, mutation and property results

| | |
| --- | --- |
| production changes | 3 (empty-basket check, `item.*` absence guard, velocity cross-check) |
| new invariants | **I34** empty-collection vacuity · **I35** event claims cross-checked · **I36** declared absence semantics |
| mutation probe | **18 → 21 mutants, 21 killed, 0 survived** |
| property/fuzz | 1,800 optimiser trials, 0 breaches |
| register | I31 converted from prose to four tests; exemption list now one entry |

## 21. Performance

No new claim. The previous campaign's three-pass correction stands: exactly
quadratic, worst case n ≈ 11,200 against an official maximum of 12
(`tests/test_scale_limits.py`). The prototype's A4 result is the first measurement of
what that constant costs at *ledger* scale, and it is a reason the prototype was
rejected rather than a new claim about the shipped system.

## 22. Failed experiments and corrected conclusions

Recorded because they are the campaign's real content, not despite it.

* **The mandate ledger.** Built, worked, rejected. The prototype stays in the tree
  as the evidence.
* **History-seeded windows.** A plausible idea killed by a 9-day gap in the data.
* **"The compiler is a security risk."** Half right. It is **not in the live decision
  path** — `from_event_mandate` takes `hard_rules` from the platform verbatim. It
  decides what a customer is shown before confirming, and the offline replay's rules.
  So **19/2/24 is conditional on our reading of five English sentences** — now stated
  in `VISECA_INTEGRATION.md` and ranked in the audit package.
* **"We invented illegal rule fields."** Checked, false (H8).
* **My own commit messages.** Three carried test counts I wrote before reading the
  sync output. Caught by the machine-checked number tests, amended each time.

## 23. Remaining limitations

Unchanged in substance; two are now better characterised.

1. **Merchant-claimed facts** — the largest real exposure, unfixable in the vocabulary.
2. **Cross-run reuse** — now *proven* protocol-level (§9), and disclosed.
3. **Multi-process execution** — at-most-once per process.
4. **Step-up channel** — unauthenticated, no `resolved_by`.
5. **No total-spend bound** — the vocabulary cannot express one.
6. **Account limits** — real in `accounts.csv`, no endpoint to enforce them.
7. **Revoked/cancelled purchases keep window budget** — conservative on purpose.
8. **Deadline silence** — what the platform does on a missed deadline is undocumented
   and unobserved.

## 24. What we refuse to claim

`docs/WHAT_WE_REFUSE_TO_CLAIM.md` is the authority and was updated this campaign.
Specifically: no formal proof, no exhaustive mutation testing, no cross-session
enforcement, no detection of merchant lies, no exactly-once execution, and the replay
counts are a regression boundary and not a score.

## 25. Judge-facing differentiation thesis

Not "more tests". This:

> **We can tell you what this wallet does not protect, and prove we looked.**

Concretely, three things most teams will not have: a **mutation probe** that breaks
21 security mechanisms and checks the suite notices; an **invariant register that is
machine-checked** to cite tests that exist; and **numbers about ourselves that fail
the build when they go stale.** Plus a rejected mechanism, kept in the tree with the
attacks that killed it.

## 26. Recommended 60–120 second demo

1. *(15s)* Customer writes a sentence. Show the compiled policy **and the two
   disclosures** — the rolling cap paces rather than caps; it is per session.
2. *(30s)* Run the attacks endpoint: nine attacks against the real engine, one of which succeeds and says so.
3. *(30s)* The empty-basket attack, live: a CHF 400 purchase with no items used to
   satisfy four item restrictions. Now blocked under every policy.
4. *(20s)* `python3 scripts/run_mutation_probe.py` — break the wallet on purpose,
   21/21 caught.
5. *(15s)* Open `WHAT_WE_REFUSE_TO_CLAIM.md`. "This is the part we would rather you
   read."

## 27. Commands an external auditor can run

```bash
python3 -m pytest -q                        # 728 collected, 5 reported skips
python3 scripts/run_replay.py               # 45 events — 19 allow / 2 review / 24 block
python3 scripts/run_red_team_corpus.py      # 133/133
python3 scripts/run_red_team.py             # 17/17
python3 scripts/run_mutation_probe.py       # 21 mutants, 21 killed
python3 scripts/run_economic_optimizer.py   # 1,800 trials, 0 window breaches
```

## 28. Final repository state

Branch `rnd/productization`; `main` untouched at `1aa3bac`. Six commits this
campaign, `5fd7396` … and this one. 728 collected / 723 pass / 5 reported skips.
Replay unchanged at 45 · 19/2/24 through every change.

## 29. Verdict

**SATURATED UNDER CURRENT PROTOCOL CONSTRAINTS.**

The qualifier is load-bearing. Saturation is a statement about the *protocol*, not a
compliment to the code — this campaign found two exploitable defects in an
implementation that had already survived several adversarial passes. What it did not
find, after prototyping the strongest candidate and killing it with its own attack
suite, is a concept this system is missing.

The remaining exposure is not in the wallet. It is that a customer's own policy,
faithfully enforced, cannot bound what they have delegated — and the only honest
response available inside this vocabulary is to say so before they confirm.
