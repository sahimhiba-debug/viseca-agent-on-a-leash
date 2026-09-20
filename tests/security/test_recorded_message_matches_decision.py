"""A re-presented decision must never describe itself as something it is not.

`_recorded_message` has now produced two defects of the same shape, and both were
found by looking at a surface rather than by a test. The first emitted raw reason
codes (`"Declined: hard_rule_failed:authorization.billing_amount_chf"`) to a
customer. The second is this one: everything that was neither a block nor an
ANSWERED review fell through to "Approved: this purchase matched your wallet
policy", including a review still WAITING for the customer.

That made the single most important decision in the whole demo lie about itself.
In SCEN0004 there is exactly one authorization where every rule the customer wrote
passed and the wallet stopped the purchase anyway -- policy `allow`, security
`review`, a suspected duplicate -- and the card told the customer it was approved
while showing the verdict as `review` beside it.

The invariant, stated so it cannot rot again: **the customer-facing sentence for a
stored decision must agree with that decision's verdict**, for every verdict the
engine can produce, not just the two somebody remembered.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from wallet_control.api import _recorded_message, app
from wallet_control.state import StoredDecision

client = TestClient(app)


def _stored(decision, *, reason_codes=(), was_reviewed=False, resolved_at=None):
    return StoredDecision(
        authorization_id="AU_TEST", decision=decision,
        billing_amount_chf=Decimal("100"), timestamp=datetime(2026, 8, 12, tzinfo=timezone.utc),
        counted_in_spend=False, merchant_id="ME0001", basket_key=(),
        was_reviewed=was_reviewed, resolved_at=resolved_at, reason_codes=tuple(reason_codes))


@pytest.mark.parametrize("decision,reason_codes,was_reviewed,resolved,forbidden", [
    ("review", ("uncertain:order.duplicate_suspected",), True, None, "approved"),
    ("review", ("uncertain:order.return_window_days",), True, None, "approved"),
    ("review", (), True, None, "approved"),
    ("block", ("hard_rule_failed:authorization.billing_amount_chf",), False, None, "approved"),
])
def test_a_decision_that_is_not_an_approval_never_says_approved(
        decision, reason_codes, was_reviewed, resolved, forbidden):
    message = _recorded_message(
        _stored(decision, reason_codes=reason_codes, was_reviewed=was_reviewed,
                resolved_at=resolved), {})
    assert forbidden not in message.lower(), f"{decision!r} described itself as: {message!r}"


def test_a_pending_review_says_it_is_waiting_and_why_in_plain_words():
    message = _recorded_message(
        _stored("review", reason_codes=("uncertain:order.duplicate_suspected",),
                was_reviewed=True), {})
    assert message.startswith("Waiting for you:")
    assert "already placed" in message, message
    # ...and never the machine's vocabulary. This is the I39 lesson, on the surface
    # it was originally missed on.
    for internal in ("uncertain:", "order.duplicate_suspected", "hard_rule", "_"):
        assert internal not in message, f"leaked {internal!r}: {message!r}"


def test_an_answered_review_reports_who_answered_it():
    when = datetime(2026, 8, 12, 10, tzinfo=timezone.utc)
    assert "You approved" in _recorded_message(
        _stored("allow", was_reviewed=True, resolved_at=when), {})
    assert "You declined" in _recorded_message(
        _stored("block", was_reviewed=True, resolved_at=when), {})


# ============================================ the demo beat itself, pinned end to end
def _run(scenario):
    run_id = client.post(f"/api/scenarios/{scenario}/run", json={}).json()["run_id"]
    return client.get(f"/api/runs/{run_id}").json()["decisions"]


def test_SCEN0004_still_contains_the_one_case_the_demo_is_built_on():
    """"Every rule you wrote was satisfied. The wallet stopped this anyway."

    That sentence is only honest if a decision exists where policy says allow and
    security does not. The demo script pointed at SCEN0002 for two campaigns; its
    review is a POLICY review -- the customer's own returnable rule was uncertain --
    which is a different and much weaker claim. The case actually lives here.
    """
    overrides = [d for d in _run("SCEN0004")
                 if d["policy_verdict"] == "allow" and d["security_verdict"] != "allow"]
    assert len(overrides) == 1, (
        f"SCEN0004 has {len(overrides)} policy-allow/security-block decisions; the demo "
        "script promises exactly one and names it on screen")
    only = overrides[0]
    assert only["decision"] == "review"
    assert only["reason_codes"] == ["uncertain:order.duplicate_suspected"]
    assert "approved" not in only["customer_message"].lower(), only["customer_message"]


def test_SCEN0002_is_NOT_a_security_override_and_we_do_not_say_it_is():
    """Kept as a test rather than a comment, because the demo script made exactly
    this mistake and nothing failed."""
    overrides = [d for d in _run("SCEN0002")
                 if d["policy_verdict"] == "allow" and d["security_verdict"] != "allow"]
    assert not overrides, (
        "SCEN0002 now contains a security override -- if that is intended, the demo "
        "script and FINAL_DEMO_SCRIPT.md should be revisited")


@pytest.mark.parametrize("answer,expect_decision,expect_text", [
    ("block", "block", "You declined this purchase."),
    ("allow", "allow", "You approved this purchase."),
])
def test_the_customers_own_answer_is_reported_as_theirs_end_to_end(
        answer, expect_decision, expect_text):
    """Through the real HTTP path, not a constructed record.

    Before the branch order was fixed, declining a step-up came back as
    "Declined: a check failed." -- blaming the wallet for a decision the customer
    had just made with their own thumb.
    """
    run_id = client.post("/api/scenarios/SCEN0004/run", json={}).json()["run_id"]
    pending = [d for d in client.get(f"/api/runs/{run_id}").json()["decisions"]
               if d["decision"] == "review"]
    assert pending, "SCEN0004 no longer raises a step-up for the customer to answer"
    auth_id = pending[0]["authorization_id"]

    resolved = client.post(
        f"/api/runs/{run_id}/authorizations/{auth_id}/resolve", json={"decision": answer})
    assert resolved.status_code == 200, resolved.text

    after = [d for d in client.get(f"/api/runs/{run_id}").json()["decisions"]
             if d["authorization_id"] == auth_id][0]
    assert after["decision"] == expect_decision
    assert after["customer_message"] == expect_text
