"""Phase 17: "What happens if the API disappears for 30 seconds?" -- a network-level
failure must surface the same way an HTTP error status does, and a plausible-but-
undocumented 204/empty response must not crash a caller.
"""

from unittest.mock import patch

import httpx
import pytest

from wallet_control.viseca_client import VisecaApiError, VisecaClient


def _client():
    return VisecaClient("https://example.invalid", "test-key")


def test_network_level_failure_is_normalized_to_viseca_api_error():
    client = _client()
    with patch.object(client._client, "request", side_effect=httpx.ConnectTimeout("timed out")):
        with pytest.raises(VisecaApiError) as exc_info:
            client.bootstrap()
    assert exc_info.value.status_code == 0
    assert "test-key" not in str(exc_info.value)  # the bearer key must never leak into the exception


def test_dns_or_connection_failure_is_also_normalized():
    client = _client()
    with patch.object(client._client, "request", side_effect=httpx.ConnectError("connection refused")):
        with pytest.raises(VisecaApiError):
            client.healthz()


def test_http_error_status_is_still_a_viseca_api_error_with_the_real_status_code():
    client = _client()
    response = httpx.Response(503, json={"error": "unavailable"}, request=httpx.Request("GET", "https://example.invalid/v1/bootstrap"))
    with patch.object(client._client, "request", return_value=response):
        with pytest.raises(VisecaApiError) as exc_info:
            client.bootstrap()
    assert exc_info.value.status_code == 503


def test_a_204_response_does_not_crash_json_parsing():
    """revoke_mandate and similar calls must not assume every success has a JSON
    body -- a 204 No Content is a plausible, idiomatic response the contract does
    not explicitly rule out."""
    client = _client()
    response = httpx.Response(204, request=httpx.Request("DELETE", "https://example.invalid/v1/mandates/TM1"))
    with patch.object(client._client, "request", return_value=response):
        result = client.revoke_mandate("TM1")
    assert result == {}


def test_repr_never_exposes_the_api_key():
    client = _client()
    assert "test-key" not in repr(client)


def test_next_decision_request_uses_a_timeout_larger_than_the_long_poll_wait():
    """A `wait=25` long-poll held server-side for 25s must not be cut short by a
    client-side timeout shorter than that."""
    client = _client()
    captured = {}

    def fake_request(method, path, **kwargs):
        captured.update(kwargs)
        return httpx.Response(204, request=httpx.Request(method, f"https://example.invalid{path}"))

    with patch.object(client._client, "request", side_effect=fake_request):
        client.next_decision_request(wait=25)
    assert captured["timeout"] > 25
