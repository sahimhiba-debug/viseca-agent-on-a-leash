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

MANIFEST = Path(__file__).resolve().parents[1] / "ui" / "attacks.json"


def manifest() -> list[dict]:
    return [{"key": a.key, "title": a.title, "goal": a.goal, "merchant": a.merchant,
             "expected": a.expected, "repeat": a.repeat} for a in ATTACKS]


def main() -> int:
    MANIFEST.write_text(json.dumps(manifest(), indent=2) + "\n")
    print(f"wrote {len(ATTACKS)} attacks to {MANIFEST.relative_to(MANIFEST.parents[1])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
