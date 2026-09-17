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
"""

from __future__ import annotations

from typing import Any

import httpx


class VisecaApiError(Exception):
    """A non-2xx response from the API. Carries the status code and parsed error
    body (never the request headers, so the bearer key cannot leak into a log
    via `str(exc)`)."""

    def __init__(self, status_code: int, body: Any) -> None:
        super().__init__(f"Viseca API error {status_code}: {body}")
        self.status_code = status_code
        self.body = body


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
        response = self._client.request(method, path, **kwargs)
        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = response.text
            raise VisecaApiError(response.status_code, body)
        return response

    # --- read-only / setup ------------------------------------------------------------
    def healthz(self) -> dict[str, Any]:
        return httpx.get(f"{self._client.base_url}/healthz", timeout=self._client.timeout).json()

    def bootstrap(self) -> dict[str, Any]:
        return self._request("GET", "/v1/bootstrap").json()

    def reference_data(self) -> dict[str, Any]:
        return self._request("GET", "/v1/reference-data").json()

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
        return self._request("POST", "/v1/mandates", json=payload).json()

    def confirm_mandate(self, draft_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v1/mandates/{draft_id}/confirm", json={"confirmed": True}).json()

    def get_mandate(self, mandate_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/mandates/{mandate_id}").json()

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
        return self._request("PATCH", f"/v1/mandates/{mandate_id}", json=payload).json()

    def revoke_mandate(self, mandate_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v1/mandates/{mandate_id}").json()

    # --- scenario runs -----------------------------------------------------------------
    def start_scenario_run(self, scenario_id: str, mandate_id: str) -> dict[str, Any]:
        return self._request("POST", "/v1/scenario-runs", json={"scenario_id": scenario_id, "mandate_id": mandate_id}).json()

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v1/scenario-runs/{run_id}").json()

    # --- decision loop -------------------------------------------------------------------
    def next_decision_request(self, wait: int = 25) -> dict[str, Any] | None:
        """Long-poll for the next decision request. Returns the envelope dict on
        HTTP 200, or None on HTTP 204 (no work available right now -- NOT "run
        finished"; the caller must check run progress separately)."""
        response = self._request("GET", "/v1/decision-requests/next", params={"wait": wait})
        if response.status_code == 204:
            return None
        return response.json()

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
        return self._request("POST", f"/v1/authorizations/{authorization_id}/decision", json=payload).json()

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
        return self._request("POST", f"/v1/authorizations/{authorization_id}/resolve", json=payload).json()

    def list_authorizations(self) -> dict[str, Any]:
        return self._request("GET", "/v1/authorizations").json()

    def events(self, since: int = 0) -> dict[str, Any]:
        return self._request("GET", "/v1/events", params={"since": since}).json()

    def team_reset(self) -> dict[str, Any]:
        return self._request("POST", "/v1/team/reset").json()
