# State machine audit

Every lifecycle state, every illegal transition, attacked through the running API
rather than reasoned about.

---

## The states

**A decision** is one of `allow`, `block`, `review`. A `review` is *pending* until a
human answers, then *resolved* to `allow` or `block`. **A run** is open or revoked.
**An authority** exists only for an approved decision, and is unissued, issued,
consumed, revoked or expired.

Two facts make the machine tractable. The execution lifecycle lives **on** the
decision record rather than in a second object — two records describing one
authorization was the shape that produced four separate vulnerabilities. And
revocation is **run-scoped state**, not a sweep over existing records, so it covers
records that do not exist yet.

## Illegal transitions, attacked

| transition | result | why |
| --- | --- | --- |
| revoke → approve a pending step-up | **200, final `block`, authority `None`** | revocation is the later and stronger instruction |
| `block` → resolve(allow) | **409** | only a purchase still waiting may be answered |
| `allow` → resolve(block) | **409** | same |
| resolved → flip the answer | **409** | a customer cannot un-answer |
| resolve twice, same answer | **200**, idempotent | a double-clicked button is not a conflict |
| approve → then revoke | authority **`None`** | unspent authority dies |
| revoke twice | **200 / 200**, idempotent | |
| revoke an unknown run | **404** | |
| resolve an unknown authorization | **404** | |
| resolve with an invalid verdict | **400** | `allow` or `block`, nothing else |
| new mandate on a live session | **409** | rules that can change under a running agent can be widened under one |
| agent's `authorization_id` against `/api/runs/` | **404** | separate namespaces |
| same `authorization_id` re-sent | idempotent; spend counted **once** | an ordinary network retry must not double-count |

## Timestamps: who owns each

No caller can fabricate any of them. All four attacks rejected.

| timestamp | supplied by | authority | used for | fabricable |
| --- | --- | --- | --- | --- |
| purchase time | platform (simulated) | platform | **security** — rolling windows | **no** |
| `deadline_at` | platform (real) | platform | response deadline | no |
| `resolved_at` | wallet (real clock) | wallet | audit display | **no** |
| `confirmed_at` | **wallet** (server-stamped) | wallet | audit display | **no** — was caller-supplied, and reached an entry attributed to `actor="customer"` |
| revocation time | wallet (real clock) | wallet | **security** — the revocation boundary | **no** |
| authority issue / expiry | wallet | wallet | **security** — TTL | no |

The audit labels every entry `real` or `simulated` alongside its actor, so a reader
can see which clock a fact came from. Windows key on *simulated* purchase time;
deadlines and human answers key on the *real* clock. A human answering an hour later
must not shift a purchase's window attribution.

## State × economics

| situation | budget consumed | correct |
| --- | --- | --- |
| approved purchase | full amount | ✓ |
| blocked purchase | **nothing** | ✓ |
| step-up **pending** | **nothing** — no reservation | ✓ |
| step-up approved | counted at resolution | ✓ |
| step-up declined | **nothing** | ✓ |
| duplicate `authorization_id` | counted **once** | ✓ |
| after revocation | spent stays spent; nothing further approves | ✓ |
| new run | **resets to zero** | per-run scope — see `FINAL_LIMITATIONS_AUDIT.md` |

### The over-commit attack, and a near-miss worth recording

A compromised agent chooses what gets queued, so it can push several
individually-reasonable purchases into the step-up queue and have them approved one
at a time, together far over the customer's cap. Pending step-ups deliberately
reserve **nothing** — reserving budget for a purchase that may never happen is its
own defect — so the defence has to live at resolution time, and it does:
`_period_rules_breached_now` re-checks the window before recording an approval.

This audit reproduced "CHF 400 approved against a stated CHF 300/7-day cap" and it
looked live for several minutes. **It was not.** The test had called
`resolve_authorization` without the `mandate` argument, which is optional for
backward compatibility, and when it is omitted the re-check silently never runs.
Called the way `api.py` calls it, the second approval is **blocked** and the window
holds at CHF 200.

That near-miss is now a permanent guard: an AST test asserts every runtime caller
passes the mandate, and the hazard itself is pinned so that making the parameter
required shows up as a deliberate red test rather than an accident.
