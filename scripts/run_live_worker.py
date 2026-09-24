#!/usr/bin/env python3
"""Run one scenario against the hosted Viseca API (event day only).

Usage:
    export LEASH_BASE_URL="https://..."
    export TEAM_API_KEY="<your team key>"
    python scripts/run_live_worker.py SCEN0000

Creates and confirms a mandate compiled from the scenario's own
cardholder_instruction, starts the run, and drives the poll/decide/submit loop
until the run has no more pending work. Never prints TEAM_API_KEY.

A step_up is put to whoever is at this terminal, while the worker keeps polling:
approve, decline, or leave it unanswered. Nothing answers on the customer's behalf,
so with no one at the terminal (stdin closed) a step_up waits out its window and
the platform records the timeout.
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import select
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wallet_control.csv_data import history_csv_path, load_scenario_catalogue  # noqa: E402
from wallet_control.live_worker import LiveWorker  # noqa: E402
from wallet_control.policy_compiler import compile_instruction  # noqa: E402
from wallet_control.state import HistoryIndex  # noqa: E402
from wallet_control.viseca_client import VisecaClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("run_live_worker")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario_id")
    parser.add_argument("--wait", type=int, default=25, help="long-poll wait seconds")
    parser.add_argument("--max-idle-polls", type=int, default=6,
                        help="stop after this many empty polls in a row if the run never reports completed")
    parser.add_argument(
        "--acknowledge-unsupported",
        action="store_true",
        help="proceed even though the instruction restricts in ways this wallet cannot enforce",
    )
    args = parser.parse_args()

    base_url = os.environ.get("LEASH_BASE_URL")
    api_key = os.environ.get("TEAM_API_KEY")
    if not base_url or not api_key:
        sys.exit("Set LEASH_BASE_URL and TEAM_API_KEY before running this script.")

    catalogue = load_scenario_catalogue()
    if args.scenario_id not in catalogue:
        sys.exit(f"unknown scenario_id {args.scenario_id!r}; known: {sorted(catalogue)}")
    instruction = catalogue[args.scenario_id]["cardholder_instruction"]

    with VisecaClient(base_url, api_key) as client:
        logger.info("healthz: %s", client.healthz())
        bootstrap = client.bootstrap()
        # technical_details.md documents this call's purpose ("API/data versions,
        # scenarios, timeout values, limits, and enabled features") but not exact
        # field names, so this is logged defensively rather than parsed.
        logger.info("bootstrap: %s", bootstrap)

        compiled = compile_instruction(instruction)
        draft = client.create_mandate_draft(
            instruction,
            [r.as_dict() for r in compiled.hard_rules],
            compiled.uncertainty_policy.value,
            compiled.guidance,
            compiled.open_questions,
        )
        draft_id = draft["draft_id"]
        logger.info("mandate draft created: %s", draft_id)
        logger.info("compiled hard_rules: %s", [r.as_dict() for r in compiled.hard_rules])
        if compiled.open_questions:
            logger.warning("open questions for the customer before confirming: %s", compiled.open_questions)

        # THE GATE. This script used to say "in a real product this pauses for the
        # customer's explicit confirmation" and then confirm anyway, three statements
        # after compiling. An audit found the consequence: an instruction whose
        # restriction the compiler cannot represent produced
        # warning -> automatic confirmation -> unenforced restriction, with no human
        # in the chain and the warning written only to a log.
        #
        # Unsupported restrictive intent now stops this script. `--acknowledge-unsupported`
        # is the operator standing in for the customer, and it requires them to have
        # read the list, because the list is printed here and nowhere else in the flow.
        if compiled.unsupported_restrictions:
            for item in compiled.unsupported_restrictions:
                logger.error("UNSUPPORTED RESTRICTION: %s", item)
            if not args.acknowledge_unsupported:
                sys.exit(
                    f"refusing to confirm {draft_id}: this instruction restricts in "
                    f"{len(compiled.unsupported_restrictions)} way(s) this wallet cannot enforce "
                    "(listed above). A customer must see and accept them. Re-run with "
                    "--acknowledge-unsupported to proceed on their behalf."
                )
            logger.warning(
                "proceeding with %d unenforceable restriction(s) on the operator's acknowledgement",
                len(compiled.unsupported_restrictions),
            )

        confirmed = client.confirm_mandate(draft_id)
        mandate_id = confirmed["mandate_id"]
        logger.info("mandate confirmed: %s", mandate_id)

        run = client.start_scenario_run(args.scenario_id, mandate_id)
        run_id = run["run_id"]
        logger.info("run started: %s", run_id)

        history = HistoryIndex.from_csv(history_csv_path())
        questions: "queue.Queue[tuple]" = queue.Queue()
        worker = LiveWorker(
            client,
            history,
            # What the customer confirmed, so the platform's echo of it in the run's
            # first event is CHECKED rather than adopted. Without this the echo simply
            # becomes the policy -- an audit widened it and turned a CHF 9,000 purchase
            # at an unknown seller from BLOCK into ALLOW for the whole run.
            confirmed_rules=compiled.hard_rules,
            confirmed_uncertainty_policy=compiled.uncertainty_policy,
            on_step_up=lambda run, result, event: questions.put((time.monotonic(), run, result, event)),
        )
        # The worker auto-registers the run from the first event's own `mandate`
        # block (see live_worker.py) since customer_id/card_id/profile_id are only
        # known once the platform assigns them here.

        step_up_seconds = float((bootstrap.get("limits") or {}).get("step_up_timeout_seconds") or 120)

        def poll() -> None:
            processed = 0
            idle_polls = 0
            while True:
                n = worker.run_forever(wait_seconds=args.wait, max_polls=1)
                processed += n
                if n:
                    idle_polls = 0
                    continue
                idle_polls += 1
                status = client.get_run(run_id)
                logger.info("no work this poll; run status: %s", status)
                if status.get("status") == "completed":
                    logger.info("run %s completed. processed=%d", run_id, processed)
                    return
                if idle_polls >= args.max_idle_polls:
                    logger.info("no work after %d consecutive polls; stopping. processed=%d", idle_polls, processed)
                    return

        poller = threading.Thread(target=poll, name="poll", daemon=True)
        poller.start()
        while poller.is_alive() or not questions.empty():
            try:
                asked_at, run, result, event = questions.get(timeout=1.0)
            except queue.Empty:
                continue
            # The window runs from when the platform took the step_up, not from when
            # the previous question at this terminal was answered.
            _ask_customer(worker, run, result, event, asked_at + step_up_seconds)


def _ask_customer(worker: LiveWorker, run_id: str, result, event: dict, deadline: float) -> None:
    """Put one step_up to the person at the terminal. Silence is not an answer."""
    auth = event["authorization"]
    lines = "\n".join(f"      - {i.get('quantity')} x {i.get('item_name')} ({i.get('unit_price')} {i.get('currency')})"
                      for i in auth.get("items") or [])
    reasons = "\n".join(f"      - {r}" for r in result.plain_reasons) or f"      - {result.customer_message}"
    print(f"""
=== The wallet is asking you: {result.authorization_id} ===
    {auth['merchant']['merchant_name']}, {auth['billing_amount_chf']} CHF
{lines}
    Why it is asking:
{reasons}
Approve? [a]pprove / [d]ecline / Enter = no answer  ({max(0, int(deadline - time.monotonic()))} s left)""", flush=True)
    answer = ""
    while time.monotonic() < deadline:
        ready, _, _ = select.select([sys.stdin], [], [], max(0.0, deadline - time.monotonic()))
        if not ready:
            break
        line = sys.stdin.readline()
        if not line:  # stdin closed: no one is there to answer
            break
        answer = line.strip().lower()[:1]
        if answer in ("a", "d", ""):
            break
        print("    a, d, or Enter", flush=True)
    if answer not in ("a", "d"):
        logger.warning("%s: no answer from the customer; left to the platform's step_up timeout", result.authorization_id)
        return
    decision = "allow" if answer == "a" else "block"
    try:
        worker.resolve(run_id, result.authorization_id, decision)
        logger.info("%s: the customer answered %s", result.authorization_id, "approve" if answer == "a" else "decline")
    except Exception as exc:  # noqa: BLE001 -- a failed resolve is reported, never retried as a different answer
        logger.error("%s: could not record the customer's answer: %s", result.authorization_id, exc)


if __name__ == "__main__":
    main()
