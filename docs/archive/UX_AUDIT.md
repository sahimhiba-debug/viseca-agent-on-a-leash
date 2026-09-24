# UX audit

<!-- snapshot -->
> **SNAPSHOT — written 18 September 2026, not maintained.** Every figure below was measured
> when this was written. Several have moved since, including the official replay
> split, the test count and the mutation count. This page is kept because the
> reasoning in it is the evidence for why the boundary moved; it is not a
> description of the present. For current figures see `docs/BASELINE_CURRENT.md`,
> or run the commands in `docs/FINAL_AUDIT_PACKAGE.md`.

An independent reviewer was given the running product and the official challenge
framing, and nothing else — no docs, no git history. They drove every tab, ran a
scenario, approved a step-up, revoked a mandate and read the audit trail.

Their headline: *the honesty content is genuinely excellent — the problem is that its
two best disclosures are unreachable in the natural flow, one interaction destroys the
entire explanation layer, and three surfaces claim a confirmation step that does not
exist.*

## Must-fix findings, and what was done

| # | Finding | Action |
| --- | --- | --- |
| 1 | **Approving a step-up erased every explanation on the page.** `GET /api/runs/{id}` returned four fields while `POST /run` returned the full decision; the UI re-renders from the former. The one action a customer is guaranteed to take deleted the product's core promise. | **Fixed.** Both endpoints return the same shape. |
| 2 | **Three surfaces claimed a customer confirmation step; no confirm control existed.** The audit even recorded "Mandate confirmed" with no timestamp — because no such event had happened. | **Fixed.** A real confirm gate exists on Delegate and stamps the audit entry with its actual time. |
| 3 | **The audit recorded `Wallet decision: ALLOW` for a purchase the wallet had stepped up**, at the original timestamp — under a banner promising the projection cannot drift. An auditor could not tell the wallet had ever hesitated. | **Fixed.** `wallet_decision` is recorded separately from the final outcome; the customer's override is its own later event. |
| 4 | **Every card was titled with the item the customer requested, not the one proposed.** Eleven cards read "27-inch computer monitor" — including the one whose basket was a gift voucher. The engine caught every substitution and the card concealed it. | **Fixed.** Cards list the basket the agent actually proposed, substituted lines in red. |
| 5 | The typosquat block (`PixelHarbour` vs `PixelHarbor`) never mentioned the near-identical name. | **Partially.** The reason is now *"You have never paid this seller before"* in plain language. We deliberately do **not** claim lookalike detection — the wallet blocks on unfamiliarity, not on spelling, and saying otherwise would be an overclaim. |
| 6 | **The Overview headlined job-level deduplication; the flagship scenario shows five approvals of the same job.** A judge doing the arithmetic concludes the claim is false. | **Fixed by narrowing the claim**, not by broadening the check. Decisions now shows a standing note when several purchases are approved, saying plainly that repeats can each be individually valid. |
| 7 | **The best disclosure in the product was unreachable** — "What you are delegating" only populated after a run on a different tab. | **Fixed.** It renders immediately on compile, from the mandate alone, and the scenario choice carries across tabs. |
| 8 | **Customer-facing reasons were raw engine output** — dotted field paths, `(fail)`, Python list literals, `(unknown)`. | **Fixed.** One plain sentence per failed check; the machine string moved behind "Technical evidence". |
| 9 | The header badge read `replay 45 · 19/2/24`, which parses as a date. | **Fixed.** Now `replay OK`, with the counts on the Home tab. |
| 10 | **After revocation, six cards still showed green ALLOW**, and nothing said what revocation did *not* stop. | **Fixed.** Those cards render as **Cancelled**, and a banner states what did and did not happen. |

## Findings deliberately not actioned

- **A filter or grouping for the ~29-entry audit timeline.** Real, but it is a scroll, not
  a failure, and adding filter state to a 543-line single-file UI costs more clarity than
  it buys.
- **A run timestamp on each attack card.** Added at the summary level; per-card state
  transitions were judged noise.
- **Linking the docs cited in the UI.** They are repository files, not routes; a dead link
  would be worse than a filename.

## On the security-model constraint

The reviewer was told they could not suggest changes that weaken or overstate the
security model, and reported finding **no place where the product understates a
protection it has**. The three overclaims they did find (#2, #3, #6) were all closed by
*narrowing the claim or building the missing control* — never by adding a protection we
could not prove.
