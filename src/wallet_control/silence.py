"""The cheapest way past a rule is to make sure it cannot be checked.

THE PROBLEM

A hard rule needs evidence. "Only buy what I can send back within 14 days" is
checked against a return window the SELLER states. A seller who states five days
fails the rule and the purchase is declined. A seller who states nothing produces
no fact at all, so the rule is UNKNOWN -- and an unknown is not a failure. It is
routed to `uncertainty_policy`, which the customer set once, for the whole
mandate, before any of this was in front of them.

    customer: "groceries I can send back within 14 days"   (+ ask me when unsure)

        seller states 30 days   ->  ALLOW    the rule was checked and passed
        seller states  5 days   ->  BLOCK    the rule was checked and failed
        seller states nothing   ->  REVIEW   the rule was never checked

The third row is the finding. Describing the SAME purchase with LESS information
made it more acceptable, and that is backwards: evidence of a bad term is punished
while the absence of any term is not.

WHY THIS IS AN ATTACK AND NOT A CURIOSITY

The party that picks the seller is the agent, and the agent is the party the rule
constrains. So compliance with the customer's requirement is optional for the
counterparty, and the counterparty is chosen by the adversary. Under `approve when
unsure` this turns a definite refusal into a definite approval. Under `ask` -- the
DEFAULT -- it turns a definite refusal into a question for the customer, which is
an attack on their attention rather than on the wallet: enough of them and the
answer becomes reflex.

The agent never lies. It never sees a policy value. It just shops where less is
said.

WHAT CANNOT BE CLAIMED

Only two rules in this engine are exposed this way, and they are named rather than
generalised: `order.return_window_days` and `item.size`. Both read a fact the
seller publishes, and the agent chooses the seller. `merchant.familiar` also has an
UNKNOWN branch and is NOT exposed, because it goes unknown only when the card's
authorization history is unavailable altogether -- a platform condition no choice
of shop can bring about. Period-spend UNKNOWN is likewise not seller-supplied.

WHAT THIS MODULE DOES

It finds the witness and shows it to the customer before they confirm, next to the
question they can actually answer: `ask`, `approve` or `decline` when unsure. Under
`decline` an unknown blocks, so silence buys nothing and this panel says nothing at
all -- which is the property that keeps it from becoming another warning people
learn to click through.

DECIDES NOTHING. Advisory, like the compiler's open questions.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any, Callable

from .mandate import HardRule, UncertaintyPolicy
from .policy_compiler import compile_instruction
from .witness import PERMISSIVENESS, Purchase, judge


@dataclass(frozen=True)
class SellerSays:
    """Three sellers offering the same goods at the same price, differing only in
    what they publish about the order."""

    field: str
    question: str
    # Each returns the `item_details` string a seller of that kind would publish.
    good: Callable[[HardRule], str]
    bad: Callable[[HardRule], str]
    silent: str = ""


def _window_good(rule: HardRule) -> str:
    return f"returns accepted within {int(rule.value) + 16} days"


def _window_bad(rule: HardRule) -> str:
    """A stated window the rule REFUSES. `>=` is what the compiler emits; the other
    operators are handled rather than assumed so a future rule shape cannot quietly
    fall through to a value that happens to pass."""
    value = int(rule.value)
    failing = {">=": value - 1, ">": value, "<=": value + 1, "<": value, "=": value + 1}
    return f"returns accepted within {max(failing.get(rule.operator, value - 1), 0)} days"


def _size_good(rule: HardRule) -> str:
    return f"size {rule.value}"


def _size_bad(rule: HardRule) -> str:
    stated = str(rule.value)
    try:
        return f"size {int(stated) + 1}"
    except ValueError:
        return "size XL" if stated.upper() != "XL" else "size S"


SELLERS: tuple[SellerSays, ...] = (
    SellerSays("order.return_window_days",
               "What should happen when a seller does not publish a return window?",
               _window_good, _window_bad),
    SellerSays("item.size",
               "What should happen when a seller does not state the size?",
               _size_good, _size_bad),
)


def _amount_that_passes(rules: list[HardRule]) -> float:
    """An amount no money rule objects to, so the witness isolates the ONE question
    it is asking. Half the smallest ceiling; a period cap is halved again because a
    single purchase should not approach a window that a sequence is meant to fill."""
    ceilings = [Decimal(str(r.value)) / (2 if r.scope == "period" else 1)
                for r in rules if r.field == "authorization.billing_amount_chf"]
    if not ceilings:
        return 40.0
    return float(round(min(ceilings) / 2, 2))


def _category(rules: list[HardRule]) -> str:
    for rule in rules:
        if rule.field == "item.category" and rule.operator == "in":
            values = rule.value if isinstance(rule.value, list) else [rule.value]
            if values:
                return str(values[0])
    return "groceries"


def _item_name(rules: list[HardRule]) -> str:
    """The witness must satisfy any `item.name_contains` rule, or it would be refused
    for the wrong reason and report a silence that is not there."""
    needles = [str(r.value) for r in rules if r.field == "item.name_contains"]
    return " ".join(needles) or "item"


def silence_witness(instruction: str, *, uncertainty: UncertaintyPolicy | None = None
                    ) -> list[dict[str, Any]]:
    """Every rule of this mandate whose requirement a seller can escape by publishing
    nothing, with the three verdicts that prove it.

    `uncertainty` overrides what the sentence compiled to, so the customer (and a
    jury) can move the one dial that changes the answer and watch the finding appear
    and disappear.
    """
    compiled = compile_instruction(instruction)
    rules = list(compiled.hard_rules)
    policy = uncertainty or compiled.uncertainty_policy
    unsupported = list(compiled.unsupported_restrictions)

    base = Purchase(amount=_amount_that_passes(rules), category=_category(rules),
                    item_name=_item_name(rules), returnable="true")

    found: list[dict[str, Any]] = []
    for seller in SELLERS:
        rule = next((r for r in rules if r.field == seller.field), None)
        if rule is None:
            continue

        # HOLD EVERY OTHER SELLER-TEXT FACT AT A SATISFYING VALUE.
        #
        # The witness varies ONE thing; anything else left unstated is a second
        # unknown, and a second unknown decides the purchase on its own. On the
        # official shoes mandate -- a return window AND a size -- the return-window
        # witness published nothing about size, so the "good" seller who stated a
        # 30-day window still came back ASKS YOU. Three rows, two of them the same
        # verdict, and the demonstration reading as though stating good terms gains
        # the seller nothing.
        #
        # The suffix is not shown to the customer: `says` stays the isolated
        # sentence, because what the panel is about is the one fact under test.
        others = "; ".join(
            other.good(other_rule)
            for other in SELLERS if other.field != seller.field
            for other_rule in [next((r for r in rules if r.field == other.field), None)]
            if other_rule is not None)

        def _details(text: str) -> str:
            return "; ".join(part for part in (text, others) if part)

        verdicts = {
            kind: judge(rules, policy, replace(base, details=_details(details)),
                        unsupported=unsupported)
            for kind, details in (("good", seller.good(rule)),
                                  ("bad", seller.bad(rule)),
                                  ("silent", seller.silent))
        }
        # No witness unless saying LESS did better than saying something bad. Under
        # `decline` it does not, and this list comes back empty.
        if PERMISSIVENESS[verdicts["silent"]] <= PERMISSIVENESS[verdicts["bad"]]:
            continue
        found.append({
            "field": seller.field,
            "question": seller.question,
            "uncertainty_policy": policy.value,
            "amount": base.amount,
            "states_acceptable": {"says": seller.good(rule), "verdict": verdicts["good"]},
            "states_unacceptable": {"says": seller.bad(rule), "verdict": verdicts["bad"]},
            "states_nothing": {"says": "", "verdict": verdicts["silent"]},
        })
    return found
