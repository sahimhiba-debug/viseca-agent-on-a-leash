import pytest

from wallet_control.mandate import HardRule, Mandate, MandateError, MandateSnapshot, MandateStatus, UncertaintyPolicy


def _amount_rule(value=100):
    return HardRule(field="authorization.billing_amount_chf", operator="<=", value=value, currency="CHF", scope="purchase")


def test_draft_starts_in_draft_status():
    m = Mandate.draft("Buy stuff", [_amount_rule()], UncertaintyPolicy.ASK)
    assert m.status == MandateStatus.DRAFT
    assert m.mandate_id.startswith("draft_")


def test_confirm_requires_explicit_true():
    m = Mandate.draft("Buy stuff", [], UncertaintyPolicy.ASK)
    with pytest.raises(MandateError):
        m.confirm(confirmed=False, customer_id="CU1", card_id="CA1", profile_id="P1")
    assert m.status == MandateStatus.DRAFT


def test_confirm_activates_and_assigns_tm_id():
    m = Mandate.draft("Buy stuff", [], UncertaintyPolicy.ASK)
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    assert m.status == MandateStatus.ACTIVE
    assert m.mandate_id.startswith("TM")


def test_cannot_confirm_twice():
    m = Mandate.draft("Buy stuff", [], UncertaintyPolicy.ASK)
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    with pytest.raises(MandateError):
        m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")


def test_tighten_hard_rules_only_appends_never_removes():
    m = Mandate.draft("Buy stuff", [_amount_rule(200)], UncertaintyPolicy.ASK)
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    original = m.hard_rules
    m.tighten_hard_rules([HardRule(field="merchant.familiar", operator="=", value="true")])
    assert original[0] in m.hard_rules  # the original rule is untouched and still present
    assert len(m.hard_rules) == 2


def test_tighten_hard_rules_is_idempotent_for_identical_rules():
    rule = _amount_rule(200)
    m = Mandate.draft("Buy stuff", [rule], UncertaintyPolicy.ASK)
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    m.tighten_hard_rules([rule])
    assert len(m.hard_rules) == 1  # PATCHing the same rule again must not duplicate it


def test_hard_rules_property_returns_a_copy_not_the_live_list():
    """Aliasing hazard: a caller must not be able to mutate mandate internals by
    holding a reference to `hard_rules`."""
    m = Mandate.draft("Buy stuff", [_amount_rule()], UncertaintyPolicy.ASK)
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    snapshot_tuple = m.hard_rules
    assert isinstance(snapshot_tuple, tuple)
    m.tighten_hard_rules([HardRule(field="merchant.familiar", operator="=", value="true")])
    assert len(snapshot_tuple) == 1  # the earlier tuple is unaffected by the later mutation


def test_hard_rule_is_frozen():
    rule = _amount_rule()
    with pytest.raises(Exception):
        rule.field = "something.else"  # type: ignore[misc]


@pytest.mark.parametrize(
    "start,attempt,allowed",
    [
        (UncertaintyPolicy.ASK, UncertaintyPolicy.DECLINE, True),
        (UncertaintyPolicy.APPROVE, UncertaintyPolicy.DECLINE, True),
        (UncertaintyPolicy.APPROVE, UncertaintyPolicy.ASK, False),  # not allowed: widens uncertainty handling
        (UncertaintyPolicy.DECLINE, UncertaintyPolicy.ASK, False),  # not allowed: loosens the strictest setting
        (UncertaintyPolicy.DECLINE, UncertaintyPolicy.APPROVE, False),
    ],
)
def test_uncertainty_policy_transitions_are_tighten_only(start, attempt, allowed):
    m = Mandate.draft("Buy stuff", [], start)
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    if allowed:
        m.set_uncertainty_policy(attempt)
        assert m.uncertainty_policy == attempt
    else:
        with pytest.raises(MandateError):
            m.set_uncertainty_policy(attempt)
        assert m.uncertainty_policy == start


def test_revoke_is_terminal_and_idempotent():
    m = Mandate.draft("Buy stuff", [], UncertaintyPolicy.ASK)
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    m.revoke()
    assert m.status == MandateStatus.REVOKED
    m.revoke()  # calling twice must not raise or change state
    assert m.status == MandateStatus.REVOKED


def test_cannot_tighten_a_revoked_mandate():
    m = Mandate.draft("Buy stuff", [], UncertaintyPolicy.ASK)
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    m.revoke()
    with pytest.raises(MandateError):
        m.tighten_hard_rules([_amount_rule()])


def test_snapshot_is_immutable_to_later_mandate_changes():
    """A run keeps its original snapshot even if the live mandate is later patched
    or revoked (technical_details.md step 6: 'A run uses a snapshot...')."""
    m = Mandate.draft("Buy stuff", [_amount_rule(200)], UncertaintyPolicy.ASK)
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    snapshot = m.snapshot()
    m.tighten_hard_rules([HardRule(field="merchant.familiar", operator="=", value="true")])
    m.revoke()
    assert len(snapshot.hard_rules) == 1
    assert snapshot.status.value == "active"


def test_snapshot_round_trips_through_event_mandate_block():
    """The live worker rebuilds a MandateSnapshot from an event's `mandate` object
    (see live_worker.py) rather than guessing platform-assigned identity fields;
    this must reproduce the original snapshot faithfully."""
    m = Mandate.draft(
        "Buy stuff",
        [_amount_rule(200), HardRule(field="merchant.category", operator="in", value=["sporting_goods"])],
        UncertaintyPolicy.DECLINE,
    )
    m.confirm(confirmed=True, customer_id="CU1", card_id="CA1", profile_id="P1")
    original = m.snapshot()

    event_mandate_block = {
        "mandate_id": original.mandate_id,
        "status": original.status.value,
        "customer_id": original.customer_id,
        "card_id": original.card_id,
        "instruction": original.instruction,
        "hard_rules": [r.as_dict() for r in original.hard_rules],
        "uncertainty_policy": original.uncertainty_policy.value,
        "profile_id": original.profile_id,
    }
    rebuilt = MandateSnapshot.from_event_mandate(event_mandate_block)
    assert rebuilt == original


@pytest.mark.parametrize(
    "bad_kwargs",
    [
        dict(field="", operator="<=", value=1),
        dict(field="x", operator="~=", value=1),
        dict(field="x", operator="=", value=True),
        dict(field="x", operator="=", value=None),
        dict(field="x", operator="in", value=[1, 2]),
        dict(field="x", operator="=", value=1, currency="JPY"),
        dict(field="x", operator="=", value=1, scope="lifetime"),
        dict(field="x", operator="=", value=1, period_days=0),
    ],
)
def test_hard_rule_rejects_invalid_shapes(bad_kwargs):
    with pytest.raises(MandateError):
        HardRule(**bad_kwargs)
