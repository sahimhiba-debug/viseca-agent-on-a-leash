# What this wallet does not do

Five limitations, in plain language, with exact scope. Nothing here is hedged; if a
judge finds a sixth, we would rather they find it here first.

---

### 1. Anyone who can reach the customer screen can open another budget

**Scope.** A rolling cap like *"CHF 300 across any seven days"* is enforced **within
one delegation**. Opening a second delegation starts a second allowance. Measured:
twelve self-opened delegations put **CHF 1,296** through a stated CHF 300 / 7 days.

**What we fixed.** The agent used to be able to do this by inventing a session id —
it chose the key that scoped its own budget. That is closed: every id it invents now
lands in one delegation.

**What remains.** The customer endpoint has **no authentication**, so a caller on the
same socket can open a delegation. That is what authentication is for and this demo
does not have it. The total across delegations is now displayed on the delegate
screen, marked *shown, not enforced*.

### 2. We do not know who answered a step-up

**Scope.** When the wallet asks a human and a human answers, we know an answer
arrived. We do not know whose. The protocol carries no identity here and we have not
invented one.

**What is enforced instead.** The answer binds to exactly one purchase, moves no
other, cannot be flipped afterwards, cannot survive revocation, and cannot breach a
rolling window that filled while it was waiting.

### 3. One approval, at most one charge — within one process

**Scope.** Eight concurrent attempts to charge one approval produce exactly one
charge, and a restart cannot consume an authority that was already consumed.

**What remains.** Two processes restoring the **same checkpoint** each hold their own
lock, so each consumes once and the money moves twice. It is **at-most-once per
process**, not exactly-once. Closing it needs a durable shared store this project
does not have.

### 4. We cannot tell that a product is real, or that a seller is telling the truth

**Scope.** Return windows, sizes and finality are claims extracted from merchant
text. Nothing in the API lets the wallet check a catalogue or verify a claim.

**What is enforced instead.** Merchant text can only ever **narrow** a decision,
never widen one. An invented product is bound by exactly the rules a real one obeys —
so a phantom item over the ceiling, in the wrong category, or from the wrong shop is
refused like anything else. Lying about the goods gains the agent nothing.

**What remains.** A plausible lie beats us: *"returns accepted within 90 days"*
satisfies any realistic threshold.

### 5. A patient agent can learn the policy, and we publish the price

**Scope.** Any system that answers yes or no is an oracle. Recovering a hidden
CHF 137 ceiling costs about **twelve probes and CHF 531** in purchases the agent must
keep. That cost is the only thing making it tolerable, and it cannot be removed
without removing the wallet.

**What is enforced instead.** The agent is told the **class** of constraint, never a
number — no amount, no remaining budget, no threshold, no decimal at all. Our own
planner walks *away* from the limit rather than toward it: CHF 7.50 against that
hidden CHF 137, on its first proposal. That is a property of our planner, not of the
interface — a different planner behind the same seam could probe.

---

**Also true, and smaller:** no mandate in the official rule format can cap total
spending or set an end date; your account's monthly limit is real data we display and
do not enforce; the payment step is our own simulation; **no real language model has
been benchmarked** — the adapters exist and no key was available.
