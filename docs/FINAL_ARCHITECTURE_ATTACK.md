# Final Architecture Attack & Arbitration

Fourth and final adversarial pass. Everything below was re-derived by attacking
the running code, not by trusting any previous pass's conclusions. Where a prior
claim did not survive contact with the code, this document says so.

---

## 0. Two premises in the brief that did not survive verification

These are stated first because the rest of the arbitration depends on them.

### 0.1 There is no second engineering track in this repository

The brief describes an independent "Cursor" track — 1876 tests, an intent-fidelity
engine, a 55-case semantic corpus, and three documents
(`CURSOR_INTENT_FIDELITY.md`, `CURSOR_DEEP_AUDIT.md`, `CURSOR_FINAL_SECURITY_MODEL.md`).

None of it is present:

| Checked | Result |
| --- | --- |
| `git branch -a` | only `main` and `rnd/verifiable-agentic-wallet` |
| `git log --all --grep=ursor` | no commits |
| `git stash list` / `git worktree list` | empty / single worktree |
| `git remote -v` | no remotes configured |
| `docs/CURSOR_*.md` | do not exist |
| `grep -ril cursor` across the repo | no matches |
| filesystem search of `~/code`, `~/Documents`, `~/Desktop`, `~/Downloads` | no matches |

So this pass could not reconcile two implementations. What it *can* do — and did —
is evaluate the Cursor **ideas** as a design proposal on their merits, and attack
the one implementation that exists. Every claim below about intent fidelity is an
assessment of the concept as described in the brief, tested against the real
official data. It is not a review of code I could not find.

**If that code exists somewhere, this arbitration is incomplete and should be
re-run with it present.** Nothing here should be read as a judgment on work I
never saw.

### 0.2 The "17 allow" baseline is arithmetically impossible

The brief reports two different baselines and asks that the difference be
investigated rather than hidden:

- current implementation: **19 allow / 2 review / 24 block** = 45 ✓
- claimed reconciled figure: **17 allow / 2 review / 24 block** = **43 ✗**

45 attempts cannot split into 43. Two events are unaccounted for, so the figure
cannot be a real engine output — at least one of its three numbers is wrong. The
verified number for this codebase, re-run for this pass, is 19 / 2 / 24 = 45.

A plausible (unproven) explanation: `17` is the red-team matrix's `17/17` score
transposed into the replay row. Recorded as a hypothesis, not a finding.

**No number in this repository was changed to resolve this.** The replay is
reported as the engine actually decides.

---

## 1. Executive verdict

**Survives, genuinely security-relevant:**
- The deterministic rule engine and its fail-closed uncertainty handling.
- The payment boundary in `payment.py` — after this pass it is the *single*
  enforcement point, which it previously was not.
- The repeat-delivery fingerprint (`authorization_id_conflict`) — after this pass
  it covers item identity and merchant-text-derived facts, which it previously
  did not. This was the weakest load-bearing component in the system.
- Human-resolution scoping. Attacked hard; held on every vector.
- Live-event dominance over reference data. Structural, not incidental.

**Survives, but demo-level rather than security-level:**
- `AuthorizationDrift` — real explanatory value, zero gating value. Honest as
  evidence; would be dishonest as a control.
- `policy_verdict` / `security_verdict` — a presentation split, provably unable
  to change a decision. Keep, label as such.
- The 17-case red-team matrix — a test harness and a demo artifact. It
  demonstrates properties; it does not create them.

**Does not survive as proposed:**
- **`intent_faithful` as a hard security gate.** Section 7 asks that this be said
  plainly if true. It is true. See §7.
- **`PaymentAuthority` as a capability object.** It is not a capability in the
  cryptographic sense and was, until this pass, partly decorative. What survives
  is a narrower, honest claim. See §5.

**Four real vulnerabilities were found and fixed in this pass.** Three of them
were in code written by the previous pass and asserted to be hardened.

---

## 2. Threat model

| Actor | Can do | Cannot do (by construction) |
| --- | --- | --- |
| Compromised shopping agent | propose any purchase; re-send any authorization_id; mutate any field it controls; retry endlessly | mint authority; alter a recorded decision; answer its own step-up; charge |
| Malicious merchant | write arbitrary `item_details`, `merchant_name`, `purchase_description`; lie about return terms and size | be read as an instruction; alter a mandate; reach the decision path except through 3 whitelist extractors |
| Stale / replayed data | re-deliver an old event | override the live event (§9) |
| Confused deputy via human approval | present a purchase for approval | have the approval apply to different facts (§8) |
| Policy mutation | tighten or revoke the mandate | retroactively rewrite decisions already returned |

Out of scope, stated so it is not implied: a hostile *platform*. Every fact
originates from the platform's event stream. If that stream lies about
`billing_amount_chf` or `order_returnable`, no check in this layer can detect it.

---

## 3. Trust model

Five tiers. The rule that matters is the last column.

| Tier | Source | May establish a security fact? |
| --- | --- | --- |
| 0 | Customer policy / instruction | **Yes.** The only source of authority. |
| 1 | Wallet-verified structured facts (FX recomputation, amount integrity, run state, spend ledger) | **Yes.** Derived by us from first principles. |
| 2 | Historical customer-authorized facts (`authorization_history`) | **Corroborate only.** Three-valued; absence is `unknown`, never `false`. |
| 3 | Agent-supplied proposal fields (the `authorization` block) | **No.** This is the *subject* of the decision, never evidence for it. Checked and fingerprinted, never trusted. |
| 4 | Merchant text (`item_details`, `merchant_name`, `purchase_description`) | **No** — with one honest and uncomfortable exception, below. |

**The Tier-4 exception, stated plainly.** Merchant text is read through exactly
three whitelist extractors (return window, final sale, stated size). Two of those
can make a customer rule **pass**: a merchant who writes "returns accepted within
30 days" satisfies `order.return_window_days >= 14`, and a merchant who writes
"size 43" satisfies `item.size = 43`. The wallet cannot verify either claim —
there is no independent source for return terms or sizing in this challenge's
data model.

So the honest statement is *not* "merchant text can never make a decision more
permissive." It is: **merchant text can satisfy exactly two narrow, enumerated
factual predicates, and can do nothing else — it cannot grant authority, relax a
limit, change a rule, or be interpreted as an instruction.** That residual is
inherent to the data model, not a defect in this implementation, and it is listed
in §14 rather than glossed over.

---

## 4. Security invariants (this pass)

Existing invariants I1–I28 are in `SECURITY_INVARIANTS.md` and were re-verified.
This pass adds four, all backed by mutation-verified tests in
`tests/test_final_arbitration.py`:

- **I29.** Revoking the mandate revokes every outstanding payment authority in
  that run. The customer's emergency brake stops money that has not yet moved.
- **I30.** Expiry and revocation are enforced inside `MockPSP.charge()` against
  the run's live records — there is no second door. A stale authority object
  handed to `charge_via_authority` cannot resurrect a revoked grant.
- **I31.** The repeat-delivery fingerprint includes item identity (`item_name`),
  so a renamed line under a reused authorization_id is a conflict, not a replay.
- **I32.** The fingerprint includes the *facts derived from* merchant text, never
  the text itself — so a details edit that moves a security-relevant fact is a
  conflict, while cosmetic noise (casing, padding, zero-width characters) remains
  an ordinary retry. Both directions are pinned by mutation testing.

---

## 5. PaymentAuthority: exact guarantees and exact limits

The brief asks whether this is a real capability or a richer JSON object. The
answer, after attacking it, is: **neither — it is an inspectable record of a
grant, and the enforcement lives elsewhere.**

**What it actually binds** (all re-checked at execution):

| Bound | Enforced where | Verified by |
| --- | --- | --- |
| authorization_id | `charge()` | P4 probe |
| merchant | `charge()` | P5 probe |
| approved amount | `charge()` | P3b probe |
| single execution | `charge()` | existing I6 |
| expiry (15 min, real clock) | `charge()` after this pass | P8 probe, I30 |
| explicit revocation | `charge()` after this pass | I29, I30 |
| authority's own (possibly attenuated) ceiling | `charge_via_authority()` | existing tests |

**What it does NOT provide, stated so no one claims otherwise:**

- **No cryptography.** Not signed, no key, no verifier, no relying party. Calling
  it "verifiable" is only defensible in the sense of *locally inspectable and
  independently re-checked*, and the docs should say exactly that.
- **`policy_version` is provenance, not a binding.** It records the rule-set hash
  the grant was minted under. Nothing enforces it. This pass deliberately did not
  add enforcement, because it is **unreachable**: a run is bound to one mandate
  snapshot taken at run start (`api.py` and `live_worker.py` both build it once
  per `run_id`, per "an existing run keeps its original snapshot"), and
  authorities live inside one `RunState`. A policy version cannot change beneath
  an outstanding authority. An enforcement branch would be dead code.
- **`basket_fingerprint` is likewise provenance.** The charge path takes an amount,
  not a basket, so there is nothing to compare it against at execution. The basket
  is instead frozen at the *decision* layer by `authorization_id_conflict` (§6),
  which is where it belongs.
- **It is not required.** `charge()` remains callable directly. That is now safe
  (I30) precisely because enforcement was moved into it, rather than left in the
  wrapper.

**Gap found and fixed (G1, G2).** Before this pass: revoking the mandate left
outstanding authorities chargeable (reachable through the existing demo API), and
`charge()` consulted no authority at all, so expiry and revocation were opt-in.
A lock only the polite caller respects is not a lock.

---

## 6. AuthorizationDrift: bound vs mutable facts

Drift is a pure diff over `(merchant_id, basket_key, billing_amount_chf)`,
classified `none` / `narrowing` / `widening` / `unrelated_change`. It is computed
**after** `_decide()` and is never read by it. That is the right design and it
should stay advisory.

The security-relevant question is not what drift *reports* but what the
fingerprint *freezes*, because that is what makes a reused authorization_id a
conflict. Before this pass the fingerprint was `(item_id, quantity)` — and that
was the weakest component in the system.

| Fact | Frozen before | Frozen now |
| --- | --- | --- |
| merchant | yes | yes |
| total amount (CHF) | yes | yes |
| item_id, quantity | yes | yes |
| **item_name** | **no — G3** | yes |
| **stated size (from merchant text)** | **no — G4** | yes |
| **return window (from merchant text)** | **no — G4** | yes |
| **final-sale flag (from merchant text)** | **no — G4** | yes |
| per-line `unit_price` | no | no — deliberate (§14) |
| `order_returnable` (platform field) | no | no — deliberate (§14) |

**On the quantity/SKU gap the brief flags:** quantity was already in the
fingerprint and probe P6 confirms a 1→5 change is caught. SKU/generation identity
is not, and cannot be — see §7 and §14.

---

## 7. Intent fidelity: the central arbitration

I attacked this as the brief asked, and tested it against the real data rather
than reasoning about it abstractly.

### 7.1 The worked example does not hold for this implementation

The brief's demo case is AU0020: policy permits, intent violated. AU0020 is real
and is exactly as described — the official data ships a purchase whose
`purchase_description` says "Running shoes order" while the single item line is a
**Cycling helmet**, CHF 120, under the road-running-shoes mandate.

But the premise `policy_permit = TRUE` is **false here**:

```
AU0020 DECISION: block ('hard_rule_failed:item.name_contains',
                        'hard_rule_failed:item.size')
  [pass] billing_amount_chf=120.0     [pass] merchant.category=sporting_goods
  [pass] item_categories=[sporting_goods]
  [FAIL] item.name_contains: ['Cycling helmet'] not matching 'road-running'
  [FAIL] item.size: item_sizes=['M']            [pass] return_window_days=30
```

The wallet already blocks it, on product identity, twice over. The description
laundering also already fails, because the engine reads the **item lines**, never
`purchase_description`.

### 7.2 Why — and this is the structural argument

The official rule vocabulary is not a spend-cap vocabulary. It contains
`item.category`, `item.name_contains`, `item.size`, `item.unrequested_present`,
`order.return_window_days`. **Product-identity constraints are native to the
policy language.** So the compiler already compiles intent into policy:
`"road-running shoes in size 43"` becomes `item.name_contains='road-running'` and
`item.size='43'`.

That collapses the proposed dichotomy. Intent fidelity can only ever be as
specific as the customer's instruction:

- If the instruction is **specific**, the compiler extracts the anchors into hard
  rules — and it is policy, checked deterministically.
- If the instruction is **vague** ("buy clothing up to CHF 250"), there is no
  specific intent to be unfaithful to. A CHF 249 scarf instead of a raincoat is
  something the customer genuinely authorized.

There is no gap in between for a second engine to occupy.

### 7.3 The decisive empirical test

I examined the basket of **every one of the 19 ALLOW decisions** across all five
official scenarios. Every one is semantically faithful: groceries under grocery
mandates, three lines literally named "Road-running shoes" under the shoe
mandate, clothing under the clothing mandate, five lines literally named "27-inch
computer monitor" under the monitor mandate.

**Intent fidelity would flip zero of the 19.** Not two — zero. On this benchmark
it is not a second dimension; it is a re-derivation of the first.

### 7.4 Answering the 20 attack questions, compressed

Deterministic? Only for the subset already expressible as rules. Beyond that it
requires product ontology the system does not have. Can a merchant manufacture
evidence? Yes — Tier 4 supplies size and return terms (§3), so a *fidelity* check
reading merchant text inherits exactly the weakness the policy check has. Can
road-running vs trail-running be distinguished? Only by substring match on a
merchant-supplied name. SKU/generation, colour, width, gender? No. Can
`"the one I chose"` be bound? **No — and that is the one real residual.**

### 7.5 What is genuinely left: unbindable referential anchors

`"Buy the 27-inch monitor **I chose**"` — the compiler extracts `27-inch`, but
"the one I chose" refers to a cart the wallet cannot see. A different 27-inch
monitor passes every rule. This is real, and it is the only part of the intent
proposal that is not already covered.

**It must stay advisory.** Making unbindable reference an `unknown` would route
it through `ask` and flip all five SCEN0004 allows to review — changing the
official replay from 19/2/24 to 14/7/24. Section 24 forbids exactly that, and it
would be optimizing the benchmark to flatter a synthetic concept.

**Verdict: REJECT as a hard gate. ACCEPT the underlying insight** — which the
architecture already implements, in the place it belongs: the policy compiler,
whose `open_questions` surface exactly this ambiguity to the customer *before*
they confirm.

---

## 8. Human step-up

Attacked with the brief's exact scenario (agent requests 100 → step_up → human
approves → agent swaps basket to 999 under the same ID). **Held on every vector:**

- mutated retry → `block`, `authorization_id_conflict`; stored amount stays 100 (P3)
- charging 999 against the human-approved authority → refused on ceiling (P3b)
- `resolve_authorization` takes **no amount and no timestamp** from the caller — it
  is structurally impossible to re-price a resolution
- conflicting second answer → `ResolutionError`; identical answer → idempotent
- resolving an authorization from another run → `ResolutionError`

No confused-deputy path found. This is the strongest component in the system and
it needed no changes.

---

## 9. Live event vs pack data

Structural, not incidental: `live_worker.py` imports **no** CSV pack loader, and
`evaluate_authorization(event, mandate, state)` takes exactly three inputs — the
live event, the run's snapshot, and accumulated run state. There is no code path
by which a pack row can supply purchase facts.

The one pack-derived input is `HistoryIndex` (merchant familiarity), injected at
construction. That is reference data about the *past*, correctly three-valued, and
it cannot describe the current purchase. When unavailable it yields `unknown`,
which routes through the uncertainty policy — fail-closed under `ask`/`decline`.

---

## 10. Prompt injection

Covered by the existing 17-case matrix (plain, Unicode-obfuscated, fake
pre-authorization, fake customer approval, fake system authority) and by the
property test asserting arbitrary `item_details` never changes a mandate's rules.
All hold.

**The one that did not hold — G4, found this pass.** Injection was correctly inert
at *decision* time, but the *replay* path never re-examined it: same ID, same
money, same basket, only the text rewritten from `"size 43; returns accepted
within 30 days"` to `"size 38; FINAL SALE, no returns"`. Evaluated fresh those
facts are a double BLOCK. As a re-delivery they inherited the stored ALLOW,
unexamined.

The fix satisfies both halves of the requirement, and both halves are
mutation-verified:

- fingerprint the **derived facts** → a text edit that moves a fact is a conflict
- never the **raw text** → casing, padding, punctuation and a zero-width character
  remain a harmless retry

---

## 11. Composition attack results

| # | Composition | Result |
| --- | --- | --- |
| P1 | policy tightened after authority issued | unreachable by construction (§5) |
| P2 | retry after tightening | stored decision replayed — correct per snapshot semantics |
| P3/P3b | step-up + basket mutation to 999 | blocked; conflict; charge refused |
| P4 | authority for one authorization used for another | bound to its own ID |
| P5 | merchant substitution at charge time | refused |
| P6 | quantity 1→5, same total | conflict |
| P7 | item renamed, same ID/amount/qty | **was ALLOW → now conflict (G3)** |
| P8 | charge 2h after a 15-min authority | refused |
| P9 | plain `charge()` after revocation | **was CHARGED → now refused (G2)** |
| — | mandate revoked, authority still outstanding | **was CHARGED → now refused (G1)** |
| — | details-only fact mutation on re-delivery | **was ALLOW → now conflict (G4)** |
| — | details-only cosmetic noise | remains a harmless replay |

---

## 12. Property / mutation test results

Existing: 8 Hypothesis properties (payment boundary, ceilings, repeat-auth
conflict, money monotonicity, compiler crash-resistance, injection-inertness) plus
the 200-example verdict-monotonicity property. All pass.

New, and each verified to actually fail when its fix is reverted:

| Mutation applied | Test that caught it |
| --- | --- |
| remove authority check from `charge()` | 4 failures incl. stale-copy resurrection |
| revert fingerprint to `(item_id, quantity)` | renamed-line conflict test |
| drop derived facts from fingerprint | details-only attack test |
| fingerprint raw text instead of derived facts | cosmetic-noise false-conflict test |

The last two pin the fingerprint from **both** sides — under-fingerprinting and
over-fingerprinting each break a different test.

---

## 13. Official replay results

| | allow | review | block | total |
| --- | --- | --- | --- | --- |
| Before this pass | 19 | 2 | 24 | 45 |
| **After this pass** | **19** | **2** | **24** | **45** |

**Unchanged, and necessarily so.** All 45 official authorization_ids are unique,
so the repeat-delivery path — where every one of this pass's decision-layer
changes lives — is never exercised by the official replay. The fixes are provably
orthogonal to the benchmark.

On the 17-vs-19 discrepancy: see §0.2. Nothing was tuned.

---

## 14. Remaining vulnerabilities (honest)

**Inherent to the data model — cannot be fixed in this layer:**
1. A lying merchant can satisfy `order.return_window_days` and `item.size` by
   writing text (§3). No independent source exists to check it against.
2. Unbindable referential anchors — "the one I chose", "my usual" (§7.5).
3. SKU / generation / colour / width / gender identity. No ontology, and a
   heuristic one pretending to be ground truth would be worse than none.
4. A hostile platform. Out of scope by construction.

**Deliberately scoped out, with reasoning:**
5. `order_returnable` is a *platform* field that also feeds the effective return
   window, and is not fingerprinted. An adversary able to flip it is already able
   to rewrite `item_details`, so this closes no new capability — but it is the
   same class as G4 and is named here rather than hidden. Folding it in means a
   `StoredDecision` schema change and a checkpoint-format break, which is not
   worth it for zero incremental adversary capability.
6. Per-line `unit_price` is not fingerprinted. Re-allocating the same total across
   lines changes no rule outcome (per-item ceilings are a documented non-feature).

**Structural:**
7. Crash recovery is checkpoint-based and best-effort (existing I25). Unchanged.
8. `MockPSP` is in-memory. Real PSP semantics (auth vs capture, partial capture,
   reversal) are out of scope and must not be implied.

---

## 15. Minimum final architecture

```
CUSTOMER INSTRUCTION
   └─ policy_compiler ──► HARD RULES + open_questions      [Tier 0 authority]
                                │
AGENT PROPOSAL (live event)     │                          [Tier 3 — subject]
   └─ facts.py ──► VERIFIED FACTS                          [3 whitelist extractors
                                │                           over Tier 4 text]
                                ▼
                    ┌───────────────────────┐
                    │ decision_engine       │  fail > unknown > pass
                    │ + always-on safety    │  uncertainty_policy on unknown
                    └───────────────────────┘
                                │
              ALLOW ────────────┼──────────── REVIEW ──► human (scoped, amount
                │               │                        and time not caller-supplied)
                ▼               ▼
        PaymentAuthority   BLOCK
        (inspectable record of the grant)
                │
                ▼
        payment.charge()  ◄── SINGLE enforcement point:
                                decision · merchant · amount · single-use
                                · expiry · revocation
                │
                ▼
             AUDIT
```

Two things were **removed** rather than added: duplicated expiry/revocation logic
in `charge_via_authority`, and a speculative `policy_version` parameter that would
have been an unreachable branch.

The brief's proposed diagram (§17) adds `INTENT FIDELITY` as a second box beside
`POLICY PERMISSION`. **That box is not in the final architecture**, for the reasons
in §7: on this challenge it is the same box.

---

## 16. Demo architecture

The AU0020 story is still the strongest — but it must be told **accurately**, and
the accurate version is better:

> "The agent stayed inside the spending limit — CHF 120 of the customer's CHF 200 —
> and the order is even described as a 'Running shoes order'. The wallet blocks it
> anyway, because it reads the basket, not the story: the line is a cycling helmet
> in size M, and the customer asked for road-running shoes in size 43."

Then the part a spend-cap wallet genuinely cannot show:

1. **Reuse the same authorization_id with the text rewritten** — size 43→38, FINAL
   SALE. Same ID, same money, same basket. The wallet refuses to inherit its own
   earlier approval. *(G4 — this is the novel beat.)*
2. **Show cosmetic noise is still just a retry** — the same edit with only casing
   and a zero-width character changed stays a harmless replay. Precision, not
   paranoia.
3. **Revoke the mandate** and watch the outstanding payment authority die with it:
   *"1 outstanding payment authority revoked (AU0001) — approved money that had
   not moved yet can no longer be charged."* *(G1 — live in the UI.)*
4. **Run the red-team matrix live**: 17/17.

Claim to judges: *"A spend-cap wallet asks whether the amount is allowed. This one
also refuses to let an approval be reused for a different purchase — including when
the only thing that changed is the merchant's own text."* That is demonstrable,
and true.

---

## 17. What we must not claim

- ❌ "Cryptographically verifiable payment authority." No keys, no signatures.
- ❌ "The wallet understands customer intent." It matches compiled anchors.
- ❌ "Protected against a compromised agent." Bounded, not protected — the agent
  still chooses what to propose, within the customer's rules.
- ❌ "Intent fidelity is a second security dimension." On this challenge it is the
  same dimension (§7.3: zero of 19 would change).
- ❌ "Merchant text can never make a decision more permissive." It can satisfy two
  enumerated predicates (§3).
- ❌ Any claim resting on the 17/2/24 baseline. It does not sum to 45.

---

## 18. Final recommendation

**Merge / retain:** the four fixes (I29–I32) and their 13 mutation-verified tests;
the enforcement consolidation into `charge()`; the deterministic engine; human
resolution; live-event dominance.

**Retain, relabel:** `PaymentAuthority` as *"an inspectable record of a grant,
independently re-checked at execution"* — never as a cryptographic capability.
Drift and the verdict split as *evidence*, never as gates.

**Reject:** intent fidelity as a hard gate; a parallel semantic engine; any
product ontology; enforcement of `policy_version` (unreachable).

**Defer:** `order_returnable` in the fingerprint (§14.5) — named, ranked, cheap to
add if the threat model ever includes a partly-hostile platform.

**Ready for HackZurich:** yes, with the §17 language discipline. 248 tests, 45/45
replay unchanged, 17/17 red team, four real vulnerabilities closed. The honest
pitch is not that this wallet understands intent — it is that it refuses to let an
approval be reused for anything other than exactly what was approved, and can
demonstrate that live against its own code.
