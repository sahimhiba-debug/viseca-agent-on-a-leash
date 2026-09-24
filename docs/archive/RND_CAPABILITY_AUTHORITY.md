# R&D Track A: Verifiable Payment Authority (capability-based authorization)

## Threat model

Today, "what was actually approved" for a purchase lives implicitly, as separate
fields scattered across `StoredDecision` (`state.py`): `decision`, `billing_amount_chf`,
`merchant_id`, `basket_key`, `timestamp`. `MockPSP.charge` reads these fields
individually and re-checks each one. This works (verified extensively in prior
audit passes) but has two weaknesses a capability-based redesign can close:

1. **There is no single, self-contained, inspectable object a judge, an auditor,
   or another service could hold and verify independently** -- "what was
   approved" can only be reconstructed by reading multiple fields off an internal
   dataclass, not shown as one artifact.
2. **There is no explicit expiry on the authority to charge.** An `allow`
   decision, once recorded, remains chargeable indefinitely (bounded only by the
   process lifetime) -- there is no notion of "this authorization to charge is
   itself only valid for N minutes/hours," independent of the original purchase's
   `deadline_at` (which governs the *decision* response window, not the *payment
   execution* window).

## Design

A `PaymentAuthority` (this project's local, unsigned analog of AP2's Payment
Mandate / Mastercard's Agentic Token -- see `AGENTIC_COMMERCE_RESEARCH.md`):

```python
@dataclass(frozen=True)
class PaymentAuthority:
    authorization_id: str
    mandate_id: str              # which confirmed mandate granted this
    merchant_id: str             # bound payee -- cannot be charged to any other
    amount_ceiling_chf: Decimal  # bound amount -- cannot be exceeded
    currency: str                # always "CHF" in this system; kept explicit
    issued_at: datetime          # simulated purchase time
    expires_at: datetime         # issued_at + a bounded TTL
    basket_fingerprint: tuple[tuple[str, int], ...]
    policy_version: str          # a hash of the mandate's hard_rules at issue time
    evidence_ref: str            # opaque pointer back to the EngineDecision's evidence
    revoked: bool = False
```

It is **issued only as a byproduct of an ALLOW decision** (never independently
constructible), is **immutable**, and `MockPSP.charge` is changed to consume a
`PaymentAuthority` instead of five loose keyword arguments -- collapsing five
independent checks into one: "does this authority, as a whole, permit this
charge?" `RunState` gains `revoke_authority(authorization_id)` so a mandate
revocation (or a customer-initiated "actually, cancel that" after step_up) can
invalidate an already-issued authority before it is spent, even though the
original decision was ALLOW.

## Alternatives considered

- **Do nothing; keep the current scattered-fields design.** Rejected because it
  cannot be demonstrated as a single artifact, and has no expiry concept at all --
  both real, if narrow, gaps confirmed by comparing against every real-world
  system researched (all of them scope authority with an explicit TTL).
- **A fully cryptographically signed Verifiable Credential (à la AP2).** Rejected
  per `AGENTIC_COMMERCE_RESEARCH.md`: there is no PKI, relying party, or verifier
  in this challenge's sandbox; a "signature" with no one able to verify it would
  be theatre, not security.
- **Store the authority server-side only, never serialize it.** Rejected because
  the entire point of a capability model is that the object itself is the
  evidence -- an internal-only representation loses the "verifiable" property the
  research direction is named for, and the demo value (showing the actual JSON) is
  lost too.

## Attack examples this closes or clarifies

- **Charge after expiry**: even a correctly-approved purchase, charged an hour
  later, is currently accepted by `MockPSP` with no time bound at all beyond the
  process being alive. A `PaymentAuthority` with `expires_at` closes this
  explicitly, with a policy decision to make (see Implementation below on the TTL
  value chosen and why).
- **Charge after mandate revocation, before the authority was consumed**: today,
  revoking a `Mandate` does not touch any already-issued `StoredDecision`.
  `revoke_authority` makes this an explicit, one-line, auditable action instead of
  an unaddressed gap.

## Implementation cost

Small. `PaymentAuthority` is a new, additive dataclass; `MockPSP.charge` is
refactored to accept one authority object instead of four parameters (a pure
internal refactor, no change to `decision_engine.py`'s public contract);
`RunState` gains one new method and one new dict. No change to the official
Viseca wire contract (this is entirely internal/local, as `docs/VISECA_INTEGRATION.md`
already establishes for `MockPSP` as a whole).

## Demo value

High and concrete: the demo UI can show the actual `PaymentAuthority` JSON
alongside a decision -- "here is exactly what was authorized, bound to this
merchant, this amount, expiring at this time" -- which is a more compelling,
verifiable artifact than a log line saying "approved."

## Compatibility

Fully compatible. `PaymentAuthority` is issued and consumed entirely within this
codebase; nothing about it is sent to or expected by the hosted Viseca API.

## Recommendation: **PROTOTYPE** (selected for implementation)

Scores highest of all ten tracks on Viseca relevance (directly demonstrates "the
agent proposes, the wallet grants bounded authority, not a blank cheque" -- the
challenge's own framing) combined with low implementation cost and zero
regression risk (additive, with the existing `MockPSP` test suite as a
regression baseline). See `docs/archive/RND_FINAL_DECISION.md` for the scoring table.
