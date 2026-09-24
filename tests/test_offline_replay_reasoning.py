"""docs/OFFLINE_REPLAY.md explains every official decision. It must be right.

The README sends a reader there for "the reasoning behind every one of the 45
decisions". It stated a 19/2/24 split and called AU0026 and AU0040 approvals for
three boundary moves after both had become questions, because nothing compared the
page to the engine. This does: every bold "AUxxxx VERDICT" on the page is checked
against the replay, and every official decision must be explained there.
"""

from __future__ import annotations

import re
from pathlib import Path

from wallet_control.offline_replay import replay_all

PAGE = Path(__file__).resolve().parents[1] / "docs" / "OFFLINE_REPLAY.md"
WORD = {"allow": "ALLOW", "review": "REVIEW", "block": "BLOCK"}


def _stated() -> dict[str, str]:
    stated: dict[str, str] = {}
    for bold in re.findall(r"\*\*([^*]+)\*\*", PAGE.read_text()):
        verdict = re.search(r"\b(ALLOW|REVIEW|BLOCK)\b", bold)
        for authorization_id in re.findall(r"\bAU\d{4}\b", bold):
            if verdict:
                stated[authorization_id] = verdict.group(1)
    return stated


def test_every_stated_verdict_is_the_engines():
    actual = {d.authorization_id: WORD[d.decision] for s in replay_all().scenarios for d in s.decisions}
    stated = _stated()
    wrong = {a: (v, actual.get(a)) for a, v in stated.items() if actual.get(a) != v}
    assert not wrong, f"the page says (stated, engine): {wrong}"


def test_every_official_decision_is_explained():
    actual = {d.authorization_id for s in replay_all().scenarios for d in s.decisions}
    missing = sorted(actual - set(_stated()))
    assert not missing, f"no stated verdict for {missing}"
