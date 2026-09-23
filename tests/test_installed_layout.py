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


SECRET_NAMES = ("API_KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD",
                "CREDENTIAL", "PRIVATE_KEY", "ACCESS_KEY")


def _baked_secrets(text: str, name: str) -> tuple[list[str], list[str]]:
    """Lines that assign a credential a literal value, and every line examined.

    Returns BOTH, because the count of lines examined is the only thing that
    distinguishes "nothing is baked in" from "nothing was looked at"."""
    baked, examined = [], []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not any(s in line for s in SECRET_NAMES):
            continue
        # `NAME=value` (Dockerfile ENV/ARG) or `NAME: value` (compose YAML).
        for separator in ("=", ":"):
            _, _, value = line.partition(separator)
            if not value.strip():
                continue
            examined.append(f"{name}: {stripped}")
            literal = value.strip().strip('"\'')
            if literal and "${" not in literal and not literal.startswith("$"):
                baked.append(f"{name}: {stripped}")
            break
    return baked, examined


def test_the_dockerfile_and_compose_exist_and_bake_no_secrets():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text()
    compose = (root / "docker-compose.yml").read_text()

    assert "uvicorn" in dockerfile and "8420" in dockerfile
    for path in ("data/", "ui/", "src/"):
        assert f"COPY {path}" in dockerfile, path

    # Keys may be PASSED THROUGH from the environment; none may be baked in.
    baked, examined = _baked_secrets(dockerfile, "Dockerfile")
    more, seen = _baked_secrets(compose, "docker-compose.yml")
    baked += more
    examined += seen

    assert not baked, "a credential appears to be baked into the image:\n  " + "\n  ".join(baked)
    # THE SCAN MUST HAVE SCANNED SOMETHING.
    #
    # The previous version looked for lines containing both "API_KEY" and "=". The
    # Dockerfile bakes nothing and mentions the variables only in a comment, and
    # docker-compose.yml passes them through as YAML -- `ANTHROPIC_API_KEY:
    # "${ANTHROPIC_API_KEY:-}"` -- which has a colon and no equals sign. So the
    # condition was false for every line of both files and the assertion inside it
    # never ran once, measured with `coverage` over a full passing suite. It would
    # have gone equally green over a hard-coded key, which is the only thing it
    # existed to prevent.
    assert len(examined) >= 2, (
        f"this scan examined {len(examined)} credential-bearing lines. It is meant to "
        f"check the two API keys that docker-compose.yml passes through; finding none "
        f"means the pattern no longer matches the file, not that the file is clean.")


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


@pytest.mark.parametrize("line", [
    'ENV ANTHROPIC_API_KEY=sk-ant-abcdef0123456789',
    'ARG APERTUS_API_KEY=live-key-not-a-placeholder',
    '    ANTHROPIC_API_KEY: "sk-ant-hardcoded"',
    'ENV DATABASE_PASSWORD=hunter2',
    'ENV AWS_ACCESS_KEY=AKIAIOSFODNN7EXAMPLE',
])
def test_the_secret_scan_catches_a_baked_key(line):
    """THE NEGATIVE CONTROL THIS CHECK NEVER HAD.

    Its predecessor matched no line of either file, so it passed for the same reason
    an empty scan passes: there was nothing to disagree with. A scan that has never
    been shown to catch anything is a comment with an assert in it."""
    baked, _ = _baked_secrets(line, "synthetic")
    assert baked, f"a baked credential was not detected:\n  {line}"


@pytest.mark.parametrize("line", [
    '    ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY:-}"',
    'ENV APERTUS_API_KEY=${APERTUS_API_KEY}',
    '# No secrets baked in. Model adapters read ANTHROPIC_API_KEY from the environment',
])
def test_the_secret_scan_permits_a_passthrough(line):
    """The other half: a scan that flagged every mention would be turned off within a
    day, and the whole point is that the keys ARE named in these files."""
    baked, _ = _baked_secrets(line, "synthetic")
    assert not baked, f"a legitimate passthrough was flagged:\n  {line}"
