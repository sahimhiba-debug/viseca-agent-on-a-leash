"""Five purchases. One amount. Five different answers.

The strongest expression of the distinction, because it removes the variable
everyone assumes is doing the work.

Whenever someone says "a spending limit already does that", the unspoken model is
that a bad purchase is an EXPENSIVE purchase -- so a well-set limit catches it. That
model is wrong, and the cleanest way to show it is to hold the amount constant and
vary only the intent.

Every basket below costs exactly CHF 62. Every item is a real row of
`data/official/items.csv` priced inside its own published band. Every merchant is a
real grocer from `merchants.csv`, and which of them this card has paid before comes
from the real authorization history.

A card limit sees one number, five times, and says yes five times. It is not being
stupid: CHF 62 IS within the limit, at a grocer, in Switzerland. There is nothing
about the number to object to. The objection is about everything else.

    A limit is a number. Intent is a sentence.
    You cannot enforce a sentence with a number.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient                          # noqa: E402

from research.card_limit_control import CardLimitControl           # noqa: E402
from wallet_control.api import app                                 # noqa: E402

client = TestClient(app)

AMOUNT = 62.0
FAMILIAR, STRANGER = "ME0001", "ME0005"


def _line(item_id, name, category, price, merchant, return_days=30):
    return {"item_id": item_id, "name": name, "category": category,
            "unit_price": price, "quantity": 1, "merchant": merchant,
            "return_days": return_days}


#  id       name                        category       price  returns
PRODUCE = ("IT0018", "Fresh produce order",       "groceries",   30, 30)
BREAKFA = ("IT0020", "Family breakfast supplies", "groceries",   32, 30)
CLEARAN = ("IT0004", "Weekly grocery basket",     "groceries",   45,  0)   # final sale
SUPPLIE = ("IT0003", "Breakfast supplies",        "groceries",   17, 30)
CHARGER = ("IT0047", "Phone charger",             "electronics", 32, 30)   # not groceries

CASES = [
    ("exactly what was asked for",
     "everything the customer's sentence permits",
     [_line(*PRODUCE[:4], FAMILIAR, PRODUCE[4]), _line(*BREAKFA[:4], FAMILIAR, BREAKFA[4])]),

    ("from a shop this card has never paid",
     "the customer said 'a shop I have used before'",
     [_line(*PRODUCE[:4], STRANGER, PRODUCE[4]), _line(*BREAKFA[:4], STRANGER, BREAKFA[4])]),

    ("holding a line the seller will not take back",
     "the customer said 'only if returnable within 14 days'",
     [_line(*CLEARAN[:4], FAMILIAR, CLEARAN[4]), _line(*SUPPLIE[:4], FAMILIAR, SUPPLIE[4])]),

    ("with something the customer never asked for",
     "a phone charger, carried in on a grocery basket at a grocer",
     [_line(*PRODUCE[:4], FAMILIAR, PRODUCE[4]), _line(*CHARGER[:4], FAMILIAR, CHARGER[4])]),

    ("after the week's allowance is used up",
     "identical to the first basket, proposed once too often",
     [_line(*PRODUCE[:4], FAMILIAR, PRODUCE[4]), _line(*BREAKFA[:4], FAMILIAR, BREAKFA[4])]),
]


def run() -> list[dict]:
    """Both controls, five baskets, one FRESH session so the allowance fills exactly
    once.

    The session id is unique per call. An earlier version reused one id, so calling
    `run()` twice in a process started the second run with the window already full
    and the first basket -- the compliant one -- came back refused. The experiment
    has to be self-contained or it is not an experiment.
    """
    import uuid

    session = f"same_amount_{uuid.uuid4().hex[:10]}"
    card = CardLimitControl()
    results = []
    for index, (title, why, lines) in enumerate(CASES):
        total = sum(l["unit_price"] * l["quantity"] for l in lines)
        assert total == AMOUNT, f"{title}: CHF {total}, not CHF {AMOUNT}"

        # A card sees the MERCHANT's category, never the basket. Both shops are
        # grocers, so a phone charger bought at a grocer reads as groceries.
        card_verdict = card.decide({"amount_chf": total, "mcc": "5411", "country": "CH"})

        # The last case must be judged after the earlier ones have spent the window,
        # which is why every case shares one session.
        if index == len(CASES) - 1:
            filler = [_line(*PRODUCE[:4], FAMILIAR, PRODUCE[4]),
                      _line(*BREAKFA[:4], FAMILIAR, BREAKFA[4])]
            for _ in range(4):
                client.post("/api/agent/propose",
                            json={"session_id": session, "lines": filler})

        response = client.post("/api/agent/propose",
                               json={"session_id": session, "lines": lines})
        body = response.json() if response.status_code == 200 else {
            "decision": "block", "blocked_by": ["malformed"]}

        results.append({"title": title, "why": why, "amount": total,
                        "card": card_verdict["decision"],
                        "wallet": body["decision"],
                        "blocked_by": body.get("blocked_by", [])})
    return results


def main() -> int:
    results = run()
    print(f"FIVE PURCHASES. ALL EXACTLY CHF {AMOUNT:.2f}. ALL AT A SWISS GROCER.\n")
    print(f"  {'':52s} {'card':>6s} {'wallet':>8s}   why")
    for r in results:
        print(f"  {r['title']:52s} {r['card']:>6s} {r['wallet']:>8s}   "
              f"{','.join(r['blocked_by']) or '-'}")

    card_yes = sum(r["card"] == "allow" for r in results)
    wallet_yes = sum(r["wallet"] == "allow" for r in results)
    print(f"\n  A card limit says yes {card_yes} times out of {len(results)}.")
    print(f"  The wallet says yes {wallet_yes}.")
    print("""
  The card is not being careless. CHF 62 is inside the limit, the merchant is a
  grocer, the country is Switzerland. There is nothing about the NUMBER to object
  to in any of the five -- and four of them are still not what the customer asked
  for.

  A limit is a number. Intent is a sentence.
  You cannot enforce a sentence with a number.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
