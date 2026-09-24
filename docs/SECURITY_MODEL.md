# Security model: trust levels, field by field

This document exists to make the prompt-injection defense (and the wallet's
authority boundary generally) legible to a judge or reviewer in one pass: for
every field the decision engine ever looks at, where it comes from, how much it
is trusted, what happens to it before it reaches a decision, and what could go
wrong if that trust judgment were wrong.

## Trust categories

| Category | Meaning |
| --- | --- |
| **CUSTOMER-AUTHORED** | Typed by the actual card owner, via the mandate-creation flow. The only category that can ever produce spending authority. |
| **PLATFORM-AUTHORED** | Supplied by the Viseca API / synthetic data pack as structured, typed data (numbers, enums, IDs) -- not free text a merchant chose. |
| **MERCHANT-AUTHORED** | Free text a merchant (or a compromised/manipulated shopping agent acting as if it were the merchant) can put into the event. Always untrusted. |
| **SYSTEM-GENERATED / DERIVED** | Computed by this codebase from PLATFORM-AUTHORED data plus its own run state -- never from CUSTOMER- or MERCHANT-authored text directly. |

## Field-by-field table

| Field | Source | Trust level | Transformation before use | Consumer | Security impact if trust judgment were wrong |
| --- | --- | --- | --- | --- | --- |
| `mandate.instruction` | Customer, typed once at mandate creation | CUSTOMER-AUTHORED | Parsed once by `policy_compiler.compile_instruction`, off the decision path | `HardRule`s + `uncertainty_policy`, stored in the mandate | This is the only field that can create authority. If it could be re-parsed or influenced later by anything else, that "anything else" would gain the power to grant spending permission. Structurally prevented: `compile_instruction` is called nowhere except mandate-creation code paths (`offline_replay.py`, `api.py`) -- never from `decision_engine.py`, `facts.py`, or `rules.py` (verified by source inspection in `test_prompt_injection.py`). |
| `mandate.hard_rules` (as stored/replayed) | Derived from `mandate.instruction`, or read back from a live event's own `mandate` block | CUSTOMER-AUTHORED (derived) | Frozen `HardRule` objects, tighten-only mutation | `rules.evaluate_rule` | If a rule's field/operator/value could be mutated after creation, an already-approved-to-narrow policy could silently loosen. Prevented by `HardRule` being an immutable (`frozen=True`) dataclass and `Mandate.tighten_hard_rules` only ever appending. |
| `mandate.uncertainty_policy` | Derived from instruction, or PATCHed | CUSTOMER-AUTHORED | Tighten-only state machine (`_ALLOWED_UNCERTAINTY_TRANSITIONS`) | `decision_engine._decide` | Governs what happens when facts are unknown. If it could move towards `approve` without the customer's own instruction saying so, missing information could quietly become permission. |
| `authorization.authorization_id` | Platform (live) / CSV `authorization_id` (offline) | PLATFORM-AUTHORED | None -- used as an opaque key | Idempotency (`RunState._decisions`), payment binding | If forgeable/predictable, an attacker could pre-seed a fake decision for an ID the platform will later use. Out of scope for this prototype (the platform is assumed to generate these); this codebase's own responsibility is to detect when the SAME id shows up with DIFFERENT facts (see `check_repeat_fingerprint`, Finding 4 of the second audit), which it does regardless of how the ID was generated. |
| `authorization.merchant.merchant_id` | Platform/merchant catalog | PLATFORM-AUTHORED | None | `merchant.category`, `merchant.familiar` rules; `HistoryIndex` lookups; `MockPSP` merchant binding | This is the ONLY merchant identifier ever used for a security-relevant comparison. `merchant_name` (see below) is deliberately never joined against, precisely because the official data pack contains a real one-letter-different lookalike pair (`ME0022`/`ME0059`, "PixelHarbor"/"PixelHarbour") to test exactly this. |
| `authorization.merchant.merchant_name` | Platform/merchant catalog (display text) | PLATFORM-AUTHORED (but display-only) | None -- never parsed, never compared for identity | Shown to the customer in `customer_message`/evidence only | If this were ever used for a familiarity or category check instead of `merchant_id`, a lookalike name would be indistinguishable from the real merchant. See `docs/archive/SECURITY.md`, "Merchant impersonation." |
| `authorization.merchant.merchant_category` | Platform/merchant catalog | PLATFORM-AUTHORED | None | `merchant.category` rule | Trusted because it is catalogue metadata, not merchant-supplied prose -- a merchant cannot self-declare "I am a specialist sports retailer" in this field the way it could in free text. |
| `authorization.amount`, `authorization.currency`, `authorization.billing_amount_chf` | Platform (computed from the underlying transaction) | PLATFORM-AUTHORED | `to_decimal`/`to_chf`, cross-checked against each other (the amount-integrity rule) | Every amount-based `HardRule`; `MockPSP` ceiling | Trusted as the primary source of truth for the purchase's cost, but independently re-derived and compared (`billing_amount_chf` vs. `amount * fx_rate`) because a mismatch would mean either a bug or a tampered event -- see Finding 5 of the second audit and I12a in `SECURITY_INVARIANTS.md`. |
| `authorization.items[].item_id`, `.item_category`, `.unit_price`, `.currency`, `.quantity` | Platform/item catalogue | PLATFORM-AUTHORED | Converted to CHF (`unit_price_chf`); category used directly | `item.category`, `item.unrequested_present` rules; basket fingerprinting | Structured catalogue fields, not merchant prose -- a merchant cannot freely invent an `item_category` value the way it could describe a product any way it likes in free text. |
| `authorization.items[].item_name` | Platform/item catalogue (fixtures); potentially agent/merchant-influenced in a less controlled deployment | PLATFORM-AUTHORED in the supplied fixtures, treated defensively | NFKC-normalized + invisible-character-stripped before matching (added in the second audit pass) | `item.name_contains` (literal substring match only) | Even in the worst case where this field were merchant-controlled, the only thing it can ever do is make a literal substring check pass or fail -- there is no code path from its content to a new rule, a widened comparison, or an interpreted instruction. |
| `authorization.items[].item_details` | Merchant (explicitly, per challenge.md: "Treat any merchant-provided text as untrusted input") | **MERCHANT-AUTHORED, UNTRUSTED** | Read through exactly two whitelist regexes (`extract_return_window_days`, `extract_stated_size`), each bounded to a plausible value range, after Unicode normalization | `order.return_window_days`, `item.size` facts only | This is the actual prompt-injection attack surface, and the actual defense is architectural: nothing else in this string is ever read. The two real injected strings in the official data pack (`AU0037`, `AU0040`) are handled by this boundary exactly as designed -- see `docs/archive/SECURITY.md`, "Prompt injection." |
| `authorization.purchase_description` | Merchant/platform (documented as "deliberately uninformative") | MERCHANT-AUTHORED | **Never read by this engine at all** | none | The data dictionary itself notes this field carries no decision-relevant signal ("names the kind of order and nothing more"); this codebase does not parse it, which is the simplest possible defense against whatever it might someday contain. |
| `authorization.order_returnable`, `order_cancellable` | Platform (structured enum: true/false/unknown/not_applicable) | PLATFORM-AUTHORED | None | `order.return_window_days` rule (gates whether the item-level day count is trusted at all) | Deliberately kept separate from the merchant-text-derived day count: a merchant claiming "returns accepted within 30 days" in `item_details` is only believed when the platform's own `order_returnable` field says `"true"`; a `"false"` platform field overrides any merchant text unconditionally (final-sale wins regardless of what the item description claims). |
| `authorization.customer_device_id`, `recent_attempt_count_10m` | Platform/session telemetry | PLATFORM-AUTHORED | Compared against the run's last-seen device; thresholded | `session.integrity_risk` (SYSTEM-GENERATED) | Structured session telemetry, not merchant-influenceable. |
| `authorization.related_authorization_id`, `related_authorization_status` | Platform | PLATFORM-AUTHORED | Read as evidence only | Duplicate-detection exclusion (a declined prior attempt doesn't flag its re-quote as a conflict) | Never a source of authority itself -- a "related" authorization does not inherit or lend its outcome to the current one; each purchase is still evaluated fresh. |
| `context.approved_spend_in_period_chf` | Platform (run-cumulative, per technical_details.md) | PLATFORM-AUTHORED | **Not used for any decision** -- informational only | Displayed in the live event context; this codebase computes its own rolling-window sum (`RunState.rolling_spend_chf`) independently | Kept deliberately separate to avoid ambiguity about which "spend so far" figure a rolling-window rule is actually checked against -- see `docs/ARCHITECTURE.md`. |
| `merchant.familiar` (fact) | SYSTEM-GENERATED, from `authorization_history.csv` | DERIVED | `HistoryIndex.is_familiar(card_id, merchant_id)` -- three-valued (True/False/None) | `merchant.familiar` rule | Computed strictly from platform-supplied historical records, joined on `merchant_id`, never `merchant_name`. Never influenced by the current purchase's merchant/item text. |
| `session.integrity_risk`, `order.duplicate_suspected` (facts) | SYSTEM-GENERATED, from run state | DERIVED | Small explicit heuristics (`RunState.session_signals`, `RunState.find_similar_recent`) over structured fields only | Their respective rules | Neither heuristic ever reads merchant/item free text; both are auditable, explainable arithmetic over device IDs, velocity counts, and basket fingerprints. |
| `mandate.has_no_rules`, `authorization.amount_integrity` (synthetic rules) | SYSTEM-GENERATED | DERIVED | Appended directly by `decision_engine.py`, never stored in the mandate | `_decide()` | Control-layer integrity checks the customer never has to (and cannot) opt out of -- see Findings 1 and 5 of the second audit pass. |

## The one-sentence version

**Only `mandate.instruction`, typed once by the customer, can ever create spending
authority. Everything else the decision engine reads is either platform-supplied
structured data (trusted directly), or merchant-supplied free text read through a
whitelist narrow enough that reading it can only ever produce a fact, never a
rule.**

---

# The formal authority model

Added by the deep-security pass, which asked the question this document had never
answered precisely: **what exactly does an authority authorize?**

Derived from the code, not from intent. `RunState.issue_authority` is the only
constructor of a `PaymentAuthority` in the repository, and `MockPSP.charge` is the
only consumer.

## The tuple

An approval authorizes exactly this, and nothing wider:

```
AUTHORIZE(
    authorization_id   -- this one purchase, by the platform's live id
    merchant_id        -- this one counterparty
    amount <= ceiling  -- at most the amount actually approved, in CHF
    once               -- consumed_at; durable across a restart iff a persist hook
                          is wired, and scoped to ONE run state
    until expires_at   -- 15 real-clock minutes from issue, never extended
    while not revoked  -- the customer's brake, the platform's authority/card
                          status fields, AND mandate.status being ACTIVE
)
```

So the answer to "is it CHF 400, or CHF 400 at merchant X, or this exact
transaction?" is: **this exact transaction, once, for a short while, unless
stopped** — with the two qualifications below, which are part of the answer rather
than exceptions to it.

## What is bound, and where it is enforced

| Element | In the authority | Enforced at execution | Notes |
| --- | --- | --- | --- |
| authorization_id | yes | yes | the charge is bound to it; it cannot be redirected |
| merchant_id | yes | yes | compared against the **stored decision**, not the passed object |
| amount ceiling | yes | yes | `Decimal`; CHF 0.001 over is refused |
| single use | `consumed_at` | yes | durable across a crash only when the executor has a persist hook; per-`RunState`, so two workers each execute once (V11) |
| expiry | `expires_at` | yes | judged by the boundary's **own** clock |
| revocation | `revoked` | yes | re-read live, so a stale copy cannot resurrect it |
| mandate_id | yes | **no** | provenance. Caller-asserted at resolution time and unverified; it labels the audit record, it does not gate money |
| policy_version | yes | **no** | provenance. A run is bound to one snapshot, so it cannot change beneath an outstanding authority; enforcing it would be a dead branch |
| basket_fingerprint | yes | **no** | provenance *here*. The basket is frozen at the DECISION layer by `authorization_id_conflict`, which is where the comparison is actually possible — the charge path receives an amount, not a basket |
| currency | yes | n/a | always CHF; conversion happens before the boundary |

Two things are deliberately **not** in the tuple: there is no parent/child
authority, no attenuation and no authority family in this codebase. Earlier
briefing material described such a model; it does not exist here, and inventing one
to match the description would add a lifecycle with no caller.

## What freezes the facts

The authority binds *money and counterparty*. What binds the *purchase* is a
separate mechanism at the decision layer, the repeat-delivery fingerprint:

```
(merchant_id, billing_amount_chf,
 [(item_id, item_name, quantity, return_window_days, final_sale, stated_size), ...])
```

Note the last three: facts **derived from** merchant text, never the raw text. That
asymmetry is load-bearing in both directions — a text edit that moves a fact is a
conflict, while casing, padding and zero-width characters remain an ordinary retry.

Not in the fingerprint, each for a stated reason: `unit_price` (no rule reads it;
the total is compared separately), `order_returnable` (platform-supplied, different
trust tier), `timestamp` (a re-delivery may legitimately carry a new one).

Identity — `card_id` and `mandate_id` — is checked *before* the fingerprint, because
"is this event ours?" precedes "have we seen this purchase?".

## The one-sentence version, restated precisely

An ALLOW is not permission to spend; it is a single-use, time-boxed, merchant- and
amount-bound authorization to execute one specific purchase, revocable until it is
spent, and independently re-verified against persisted state at the only point
where money moves.
