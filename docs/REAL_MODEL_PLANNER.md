# Two real language models at the planner seam

**Status: SUPPORTED BY EXPERIMENT** — three runs, eleven episodes, two models. A
sample, not a proof. Until this page, every model number in this repository came
from stubs; the stub results still stand and are not what this page reports.

## What was run

`research/architecture_comparison.py` drives the shopping agent's planner seam
(`opening` / `next_step`) through the eleven episodes of
`research/planning_benchmark.py`. Every basket a planner proposes goes through the
same deterministic wallet (`evaluate_authorization`). **No model decides a payment.**
The model only chooses what to propose.

| model | endpoint | adapter |
| --- | --- | --- |
| Apertus 1.5 70B (`swiss-ai/Apertus-v1.5-70B`) | Swisscom AI Platform, Swiss {ai} Weeks | `apertus_completer` |
| OpenAI `gpt-4.1-mini` | api.openai.com | `openai_completer` |

Settings: temperature 0, 256 output tokens, the prompt `describe()` builds, and the
strict JSON reader `parse()`. Keys come from environment variables and are not stored
anywhere in the repository.

```bash
APERTUS_API_KEY=... OPENAI_API_KEY=... python3 research/architecture_comparison.py
```

## Results (score out of 11, three runs)

| architecture | run 1 | run 2 | run 3 |
| --- | --- | --- | --- |
| deterministic (shipped) | 11 | 11 | 11 |
| Apertus, model only | 8 | 8 | 8 |
| Apertus, hybrid (search repairs) | 9 | 8 | 8 |
| gpt-4.1-mini, model only | 7 | 7 | 7 |
| gpt-4.1-mini, hybrid | 9 | 9 | 10 |

Temperature 0 is not deterministic on either API: the hybrid scores moved by one
point between runs. Quote a range, not a figure.

## What the failures were

A separate run recorded the reason for every failed episode:

* **D, E, H, K: the customer was asked when the benchmark expected an approval.**
  The model proposed a basket the wallet could not approve outright (a
  non-returnable item, the combination that breaks a rule, a basket that misses the
  stated objective), so the wallet put the question to the customer. That is the
  safe direction: a lost convenience, not a lost franc.
* **G: an item that sold out after the first proposal stayed in the basket.** Every
  model arm made this mistake on every run, hybrid included. The hybrid only takes
  over when the model's reply is *unusable*, and a sold-out item is a valid ID. The
  mandate still held: the wallet has no stock information, and the item was within
  the rules. This is a planning error that a real shop would turn into a failed
  order.

**No purchase the mandate forbids was approved, in any arm or any run.** That is
the property the architecture exists for, and here it held against real models as
it did against the stubs. It holds by construction, because the wallet is the same
deterministic engine whoever proposes. So this is a confirmation, not a discovery.

## What this changes, and what it does not

* **Confirms the design decision with real numbers.** A model at this seam adds
  network calls (13 to 17 per benchmark) and loses 1 to 4 episodes against the
  search it would replace. The stub prediction was that "a confidently wrong model
  with a fallback is worse than no model", and episode G is exactly that case,
  observed.
* **Does not show that models are bad at shopping.** Eleven episodes, one prompt
  format, a strict JSON reader, two models. The prompt was not tuned, deliberately:
  tuning it to this benchmark would measure the tuning.
* **Does not put a model in the judged path.** Nothing in `src/wallet_control/`
  imports either adapter. The seam proves the planner is replaceable. The wallet
  stays deterministic whichever planner is plugged in.
