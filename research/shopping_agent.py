"""An autonomous shopping agent that proposes, is refused, and adapts.

RESEARCH APPARATUS, never imported by `src/wallet_control/` -- the wallet must run
identically with this file deleted, which `tests/test_runtime_boundary.py` enforces.
The agent is a CLIENT of the wallet, and putting it anywhere else would blur the one
boundary this whole project exists to draw.

WHY IT IS DETERMINISTIC AND NOT A MODEL
---------------------------------------
`technical_details.md` requires a solution that "must still give a predictable
response when the model or another external service is unavailable". An LLM here
would make the demo unreproducible and the wallet's guarantees conditional on a
third party. The planning is a few lines of arithmetic; the interesting part was
never the planner, it is what the agent is allowed to LEARN.

WHAT THE AGENT MAY SEE
----------------------
Only `decision_engine.agent_view(...)`: the decision, the CLASS of constraint that
failed, and whether a human is being asked. No rule values, no remaining budget, no
evidence strings.

That restriction is the mechanism, not a courtesy. The wallet is an oracle -- every
decision system is -- and an agent seeing only ALLOW/BLOCK recovers a secret CHF 137
ceiling to within CHF 0.24 in twelve probes, spending CHF 531 of the customer's money
to do it. The customer's own payload carries the rule's `value` and "projected 7-day
spend=287.50 CHF", which would collapse that to zero probes. So the agent adapts
without ever being told the limit: it learns "propose less", never "propose 119.99".

The loop cannot manufacture authority. A revised basket is approved only if it
independently satisfies the same confirmed mandate; the wallet re-decides it from
scratch. Adaptation consumes the delegation, it never widens it.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from itertools import combinations
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

_ITEMS = Path(__file__).resolve().parents[1] / "data" / "official" / "items.csv"
_MERCHANTS = Path(__file__).resolve().parents[1] / "data" / "official" / "merchants.csv"

# How many revisions before the agent gives up and asks the customer. Bounded because
# an unbounded loop is exactly the cheap-probing case the oracle analysis warns about,
# and because every attempt is a recorded decision an auditor can count.
MAX_REVISIONS = 4


@dataclass(frozen=True)
class Line:
    item_id: str
    name: str
    category: str
    unit_price: Decimal
    quantity: int = 1
    # Which shop this line was taken from. The search ranks (basket, MERCHANT)
    # pairs and used to return only the basket; `shop()` then recovered a merchant
    # by asking the tool which shop could supply it. That works only while each
    # item is sold in exactly one place. Give two shops the same goods at the same
    # prices -- which is precisely the world needed to ask whether an agent prefers
    # a seller who publishes less -- and the loop silently bought from whichever
    # shop sorted first, discarding the answer the search had just computed.
    #
    # The basket now names its shop and the tool VERIFIES it (see `merchant_for`),
    # rather than either trusting the planner or ignoring it.
    merchant: str | None = None

    @property
    def total(self) -> Decimal:
        return self.unit_price * self.quantity


@dataclass
class Attempt:
    revision: int
    lines: tuple[Line, ...]
    amount_chf: Decimal
    agent_view: dict[str, Any]
    rationale: str


@dataclass
class Episode:
    """The whole plan→propose→observe→revise trace, for the audit trail and the demo."""

    mission: str
    attempts: list[Attempt] = field(default_factory=list)
    outcome: str = "unresolved"
    # Why the agent handed back to the customer, when it did. Distinct from an empty
    # basket: "I cannot fix this by shopping" is a RESULT, not a failure.
    handoff_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "mission": self.mission,
            "outcome": self.outcome,
            "handoff_reason": self.handoff_reason,
            "attempts": [
                {
                    "revision": a.revision,
                    "amount_chf": float(a.amount_chf),
                    "lines": [{"name": l.name, "category": l.category,
                               "unit_price": float(l.unit_price), "quantity": l.quantity}
                              for l in a.lines],
                    "wallet": a.agent_view,
                    "rationale": a.rationale,
                }
                for a in self.attempts
            ],
        }


# Which refusals the agent may answer by shopping differently, and which it must not.
#
# The line is not "can I think of a move" -- it is WHAT THE WALLET OBJECTED TO. A
# constraint on the PURCHASE (too dear, wrong shop, goods that cannot be sent back)
# is answered by choosing different goods: that is shopping. A constraint on the
# AGENT'S OWN BEHAVIOUR (this looks like a duplicate, this session looks wrong) is
# not, and answering it with a different basket is precisely the probing we refuse
# to do -- it would be an agent that responds to "you look like a runaway" by
# rephrasing itself until the wallet stops noticing. Those go to the human, always,
# even when a perfectly good alternative basket is sitting right there.
_SHOPPABLE = {"amount", "budget_window", "item", "basket", "merchant", "order_terms"}
_STOP = {"session", "duplicate", "other"}


@dataclass(frozen=True)
class Mission:
    """What the customer actually wants, separate from any one basket.

    The agent plans against THIS, not against the last thing it happened to propose.
    `target_lines` is how much of the errand counts as done, and it is the first term
    of the objective function -- so the goal is what the search maximises, not a
    label on a loop.
    """

    description: str
    category: str
    target_lines: int = 5
    unavailable: frozenset[str] = frozenset()   # item_ids the shop cannot supply
    merchants: tuple[str, ...] = ("ME0001",)


class Offer:
    """One thing that can actually be bought, at one shop, right now.

    Distinct from `Line` (what the agent has decided to put in a basket) because the
    old design conflated them and thereby assumed the shop never changes. An offer
    carries the seller's OWN stated return window -- public product data, not policy.
    """

    __slots__ = ("item_id", "name", "category", "unit_price", "merchant", "stated_return_days")

    def __init__(self, item_id, name, category, unit_price, merchant, stated_return_days=None):
        self.item_id, self.name, self.category = item_id, name, category
        self.unit_price, self.merchant = unit_price, merchant
        self.stated_return_days = stated_return_days

    def line(self, quantity: int = 1) -> "Line":
        return Line(self.item_id, self.name, self.category, self.unit_price, quantity,
                    self.merchant)


class Shop:
    """The agent's TOOL, and the only way it learns what exists.

    The previous version read a module-level CSV inside `plan`, so it could not be
    pointed at a different shop and, worse, could not notice that the shop had
    changed: availability was frozen before the first proposal, and in benchmark
    episode G the agent re-proposed an item that had sold out two attempts earlier.
    A tool called on every replanning step fixes that by construction.
    """

    def search(self, category: str | None = None) -> list[Offer]:
        raise NotImplementedError

    def available(self, item_id: str) -> bool:
        return any(o.item_id == item_id for o in self.search())

    def merchant_for(self, lines: list["Line"]) -> str | None:
        """Which shop can supply this whole basket. None if no single shop can.

        The agent asks rather than assumes, so that a basket produced by ANY planner
        -- including a hostile one -- is still sent to a shop that actually stocks
        it. The old loop took the merchant from the mission and the items from the
        catalogue independently, and they were never checked against each other.

        A basket that NAMES its shop is honoured only if that shop really stocks
        every line. So a planner's own choice survives -- which it did not before,
        when two shops carrying the same goods collapsed to whichever sorted first
        -- and a hostile planner still cannot send a basket somewhere it is not
        sold, because the claim is checked against `search()` and not believed."""
        wanted = {l.item_id for l in lines}
        if not wanted:
            return None
        stock: dict[str, set[str]] = {}
        for o in self.search():
            stock.setdefault(o.merchant, set()).add(o.item_id)
        named = {l.merchant for l in lines}
        if len(named) == 1:
            claimed = named.pop()
            if claimed is not None and wanted <= stock.get(claimed, set()):
                return claimed
        for merchant in sorted(stock):
            if wanted <= stock[merchant]:
                return merchant
        return None


class CatalogueShop(Shop):
    """The official item and merchant lists, read fresh on every call."""

    def __init__(self, unavailable: frozenset[str] = frozenset(),
                 return_days: dict[str, int] | None = None) -> None:
        self._unavailable = unavailable
        self._return_days = return_days or {}

    def search(self, category: str | None = None) -> list[Offer]:
        with _ITEMS.open(newline="", encoding="utf-8") as f:
            items = [r for r in csv.DictReader(f)]
        with _MERCHANTS.open(newline="", encoding="utf-8") as f:
            shops = [r for r in csv.DictReader(f)]
        out: list[Offer] = []
        for r in items:
            if r["item_id"] in self._unavailable:
                continue
            if category and r["item_category"] != category:
                continue
            for s in shops:
                if s["merchant_category"] != r["item_category"]:
                    continue
                out.append(Offer(r["item_id"], r["item_name"], r["item_category"],
                                 Decimal(r["unit_price_typical_chf"]), s["merchant_id"],
                                 self._return_days.get(r["item_id"])))
        return out


def catalogue(category: str | None = None) -> list[Line]:
    """Kept because the browser demo and the older tests speak in `Line`s."""
    seen: dict[str, Line] = {}
    for o in CatalogueShop().search(category):
        seen.setdefault(o.item_id, o.line())
    return list(seen.values())


@dataclass
class Beliefs:
    """Everything the agent has worked out from being refused.

    This is the whole learning mechanism, and it is deliberately tiny, because every
    fact in here was paid for with one of the customer's refused purchases.

    Note what is NOT here: any number the wallet holds. `ceiling` is not the
    customer's limit -- it is "strictly less than a total I already tried", which is
    all a refusal can honestly tell you. The agent converges toward the real limit
    from above and never learns it, which is exactly the property
    `test_NO_POLICY_EXTRACTION` pins down.
    """

    ruled_out_merchants: set[str] = field(default_factory=set)
    ceiling: Decimal | None = None          # strictly below this total
    returns_matter: bool = False            # a refusal mentioned the order's terms
    tried: set[frozenset[str]] = field(default_factory=set)
    # Whether the last refusal was about the ROLLING ALLOWANCE rather than this one
    # order. The two need different moves and used to be indistinguishable: "this
    # order is too large" is fixed by a cheaper basket of any size, while "the
    # allowance is used up" is fixed only by fitting the remainder -- and once the
    # remainder is smaller than anything on sale, not by shopping at all.
    #
    # The agent still learns no number. It learns that the ceiling it is converging
    # on is a shared, shrinking one rather than a per-order one, which is exactly
    # the difference between "buy something cheaper" and "buy less".
    budget_window_hit: bool = False

    def learn(self, basket: list[Line], merchant: str, blocked_by: list[str]) -> bool:
        """Fold one refusal into what the agent believes. True if anything is new."""
        before = (len(self.ruled_out_merchants), self.ceiling, self.returns_matter,
                  len(self.tried), self.budget_window_hit)
        self.tried.add(frozenset(l.item_id for l in basket))
        total = sum((l.total for l in basket), Decimal("0"))
        if "budget_window" in blocked_by:
            self.budget_window_hit = True
        if ({"amount", "budget_window"} & set(blocked_by)
                and (self.ceiling is None or total < self.ceiling)):
            self.ceiling = total
        if "merchant" in blocked_by:
            self.ruled_out_merchants.add(merchant)
        if "order_terms" in blocked_by:
            self.returns_matter = True
        after = (len(self.ruled_out_merchants), self.ceiling, self.returns_matter,
                 len(self.tried), self.budget_window_hit)
        return before != after


# How wide the search may go. Bounded because an agent that enumerates without limit
# is a denial-of-service against the customer's own wallet, and because every basket
# it eventually proposes costs a real decision.
MAX_BASKET = 5
MAX_OFFERS_PER_MERCHANT = 12
# ...and how many shops. The search is linear in merchants, and a shop that lists
# enough of them is a denial-of-service against the agent: 1,000 merchants x 50 items
# took 1.6s to enumerate, against a wallet deadline of 8s. The cap is on the AGENT's
# own work, chosen by cheapest entry price so the choice is deterministic and not a
# function of the order a hostile catalogue happens to return.
MAX_MERCHANTS = 50


def score(basket: list[Offer], mission: "Mission", beliefs: Beliefs) -> tuple:
    """THE OBJECTIVE FUNCTION. Stated once, here, in the order the customer would.

        1. do more of the errand          (coverage, up to what was asked for)
        2. prefer goods that can be sent back, once a refusal showed that matters
        3. spend less of the customer's money

    Price is LAST, not first. That inversion is the entire fix for benchmark episode
    K, where three baskets looked buyable, exactly one was allowed, and the old agent
    deleted that one first precisely because it was the dearest. Ranking by price is
    not ranking by what the customer asked for.

    Every term is computed from things the agent can legitimately see: its own
    mission, the seller's published terms, and the CLASS of constraint that refused
    it. No term reads a rule value, because it has never been told one.
    """
    coverage = min(len(basket), mission.target_lines)
    worst_window = min((o.stated_return_days if o.stated_return_days is not None else -1)
                       for o in basket) if beliefs.returns_matter else 0
    # NOT re-ordered when the rolling allowance is binding, though an earlier draft
    # of this phase did exactly that -- "spend least first" -- and made the agent buy
    # ONE line for CHF 30 where two lines for CHF 62 also fit. The candidate search
    # already filters to baskets under what the agent believes it may spend, so every
    # option here fits; among options that fit, doing more of the errand is still the
    # point. What `budget_window` changes is where the agent looks and when it stops,
    # not what it wants.
    return (coverage, worst_window, -sum((o.unit_price for o in basket), Decimal("0")))


def _plausible(offer: Offer, mission: Mission) -> bool:
    """Whether an offer is worth considering at all.

    The tool is the agent's only contact with a world it does not control, so what
    comes back through it is untrusted input and is checked like any other. A shop
    quoting a price of CHF -1000 was enough to make the search propose it, because
    the objective prefers spending less and nothing spends less than a refund. The
    wallet blocked it -- it refuses any non-positive amount -- so no money moved, but
    the agent had spent one of the customer's four attempts on nonsense, and a
    catalogue full of such offers would spend all of them.

    This is not the wallet's rule restated on the agent's side. The agent is checking
    that its TOOL is behaving, which is its own business and nobody else's.
    """
    return (isinstance(offer.item_id, str) and offer.item_id.strip() != ""
            and offer.unit_price > 0
            and offer.category == mission.category)


def _candidates(shop: Shop, mission: Mission, beliefs: Beliefs):
    """Yield every basket worth considering: subsets of ONE merchant's offers.

    One merchant per basket because the goods physically live at a shop. The old
    agent chose items and a merchant independently, which is why its "try another
    merchant" rung could never actually help -- it moved the basket to a shop that
    did not stock it, and, re-measured honestly, reported four successes while
    holding goods from a shop the customer had excluded.

    A generator rather than a list so that a catalogue large enough to exhaust
    memory cannot, and so the bounds below are the only thing that grows.
    """
    by_merchant: dict[str, list[Offer]] = {}
    for o in shop.search(mission.category):
        if not _plausible(o, mission) or o.merchant in beliefs.ruled_out_merchants:
            continue
        by_merchant.setdefault(o.merchant, []).append(o)

    ranked = sorted(by_merchant.items(),
                    key=lambda kv: (min(o.unit_price for o in kv[1]), kv[0]))[:MAX_MERCHANTS]
    for merchant, offers in ranked:
        offers = sorted(offers, key=lambda o: (o.unit_price, o.item_id))[:MAX_OFFERS_PER_MERCHANT]
        for size in range(1, min(MAX_BASKET, mission.target_lines, len(offers)) + 1):
            for combo in combinations(offers, size):
                ids = frozenset(o.item_id for o in combo)
                if ids in beliefs.tried:
                    continue
                total = sum((o.unit_price for o in combo), Decimal("0"))
                if beliefs.ceiling is not None and total >= beliefs.ceiling:
                    continue
                yield list(combo), merchant


def best_basket(shop: Shop, mission: Mission, beliefs: Beliefs,
                objective: Callable[[list[Offer], "Mission", Beliefs], tuple] = None
                ) -> tuple[list[Offer], str] | None:
    """Search, rather than repair. Returns the highest-scoring untried basket.

    `objective` defaults to `score` and exists so that "two agents differing in
    exactly one term of the objective function" is a fact about the code rather
    than a claim in a docstring. `research/silence_channel.py` uses it to run an
    adversary that is identical to the shipped planner except in what it believes
    an UNSTATED return window is worth.

    Ties break on the basket's item ids, so the same shop and the same beliefs give
    the same basket on every run and on every machine. A search whose answer depends
    on dictionary order is not reproducible, and reproducibility is the property this
    whole system is built to keep.
    """
    objective = objective or score
    best, best_key = None, None
    for combo, merchant in _candidates(shop, mission, beliefs):
        key = (objective(combo, mission, beliefs), tuple(sorted(o.item_id for o in combo)))
        if best_key is None or key > best_key:
            best, best_key = (combo, merchant), key
    return best


def plan(mission: Mission, shop: Shop | None = None, beliefs: Beliefs | None = None,
         objective=None) -> list[Line]:
    """Opening basket: the best-scoring one the shop can supply."""
    found = best_basket(shop or CatalogueShop(mission.unavailable), mission,
                        beliefs or Beliefs(), objective)
    return [o.line() for o in found[0]] if found else []


def replan(lines: list[Line], blocked_by: list[str], mission: Mission,
           merchant_index: int, shop: Shop | None = None,
           beliefs: Beliefs | None = None, merchant: str | None = None,
           objective=None):
    """One replanning step: learn from the refusal, look at the shop AGAIN, re-search.

    Returns a new (basket, rationale, merchant_index), or a STRING naming why the
    agent is handing back. There is no ladder of repairs any more. A ladder can only
    subtract, so every constraint it had no rung for -- a shop the customer excluded,
    goods that cannot be returned -- became a human handoff while a perfectly good
    alternative sat unexamined in the same catalogue. Six of eleven benchmark
    episodes failed that way.
    """
    if not blocked_by:
        return "the wallet gave no reason the agent can act on"

    halt = sorted(c for c in blocked_by if c not in _SHOPPABLE)
    if halt:
        return (f"the wallet raised something about this session rather than about the "
                f"goods ({', '.join(halt)}); only the customer can resolve that")

    shop = shop or CatalogueShop(mission.unavailable)
    beliefs = beliefs if beliefs is not None else Beliefs()
    current = merchant or (mission.merchants[merchant_index] if mission.merchants else "")

    if not beliefs.learn(lines, current, blocked_by):
        return "nothing was learned from that refusal, so trying again would only repeat it"

    found = best_basket(shop, mission, beliefs, objective)
    if found is None:
        if beliefs.budget_window_hit:
            # A shared allowance is not a property of the shop, so "no basket this
            # shop can supply" would be both wrong and the kind of wrong that sends a
            # customer looking for a better shop. The agent knows the KIND of limit
            # it hit; it still does not know the number, and says neither.
            return ("what is left of the spending allowance for this period is less "
                    "than anything worth buying; the errand can continue once the "
                    "window moves on")
        return "no basket this shop can supply would satisfy what the customer asked for"

    offers, new_merchant = found
    index = merchant_index
    if new_merchant != current and new_merchant in mission.merchants:
        index = mission.merchants.index(new_merchant)
    return [o.line() for o in offers], _why(lines, offers, current, new_merchant, blocked_by), index


def _why(old: list[Line], new: list[Offer], old_merchant: str, new_merchant: str,
         blocked_by: list[str]) -> str:
    """Plain language for the audit trail. Says what CHANGED and what prompted it,
    never a threshold, because the agent does not have one to leak."""
    was, now = {l.item_id for l in old}, {o.item_id for o in new}
    bits = []
    if new_merchant != old_merchant:
        bits.append(f"moved to {new_merchant}")
    added = [o.name for o in new if o.item_id not in was]
    dropped = [l.name for l in old if l.item_id not in now]
    if dropped:
        bits.append("dropped " + ", ".join(dropped))
    if added:
        bits.append("took " + ", ".join(added))
    because = {"amount": "the total was refused",
               "budget_window": "the rolling allowance is used up",
               "merchant": "that shop was refused",
               "order_terms": "the return terms were refused", "item": "an item was refused",
               "basket": "the basket was refused"}
    reasons = [because[c] for c in blocked_by if c in because]
    return (", ".join(bits) or "kept the basket") + (f" -- {reasons[0]}" if reasons else "")


@dataclass(frozen=True)
class Planner:
    """The replaceable half of the agent.

    `plan` and `replan` are the only reasoning in this system, and they are injectable
    precisely so that the architectural claim can be TESTED rather than asserted: a
    model-based planner would slot in here, outside the authority boundary, and the
    wallet's decisions must be identical whether the planner is the deterministic one,
    a language model, a hallucinating stub, or an adversary.

    We ship the deterministic planner. A model is deliberately NOT in the judged path:
    `technical_details.md` requires a predictable response when the model is
    unavailable, and a network call would make the demo irreproducible -- which is a
    jury criterion we would rather win outright. What we do instead is prove the seam
    holds against planners far worse than any real model
    (`tests/test_agent_planner_boundary.py`).
    """

    plan: Callable[[Mission], list[Line]] = None          # type: ignore[assignment]
    replan: Callable[..., Any] = None                      # type: ignore[assignment]

    def opening(self, mission, shop=None, beliefs=None) -> list[Line]:
        if self.plan is not None:
            return self.plan(mission)
        return plan(mission, shop, beliefs)

    def next_step(self, lines, blocked_by, mission, merchant_index, shop=None,
                  beliefs=None, merchant=None):
        if self.replan is not None:
            return self.replan(lines, blocked_by, mission, merchant_index)
        return replan(lines, blocked_by, mission, merchant_index, shop, beliefs, merchant)


DETERMINISTIC = Planner()


def shop(
    mission: Mission,
    propose: Callable[[list[Line], int, str], dict[str, Any]],
    max_revisions: int = MAX_REVISIONS,
    planner: Planner = DETERMINISTIC,
    shop_tool: Shop | None = None,
) -> Episode:
    """Plan, propose, observe, replan -- stopping on success, on a human, or when the
    agent judges that no further basket change would help.

    `propose` submits a basket to the wallet and returns an `agent_view`. That is the
    ONLY channel through which the agent learns anything about the policy.
    """
    episode = Episode(mission=mission.description)
    tool = shop_tool or CatalogueShop(mission.unavailable)
    beliefs = Beliefs()
    # A planner that raises, returns nothing, or returns nonsense must not take the
    # wallet down with it: the agent degrades to asking the customer.
    try:
        lines = planner.opening(mission, tool, beliefs)
    except Exception as exc:                                   # noqa: BLE001 -- any planner failure
        episode.outcome = "asked_customer"
        episode.handoff_reason = f"the planner failed to produce a basket ({type(exc).__name__})"
        return episode
    if not lines:
        episode.outcome = "asked_customer"
        episode.handoff_reason = "the planner produced no basket"
        return episode
    merchant_index = 0
    current = tool.merchant_for(lines) or (mission.merchants[0] if mission.merchants else "")
    rationale = f"opening basket: {len(lines)} {mission.category} line(s), the best the shop offers"

    for revision in range(max_revisions + 1):
        amount = sum((l.total for l in lines), Decimal("0"))
        view = propose(lines, revision, current)
        episode.attempts.append(Attempt(revision, tuple(lines), amount, view, rationale))

        if view["decision"] == "allow":
            episode.outcome = "approved"
            return episode
        if view.get("awaiting_customer"):
            episode.outcome = "awaiting_customer"
            return episode

        try:
            step = planner.next_step(lines, view.get("blocked_by", []), mission,
                                     merchant_index, tool, beliefs, current)
        except Exception as exc:                               # noqa: BLE001
            episode.outcome = "asked_customer"
            episode.handoff_reason = f"the planner failed while replanning ({type(exc).__name__})"
            return episode
        if not isinstance(step, tuple) or len(step) != 3 or not step[0]:
            episode.outcome = "asked_customer"
            episode.handoff_reason = step if isinstance(step, str) else "the planner returned an unusable step"
            return episode
        if isinstance(step, str):
            episode.outcome = "asked_customer"
            episode.handoff_reason = step
            return episode
        lines, rationale, merchant_index = step
        # Ask the tool again rather than assuming the new basket is still sold where
        # the last one was. This is the loop's only claim about the world, and it is
        # re-checked on every pass.
        current = tool.merchant_for(lines) or current

    episode.outcome = "gave_up"
    episode.handoff_reason = "ran out of revisions"
    return episode
