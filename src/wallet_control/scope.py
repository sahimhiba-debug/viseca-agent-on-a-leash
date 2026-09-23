"""How big is the thing you just delegated? Count it.

A mandate is shown to the customer as rules: "each order at or below CHF 120",
"from a shop you have used before". Those are true and they are not an answer to
the question a person actually has, which is *how much rope did I just hand over*.

So count it. Enumerate every purchase this world can produce, put each one through
the REAL engine under the drafted mandate, and report the size of the set that
comes back approved.

    "Order our household groceries."                      595 of 595 purchases
    "...at or below CHF 120."                             145           -450
    "...from a shop I have used before."                  116            -29
    "...at or below CHF 60..."                             28            -88

Every clause removes purchases. That number is the only honest answer to "what did
that word actually do?", and it is measured rather than described.

WHY THIS IS THE RIGHT OBJECT

`optimized-apertus` is about speculative decoding: an 8B draft proposes, a 70B
target verifies, and the guarantee is that the output distribution is the target's
alone -- a bad draft changes the speed, never the answer. The same shape is the
whole architecture here, and it names the object: the **acceptance set** is our
output distribution. An agent picks where in it to go and how fast; no agent, however
compromised, can enlarge it. `research/acceptance_set.py` checks that by running
four brains -- including one with no taste at all -- over hundreds of proposals and
asserting that not one approved purchase falls outside the set.

It also gives a second, independent check on the read-back: **a word that changed no
rule cannot change the size of the set.** Cause and consequence, measured separately.

BOUNDED AND HONEST. The universe is one shop per basket, up to `MAX_LINES` lines,
from the official item and merchant catalogue. The absolute figures are a function
of that bound and mean nothing on their own -- what carries meaning is how they
MOVE when the sentence changes. Every count comes from the real engine deciding a
real event.

DECIDES NOTHING.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from itertools import combinations
from typing import Any

from .csv_data import history_csv_path, load_items, load_merchants
from .mandate import HardRule, MandateSnapshot, UncertaintyPolicy
from .policy_compiler import compile_instruction
from .state import HistoryIndex
from .witness import CARD, judge_event, snapshot

MAX_LINES = 5

# WHICH PRICE THE COUNTED WORLD QUOTES.
#
# `items.csv` gives every item a min/typical/max, and this panel used to enumerate at
# `typical` only -- one point of a band whose median span is 1.8x the typical price.
# That is not a detail. Measured on the shipped mandate:
#
#     min prices      476 of 595 authorised
#     typical         116 of 595          <- the number this panel used to show
#     max              16 of 595
#
# All 56 official purchase lines sit inside their band, and their median price is
# CHF 16.50 BELOW typical -- so `typical` is not even the middle of what really
# happens, and the panel was understating the delegation by a factor of four in the
# one direction that costs the customer something.
#
# The price is the SELLER's to choose. So the honest size of what was handed over is
# the union across the band, which for an amount ceiling is exactly the count at the
# cheapest prices (a basket affordable at `max` is affordable at `min`; the reverse
# is false). `_ordering_holds` checks that containment rather than assuming it.
PRICE_POINTS = ("min", "typical", "max")
_PRICE_COLUMN = {"min": "unit_price_min_chf",
                 "typical": "unit_price_typical_chf",
                 "max": "unit_price_max_chf"}

# The card the counted world belongs to. The official demo card, so the familiarity
# rule carves a real piece out of the universe rather than nothing.
COUNTED_CARD = "CA0001"


@lru_cache(maxsize=1)
def familiar_merchants(card_id: str = COUNTED_CARD) -> frozenset[str]:
    """Which shops this card has actually paid before, from the SAME history file the
    engine reads.

    This was a hard-coded `frozenset({"ME0001", ..., "ME0004"})`. It happened to be
    exactly right, which is the worst state for a fact to be in: correct today,
    unmoored from its source, and silently wrong the moment the data changes. A
    policy-bearing set asserted in one place and derived in another is the shape
    every defect in `docs/ABSENCE.md` has -- here it would not have been an absence
    but a drift, and the panel would have gone on reporting a confident number about
    a world that no longer existed.
    """
    history = HistoryIndex.from_csv(history_csv_path())
    return frozenset(
        merchant for merchant in load_merchants()
        if history.is_familiar(card_id, merchant) is True)


# Kept as a module attribute because `disagreement.py` and the research modules read
# it; it is now DERIVED rather than declared.
FAMILIAR = familiar_merchants()


@lru_cache(maxsize=8)
def _world(category: str, price_point: str = "typical"
           ) -> tuple[tuple[str, tuple[tuple[str, str, Decimal], ...]], ...]:
    """Every basket this world can produce: one shop, up to MAX_LINES lines.

    One shop per basket because the goods physically live somewhere -- the same
    constraint a real proposal is under."""
    items = [r for r in load_items().values() if r["item_category"] == category]
    shops = [m for m, r in load_merchants().items() if r["merchant_category"] == category]
    lines = tuple(sorted(
        (r["item_id"], r["item_name"], Decimal(r[_PRICE_COLUMN[price_point]])) for r in items))
    out: list[tuple[str, tuple]] = []
    for merchant in sorted(shops):
        for size in range(1, min(MAX_LINES, len(lines)) + 1):
            for combo in combinations(lines, size):
                out.append((merchant, combo))
    return tuple(out)


def _categories(rules: list[HardRule]) -> str:
    for rule in rules:
        if rule.field == "item.category" and rule.operator == "in":
            values = rule.value if isinstance(rule.value, list) else [rule.value]
            if values:
                return str(values[0])
    return "groceries"


def _count(mandate: MandateSnapshot, category: str,
           price_point: str = "typical") -> dict[str, Any]:
    counts = {"allow": 0, "review": 0, "block": 0}
    totals: list[Decimal] = []
    for index, (merchant, combo) in enumerate(_world(category, price_point)):
        verdict = judge_event(mandate, index, merchant, category, combo, familiar=FAMILIAR)
        counts[verdict] += 1
        if verdict == "allow":
            totals.append(sum((price for _id, _name, price in combo), Decimal("0")))
    totals.sort()
    counts["cheapest_chf"] = float(totals[0]) if totals else None
    # Every authorised basket's price, cheapest first, so "how many times" can be
    # counted rather than divided. See `_repetition`.
    counts["authorised_totals"] = totals
    return counts


def _repetition(rules: list[HardRule], cheapest: float | None,
                totals: list[Decimal] | None = None) -> dict[str, Any]:
    """HOW MANY TIMES, which is the half of "how much rope" that a count of purchases
    does not answer.

    A number of authorised purchases reads as a quantity of rope. It is not: without
    a rolling rule the agent may make every one of them, and then make them all again
    tomorrow. The panel that shows 116 and stops there creates exactly the false
    belief this project spends its time removing -- a correct figure that a person
    will attach to the wrong question.

    With a rolling cap the bound is real and computable: the sum over any window must
    stay under the cap, so at most `cap / cheapest authorised basket` purchases fit
    in one. Reported as the ceiling it is, not as a forecast.

    TWO THINGS THIS GOT WRONG, BOTH FOUND BY ATTACKING IT RATHER THAN TESTING IT.

    1. `cheapest` was the cheapest basket AT TYPICAL PRICES, so the ceiling on how
       many times understated itself exactly as `authorised` did -- the seller picks
       the price, and the cheapest basket the catalogue admits is cheaper than the
       cheapest typical one. The caller now passes the band's floor.

    2. THE PERIOD WAS INVISIBLE IN THE NUMBER. `cap / cheapest` does not mention
       `period_days`, so "CHF 300 per 7 days" and "CHF 300 per 30 days" both reported
       "at most 10 purchases" -- a customer who tightened the window by a factor of
       four saw the headline figure not move. The rate does move, and is reported
       beside it, because a ceiling without a period is not a pace."""
    totals = totals or []
    window = next((r for r in rules
                   if r.field == "authorization.billing_amount_chf"
                   and r.scope == "period" and r.period_days), None)
    if window is None:
        return {"bounded": False, "cap_chf": None, "period_days": None,
                "most_purchases_per_period": None, "cheapest_chf": cheapest,
                "note": ("Nothing here limits how many times. The agent may make "
                         "every one of these purchases, and then make them again. "
                         "A rolling limit paces that; only revoking stops it.")}
    try:
        cap = Decimal(str(window.value))
    except (ArithmeticError, TypeError, ValueError):
        # A period rule whose value is not a number is UNKNOWN to the engine, so it
        # bounds nothing. Saying otherwise here would be the panel inventing a limit.
        return {"bounded": False, "cap_chf": None, "period_days": window.period_days,
                "most_purchases_per_period": None, "cheapest_chf": cheapest,
                "note": "This mandate's rolling limit is not a number the engine can apply."}
    # HOW MANY DISTINCT BASKETS FIT, not `cap / cheapest`.
    #
    # Dividing assumes the agent can buy the cheapest basket over and over. It
    # cannot: repeating one is what the duplicate check is for, so a patient agent
    # works down the list of DIFFERENT authorised baskets, and the second-cheapest
    # costs more than the first. Measured against the exhaustive adversary on the
    # shipped mandate, the division predicted 25 where the best any ordering achieved
    # was 20 -- a ceiling loose enough to tell the customer nothing.
    #
    # Counting the cheapest distinct baskets until the cap is exhausted is still an
    # upper bound (it ignores the duplicate check, which can only reduce it further)
    # and it is tight enough to mean something.
    if totals:
        most, running = 0, Decimal("0")
        for price in totals:
            if running + price > cap:
                break
            running += price
            most += 1
        most = most or None
    else:
        most = None
    from .money import annual_exposure

    days = window.period_days or 0
    # THE SAME FIGURE THE COMPILER AND THE AUDIT USE. A per-day rate was a second
    # unit for a fact this product already states in years; two renderings of one
    # fact is how they drift apart.
    rate = annual_exposure(cap, days)[1] if days else None
    pace = (f" The window re-opens, so at this rate the delegation is worth about "
            f"CHF {rate:,.0f} a year -- the format has no way to set a total."
            if rate is not None else "")
    return {"bounded": True, "cap_chf": float(cap), "period_days": window.period_days,
            "most_purchases_per_period": most, "cheapest_chf": cheapest,
            # The PACE, so that shortening the window changes a number and not only a
            # word. Two mandates with the same ceiling over different periods are not
            # the same delegation, and the panel has to be able to say so.
            "chf_per_year": rate,
            "note": (f"At most CHF {float(cap):g} in any {days} days "
                     f"\u2014 {most} of these purchases at the cheapest, fewer at any "
                     f"other price.{pace}" if most else
                     f"At most CHF {float(cap):g} in any {days} days.{pace}")}


def authorised_baskets(instruction: str, price_point: str = "typical",
                       uncertainty: UncertaintyPolicy | None = None) -> frozenset:
    """WHICH baskets are authorised at this price point, not merely how many.

    Exists so the containment the panel relies on can be CHECKED rather than argued:
    a basket affordable at `max` is affordable at `min`, and no rule other than the
    amount ceiling reads the price, so

        A(max)  subset-of  A(typical)  subset-of  A(min)

    must hold. If it ever does not, "the union across the band is the count at the
    cheapest prices" stops being true and `authorised_upper` stops meaning anything.
    """
    compiled = compile_instruction(instruction)
    rules = list(compiled.hard_rules)
    category = _categories(rules)
    mandate = snapshot(rules, uncertainty or compiled.uncertainty_policy,
                       list(compiled.unsupported_restrictions))
    return frozenset(
        (merchant, tuple(item_id for item_id, _name, _price in combo))
        for index, (merchant, combo) in enumerate(_world(category, price_point))
        if judge_event(mandate, index, merchant, category, combo,
                       familiar=FAMILIAR) == "allow")


def uncertainty_tradeoff(instruction: str) -> dict[str, Any]:
    """WHAT THE UNCERTAINTY DIAL COSTS, counted in purchases.

    `uncertainty_policy` is the most consequential setting in a mandate and the least
    legible: "what should I do when I cannot tell?" is asked once, in the abstract,
    about facts the customer has not met yet. Three words, and nothing shows what any
    of them does.

    Measured, it is not abstract at all. On "groceries under CHF 120 from a shop I
    have used before, only if returnable within 14 days" -- a return window being a
    fact no independent source can confirm:

        decline    0 approved,   0 asked,  595 refused
        ask        0 approved, 116 asked,  479 refused
        approve  116 approved,   0 asked,  479 refused

    WHY THIS IS THE PAIR OF NUMBERS THAT MATTERS. `research/erasure.py` measures,
    over 8,124 erasures of the official events, that `decline` is the ONLY setting in
    which saying less never buys the proposer more -- a seller who publishes nothing
    beats one who publishes bad terms under `ask` and `approve`, and under `decline`
    beats nobody. That is the security half. This is the price: on this mandate,
    `decline` is 116 purchases the customer cannot make without being asked again.

    A dial with a security property on one side and a cost on the other is a choice.
    Shown as one number it is a guess.

    Returns identical counts for all three where the mandate has no unknowable fact,
    which is correct and worth seeing: the dial only spends what uncertainty exists.
    """
    out = {}
    for policy in (UncertaintyPolicy.DECLINE, UncertaintyPolicy.ASK,
                   UncertaintyPolicy.APPROVE):
        sized = delegation_size(instruction, policy)
        out[policy.value] = {"approved": sized["authorised"],
                             "asked": sized["asks_you"],
                             "refused": sized["refused"]}
    spread = {v["approved"] for v in out.values()}
    out["dial_changes_anything"] = len(spread) > 1 or len({v["asked"] for v in out.values()}) > 1
    return out


def outcome_sets(instruction: str, price_point: str = "typical",
                 uncertainty: UncertaintyPolicy | None = None) -> tuple[frozenset, frozenset]:
    """(approved, put-to-you) -- because what the wallet will ASK about is part of
    what was delegated, not a leftover.

    `authorised_baskets` counts approvals alone, which makes the strictest edit a
    customer can make invisible: changing `ask` to `decline` moves purchases from
    review to block and leaves the approved set untouched. It also makes every
    variant of a mandate whose purchases all end in review look identical, since the
    approved set is empty under all of them.
    """
    compiled = compile_instruction(instruction)
    rules = list(compiled.hard_rules)
    category = _categories(rules)
    mandate = snapshot(rules, uncertainty or compiled.uncertainty_policy,
                       list(compiled.unsupported_restrictions))
    approved, asked = set(), set()
    for index, (merchant, combo) in enumerate(_world(category, price_point)):
        verdict = judge_event(mandate, index, merchant, category, combo, familiar=FAMILIAR)
        key = (merchant, tuple(item_id for item_id, _n, _p in combo))
        if verdict == "allow":
            approved.add(key)
        elif verdict == "review":
            asked.add(key)
    return frozenset(approved), frozenset(asked)


def delegation_size(instruction: str,
                    uncertainty: UncertaintyPolicy | None = None) -> dict[str, Any]:
    """How many purchases this sentence authorises, right now, out of how many exist."""
    compiled = compile_instruction(instruction)
    rules = list(compiled.hard_rules)
    category = _categories(rules)
    mandate = snapshot(rules, uncertainty or compiled.uncertainty_policy,
                       list(compiled.unsupported_restrictions))
    counts = _count(mandate, category)
    universe = counts["allow"] + counts["review"] + counts["block"]
    # TWO PASSES, NOT THREE. The headline needs the band's floor and the context
    # line needs `typical`; `max` is the least informative of the three -- it is the
    # count nobody is delegating -- and it cost a third of the panel's latency. It
    # stays reachable through `_count(..., "max")` for the research sweeps that
    # actually compare the whole band.
    at_floor = _count(mandate, category, "min")
    band = {"min": at_floor["allow"], "typical": counts["allow"]}
    return {
        # THE SIZE OF THE DELEGATION, over the prices the catalogue itself says these
        # goods can have. `authorised` stays the count at typical prices so the
        # shrink table keeps comparing like with like; `authorised_upper` is what was
        # actually handed over, because the seller picks the price.
        "price_band": band,
        "authorised_upper": band["min"],
        # NOT computed here. `uncertainty_tradeoff` runs this whole enumeration three
        # more times, which tripled the latency of a panel that updates as the
        # customer types. It has its own endpoint, asked for when the customer looks
        # at the dial rather than on every keystroke.
        # The band's FLOOR, not the typical point: "how many times" is a ceiling, and
        # a ceiling computed from the dearer of two possible prices is not one.
        "how_many_times": _repetition(rules,
                                      at_floor["cheapest_chf"] or counts["cheapest_chf"],
                                      at_floor["authorised_totals"]),
        "instruction": instruction,
        "universe": universe,
        "authorised": counts["allow"],
        "asks_you": counts["review"],
        "refused": counts["block"],
        "category": category,
        "max_lines": MAX_LINES,
        # What the figure is OF, in the payload rather than only in a docstring: a
        # count whose scope is not stated beside it is a number a reader will attach
        # to whatever they are looking at.
        "counted_over": {
            "shops": sorted({m for m, _ in _world(category)}),
            "card": COUNTED_CARD,
            "basis": (f"every basket of up to {MAX_LINES} lines that any one shop in "
                      f"the official {category} catalogue could supply"),
        },
        "share": (counts["allow"] / universe) if universe else 0.0,
    }
