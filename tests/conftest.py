import pytest

from wallet_control.state import HistoryIndex, RunState


@pytest.fixture
def familiar_history() -> HistoryIndex:
    """A card with an approved history at ME_TEST_0001 only."""
    return HistoryIndex({"CA_TEST": frozenset({"ME_TEST_0001"})}, available=True)


@pytest.fixture
def empty_history() -> HistoryIndex:
    """History data is available, but this card has no prior approved purchases."""
    return HistoryIndex({}, available=True)


@pytest.fixture
def unavailable_history() -> HistoryIndex:
    """History data could not be loaded at all -- everything is unknown, not False."""
    return HistoryIndex.empty()


@pytest.fixture
def run_state(familiar_history) -> RunState:
    return RunState(history=familiar_history, card_id="CA_TEST")
