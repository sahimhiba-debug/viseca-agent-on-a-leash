"""A rule is worth only as much as the provenance of the fact it reads.

THE QUESTION THIS ANSWERS

`policy_compiler` turns a sentence into rules and the Delegate tab shows them, each
looking equally solid:

    Purchases must be for the requested kind of item (groceries).
    The order must be returnable within at least 14 days.
    Purchases must be from a shop you have paid before.

They are not equally solid. Each is checked against a FACT, and the facts have
different authors:

    merchant.familiar          read from the card's own authorization history.
                               The agent picks WHICH shop; it cannot pick what that
                               shop is to this card.                        BOUND

    item.category              supplied per line, by the party proposing the
                               purchase, and checked against the official catalogue:
                               a gift card labelled `groceries` is caught, and goods
                               the catalogue cannot identify are put to the customer
                               instead of being taken on the agent's word.
                                                                       REFUTABLE

    order.return_window_days   read from what the seller wrote. There is no second
                               source. A plausible claim satisfies it.   ADVISORY

The customer wrote three requirements and got one guarantee, one refutation and one
promise. Nobody told them which was which.

THE FACT WITH NO RULE OF ITS OWN

`authorization.timestamp` is not a field any rule names, and it was therefore missed
by the first version of this table -- which classified the nine fields `rules.py`
evaluates and stopped there. It is the clock every rolling ceiling is measured in,
so it decides which week money counts against. Measured, on a CHF 300 / 7-day cap
with the ceiling already spent:

    the purchase, honestly stamped        block
    the same purchase, stamped 8 days ago ALLOW   -- CHF 600 against a CHF 300 cap

It is BOUND, and only because of how it is produced: the replay preserves the pack's
simulated time and the agent endpoint derives its own from a fixed origin, ignoring
anything a caller sends. A lesson rather than a reassurance -- a decision input with
no rule attached to it had no provenance at all until something went looking.

THE CRITERION, STATED PRECISELY

A fact is FORGEABLE if misstating it changes the decision **while leaving the purchase
itself unchanged** -- same goods, same shop, same price, same moment. That last clause
is what separates a real hole from an apparent one: an agent can also write
`billing_amount_chf`, and understating it turns a BLOCK into an ALLOW -- for less
money, since the understated figure is what is charged. Writing it is not forging it.

So the classes are about what a misstatement BUYS, not about who holds the pen.

NOT A TABLE THAT CLAIMS THIS -- A TABLE THAT IS ATTACKED.
`research/forgeable_facts.py` runs the misstatement through the real engine for every
field below and fails if the measured class differs from the declared one. The
declaration is a hypothesis; the experiment is the evidence.
"""

from __future__ import annotations

from dataclasses import dataclass

# WHAT A FACT'S ABSENCE IS ALLOWED TO MEAN. Provenance asks who WROTE a fact;
# polarity asks what its SILENCE means, and the two together decide whether saying
# nothing is profitable.
#
#   REQUIREMENT  evidence FOR authority. The customer asked for something and this
#                shows it is so. Absence must never satisfy it.
#   FLAG         evidence AGAINST. The wallet raises it on its own; absence is the
#                ordinary case, so erasing it necessarily helps the proposer -- and
#                that is not a defect. You cannot be flagged for text you did not
#                write, and not attacking is not an attack.
#
# The distinction is invisible in a field list, because one CHANNEL can carry both:
# `item_details` holds the return window (requirement) and the injection (flag), and
# a seller who deletes the text erases one of each. `research/erasure.py` measures
# the consequence over every field of the 45 official events.
REQUIREMENT = "requirement"
FLAG = "flag"

BOUND = "bound"          # the agent cannot author this fact at all
REFUTABLE = "refutable"  # it can, and an independent source can contradict it
ADVISORY = "advisory"    # it can, and nothing can contradict it


@dataclass(frozen=True)
class Provenance:
    field: str
    author: str          # who supplies the fact the rule is evaluated against
    binding: str         # BOUND | REFUTABLE | ADVISORY
    checked_by: str      # what, if anything, can contradict the claim
    customer_line: str   # what to tell the customer, in their language
    polarity: str = REQUIREMENT   # REQUIREMENT | FLAG -- see above


FACTS: tuple[Provenance, ...] = (
    Provenance(
        "merchant.familiar", "the card's own authorization history", BOUND,
        "nothing needs to: the agent never supplies it",
        "The agent cannot affect this. It chooses which shop to use; it cannot change "
        "what that shop is to your card."),
    Provenance(
        "merchant.category", "the official merchant record", BOUND,
        "loaded from reference data, never from the proposal",
        "The agent cannot affect this. The shop's kind comes from the shop's record."),
    Provenance(
        "session.integrity_risk", "the platform, plus this run's own observations", BOUND,
        "the event's velocity claim is cross-checked against what this run has seen, "
        "and only ever raised",
        "The agent cannot affect this. It is what the wallet itself saw happen.",
        polarity=FLAG),
    Provenance(
        "authorization.billing_amount_chf", "the proposal, cross-checked", BOUND,
        "amount x the fixed FX rate, to within 2 rappen -- and understating it only "
        "charges less",
        "The agent names the amount, and naming a smaller one buys a smaller thing. "
        "The figure it names is the figure that is charged."),
    Provenance(
        "authorization.timestamp", "the platform, and this wallet's own derivation", BOUND,
        "never read from the proposal: the offline replay preserves the pack's "
        "simulated purchase time and `/api/agent/propose` derives its own",
        "The agent cannot choose when this happened. That matters more than it "
        "sounds: WHEN a purchase happened decides which week it counts against."),
    Provenance(
        "item.category", "the party proposing the purchase", REFUTABLE,
        "the official item catalogue: a mismatch is refused, and an id it does not "
        "know is `unknown` rather than agreement",
        "The agent says what kind of thing this is. The wallet checks it against the "
        "official catalogue: a mismatch is refused, and goods it cannot identify are "
        "put to you rather than taken on the agent's word."),
    Provenance(
        "item.unrequested_present", "the party proposing the purchase", REFUTABLE,
        "derived from item.category, so it inherits that check",
        "Derived from the kinds of thing in the basket, so it is as strong as those."),
    Provenance(
        "item.name_contains", "the party proposing the purchase", ADVISORY,
        "nothing: a name is a name",
        "The agent says what this is called. Nothing can check a name."),
    Provenance(
        "item.size", "the seller's own product text", ADVISORY,
        "nothing: there is no second source for a stated size",
        "This is what the seller wrote. Nothing independent confirms it."),
    Provenance(
        "order.return_window_days", "the seller's own product text", ADVISORY,
        "nothing: there is no second source for a stated return window",
        "This is what the seller wrote. A seller who states a long window satisfies "
        "it; a seller who states nothing is put to you. Nothing can confirm either."),
)

BY_FIELD = {p.field: p for p in FACTS}


def for_rule(field: str) -> Provenance | None:
    return BY_FIELD.get(field)


def weakest(fields: list[str]) -> str:
    """A policy is only as strong as its weakest-provenance rule."""
    order = {BOUND: 0, REFUTABLE: 1, ADVISORY: 2}
    known = [BY_FIELD[f].binding for f in fields if f in BY_FIELD]
    return max(known, key=lambda b: order[b]) if known else BOUND
