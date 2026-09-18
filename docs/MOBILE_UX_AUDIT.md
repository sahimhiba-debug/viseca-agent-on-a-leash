# Mobile UX audit

The organizers confirmed at Q&A that the solution should be **phone-friendly**, because
most customers will use a phone. The customer-facing experience was therefore rebuilt
mobile-first — a bottom tab bar, one-column decision cards, progressive disclosure —
rather than shrinking a desktop layout. The backend and security model are unchanged
and UI-independent.

## Method

Driven in a real browser at each required viewport, with real content loaded (11
decision cards from SCEN0004 and all 8 attack cards), measuring the DOM rather than
eyeballing screenshots:

- horizontal overflow = `documentElement.scrollWidth − clientWidth`, per panel
- clipped elements = any element whose `scrollWidth` exceeds its `clientWidth`
- touch targets = every visible `button`, `select` and `summary` under 44 px tall

## Results

| viewport | horizontal overflow | clipped elements | touch targets < 44px |
| --- | --- | --- | --- |
| **375 × 812** | 0 px on all 5 panels | none | none |
| **390 × 844** | 0 px on all 5 panels | none | none |
| **412 × 915** | 0 px on all 5 panels | none | none |
| desktop (responsive) | 0 px | none | none |

Verified with the full journey loaded, not an empty page: 11 decision cards, 11
baskets, 8 attack cards, 1 step-up with both actions present.

## What was fixed during the audit

| finding | fix |
| --- | --- |
| Disclosure summaries ("Technical evidence") were 36 px tall | raised to 44 px |
| `<nav>` sat after `<main>` in the DOM, so at ≥760 px the desktop tab strip rendered at the **bottom of the page** | nav moved before `<main>`; it is `position:fixed` bottom on a phone and a static top strip on desktop, from one media query |
| Decision cards were titled with the item the customer **requested**, so the gift-voucher substitution looked identical to a legitimate monitor purchase | cards now list the basket the agent **actually proposed**, with substituted lines in red |
| Block reasons were raw engine strings (`item.category (fail): item_categories=['electronics','subscriptions'], outside requested set: [...]`) | one plain sentence per failed check; the machine string moved behind "Technical evidence" |
| `(unknown)` shown to the customer as the reason for a step-up | replaced with what is actually unknown, e.g. *"The seller did not say whether this can be returned."* |

## The mobile decision screen

Built around the six questions in order, top to bottom, no horizontal scrolling:

```
NEEDS YOU                    ← what is happening
CHF 289.00                   ← what the agent is trying to do
PixelHarbor
1× 27-inch computer monitor  ← what it actually proposed

WHY THE WALLET IS ASKING     ← why
 • This looks like an order you already placed.
   The wallet cannot tell whether you meant to
   order it twice.

You are approving this one purchase only —      ← exact scope of the human decision
CHF 289.00 at PixelHarbor. Not a standing exception.

[ Approve once ]  [ Decline ]                   ← what you can do
  Technical evidence ▸                          ← progressive disclosure for judges
```

The blocked variant reads the same way and names the offending fact:

```
BLOCKED
CHF 195.00
PixelHarbor
1× Digital gift voucher        ← in red: not what you asked for

WHY THIS WAS STOPPED
 • This is a kind of item you did not ask for
 • This is not the item you asked for
 • The basket contains something you did not ask for
```

## Mobile design decisions

- **Bottom tab bar on phones.** Five destinations within thumb reach; it becomes a top
  strip at ≥760 px. One nav, one media query — not two implementations.
- **16 px inputs.** Anything smaller makes iOS Safari zoom on focus and break the layout.
- **`env(safe-area-inset-*)`** on the app bar and tab bar for notched devices.
- **No modals or bottom sheets.** Every flow is short enough to be a card in the page;
  a sheet would have added state and an overflow failure mode for no gain.
- **`overflow-wrap:anywhere`** on the evidence blocks — the only content long enough to
  overflow is machine output (authorization ids, reason codes), and it is inside a
  collapsed disclosure.

## The 60-second phone test

A judge with only a phone, landing on Home:

| question | answered by |
| --- | --- |
| What is this? | the first card: *"Your agent can shop for you — without holding your payment authority."* |
| What did the customer authorise? | Delegate → "What you are delegating", with an `enforced` / `not enforced` badge on every figure |
| What did the agent propose? | the basket on each decision card |
| Why did the wallet allow/ask/block? | the coloured "why" panel, one plain sentence per check |
| What can the customer do? | Approve once · Decline · Revoke this mandate |

## Remaining mobile limitations

1. **The audit timeline is long** — ~29 entries for an 11-purchase run, with no filter or
   grouping. It is readable but it is a scroll.
2. **No landscape-specific layout.** It reflows and does not overflow; it was not designed for it.
3. **Not tested on physical hardware** — these are emulated viewports in a desktop browser,
   so real iOS/Android font rendering, momentum scrolling and keyboard behaviour are unverified.
4. **No offline/PWA support.** The page needs the local backend.
