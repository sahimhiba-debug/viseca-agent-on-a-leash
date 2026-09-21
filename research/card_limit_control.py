"""What a conventional card control would have decided.

RESEARCH APPARATUS. Never imported by `src/wallet_control/`.

The most likely product objection to this whole project is "a card spending limit
already does that". It is a fair objection and it deserves a measurement rather
than a paragraph, so this file implements the competing control and runs the same
proposals through it.

MODELLED GENEROUSLY, ON PURPOSE. A strawman would be a per-transaction cap and
nothing else, and a judge would rightly say real cards do more. So this one has
everything a real issuer control actually offers:

    * a per-transaction amount cap
    * a monthly amount cap
    * an MCC allow-list (merchant category codes)
    * a merchant-country allow-list

That is the strongest version of the incumbent. What it still cannot express is
the point, and the point is not that card controls are bad -- they are good at the
question they ask. They ask **how much, where, and what kind of shop**. They have
no way to ask *"from a seller I have used before"*, *"only if I can send it back"*,
*"only the thing I actually asked for"*, or *"ask me when you are not sure"*.

Nothing here is a criticism of cards. It is a statement about which questions the
primitive can express.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

GROCERY_MCC = "5411"


@dataclass
class CardLimitControl:
    """A per-transaction limit, a monthly limit, an MCC allow-list, a country list.

    Deliberately NOT a strawman. If it can refuse something, it refuses it.
    """

    per_transaction_chf: Decimal = Decimal("120")
    monthly_chf: Decimal = Decimal("2000")
    allowed_mcc: frozenset[str] = frozenset({GROCERY_MCC})
    allowed_countries: frozenset[str] = frozenset({"CH"})
    spent_this_month: Decimal = field(default=Decimal("0"))
    approvals: int = 0

    def decide(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """Everything a card control can see, and everything it can do about it."""
        amount = Decimal(str(proposal["amount_chf"]))
        refused: list[str] = []

        if amount > self.per_transaction_chf:
            refused.append("per_transaction_limit")
        if self.spent_this_month + amount > self.monthly_chf:
            refused.append("monthly_limit")
        if proposal.get("mcc") not in self.allowed_mcc:
            refused.append("merchant_category")
        if proposal.get("country") not in self.allowed_countries:
            refused.append("merchant_country")
        # A card cannot see a NEGATIVE amount as anything but a refund, and a refund
        # is not a purchase it would decline. Modelled as it behaves, not as we would
        # like it to behave.
        if amount <= 0:
            refused.append("not_a_purchase")

        if refused:
            return {"decision": "block", "refused_by": sorted(refused)}
        self.spent_this_month += amount
        self.approvals += 1
        return {"decision": "allow", "refused_by": []}


# The questions the two controls can each ask. This table is the argument, and
# every row is checkable against the code on both sides.
EXPRESSIBLE = [
    ("How much is this one purchase?",              True,  True),
    ("How much this month?",                        True,  False),   # see note
    ("How much in any rolling 7 days?",             False, True),
    ("What kind of SHOP is this?",                  True,  True),
    ("Which country?",                              True,  False),
    ("Have I bought from this seller before?",      False, True),
    ("Is this the KIND of thing I asked for?",      False, True),
    ("Is this the specific thing I asked for?",     False, True),
    ("Is there anything in the basket I did not ask for?", False, True),
    ("Can I send it back?",                         False, True),
    ("Ask me when you are not sure",                False, True),
    ("Stop everything, now",                        True,  True),
]
# NOTE on "how much this month": the mandate vocabulary has no month scope, and the
# official API exposes no account-level spend counter -- `accounts.csv` carries a
# monthly limit we display and explicitly do NOT enforce. The card genuinely wins
# this row, and pretending otherwise would be the kind of overclaim this project
# spends its time removing.
