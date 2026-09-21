"""The demo page's attack list must be the one the tests attack with.

A jury watching eight named attacks fail is watching a claim. If the page's list
and `research/adversarial_planner.ATTACKS` can drift, the claim is about a file
nobody tests.
"""

from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_attack_manifest import MANIFEST, manifest


def test_the_manifest_is_current():
    assert MANIFEST.exists(), "run scripts/generate_attack_manifest.py"
    assert json.loads(MANIFEST.read_text()) == manifest(), (
        "ui/attacks.json is stale -- regenerate it with "
        "scripts/generate_attack_manifest.py")


def test_the_page_reads_the_manifest_rather_than_its_own_copy():
    page = (Path(__file__).resolve().parents[1] / "ui" / "index.html").read_text()
    assert "attacks.json" in page, "the page hard-codes its own attack list again"


def test_every_attack_says_what_the_wallet_can_do_about_it():
    """Three outcomes, not one, because "blocked" is false for three of the eight.

    NEUTRALISED -- an invented product and an injected instruction are ALLOWED. The
    wallet cannot tell that a product does not exist, and cannot stop a seller
    writing instructions in its own copy. It binds both by the rules that bind an
    honest basket, so neither gains the agent anything.

    PACED -- repeating an affordable order is not refusable at all: every single
    proposal is a purchase the customer's rules permit, and a wallet that blocked
    them would be blocking compliant shopping. The rolling allowance stops the
    SEQUENCE.

    A demo that showed all eight as "blocked" would be claiming three guarantees we
    do not have, and a judge would find one of them on the first attempt."""
    kinds = {a["expected"] for a in manifest()}
    assert kinds == {"refused", "neutralised", "paced"}, kinds
    assert sum(a["expected"] == "refused" for a in manifest()) >= 5
    assert all(a["repeat"] >= 1 for a in manifest())
    paced = [a for a in manifest() if a["expected"] == "paced"]
    assert paced and all(a["repeat"] > 1 for a in paced), (
        "a paced attack submitted once shows nothing: it is allowed, correctly, and "
        "looks like a failure")
