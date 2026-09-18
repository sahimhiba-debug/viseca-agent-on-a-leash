# Fulfilment audit 2 — attacking the derived model

Independent campaign against the rebuild. Deliberately not a replay of Audit 1:
that audit attacked *state*, so this one attacks *derivation* — idempotency,
inputs, and semantics of the anchor.

**Result: the central property survived. One real limitation and two API sharp
edges found.**

---

## C1 — Replay inflation  ·  MODEL HELD (and gained a property)

**Hypothesis.** If fulfilment counts approvals, re-delivering one authorization
should inflate it.

```
1 purchase + 5 idempotent re-deliveries -> first_fulfilment
```

**Survived.** The ledger is keyed by `authorization_id`, so replays collapse. A
tally fed from engine results would have counted six. This property was not
designed in; it falls out of deriving rather than counting.

---

## C2 — Denial of fulfilment  ·  REAL LIMITATION

**Hypothesis.** The anchor is a substring. Find something cheap that legitimately
contains it, buy that first, and burn the job.

```
CHF 25 "27-inch monitor stand", then the real CHF 350 monitor
-> already_fulfilled  (the real purchase now needs customer approval)
```

**Survived as a security property?** Yes — no money is wrongly authorized. The
attacker spends CHF 25 and gains a confirmation prompt.

**But it is a real limitation**, and a fix would need a product taxonomy this
project has repeatedly declined to fake. Pinned as a test that asserts the
limitation rather than hiding it.

---

## C3 — Cross-mandate derivation  ·  SHARP EDGE

`fulfilment_state(foreign_mandate, state)` computes happily. There is no
mandate/run binding, unlike `evaluate_authorization`, which now checks
`mandate_id`. A caller error, not an attacker capability — the mandate is not
attacker-supplied — but worth stating.

---

## C4 — Conflicting re-delivery  ·  MODEL HELD

A same-id, different-amount re-delivery is an `authorization_id_conflict` and does
not become a second approved decision.

```
approved decisions on file: ['AU1']
```

---

## C5 — `assessing=None`  ·  SHARP EDGE

Omitting the argument makes the current purchase count as its own predecessor, so a
single purchase reports `already_fulfilled`. A read-only query, and the differential
always passes `assessing` — but a footgun. Documented, not changed.

---

## Verdict

| | Finding | Outcome |
| --- | --- | --- |
| C1 | replay inflation | held — structurally immune |
| C2 | denial of fulfilment | real limitation, pinned as a test |
| C3 | no mandate/run binding | sharp edge, documented |
| C4 | conflicting re-delivery | held |
| C5 | `assessing=None` | sharp edge, documented |

The property under test —

> for a one-shot mandate with a specific anchor, the number of authorized
> performances is a function of the persisted ledger alone

— was attacked from a different direction than Audit 1 and did not break. The two
sharp edges are caller-side; the one real limitation costs the attacker money and
yields friction rather than funds.

**Both audits found real defects. Audit 1's ended the abstraction; Audit 2's are
bounded and documented.**
