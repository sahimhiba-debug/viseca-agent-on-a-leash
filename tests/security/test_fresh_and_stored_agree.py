"""A decision must not change its story between being made and being read back.

THE PATH NOBODY DIFFED. `POST /api/scenarios/{id}/run` returns decisions built from
live rule evaluations. `GET /api/runs/{id}` rebuilds the same decisions from the
ledger, where the evaluations are gone and only reason codes survive. The page
re-renders from the GET after every step-up and every revocation -- so the moment a
customer presses "Approve once", every card on the screen is redrawn from the second
path.

They disagreed, in three separate ways, all of them invisible unless the two are
compared directly:

  1. REASONS THAT WERE SEEN BUT DID NOT DECIDE WERE DISCARDED. A purchase blocked on
     its amount, from a seller whose listing also contained instructions aimed at an
     automated buyer, was recorded with the amount alone. Approve anything and the
     page stopped telling the customer about the injection. `observed:` codes now
     carry them.

  2. THE POLICY/WALLET SPLIT WAS RECONSTRUCTED FROM A DRIFTED COPY. `_SAFETY_FIELDS`
     listed seven fields; the engine has fourteen; one of the seven was not a field
     this engine emits at all. Seven checks the customer never opted into were being
     reported as THEIR rule stopping the purchase -- inverting the one distinction
     this product calls the most audit-relevant fact in a run. Now derived from the
     engine's own rule constants.

  3. A ROLLING-WINDOW BREACH WAS READ BACK AS A PER-ORDER ONE. Same field, different
     scope, and a reason code carried only the field -- so a customer who had spent
     their week was told the ORDER was too big. `_plain_reason` has a comment warning
     about exactly this ("blames the wrong boundary"); the defect was one layer down.

WHAT THIS ASSERTS is parity, not correctness: both paths could be wrong together.
Correctness of the wording is `test_customer_message.py`'s job. This is the property
that the story does not change depending on when you look at it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from wallet_control.api import app
from wallet_control.csv_data import load_scenario_catalogue

client = TestClient(app)

FIELDS = ("decision", "wallet_decision", "policy_verdict", "security_verdict",
          "plain_reasons", "reason_codes", "amount_chf", "merchant_name")


def _both(scenario):
    fresh = client.post(f"/api/scenarios/{scenario}/run", json={}).json()
    stored = client.get(f"/api/runs/{fresh['run_id']}").json()

    def index(decisions):
        return {d["authorization_id"]: {k: d.get(k) for k in FIELDS} for d in decisions}

    return index(fresh["decisions"]), index(stored["decisions"])


@pytest.mark.parametrize("scenario", sorted(load_scenario_catalogue()))
def test_the_ledger_tells_the_same_story_as_the_decision(scenario):
    fresh, stored = _both(scenario)
    assert set(fresh) == set(stored), (set(fresh) ^ set(stored))
    for authorization_id, made in fresh.items():
        assert made == stored[authorization_id], (
            f"{scenario} {authorization_id} is described differently once it has been "
            f"recorded:\n  fresh  {made}\n  stored {stored[authorization_id]}")


def test_the_comparison_is_not_vacuous():
    """Both paths returning nothing, or every field None, would satisfy the test
    above. The corpus has to contain the shapes the defects lived in: a block with a
    non-deciding observation beside it, a wallet check, and a rolling-window breach."""
    fresh, _ = _both("SCEN0004")
    assert len(fresh) >= 5

    observed = [d for d in fresh.values()
                if any(c.startswith("observed:") for c in d["reason_codes"])]
    assert observed, "no decision carries an observation that did not decide it"

    wallet_stopped = [d for d in fresh.values()
                      if d["policy_verdict"] == "allow" and d["security_verdict"] != "allow"]
    assert wallet_stopped, "no decision where the wallet stopped what policy allowed"

    window, _ = _both("SCEN0001")
    assert any("billing_amount_chf.period" in c
               for d in window.values() for c in d["reason_codes"]), (
        "no rolling-window breach in the corpus, so the scope defect is untested")


def test_the_safety_field_list_is_derived_not_copied():
    """The drift that caused (2). If a new safety rule is added to the engine and the
    set is not rebuilt from the constants, this fails rather than silently
    re-attributing that check to the customer."""
    import ast
    import inspect

    from wallet_control import decision_engine
    from wallet_control.decision_engine import SAFETY_RULE_FIELDS

    tree = ast.parse(inspect.getsource(decision_engine))
    declared = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not (isinstance(target, ast.Name) and target.id.endswith("_RULE")):
            continue
        for keyword in getattr(node.value, "keywords", []):
            if keyword.arg == "field" and isinstance(keyword.value, ast.Constant):
                declared.add(keyword.value.value)

    missing = declared - set(SAFETY_RULE_FIELDS)
    assert not missing, (
        f"these safety rules exist in the engine and are not in SAFETY_RULE_FIELDS: "
        f"{sorted(missing)} -- a decision stopped by one of them would be reported to "
        f"the customer as their own rule stopping it")
