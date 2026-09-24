# Authorship

**Six vulnerabilities. Six campaigns. One bug.**

```
python3 scripts/run_authorship_audit.py
```

---

## What we actually found

Over six separate adversarial campaigns this project found six real defects in its
own code. They were fixed one at a time, weeks apart, by different lines of
reasoning. Laid side by side they are indistinguishable:

| the fact | its author | accepted from | what it cost |
| --- | --- | --- | --- |
| the customer's policy | customer | **the agent** | CHF 500 refused → **ALLOWED** at a self-set CHF 900 |
| the scope of the budget | customer | **the agent** | CHF 1,296 against a stated CHF 300 / 7 days |
| when the customer confirmed | wallet | **the caller** | an audit entry attributed to the customer, stamped `1999-01-01` |
| the words shown to the customer | wallet | **the caller** | dead field, one commit from live |
| whether to re-check the window | wallet | **the caller** | omitting an argument skipped the check |
| the customer's confirmed rules | customer | **the platform** | CHF 9,000 at an unknown seller, BLOCK → **ALLOW** |

> **Every one is a fact accepted from a party that is not its author.**

None of the six fixes prevented the next one, because the pattern had no name.

## The abstraction

A delegated-authority system is not primarily about *amounts*, or *permissions*, or
even *rules*. It is about **facts, and who is entitled to write them.**

Every security-relevant fact in such a system has exactly **one rightful author**:

| fact | author | why nobody else may write it |
| --- | --- | --- |
| what I want bought | **customer** | it is their errand |
| what is permitted | **customer** | it is their money |
| what the agent is asking for | **agent** | it is a request, not an instruction |
| what the goods are | **merchant** | and therefore untrusted: it may only *narrow* |
| what happened, and when | **wallet** | it is the only party that observed it |
| what was decided | **wallet** | it is the only authority |
| that a human answered | **human** | and we cannot prove which human |

A system is safe against this entire defect class exactly when **no party can write
a fact it does not author.** Not "is checked for", not "is validated" — *cannot
write*.

## Why this is deeper than the slogan

The previous thesis was *"a limit is a number; intent is a sentence."* That is true
and it is a good demo, but it is a **consequence** rather than the cause. Authorship
explains it, and more:

- **A card limit is a fact the ISSUER authors.** Intent is a fact the CUSTOMER
  authors. That is why one cannot express the other — they have different authors,
  not merely different shapes.
- **Policy vs security separation** is authorship: rules the customer wrote versus
  checks the wallet owns. Composition is well-defined because each verdict is scoped
  to one author.
- **Merchant evidence** is authorship: a merchant authors claims about its own
  goods, so those claims may narrow a decision and never widen one.
- **The agent-facing boundary** is authorship: the agent may read *that* it was
  refused and never *what the rule is*, because it does not author the rule.
- **The oracle** is the irreducible residue: what an agent can *infer* about facts
  it cannot author.

Same idea, six places it was previously six ideas.

## The mechanism

`FIELD_AUTHORS` in `api.py` declares, for every caller-controlled field, who may
write it. `scripts/run_authorship_audit.py` enforces three rules and exits non-zero:

1. **Every caller-controlled field declares an author.** A new one cannot be added
   silently — which is how four of the six arrived.
2. **No agent-authored field is policy-bearing.** The party being judged may say
   what it *wants*; never what the rules are, when it happened, or what it may spend
   against.
3. **No security check is disabled by an omitted argument.** Two of the six were
   optional parameters whose default quietly skipped a check, safe only because one
   caller remembered. Each surviving one is declared with its reason.

## The evidence that it is real

A checker that passes on today's code proves nothing.
`tests/security/test_authorship_audit.py` **reintroduces each historical defect and
asserts the audit rejects it.** All six are caught:

```
CAUGHT   the agent authors the customer's policy
CAUGHT   the caller stamps a customer-attributed time
CAUGHT   the caller writes the wallet's words
CAUGHT   an agent-authored field becomes policy-bearing
CAUGHT   mandate= undeclared on resolve_authorization
CAUGHT   confirmed_rules= undeclared on LiveWorker
```

## What it does not do

- It is **static**. It cannot see a fact that changes author at runtime, and it
  reasons about names rather than about flow. A field called `hint` that carries a
  ceiling would pass rule 2.
- It covers **request models and function defaults**, which is where all six
  instances happened — not every path a fact can take.
- It does not make the *fixes* correct; it makes the *pattern* visible. Each of the
  six still has its own regression test.
- Rule 2 is a **name-matching heuristic**. It would not survive an adversary who
  controls the field name, and it is not meant to: it is aimed at the careless
  commit, not the malicious one.

## The sentence

> **Delegation is not about what an agent may spend.
> It is about which facts it may author.**
