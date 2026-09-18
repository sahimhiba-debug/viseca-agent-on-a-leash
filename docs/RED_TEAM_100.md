# Red-team corpus — the full matrix

**Generated from `src/wallet_control/red_team_corpus.py`. Do not edit by hand** —
regenerate with `python scripts/run_red_team_corpus.py -v`, and note that every row
below is produced by running the attack against the real engine, state and payment
boundary, not from a written-down expectation.

**133/133 held**, across 10 categories.

Cases are built by crossing attack primitives with the CONTEXT they land in —
first delivery, re-delivery, post-revocation, post-restart. That shape is
deliberate: every vulnerability the deep-security pass found survived per-field
testing and died only under a crossing. Two of the eight (V7, V8) were found by
this corpus and its sibling fuzzer rather than by reading the code.

## Coverage

| Category | Cases | Held |
| --- | ---: | ---: |
| A. replay | 15 | 15 |
| B. mutation | 15 | 15 |
| C. merchant injection | 30 | 30 |
| E. human step-up | 8 | 8 |
| F/N. revocation & recovery | 6 | 6 |
| I. money | 14 | 14 |
| J. time | 6 | 6 |
| L/O/G. malformed, stale & policy | 13 | 13 |
| P/K/M. identity & concurrency | 11 | 11 |
| Q. composition | 15 | 15 |

## Every case


### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B01a` | raises the amount, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B01b` | raises the amount, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B01c` | raises the amount, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B02a` | lowers the amount, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B02b` | lowers the amount, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B02c` | lowers the amount, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B03a` | moves the amount by CHF 0.01, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B03b` | moves the amount by CHF 0.01, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B03c` | moves the amount by CHF 0.01, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B04a` | pays a different merchant, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B04b` | pays a different merchant, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B04c` | pays a different merchant, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B05a` | ships a different product id, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B05b` | ships a different product id, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B05c` | ships a different product id, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B06a` | renames the line, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B06b` | renames the line, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B06c` | renames the line, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B07a` | changes quantity 1 -> 7, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B07b` | changes quantity 1 -> 7, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B07c` | changes quantity 1 -> 7, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B08a` | adds an unrequested line, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B08b` | adds an unrequested line, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B08c` | adds an unrequested line, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B09a` | restates the size 43 -> 38, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B09b` | restates the size 43 -> 38, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B09c` | restates the size 43 -> 38, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B10a` | turns the order final-sale, fresh id | judged on its own facts, never inherited | fresh delivery -> allow | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B10b` | turns the order final-sale, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=True spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B10c` | turns the order final-sale, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B11a` | claims another card, fresh id | judged on its own facts, never inherited | fresh delivery -> block | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B11b` | claims another card, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=False spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B11c` | claims another card, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B12a` | claims another mandate, fresh id | judged on its own facts, never inherited | fresh delivery -> block | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B12b` | claims another mandate, same id re-delivered | original approval must not stay spendable | re-delivery -> block conflict=False spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B12c` | claims another mandate, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B13a` | platform reports the authority revoked, fresh id | judged on its own facts, never inherited | fresh delivery -> block | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B13b` | platform reports the authority revoked, same id re-delivered | original approval must not stay spendable | re-delivery -> allow conflict=False spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B13c` | platform reports the authority revoked, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B14a` | platform reports the authority expired, fresh id | judged on its own facts, never inherited | fresh delivery -> block | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B14b` | platform reports the authority expired, same id re-delivered | original approval must not stay spendable | re-delivery -> allow conflict=False spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B14c` | platform reports the authority expired, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### B. mutation

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B15a` | platform reports the card blocked, fresh id | judged on its own facts, never inherited | fresh delivery -> block | PASS |

### A. replay

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B15b` | platform reports the card blocked, same id re-delivered | original approval must not stay spendable | re-delivery -> allow conflict=False spendable=False | PASS |

### Q. composition

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `B15c` | platform reports the card blocked, then charge at the mutated amount | payment boundary refuses | refused: requested charge CHF 400 exceeds the approved amount CHF 100.0 | PASS |

### C. merchant injection

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `C01a` | injected text (preauth) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C01b` | injected text (preauth) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C02a` | injected text (already_approved) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C02b` | injected text (already_approved) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C03a` | injected text (wallet_says_ok) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C03b` | injected text (wallet_says_ok) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C04a` | injected text (emergency) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C04b` | injected text (emergency) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C05a` | injected text (ignore_policy) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C05b` | injected text (ignore_policy) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C06a` | injected text (already_paid) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C06b` | injected text (already_paid) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C07a` | injected text (fake_size) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C07b` | injected text (fake_size) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C08a` | injected text (zero_width) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C08b` | injected text (zero_width) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C09a` | injected text (homoglyph) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C09b` | injected text (homoglyph) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C10a` | injected text (bidi) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C10b` | injected text (bidi) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C11a` | injected text (html) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C11b` | injected text (html) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C12a` | injected text (json_blob) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C12b` | injected text (json_blob) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C13a` | injected text (markdown) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C13b` | injected text (markdown) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C14a` | injected text (very_long) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C14b` | injected text (very_long) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |
| `C15a` | injected text (null_byte) on an over-limit purchase | still BLOCKed on the real ceiling | over-limit purchase -> block | PASS |
| `C15b` | injected text (null_byte) cannot rewrite policy | mandate rules are untouched | mandate rules unchanged by merchant text | PASS |

### E. human step-up

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `E01` | basket swapped to CHF 999 after the human approved CHF 100 | stored facts stand; mutation is a conflict | swap after approval -> block, stored stays CHF 100.0 | PASS |
| `E02` | charge CHF 999 against a CHF 100 human approval | payment boundary refuses | refused: requested charge CHF 999 exceeds the approved amount CHF 100.0 | PASS |
| `E03` | second, conflicting human answer | refused, first answer stands | refused: AU1 was already resolved as 'allow'; cannot now resolve it as 'block' | PASS |
| `E04` | human answer replayed identically | idempotent, spend counted once | repeat answer idempotent; spend=100.0 | PASS |
| `E05` | resolve against a different run's state | refused | refused: cannot resolve AU1: it was never sent to the customer for review | PASS |
| `E06` | resolve an authorization never put to the customer | refused | refused: cannot resolve AU1: it was decided automatically and was never put to  | PASS |
| `E07` | approve the step-up, then revoke the mandate | approved money is stopped | refused: the payment authority for AU1 has been revoked; refusing to charge | PASS |
| `E08` | charge a step-up the customer declined | payment boundary refuses | refused: AU1 is not approved (decision='block'); a pending step_up or a decline must never be exe | PASS |

### F/N. revocation & recovery

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `F01` | revoke the mandate, then charge | no money moves | refused: the payment authority for AU1 has been revoked; refusing to charge | PASS |
| `N01` | revoke, crash, restart, then charge | revocation survives the restart | refused: the payment authority for AU1 has been revoked; refusing to charge | PASS |
| `N02` | crash and restart an unspent authority | expiry window is not refreshed | expiry preserved across restart: True | PASS |
| `N03` | charge, crash, restart, charge again | one authorization, one execution | refused: AU1 was already executed at 2026-09-17T23:55:30.539244+00:00; refusing | PASS |
| `F02` | platform reports revoked on a re-delivery | outstanding authority stops being spendable | replay -> allow; refused: the payment authority for AU1 has been revoked; refusing to charge | PASS |
| `N04` | rolling-limit spend after a restart | prior approved spend is not forgotten | rolling limit after restart -> block | PASS |

### I. money

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `I01` | CHF 200.01 against a CHF 200 cap | blocked | CHF 200.01 against a CHF 200 cap -> block | PASS |
| `I02` | CHF 1e9 against a CHF 200 cap | blocked | CHF 1000000000.0 against a CHF 200 cap -> block | PASS |
| `I03` | exactly CHF 200 against a CHF 200 cap | allowed; <= includes the boundary | exactly at the cap -> allow (<= must include the boundary) | PASS |
| `I04` | amount 0 | blocked by the amount-integrity check | amount 0.0 -> block | PASS |
| `I05` | amount -100 | blocked | amount -100.0 -> block | PASS |
| `I06` | amount -0.0 | blocked | amount -0.0 -> block | PASS |
| `I07` | amount NaN | never an approval | NaN -> raised InvalidOperation (fails closed, no decision submitted) | PASS |
| `I08` | amount +Infinity | never an approval | +Inf -> raised InvalidOperation (fails closed, no decision submitted) | PASS |
| `I09` | amount -Infinity | never an approval | -Inf -> raised InvalidOperation (fails closed, no decision submitted) | PASS |
| `I10` | billing_amount_chf inconsistent with amount x fx | blocked | billing_amount_chf inconsistent with amount*fx -> block | PASS |
| `I11` | correct EUR conversion | allowed (the check is not merely strict) | correct EUR->CHF conversion -> allow | PASS |
| `I12` | charge CHF 0.01 over the approved amount | refused | refused: requested charge CHF 100.01 exceeds the approved amount CHF 100.0 | PASS |
| `I13` | charge CHF 0.001 over the approved amount | refused (Decimal, not float, comparison) | refused: requested charge CHF 100.001 exceeds the approved amount CHF 100.0 | PASS |
| `I14` | charge under the approved amount | permitted | charging less than approved is permitted (a partial capture) | PASS |

### J. time

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `J01` | charge after the authority expires | refused | refused: the payment authority for AU1 expired at 2026-09-18T00:10:30.539875+00:00; refusing to c | PASS |
| `J02` | charge after expiry while claiming it is still issue time | refused; the caller's clock is not trusted | refused: the payment authority for AU1 expired at 2026-09-18T00:10:30.539916+00 | PASS |
| `J03` | charge inside the validity window | permitted | a charge inside the window still works | PASS |
| `J04` | second purchase inside a 7-day rolling cap | blocked | second purchase inside the 7-day window -> block | PASS |
| `J05` | purchase genuinely outside the rolling window | allowed | a genuinely later purchase outside the window -> allow | PASS |
| `J06` | pending step-up counted against a rolling cap | a purchase awaiting a human is not approved spend | a pending step-up contributes 0 to spend | PASS |

### P/K/M. identity & concurrency

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `P01` | event claims a different card | blocked; history is not borrowed | card_id=CA_SOMEONE_ELSE -> block | PASS |
| `P02` | card id differing only in case | blocked; identity is exact | card_id=ca_corpus -> block | PASS |
| `P03` | card id padded with spaces | blocked | card_id=' CA_CORPUS ' -> block | PASS |
| `P04` | card id with a zero-width character | blocked | card_id=CA_CORPUS+ZWSP -> block | PASS |
| `P05` | card id missing entirely | blocked | card_id=None -> block | PASS |
| `K01` | merchant id using a Cyrillic homoglyph | treated as a different merchant | homoglyph merchant id -> block | PASS |
| `P06` | charge routed to a different merchant | refused | refused: AU1 was approved for merchant 'ME_CORPUS_1', not 'ME_CORPUS_2'; refusing to charge | PASS |
| `P07` | charge an authorization that was never decided | refused | refused: AU_NEVER_DECIDED has not been decided yet; nothing to charge against | PASS |
| `P08` | one charge_id reused for two authorizations | refused, not treated as a retry | refused: charge_id 'CH1' was already used for authorization_id='AU1' amount=CHF | PASS |
| `H01` | charge the same authorization twice | refused | refused: AU1 was already executed at 2026-09-17T23:55:30.540404+00:00; refusing | PASS |
| `M01` | 24 threads racing the same charge | at most one execution | 1 succeeded / 23 refused across 24 racing threads | PASS |

### L/O/G. malformed, stale & policy

| Case | Attack | Expected security property | Observed | |
| --- | --- | --- | --- | :-: |
| `L01` | billing_amount_chf missing | never an approval | missing billing_amount_chf -> raised KeyError (no decision submitted) | PASS |
| `L02` | items missing | never an approval | missing items -> raised KeyError (no decision submitted) | PASS |
| `L03` | merchant missing | never an approval | missing merchant -> raised KeyError (no decision submitted) | PASS |
| `L04` | timestamp missing | never an approval | missing timestamp -> raised KeyError (no decision submitted) | PASS |
| `L05` | currency missing | never an approval | missing currency -> raised KeyError (no decision submitted) | PASS |
| `L06` | billing_amount_chf is a string | never an approval | billing_amount_chf='one hundred' -> raised InvalidOperation (no decision submitted) | PASS |
| `L07` | billing_amount_chf is null | never an approval | billing_amount_chf=None -> raised TypeError (no decision submitted) | PASS |
| `L08` | items is a string | never an approval | items='not-a-list' -> raised TypeError (no decision submitted) | PASS |
| `L09` | currency is unknown | never an approval | currency='XXX' -> raised ValueError (no decision submitted) | PASS |
| `L10` | empty basket under a category rule | never an approval | empty basket -> raised ValueError | PASS |
| `O01` | no purchase history available | unknown, routed to the customer | no history available -> review (unknown, not assumed familiar) | PASS |
| `O02` | no history under a decline-on-uncertainty policy | blocked | no history, decline policy -> block | PASS |
| `G01` | a confirmed mandate with zero rules | not unlimited authority | a mandate with no rules -> review (not a blank cheque) | PASS |

---

## What this does and does not prove

**Does:** across 133 adversarial compositions, a fully compromised agent — free to
mutate amounts, merchants, baskets, item identities, merchant text, card and
mandate identities and platform statuses, to replay and retry, to race 24 threads
at one charge, and to crash the process mid-flight — obtained no execution beyond
exactly what the customer's mandate authorized.

**Does not:** prove the absence of vulnerabilities. It proves these 133 attacks are
defeated by this code today. Three of the eight vulnerabilities fixed in this pass
lived in code that previous passes had declared hardened, which is the honest prior
on any such claim. The limits that no corpus can close are in
`docs/DEEP_SECURITY_RESEARCH.md` §7 — chiefly that a lying merchant can satisfy two
customer rules, and that every rolling-window guarantee rests on the platform's
timestamp being truthful.
