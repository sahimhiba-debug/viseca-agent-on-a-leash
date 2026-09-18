"""Research apparatus. NOT part of the wallet runtime.

Everything here exists to attack, measure or falsify the product. None of it is
reachable from `wallet_control.api` or `wallet_control.live_worker` -- that is
asserted by a test -- and none of it can change a decision.

It lives outside `src/wallet_control` so that the shipped package contains only
code that runs in production. The research is kept because its results are cited
throughout `docs/`, and a claim whose experiment has been deleted is just an
assertion.

  fulfillment      derives "has this job already been done?" from the decision
                   ledger. The project's main architectural finding; deliberately
                   NOT wired into the decision path.
  red_team         17 hand-written adversarial scenarios.
  red_team_corpus  133 generated cases crossing attack primitives with contexts.
  security_object  eight competing models of "the fundamental security object",
                   built to be falsified against each other.
"""
