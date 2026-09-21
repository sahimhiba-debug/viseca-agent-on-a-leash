"""Write the adversarial brain's attack list where the demo page can read it.

The attacks live in `research/`, and `src/wallet_control/api.py` must never import
`research/` -- that boundary is the whole architecture. So the list is generated
into a static file the page fetches, and `tests/test_attack_manifest_matches.py`
fails if the two drift. Same arrangement as the browser planner: duplication is
allowed when a test forbids it from mattering.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from research.adversarial_planner import ATTACKS  # noqa: E402
from research.card_limit_control import EXPRESSIBLE, CardLimitControl  # noqa: E402
from research.same_amount_experiment import AMOUNT, CASES  # noqa: E402

MANIFEST = Path(__file__).resolve().parents[1] / "ui" / "attacks.json"
CARD = Path(__file__).resolve().parents[1] / "ui" / "card-control.json"
SAME_AMOUNT = Path(__file__).resolve().parents[1] / "ui" / "same-amount.json"


def manifest() -> list[dict]:
    return [{"key": a.key, "title": a.title, "goal": a.goal, "merchant": a.merchant,
             "expected": a.expected, "repeat": a.repeat} for a in ATTACKS]


def card_control() -> dict:
    """The competing control's parameters, so the page can show what it would have
    said without keeping its own copy of the numbers."""
    control = CardLimitControl()
    return {
        "per_transaction_chf": float(control.per_transaction_chf),
        "monthly_chf": float(control.monthly_chf),
        "allowed_mcc": sorted(control.allowed_mcc),
        "allowed_countries": sorted(control.allowed_countries),
        "expressible": [{"question": q, "card": c, "mandate": w} for q, c, w in EXPRESSIBLE],
    }


def same_amount() -> dict:
    """The five baskets, for the page to submit LIVE. Only the baskets are
    generated -- never the verdicts. A demo that shipped its own answers would be
    exactly the thing this project refuses to build."""
    return {"amount_chf": AMOUNT,
            "cases": [{"title": t, "why": w, "lines": l} for t, w, l in CASES]}


def main() -> int:
    SAME_AMOUNT.write_text(json.dumps(same_amount(), indent=2) + "\n")
    MANIFEST.write_text(json.dumps(manifest(), indent=2) + "\n")
    CARD.write_text(json.dumps(card_control(), indent=2) + "\n")
    print(f"wrote {len(ATTACKS)} attacks to {MANIFEST.relative_to(MANIFEST.parents[1])}")
    print(f"wrote the card control to {CARD.relative_to(CARD.parents[1])}")
    print(f"wrote {len(CASES)} same-amount baskets to {SAME_AMOUNT.relative_to(SAME_AMOUNT.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
