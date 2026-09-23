"""Every place the runtime fills an absence with a value must say why.

`docs/ABSENCE.md` records the same mistake at seven boundaries: something was
missing, and something present was quietly put in its place. Six were found one at a
time; the seventh was PREDICTED by writing the rule down and looking where the
substitution is idiomatic.

The idiom is `x.get(key, default)` and `x.get(key) or fallback`. Both are ordinary,
correct Python almost everywhere. They are dangerous in exactly one situation --
when the default is the permissive branch of a security question -- and that
situation is invisible at the site, which is why the same defect kept coming back
under different names.

So this is a REGISTRY, in the shape the authorship audit already uses. Every site in
`src/wallet_control/` is declared here with the reason its default is safe. A new
one fails this test until somebody writes that sentence. It is not a proof that the
declared ones are right; it is a guarantee that nobody added one without looking.

THREE THINGS MAKE A DEFAULT SAFE, and every entry below is one of them:

  FACT       the absence genuinely IS the fact. A line with no `item_details` is a
             seller who published nothing, which becomes UNKNOWN, not `pass`.
  SENTINEL   the default is a named value that means "absent", not a legal value.
             `_MANDATE_STATUS_ABSENT` is not `"active"`.
  PROJECTION the value is displayed, never decided on.
  GUARDED    the default is unreachable because presence is checked first.
"""

from __future__ import annotations

import ast
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "src" / "wallet_control"

FACT, SENTINEL, PROJECTION, GUARDED = "FACT", "SENTINEL", "PROJECTION", "GUARDED"

# (module, key) -> (kind, why)
DECLARED: dict[tuple[str, str], tuple[str, str]] = {
    ("facts.py", "item_details"): (
        FACT, "A line that publishes no details is a seller who stated nothing. "
              "Empty text yields no return window, no size and no final-sale marker, "
              "and every one of those becomes UNKNOWN rather than pass. This is the "
              "silence channel's own input and it must stay legal -- see silence.py."),
    ("decision_engine.py", "item_details"): (
        FACT, "The same extraction, on the duplicate-detection path. Same reasoning."),
    ("decision_engine.py", "status"): (
        SENTINEL, "`_MANDATE_STATUS_ABSENT` is not a legal mandate status, so a "
                  "missing mandate block cannot read as `active`. Mutation-tested: "
                  "'a missing mandate block reads as active' is killed."),
    ("state.py", "revoked"): (
        GUARDED, "Unreachable. The four execution-lifecycle keys are checked "
                 "all-or-nothing immediately above, so by the time this runs either "
                 "all four are present or none are and there is no authority at all. "
                 "This is the seventh instance in ABSENCE.md and the guard is the fix; "
                 "removing it restores a DOUBLE SPEND."),
    ("state.py", "authorization_id"): (
        PROJECTION, "Only to name the offending decision inside a CheckpointError "
                    "message. The key itself is required a line earlier."),
    ("api.py", "quantity"): (
        FACT, "An omitted quantity is one, which is the schema's own convention; an "
              "explicit null is refused as malformed at the boundary validator. "
              "Quantity is not a field any hard rule reads -- it reaches the decision "
              "only through the amount the agent itself proposed."),
    ("api.py", "purchase_description"): (
        PROJECTION, "Rendered on the customer's own view of a stored decision. It "
                    "reaches no rule: the engine reads merchant text only through "
                    "facts.py's whitelist patterns, and this is not one of them."),
    ("api.py", "item_name"): (
        PROJECTION, "The basket card. Every decision card used to be titled with the "
                    "item the customer REQUESTED rather than the one proposed, which "
                    "concealed eleven substitutions the engine had caught; this reads "
                    "the proposal, and decides nothing."),
    ("api.py", "item_category"): (
        PROJECTION, "The same basket card. The category that DECIDES is read from the "
                    "event by facts.py, where a missing one is not defaulted."),
    ("api.py", "items"): (
        PROJECTION, "The same basket card. An empty basket is a structural failure in "
                    "the engine, refused there, long before anything renders it."),
    ("api.py", "decisions"): (
        PROJECTION, "Scanning finished scenario runs to find one to show a judge. "
                    "An empty list means nothing to show, and decides nothing."),
    ("live_worker.py", "data"): (
        GUARDED, "Probing an under-documented listing shape. Anything unrecognised "
                 "falls through to an empty list, and every record that does not "
                 "carry a recognised decision is skipped rather than assumed."),
    ("live_worker.py", "decision"): (
        GUARDED, "Same listing. A record whose decision is not one of "
                 "approve/decline/step_up is skipped, so no fallback can become a "
                 "decision."),
    ("decision_engine.py", "authorization"): (
        GUARDED, "Inside the unreadable-event refusal, naming the authorization for "
                 "the record it returns. The absence has ALREADY been detected at "
                 "this point -- this is how the refusal labels itself when there is "
                 "no authorization block to label it with, not a fact standing in "
                 "for a missing one."),
    ("decision_engine.py", "authorization_id"): (
        SENTINEL, "Same refusal. An event with no authorization_id is refused, and "
                  "the record of that refusal is stamped '<unreadable>' rather than "
                  "a plausible id -- a sentinel no real id can collide with, so the "
                  "refusal cannot later be mistaken for a decision about a purchase."),
    ("facts.py", "item_name"): (
        PROJECTION, "An item line whose name nobody stated normalizes to the empty "
                    "string, which is what `item.name_contains` then fails to match "
                    "-- the correct answer, since an unnamed thing does not contain "
                    "what you asked for. It is NOT required by "
                    "`_unreadable_event`, on purpose: an unidentifiable item is "
                    "answered proportionally by the catalogue rather than refused."),
    ("live_worker.py", "run_id"): (
        GUARDED, "Same listing, asked whether THIS run decided anything before. A "
                 "record with no run field yields None, and the very next line only "
                 "SKIPS on a run id that is present and different -- so an absent "
                 "run id counts the record, which is the conservative direction: it "
                 "can only make prior spend read as unknown, never as zero."),
}


def _sites(path: Path) -> set[tuple[str, str]]:
    """`x.get("k", default)` and `x.get("k") or fallback`, both of which put a
    present value where an absent one was."""
    found: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) == 2
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)):
            found.add((path.name, node.args[0].value))
        if (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
                and isinstance(node.values[0], ast.Call)
                and isinstance(node.values[0].func, ast.Attribute)
                and node.values[0].func.attr == "get"
                and node.values[0].args
                and isinstance(node.values[0].args[0], ast.Constant)
                and isinstance(node.values[0].args[0].value, str)):
            found.add((path.name, node.values[0].args[0].value))
    return found


def _all_sites() -> set[tuple[str, str]]:
    return {s for path in sorted(RUNTIME.glob("*.py")) for s in _sites(path)}


def test_every_absence_filled_in_the_runtime_is_declared():
    """The gate. A new `.get(key, default)` in the runtime fails here until someone
    writes down why that default is not the permissive branch of a security
    question."""
    undeclared = sorted(_all_sites() - set(DECLARED))
    assert not undeclared, (
        "these fill an absence with a value and are not declared in "
        "tests/security/test_absence_registry.py:\n  "
        + "\n  ".join(f"{module}: .get({key!r}, ...)" for module, key in undeclared)
        + "\n\nSee docs/ABSENCE.md. Either justify it (FACT / SENTINEL / PROJECTION / "
          "GUARDED) or represent the absence instead.")


def test_the_registry_has_no_stale_entries():
    """A declaration for a site that no longer exists is a comment pretending to be a
    check, and it makes the registry look more complete than it is."""
    stale = sorted(set(DECLARED) - _all_sites())
    assert not stale, f"declared but no longer present: {stale}"


def test_every_declaration_gives_a_reason():
    for (module, key), (kind, why) in DECLARED.items():
        assert kind in (FACT, SENTINEL, PROJECTION, GUARDED), (module, key, kind)
        assert len(why) > 60, f"{module}.{key}: the reason is too short to be one"


def test_the_detector_actually_detects():
    """Otherwise an empty registry would pass forever. Both idioms, on a file we
    know contains them."""
    found = _sites(RUNTIME / "state.py")
    assert ("state.py", "revoked") in found
    assert _sites(RUNTIME / "live_worker.py") >= {("live_worker.py", "data"),
                                                  ("live_worker.py", "decision")}
    assert len(_all_sites()) >= 10, "the walk found suspiciously little"
