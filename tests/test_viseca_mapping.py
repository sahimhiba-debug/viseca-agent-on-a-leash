import pytest

from wallet_control.viseca_mapping import from_viseca_decision, to_viseca_decision


@pytest.mark.parametrize(
    "internal,wire",
    [("allow", "approve"), ("review", "step_up"), ("block", "decline")],
)
def test_mapping_is_a_consistent_round_trip(internal, wire):
    assert to_viseca_decision(internal) == wire
    assert from_viseca_decision(wire) == internal


def test_internal_vocabulary_never_leaks_as_a_wire_value():
    for internal in ("allow", "review", "block"):
        assert to_viseca_decision(internal) not in ("allow", "review", "block")
