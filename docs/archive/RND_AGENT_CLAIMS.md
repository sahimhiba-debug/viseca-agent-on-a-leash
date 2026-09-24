# R&D Track C: Agent claims vs. wallet-observed facts

## The core question

Should the shopping agent's *framing* of a purchase (e.g., `purchase_description`,
or an agent's own summary of "why" it's proposing this) ever be trusted, even
partially? And when the agent's claim and the wallet's own observation disagree,
how should that disagreement be surfaced?

## What already exists

This separation is not a new idea to introduce -- it is the **architectural
foundation this entire codebase is built on**, from the very first pass:

- `facts.py`'s module docstring: the authorization event mixes platform-supplied
  structured fields (trusted, used directly), merchant-supplied free text
  (untrusted, read through exactly two whitelist patterns), and system-derived
  signals (computed from the first category, never the second).
- `authorization.purchase_description` -- the field that most resembles an
  "agent claim" about what's being bought -- is **never read by the engine at
  all** (confirmed and documented in `SECURITY_MODEL.md`), precisely because the
  data dictionary itself says it "names the kind of order and nothing more" and
  carries no verifiable signal.
- The **amount-integrity check** (`decision_engine.py`, added in the second audit
  pass) is, structurally, already a claim-vs-fact conflict detector: it compares
  the platform's *claimed* `billing_amount_chf` against the *independently
  recomputed* `amount * fx_rate`, and blocks on disagreement. This is the CLAIM
  / FACT / CONFLICT / CONSEQUENCE model the brief describes, just not labeled
  that way in the code.
- The **repeated-authorization-id fingerprint check** (`RunState.check_repeat_fingerprint`,
  second audit pass) is the same pattern applied to identity: a re-delivered
  event's *claimed* facts (via its `authorization_id`) are checked against the
  wallet's own *recorded* facts from the first delivery, and a mismatch produces
  a `CONFLICT` outcome (`authorization_id_conflict`) rather than trusting either
  side blindly.

## What a formal "claims" layer would add

A `Claim`/`Fact`/`Conflict` type hierarchy wrapping the above, so the pattern is
named and reusable rather than implemented ad hoc twice. Prototyped mentally as:

```python
@dataclass(frozen=True)
class Conflict:
    claim: str           # what was asserted (e.g. "billing_amount_chf=520")
    observed: str         # what was independently computed/recorded (e.g. "amount*fx=520.35" or "original amount=289")
    consequence: Decision  # what this conflict forces
```

## Why this was not built as new infrastructure

Every actual conflict this system currently detects (amount-integrity mismatch,
repeated-authorization-id fingerprint mismatch) already produces a `fail` outcome
or an `authorization_id_conflict` flag with a clear evidence string naming both
sides of the disagreement (see the evidence strings in `decision_engine.py`'s
`authorization_id_conflict` branch: `"original: merchant=... received: merchant=..."`).
Wrapping these two existing, working mechanisms in a shared `Conflict` type would
improve naming consistency but detect nothing new -- there is no THIRD kind of
claim-vs-fact conflict latent in the official data model that isn't already one
of these two. (A genuinely new one -- e.g., "the agent's stated `item_name` claim
vs. a catalog fact" -- was investigated in the second and third audit passes and
found not independently verifiable: there is no independent oracle for item
identity in this data model beyond the structured `item_category`/`item_id`
fields, which are already trusted directly, not claimed.)

## Recommendation: **KEEP** (as an architectural principle, already implemented; no new code)

This track's value is almost entirely as a **framing and documentation
exercise** -- making explicit, in one place, that the claim/fact/conflict pattern
already threads through this codebase's two most security-critical checks. That
documentation work is this file plus the cross-references added to
`SECURITY_MODEL.md` and `SECURITY_INVARIANTS.md`. No new production code is
justified: the two real conflict detectors already exist, are tested (including
by property-based tests), and a wrapper type would be renaming, not hardening.
