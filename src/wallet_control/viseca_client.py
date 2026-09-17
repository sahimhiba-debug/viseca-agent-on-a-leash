"""HTTP adapter for the hosted Viseca "Agent on a Leash" API.

Implements exactly the endpoint contract in technical_details.md ("All API calls in
one place"). This module owns all knowledge of wire shapes and HTTP mechanics;
`live_worker.py` only calls these methods and never touches `httpx` directly.

Two things worth calling out because they are easy to get wrong and the challenge
brief specifically warns about them:

  * `next_decision_request` returns `None` on HTTP 204, and a 204 does *not* mean
    the run has finished (technical_details.md, step 6) -- callers must keep
    polling and separately check run progress.
  * The bearer key is read from `api_key` and is never written to a log line,
    exception message, or `__repr__` anywhere in this module.

A third thing that matters just as much in practice: a genuine network failure (a
timeout, a dropped connection, a DNS blip -- "what happens if the API disappears
for 30 seconds?") raises an `httpx` transport exception, not an HTTP status code.
`_request` normalizes both kinds of failure into the same `VisecaApiError`, so
`live_worker.py`'s single `except VisecaApiError` handler actually covers every
way a call here can fail, rather than crashing the poll loop on anything that
isn't a 4xx/5xx.
"""

from __future__ import annotations

from typing import Any

import httpx


class VisecaApiError(Exception):
    """Any failure calling the API -- a non-2xx HTTP response OR a network-level
    failure (timeout, connection error, DNS failure, ...). Carries the status code
    (0 for a network-level failure, where there was no response to have a status)
    and the parsed error body or exception message (never the request headers, so
    the bearer key cannot leak into a log via `str(exc)`)."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"Viseca API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    """Parse a response body as JSON, or return `{}` for an empty/204 body.

    technical_details.md does not pin down the exact status code every endpoint
    uses for a body-less success (a `DELETE` returning 204 No Content is
    idiomatic REST and plausible here); blindly calling `.json()` on an empty
    body raises a decode error at exactly the wrong moment -- e.g. a customer's
    mandate revocation would crash instead of succeeding.
    """
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


class VisecaClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._api_key = api_key  # never logged, never included in __repr__
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )

    def __repr__(self) -> str:  # pragma: no cover - defensive against accidental secret leakage
        return f"VisecaClient(base_url={self._client.base_url!r})"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "VisecaClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            # No response was ever received (timeout, connection refused, DNS
            # failure, ...) -- normalize to the same exception type an HTTP error
            # status raises below, so callers have exactly one thing to catch.
            raise VisecaApiError(0, f"network error calling {method} {path}: {exc}") from exc
        if response.status_code >= 400:
            body = _json_or_empty(response) or response.text
            raise VisecaApiError(response.status_code, body)
        return response

    # --- read-only / setup ------------------------------------------------------------
    def healthz(self) -> dict[str, Any]:
        return _json_or_empty(self._request("GET", "/healthz"))

    def bootstrap(self) -> dict[str, Any]:
        return _json_or_empty(self._request("GET", "/v1/bootstrap"))

    def reference_data(self) -> dict[str, Any]:
        return _json_or_empty(self._request("GET", "/v1/reference-data"))

    def authorization_history_csv(self) -> bytes:
        return self._request("GET", "/v1/reference-data/authorization-history.csv").content

    # --- mandate lifecycle --------------------------------------------------------------
    def create_mandate_draft(
        self,
        instruction: str,
        hard_rules: list[dict[str, Any]],
        uncertainty_policy: str,
        guidance: list[str] | None = None,
        open_questions: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "instruction": instruction,
            "hard_rules": hard_rules,
            "uncertainty_policy": uncertainty_policy,
            "guidance": guidance or [],
            "open_questions": open_questions or [],
        }
        return _json_or_empty(self._request("POST", "/v1/mandates", json=payload))

    def confirm_mandate(self, draft_id: str) -> dict[str, Any]:
        return _json_or_empty(self._request("POST", f"/v1/mandates/{draft_id}/confirm", json={"confirmed": True}))

    def get_mandate(self, mandate_id: str) -> dict[str, Any]:
        return _json_or_empty(self._request("GET", f"/v1/mandates/{mandate_id}"))

    def patch_mandate(
        self,
        mandate_id: str,
        *,
        hard_rules: list[dict[str, Any]] | None = None,
        uncertainty_policy: str | None = None,
        guidance: list[str] | None = None,
        open_questions: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if hard_rules is not None:
            payload["hard_rules"] = hard_rules
        if uncertainty_policy is not None:
            payload["uncertainty_policy"] = uncertainty_policy
        if guidance is not None:
            payload["guidance"] = guidance
        if open_questions is not None:
            payload["open_questions"] = open_questions
        return _json_or_empty(self._request("PATCH", f"/v1/mandates/{mandate_id}", json=payload))

    def revoke_mandate(self, mandate_id: str) -> dict[str, Any]:
        return _json_or_empty(self._request("DELETE", f"/v1/mandates/{mandate_id}"))

    # --- scenario runs -----------------------------------------------------------------
    def start_scenario_run(self, scenario_id: str, mandate_id: str) -> dict[str, Any]:
        return _json_or_empty(self._request("POST", "/v1/scenario-runs", json={"scenario_id": scenario_id, "mandate_id": mandate_id}))

    def get_run(self, run_id: str) -> dict[str, Any]:
        return _json_or_empty(self._request("GET", f"/v1/scenario-runs/{run_id}"))

    # --- decision loop -------------------------------------------------------------------
    def next_decision_request(self, wait: int = 25) -> dict[str, Any] | None:
        """Long-poll for the next decision request. Returns the envelope dict on
        HTTP 200, or None on HTTP 204 (no work available right now -- NOT "run
        finished"; the caller must check run progress separately).

        Uses a per-request timeout of `wait + 10` seconds rather than the client's
        general-purpose default: the server is documented to hold this specific
        request open for up to `wait` seconds, so a caller-supplied `wait` at or
        above the client's default timeout would otherwise time out this call
        before the server ever had a chance to respond.
        """
        response = self._request("GET", "/v1/decision-requests/next", params={"wait": wait}, timeout=wait + 10)
        if response.status_code == 204:
            return None
        return _json_or_empty(response)

    def submit_decision(
        self,
        authorization_id: str,
        decision: str,
        *,
        reason_codes: list[str] | None = None,
        customer_message: str | None = None,
        evidence: list[Any] | None = None,
        engine_version: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"authorization_id": authorization_id, "decision": decision}
        if reason_codes is not None:
            payload["reason_codes"] = reason_codes
        if customer_message is not None:
            payload["customer_message"] = customer_message
        if evidence is not None:
            payload["evidence"] = evidence
        if engine_version is not None:
            payload["engine_version"] = engine_version
        return _json_or_empty(self._request("POST", f"/v1/authorizations/{authorization_id}/decision", json=payload))

    def resolve(
        self,
        authorization_id: str,
        decision: str,
        *,
        customer_message: str | None = None,
        evidence: list[Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"decision": decision}
        if customer_message is not None:
            payload["customer_message"] = customer_message
        if evidence is not None:
            payload["evidence"] = evidence
        return _json_or_empty(self._request("POST", f"/v1/authorizations/{authorization_id}/resolve", json=payload))

    def list_authorizations(self) -> dict[str, Any]:
        return _json_or_empty(self._request("GET", "/v1/authorizations"))

    def events(self, since: int = 0) -> dict[str, Any]:
        return _json_or_empty(self._request("GET", "/v1/events", params={"since": since}))

    def team_reset(self) -> dict[str, Any]:
        return _json_or_empty(self._request("POST", "/v1/team/reset"))
