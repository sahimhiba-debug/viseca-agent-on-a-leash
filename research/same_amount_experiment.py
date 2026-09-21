"""The same basket, three times. Three different answers.

THE THESIS ARTIFACT. Everything else in this repository exists to make this
credible; this is the thing itself.

Whenever someone says "a spending limit already does that", the unspoken model is
that a bad purchase is an EXPENSIVE purchase, so a well-set limit catches it. The
cleanest refutation holds the amount constant and varies only the intent.

THE CONTROLLED TRIPLE -- cases 1, 2 and 3

    Same goods.      IT0018 Fresh produce order + IT0020 Family breakfast supplies
    Same prices.     CHF 30 + CHF 32
    Same total.      CHF 62.00
    Same shop.       ME0001 Alpine Basket, CH, MCC 5411
    Same card.       CA0001
    Same second.     2026-08-12T09:00:00Z -- each is the FIRST decision of its own
                     fresh session, so all three carry an identical timestamp

    ONE VARIABLE: what the seller says about sending it back.

        "returns accepted within 30 days"   ->  ALLOW
        the seller says nothing             ->  ASK THE CUSTOMER
        "final sale"                        ->  BLOCK

    Three authorizations. One difference. Nothing a card control can see has moved
    at all -- not the amount, not the shop, not the goods, not the clock.

CASE 4 adds a second dimension, holding the same amount, shop, card and second: a
    phone charger carried in on a grocery basket. Real item, real price, bought at
    a grocer, so the merchant's category still reads as groceries.

WHAT A CARD SEES
    On every input a card control can observe, all four are the same purchase.

TWO CASES WERE REMOVED FROM THE HEADLINE, AND WHY

    The rolling window. An earlier version used it as the fifth case under the claim
    "none of these refusals is about the amount". That claim was false: a rolling
    window bounds a SUM OF AMOUNTS, and a card with a monthly cap bounds one too. It
    was the weakest case wearing the strongest label. The old test missed it by
    grepping for the literal string "amount" after the class had been renamed to
    `budget_window` -- a rename that hid the problem from the test written to catch
    it.

    The unfamiliar merchant. "A shop I have used before" is the most intuitive
    constraint here and it is genuinely inexpressible on a card. It is still not
    airtight AS AN ISOLATED EXPERIMENT, because in the official data card CA0001 has
    paid every Swiss grocery merchant -- ME0001 through ME0004 -- and the only
    grocer it has never paid, ME0005 Rhine Pantry, is in GERMANY. A card control
    with a country allow-list would therefore also refuse it, for a reason that has
    nothing to do with the customer's intent. The dimension that cannot be held
    constant is the country, and the reason is the shape of the official data.

    Both appear below as disclosed counterexamples. Removing them costs one row each
    and buys an argument with no way in.

    A limit is a number. Intent is a sentence.
    You cannot enforce a sentence with a number.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient                          # noqa: E402

from research.card_limit_control import CardLimitControl           # noqa: E402
from wallet_control.api import app                                 # noqa: E402

client = TestClient(app)

AMOUNT = 62.0
FAMILIAR, STRANGER = "ME0001", "ME0005"


def _line(item_id, name, category, price, merchant=FAMILIAR, return_days=30):
    return {"item_id": item_id, "name": name, "category": category,
            "unit_price": price, "quantity": 1, "merchant": merchant,
            "return_days": return_days}


def _groceries(merchant=FAMILIAR, return_days=30):
    """The reference basket: CHF 30 + CHF 32."""
    return [_line("IT0018", "Fresh produce order", "groceries", 30, merchant, return_days),
            _line("IT0020", "Family breakfast supplies", "groceries", 32, merchant, return_days)]


CASES = [
    ("the seller accepts returns for 30 days",
     "exactly what the customer asked for",
     "allow", _groceries(return_days=30)),

    ("the same basket \u2014 the seller says nothing about returns",
     "identical goods, shop, price and second; the seller simply did not say",
     "review", _groceries(return_days=None)),

    ("the same basket \u2014 the seller says final sale",
     "identical goods, shop, price and second; now it cannot be sent back",
     "block", _groceries(return_days=0)),

    ("a phone charger, carried in on the grocery basket",
     "same amount, same shop, same second \u2014 but not what was asked for",
     "block", [_line("IT0018", "Fresh produce order", "groceries", 30),
               _line("IT0047", "Phone charger", "electronics", 32)]),
]

# Disclosed counterexamples. Kept OUT of the headline because an amount-only control
# could also refuse each of them -- one for the right reason, one for the wrong one.
COUNTEREXAMPLES = [
    ("the week's allowance, used up",
     "a rolling sum of amounts - a card with a periodic cap bounds one too",
     "the card can express this", _groceries()),
    ("a shop this card has never paid",
     "inexpressible on a card - but the only unfamiliar grocer in the data is in Germany",
     "the card would refuse it for the wrong reason", _groceries(merchant=STRANGER)),
]


def _merchant_row(merchant_id: str) -> dict:
    import csv
    path = Path(__file__).resolve().parents[1] / "data" / "official" / "merchants.csv"
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["merchant_id"] == merchant_id:
                return row
    raise KeyError(merchant_id)


def _card_says(lines, card=None):
    """A card sees the MERCHANT's own row -- its MCC and its country -- and never the
    basket. That is how a phone charger bought at a grocer reads as groceries.

    The real row, not a convenient one. An earlier version passed `country="CH"`
    regardless of where the shop actually was, which UNDERSTATED the card: Rhine
    Pantry is in Germany and a country allow-list would refuse it. Modelling the
    competitor as weaker than it is would have been the easiest way to lose this
    argument on stage.
    """
    row = _merchant_row(lines[0]["merchant"])
    total = sum(l["unit_price"] * l["quantity"] for l in lines)
    return (card or CardLimitControl()).decide(
        {"amount_chf": total, "mcc": row["merchant_mcc"],
         "country": row["merchant_country"]})["decision"]


def _wallet_says(lines, session):
    response = client.post("/api/agent/propose",
                           json={"session_id": session, "lines": lines})
    if response.status_code != 200:
        return {"decision": "block", "blocked_by": ["malformed"]}
    return response.json()


def run(shuffle_seed: int | None = None) -> list[dict]:
    """Every case in its OWN fresh session, so none can be explained by another.

    `shuffle_seed` runs them in a different order. A result that depends on order
    is not a result, and `tests/test_same_amount_experiment.py` checks 20 orderings.
    """
    order = list(range(len(CASES)))
    if shuffle_seed is not None:
        import random
        random.Random(shuffle_seed).shuffle(order)

    results: dict[int, dict] = {}
    for index in order:
        title, why, expected, lines = CASES[index]
        total = sum(l["unit_price"] * l["quantity"] for l in lines)
        assert total == AMOUNT, f"{title}: CHF {total}, not CHF {AMOUNT}"
        body = _wallet_says(lines, f"sa_{uuid.uuid4().hex[:10]}")
        results[index] = {
            "title": title, "why": why, "amount": total,
            "merchant": lines[0]["merchant"],
            "card": _card_says(lines),
            "wallet": body["decision"], "expected": expected,
            "blocked_by": body.get("blocked_by", []),
            "awaiting_customer": body.get("awaiting_customer", False),
        }
    return [results[i] for i in range(len(CASES))]


def run_counterexamples() -> list[dict]:
    """The two cases held out of the headline, each judged and each labelled."""
    out = []
    for title, why, note, lines in COUNTEREXAMPLES:
        session = f"sa_ctr_{uuid.uuid4().hex[:8]}"
        if "allowance" in title:                    # this one needs a filled window
            for _ in range(4):
                _wallet_says(lines, session)
        body = _wallet_says(lines, session)
        out.append({"title": title, "why": why, "note": note, "amount": AMOUNT,
                    "card": _card_says(lines), "wallet": body["decision"],
                    "blocked_by": body.get("blocked_by", [])})
    return out


_SYMBOL = {"allow": "YES", "review": "ASK", "block": "NO"}


def main() -> int:
    results = run()
    print(f"THE SAME BASKET, THREE TIMES. THEN ONE MORE. ALL CHF {AMOUNT:.2f}.\n")
    print("  Same goods, same shop, same card, same second. On every input a card")
    print("  control can see, these are the same purchase.\n")
    print(f"  {'':56s} {'card':>5s} {'wallet':>7s}   why")
    for r in results:
        print(f"  {r['title']:56s} {_SYMBOL[r['card']]:>5s} {_SYMBOL[r['wallet']]:>7s}   "
              f"{','.join(r['blocked_by']) or '-'}")

    print(f"\n  A card limit says YES {sum(r['card'] == 'allow' for r in results)} times out of {len(results)}.")
    print("  The wallet says YES once, ASKS once, and refuses twice -- for two")
    print("  different reasons, neither of which is the amount.")
    print("\n  Rows 1-3 are the IDENTICAL BASKET: same items, same prices, same shop,")
    print("  same card, same timestamp. The only variable is what the seller says")
    print("  about sending it back -- and it produces three different authorizations.")

    print("\n\nTWO CASES HELD OUT OF THE HEADLINE, AND WHY\n")
    for c in run_counterexamples():
        print(f"  {c['title']:56s} {_SYMBOL[c['card']]:>5s} {_SYMBOL[c['wallet']]:>7s}   "
              f"{','.join(c['blocked_by'])}")
        print(f"      {c['note']}: {c['why']}")

    print("""
  WHAT THIS PROVES, EXACTLY: that an amount-only control cannot encode these
  intent constraints. Not that it prevents fraud, not that it is universally
  better, and not that a card control is badly designed -- CHF 62 at a Swiss
  grocer is, on the only evidence a card has, a perfectly ordinary purchase.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
