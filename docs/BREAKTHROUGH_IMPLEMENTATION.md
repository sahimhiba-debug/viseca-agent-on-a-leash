# Breakthrough implementation

## Before

`_projected_period_spend` asked: *what is already in the window that ends at this
purchase, plus this purchase?*

```python
prior = state.rolling_spend_chf(as_of, rule.period_days)
projected[rule.period_days] = prior + this_amount
```

Correct only when decisions are made in chronological order and none is deferred.

## After

```python
projected[rule.period_days] = state.peak_window_spend_chf(
    as_of, this_amount, rule.period_days
)
```

with, in `state.py`:

```python
def peak_window_spend_chf(self, as_of, amount, period_days):
    trial = [*self._approved_spend, (as_of, amount)]
    window = timedelta(days=period_days)
    return max(
        sum((a for ts, a in trial if end - window < ts <= end), Decimal("0"))
        for end, _ in trial
    )
```

Each approved purchase (and this one) is a candidate window end; a window that contains
a purchase but ends at no purchase holds no more than one that does, so the maxima
coincide. O(n²) in the run's approved purchases — 2.2 ms at 201, 43 ms at 809, and the 8s
deadline at roughly 11,000; the largest official scenario has 12 purchase attempts
(`tests/test_scale_limits.py`).

## The same correction on the resolution path

`_period_rules_breached_now` — added in an earlier pass to close a forced-step-up
attack — used the same backward-looking window and therefore **missed exactly the case
it was written for**. A resolution is by definition out of order: the purchase was
paused at its simulated time and the customer answers later, behind decisions already
taken.

## New invariant

> ∀t : Σ{ amount(p) : p approved, t−N < time(p) ≤ t } ≤ C

## New code

| file | change |
| --- | --- |
| `state.py` | `peak_window_spend_chf` — one pure function, ~10 lines plus its rationale |
| `decision_engine.py` | two call sites replaced |

**No new module, state, endpoint, dependency or UI component.** Runtime grew ~40 lines.

## New tests

`tests/security/test_window_containment.py` — 10 tests:

1. the deferred step-up attack is refused, naming the window it would breach
2. a resolution that genuinely fits still succeeds
3. no arrival order breaches the cap (60 random permutations of official data)
4. the approval count does not depend on arrival order
5. the peak and backward windows agree when nothing is out of order (why the replay is unchanged)
6–10. the official replay, per scenario

## Regression

643 tests · official replay **45 / 19 allow / 2 review / 24 block** · corpus 133/133 ·
matrix 17/17 · differential 6 / CHF 1,787.40 · all eight scripts clean · mobile 0
overflow / 0 small targets at 390×844.

## Demo

1. *"Each order ≤ CHF 120, and ≤ CHF 300 across any seven days."*
2. A CHF 180 purchase is **paused** for the customer — the wallet being careful.
3. Two CHF 150 purchases are approved. The week reaches exactly the cap.
4. The customer approves the paused one. **Without the fix: CHF 480 in a CHF 300 week,
   every decision correct.**
5. With the fix: refused, naming the window.

**"Being careful created the hole. The pause is what broke the budget."**
