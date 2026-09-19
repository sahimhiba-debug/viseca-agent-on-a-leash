# Multi-day autonomous research program — final report

The brief was not "add features". It was to reach the **maximum defensible
understanding of this system**, and to be able to answer one question before
stopping:

> If an exceptionally capable independent security researcher received this
> repository tomorrow with no knowledge of our development history, what would
> they attack?

Then to attack it myself. This is the record.

---

## 1. The answer to the question, and what happened when I attacked it

**They would attack the newest security-critical code**, because it has had the
least time under fire, and they would find it by reading our own documents for an
admission. Ours contained one: `peak_window_spend_chf` handled multiple
overlapping period rules, and three documents said that case was *"supported but
unexercised"*.

So I exercised it: three nested caps (CHF 200/1 day, 300/7 days, 1000/30 days),
randomized amounts, timestamps spread over 35 days, ~45% of purchases forced into
step-ups and resolved in random order, 3,000 runs. **Zero breaches**, with windows
filling to 199.99 / 299.95 / 956.28 against caps of 200 / 300 / 1000 — tight, not
over-conservative. The caveat was removed from all three documents because it had
stopped being true.

**Then I asked the question a second time**, and gave a better answer: they would
not attack the code, they would attack **what the code does not check**. Nothing
here validates an incoming event against the official schema. The engine reads it
defensively, field by field — and a check written

```python
value = (event.get("block") or {}).get("field")
if value is not None and value != expected:   # <- switched off by DELETING the field
```

is disabled by *removing* what it guards. No forgery required.

That was live. `mandate.status` is the platform reporting the result of the
customer's `DELETE /v1/mandates`. Deleting it — or the whole `mandate` block —
made a **revoked mandate produce ALLOW, mint a payment authority and charge.**

The tell was an asymmetry visible from outside: three platform status fields,
`authority_status` and `card_status_at_attempt` both routing a missing value to
`unknown`, and one reading a missing required field as consent.

---

## 2. What this campaign changed

| # | finding | severity | status |
| --- | --- | --- | --- |
| R19 | A required status field could be switched off by **deleting** it; a revoked mandate charged | **critical** | fixed, pinned as a general property over the schema's own enums |
| R23 | The rolling window's start boundary was **unpinned** — a mutation widening it survived the whole suite | low (a wider window only blocks more) | pinned; found by the new mutation probe |
| R22 | The README's most-read sentence contradicted the limitations document | claim defect | corrected |
| R22 | Three test counts went stale inside one session | claim defect | self-describing numbers are now machine-checked |
| R20 | "O(n²), fine at run scale, trivially reducible" — three unverified claims | unverified claim | measured; a **second** quadratic found in the checkpoint path |
| R21 | The invariant register's test column was hand-maintained and unchecked | rot risk | machine-checked |
| R17, R18 | Nine cross-invariant attacks; a 3,000-run nested-window campaign | — | no change; negative results recorded |

Five commits, `400307a` … `7c792e9`.

---

## 3. Phase 17 — cross-invariant attacks (mandated)

Every invariant held alone. The question was whether any *pair* opens a gap its
members close individually. Nine pairings, chosen where the two mechanisms
actually interact:

idempotency×revocation · idempotency×live status · policy snapshot×live status ·
duplicate×temporal window · duplicate×human×window · evidence×human approval ·
cross-run×fulfilment · provenance×merchant text · revocation×restart

**All nine held.** An event carrying widened rules cannot override the run's
snapshot. A suspected duplicate escalates, so it cannot silently double-count.
Merchant text narrows in both directions. A replay after revocation blocks and the
charge is refused.

A negative result on a mandated phase is still a result, and it is recorded rather
than quietly dropped.

---

## 4. What an auditor can run instead of believing us

```bash
python3 -m pytest -q                      # 700 collected, 5 reported skips
python3 scripts/run_replay.py             # 45 events — 19 allow / 2 review / 24 block
python3 scripts/run_red_team_corpus.py    # 133/133
python3 scripts/run_red_team.py           # 17/17
python3 scripts/run_mutation_probe.py     # 18 mutants, 18 killed, 0 survived
```

The last one is the answer to "your tests could be theatre". It deliberately breaks
18 security mechanisms in `src/wallet_control/`, one at a time, and checks the suite
notices. It earned its place by finding a real gap on its first run.

Three claims are now machine-checked rather than asserted:

* **the invariant register** — every one of its 33 citations must resolve to a test
  that exists (`test_every_test_the_register_cites_exists`);
* **the numbers this repository states about itself** — test counts in the README
  and the audit package, and every per-scenario row of the replay table
  (`tests/test_stated_numbers.py`);
* **the omission property** — deleting a required field never buys a more permissive
  decision than its strictest legal value (`tests/security/test_required_field_omission.py`).

---

## 5. Performance, measured

| | |
| --- | --- |
| shape of `peak_window_spend_chf` | **exactly quadratic** — with window saturation removed, ms/n² is flat at ~63e-6 across n=203→1,612 (drift 0.98×) |
| 8-second deadline crossed at | **n ≈ 11,200** approved purchases in one run, worst case over window configurations (13,600 with a 30-day window at 1 purchase/hour — see §7) |
| largest official scenario | **12** purchase attempts |
| baskets | linear — 20,000 item lines is 54 ms |
| pending step-ups | do not enter the window scan; 2,000 unresolved still decide in 0.15 ms |
| **the quadratic that bites first** | not this one — `_save_checkpoint` re-serializes the whole run on every event (1.3 MiB/event at 2,000 decisions). **Disk, not CPU.** |

The quadratic is not an accident to optimize away: scanning every window that
*contains* the candidate, rather than the one ending at it, is what closed the hole
where CHF 480 was approved against a CHF 300 cap.

---

## 6. What is still risky

Ranked by where I think an auditor is most likely to find something. This is the
same list as `docs/FINAL_AUDIT_PACKAGE.md`, which is the document to read next.

1. **Merchant-claimed facts.** `order.return_window_days` and `item.size` have no
   input other than merchant free text. A plausible claim beats every realistic
   threshold with zero policy knowledge. **Not fixable inside the official rule
   vocabulary**, and the largest real exposure here.
2. **Cross-run state.** The period cap is enforced per *run*. One mandate across ten
   runs authorizes ten times the cap. I argue this is the official period semantics
   and that the agent does not control run boundaries — *attack that argument.*
3. **Multi-process execution.** Two workers restoring one checkpoint each charge
   once. At-most-once per process, never exactly-once.
4. **Fields nobody thought to mutate.** The mutation probe is targeted, not
   exhaustive. It cannot speak for a mechanism not on its list.
5. **The register's mapping.** It is now machine-checked that every cited test
   *exists*. It is not checked that a cited test *exercises* the invariant it is
   filed under. That is a human reading, and it is the weakest remaining link in
   the strongest-looking artifact.
6. **The step-up channel.** No authentication, no `resolved_by`.
7. **What the platform does if we miss a deadline.** Unknown. We fail closed on our
   own side; `technical_details.md` never says what follows a missed deadline. If
   platform-side silence *approves*, "submit nothing" is the wrong failure mode and
   is the first thing to change.

---

## 7. A correction this program made to itself, twice

The performance section did not survive its own campaign, and how it failed is
worth more than the number it produced.

**Pass 1.** Four points (n = 100…809): the constant `ms/n²` looked flat at ~66e-6
and the doubling ratios landed on 3.85 / 3.93 / **4.00**. Published: *the constant
settles, the ratios converge to 4.00, the deadline is crossed at n ≈ 11,000.* Into
a commit message, three documents, a research-log entry and a test docstring.

**Pass 2.** A longer run reaching **n = 6,418** contradicted it: the constant
*declines*, 66.6e-6 → 43.2e-6, and the ratios fall to ~3.5. Corrected to **13,600**.
Four points cannot establish convergence — the fourth ratio simply landed on 4.00
with nothing after it to disagree.

**Pass 3.** That correction was also wrong, and more dangerously, because it was
optimistic. Varying the window length while holding everything else fixed isolated
the cause: the decline is **window saturation**. At one purchase per simulated hour
a 30-day window holds ~720, so past n ≈ 720 the expensive in-window `Decimal`
additions stop growing while the cheap timestamp comparisons continue. Remove
saturation — a window nothing ever falls out of — and the constant is **flat at
~63e-6 (drift 0.98× across n = 203…1,612)**.

So the algorithm is **exactly quadratic**, which is what pass 1 said about the
*shape*, and the worst case over window configurations is **n ≈ 11,200**. Pass 2's
13,600 measured one favourable regime and quoted it as the bound.

What this cost and what it is worth:

* **Pass 1 was conservative; pass 2 was not.** Replacing a right-for-the-wrong-reason
  number with a wrong-and-optimistic one is the worse error, and it happened while
  "correcting" for rigour.
* **The failure was identical both times: reading a trend off too few points.** The
  word "settles" in pass 1 and the single configuration in pass 2 were each doing
  work the data could not support.
* **What finally settled it was varying one thing on purpose**, not measuring the
  same thing harder. Two runs of the same experiment disagreed; a third experiment
  designed to falsify a *mechanism* resolved it.

Both wrong passes are documented in `tests/test_scale_limits.py` and as R20, R24 and
R25, rather than quietly overwritten.

## 8. What this program did not do

* **No formal proof.** Everything here is empirical — 12,000 monotonicity baskets,
  3,000 lifecycle traces, 3,000 nested-window runs, 18 mutants. No proof was
  constructed and none is claimed.
* **No new features.** The only behaviour change is the omission fix, and it makes
  the engine strictly more conservative.
* **No new documents beyond this one and the tests.** There were already 88. A
  register nobody checks is worse than no register, so the effort went into making
  the existing ones machine-checked rather than into writing more.
* **`main` is untouched**, at `1aa3bac`. All work is on `rnd/productization`.

The honest summary of the campaign: the previously fixed defects stayed fixed, the
newest code had one real hole and it was found by asking what an outsider would
attack rather than by re-reading what we already trusted, and the largest exposure
in this system is still not a wallet defect — it is that a customer's own policy,
faithfully enforced, does not bound what they have delegated.
