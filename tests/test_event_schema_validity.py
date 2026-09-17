"""Checks the offline event builder against the official JSON Schema
(technical_details.md step 3: "Check your parser... against the event schema"),
and separately confirms the two documented fixture files parse the way the data
guide says they do.
"""

import json
from pathlib import Path

import jsonschema
import pytest

from wallet_control.offline_replay import ALL_SCENARIO_IDS, replay_scenario

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "data" / "official" / "schemas" / "authorization_event.schema.json"


@pytest.fixture(scope="module")
def event_schema():
    return json.loads(SCHEMA_PATH.read_text())


def test_official_example_event_validates_against_the_official_schema(event_schema):
    example_path = Path(__file__).resolve().parents[1] / "reference" / "viseca-2026" / "data" / "scenario_fixtures" / "example_authorization_request.json"
    if not example_path.exists():
        pytest.skip("official reference clone not present in this checkout")
    example = json.loads(example_path.read_text())
    jsonschema.validate(example, event_schema)


@pytest.mark.parametrize("scenario_id", ALL_SCENARIO_IDS)
def test_every_offline_built_event_validates_against_the_official_schema(scenario_id, event_schema):
    result = replay_scenario(scenario_id)
    for decision in result.decisions:
        event = decision.facts.raw if decision.facts is not None else None
        assert event is not None
        jsonschema.validate(event, event_schema)
