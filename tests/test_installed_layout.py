"""The package must work when INSTALLED, not only from a source checkout.

Both the CSV pack and the demo page were resolved as `Path(__file__).parents[2]`,
which is correct in a checkout (`src/wallet_control/..`) and points at a directory
inside the virtualenv once `pip install .` has run. The first Docker image this
project produced therefore failed on import, and would have failed in front of a
judge rather than in front of a test.

Caught by installing into a throwaway venv and running the API from an app root,
before claiming the image worked. These tests keep the resolution honest without
needing a Docker daemon, which is not available in every environment this runs in.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from wallet_control import csv_data
from wallet_control.api import _ui_dir


def test_the_data_pack_is_found_from_a_checkout():
    assert csv_data.DATA_DIR.is_dir(), csv_data.DATA_DIR
    assert (csv_data.DATA_DIR / "items.csv").is_file()


def test_the_page_is_found_from_a_checkout():
    assert _ui_dir().is_dir()
    assert (_ui_dir() / "index.html").is_file()


@pytest.mark.parametrize("variable,resolver", [
    ("WALLET_DATA_DIR", lambda: csv_data._data_dir()),
    ("WALLET_UI_DIR", _ui_dir),
])
def test_a_deployment_can_say_where_it_put_things(variable, resolver, tmp_path, monkeypatch):
    """A container should not have to match the layout of a source checkout."""
    monkeypatch.setenv(variable, str(tmp_path))
    assert resolver() == tmp_path


def test_neither_resolver_reaches_into_site_packages(monkeypatch):
    """The failure mode, stated so it cannot come back: an installed package looking
    two levels up from itself lands inside the virtualenv."""
    monkeypatch.delenv("WALLET_DATA_DIR", raising=False)
    monkeypatch.delenv("WALLET_UI_DIR", raising=False)
    for resolved in (csv_data._data_dir(), _ui_dir()):
        assert "site-packages" not in str(resolved), resolved


def test_the_dockerfile_and_compose_exist_and_bake_no_secrets():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    compose = (root / "docker-compose.yml").read_text()

    assert "uvicorn" in dockerfile and "8420" in dockerfile
    for path in ("data/", "ui/", "src/"):
        assert f"COPY {path}" in dockerfile, path

    # Keys may be PASSED THROUGH from the environment; none may be baked in.
    for text, name in ((dockerfile, "Dockerfile"), (compose, "docker-compose.yml")):
        for line in text.splitlines():
            if "API_KEY" in line and "=" in line:
                assert "${" in line or line.strip().startswith("#"), (
                    f"{name} appears to hard-code a key: {line.strip()}")


def test_the_verify_profile_cannot_pass_without_running_the_suite():
    """A GATE THAT GOES GREEN ON AN EMPTY SUITE.

    `docker compose --profile verify up` is documented as "everything that must be
    true before a demo". The image copied `data/`, `ui/`, `research/` and `scripts/`
    and NOT `tests/`, so the `pytest -q` in that chain collected nothing and exited
    0 -- and the rest of the chain ran and the profile reported success, having
    executed no tests at all.

    Measured: `pytest -q` in a directory with no tests prints "no tests ran" and
    exits **0**, so nothing downstream notices.

    The same shape as a mutation probe printing "41 killed" after examining two: a
    check that reports success without running is worse than no check, because
    everything decided afterwards rests on it. Two fixes, both asserted here -- the
    tests are in the image, and the profile refuses to trust a collection count that
    is implausibly small."""
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    assert "COPY tests/" in dockerfile, (
        "the verify profile runs pytest; without tests/ in the image it collects "
        "nothing and exits 0")

    compose = (root / "docker-compose.yml").read_text()
    assert "--collect-only" in compose and "REFUSING" in compose, (
        "verify must assert that pytest collected a plausible number of tests "
        "before trusting the suite")
    # The guard must come BEFORE the suite it guards.
    assert compose.index("--collect-only") < compose.index("python3 -m pytest -q"), (
        "the collection guard runs after the suite it is supposed to guard")
