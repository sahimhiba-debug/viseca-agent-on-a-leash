"""Who may write which fact.

Six vulnerabilities in this project were one bug: a fact was accepted from a party
that is not its author. This module holds the rule that makes the pattern visible,
so that `scripts/run_authorship_audit.py` and the live demo endpoint both check the
SAME thing rather than two things that agree today.

Nothing here decides anything about money. It decides what may be *written*, which
is a different and earlier question.
"""

from __future__ import annotations

from dataclasses import dataclass

# The parties. `agent` is the one being judged, and is therefore the interesting
# one: whatever it may author, it may author about ITSELF and never about the rules
# it is judged by.
AUTHORS = ("customer", "agent", "merchant", "wallet", "platform", "human")

# Facts the wallet reasons WITH. A field whose name carries one of these is
# policy-bearing, and no agent-authored field may be.
POLICY_BEARING = frozenset({
    "instruction", "hard_rules", "uncertainty_policy", "confirmed_at",
    "confirmed_rules", "customer_message", "mandate", "policy", "policy_version",
    "spend", "budget", "window", "period_days", "scope", "limit", "ceiling",
    "allowance", "verdict", "rule", "threshold",
    # Added after the live endpoint accepted an agent-authored `max_amount`, which
    # is the original defect under a different name. The heuristic is only as good
    # as this list, which is precisely why it is a heuristic and is documented as
    # one in AUTHORSHIP.md.
    "amount", "max", "min", "cap", "chf", "currency", "per_order", "total",
    "approve", "allow", "permit", "authoris", "authoriz", "override", "exempt",
})


@dataclass(frozen=True)
class Violation:
    rule: str
    subject: str
    detail: str

    def as_dict(self) -> dict:
        return {"rule": self.rule, "subject": self.subject, "detail": self.detail}


def check_field(model: str, field: str, author: str | None) -> list[Violation]:
    """The two rules that govern one caller-controlled field.

    Split out so a UI can ask "what if someone added THIS field?" and get the real
    answer from the real rule, rather than a description of it.
    """
    problems: list[Violation] = []

    # A name has to be a name. Not a security property -- this check is advisory --
    # but an empty or 5,000-character field sailing through makes the tool look like
    # it is not reading its input, which costs more than the check does.
    field = (field or "").strip()
    if not field or len(field) > 64:
        problems.append(Violation(
            "a field has a name", f"{model}.{field[:24]}",
            "a field name must be 1-64 characters"))
        return problems

    if author is None:
        problems.append(Violation(
            "every field declares an author", f"{model}.{field}",
            "caller-controlled and declares no author. Four of the six historical "
            "defects arrived exactly this way: a field added without anyone asking "
            "who is entitled to write it."))
        return problems

    if author not in AUTHORS:
        problems.append(Violation(
            "authors are a closed set", f"{model}.{field}",
            f"{author!r} is not one of {AUTHORS}"))

    if author == "agent":
        for word in sorted(POLICY_BEARING):
            if word in field.lower():
                problems.append(Violation(
                    "no agent-authored field is policy-bearing", f"{model}.{field}",
                    f"authored by the AGENT and matches the policy-bearing name "
                    f"{word!r}. The party being judged would be writing what it is "
                    "judged by -- which is how a CHF 500 basket became ALLOWED "
                    "under a self-set CHF 900 ceiling."))
                break

    return problems


def check_registry(registry: dict[tuple[str, str], str],
                   declared_models: dict[str, tuple[str, ...]]) -> list[Violation]:
    """Every field of every model, and every registry entry that no longer exists."""
    problems: list[Violation] = []
    for model, fields in declared_models.items():
        for field in fields:
            problems.extend(check_field(model, field, registry.get((model, field))))
    for (model, field) in registry:
        if field not in declared_models.get(model, ()):
            problems.append(Violation(
                "the registry describes what exists", f"{model}.{field}",
                "declared here but no longer a field; a stale entry hides a real one"))
    return problems
