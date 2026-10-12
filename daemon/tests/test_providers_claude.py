"""Claude provider: GET /api/oauth/usage -> ProviderResult.

The fixture mirrors the live response shape (``limits[]`` with ``session``,
``weekly_all`` and a model-scoped ``weekly_scoped`` item). HTTP is mocked with
``httpx.MockTransport`` so no network is touched.
"""

import asyncio
import datetime
import json
from pathlib import Path

import httpx
import pytest

from daemon.providers import claude, to_payload

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "claude_oauth_usage.json").read_text())


def _iso_epoch(ts: str) -> float:
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


# 110 minutes before the session reset in the fixture.
NOW = _iso_epoch("2026-10-12T08:29:59Z") - 110 * 60


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _run(coro):
    return asyncio.run(coro)


def test_poll_maps_session_weekly_and_scoped_bars():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["beta"] = request.headers.get("anthropic-beta")
        seen["ua"] = request.headers.get("user-agent")
        return httpx.Response(200, json=FIXTURE)

    res = _run(claude.poll("tok-123", client=_client(handler), now=NOW))

    assert seen["url"] == "https://api.anthropic.com/api/oauth/usage"
    assert seen["auth"] == "Bearer tok-123"
    assert seen["beta"] == "oauth-2025-04-20"
    assert seen["ua"] == claude.USER_AGENT
    assert claude.USER_AGENT != "claude-code/2.1.5"  # rejected by newer endpoints

    assert res.id == "claude"
    assert res.ok is True
    assert res.status == "allowed"
    assert res.extra == {"acct": "pro"}
    assert res.bars[0] == ("Current", 17, 110)
    weekly_mins = int(round((_iso_epoch("2026-10-12T20:59:59Z") - NOW) / 60))
    assert res.bars[1] == ("Weekly", 73, weekly_mins)
    assert res.bars[2] == ("Fable", 1, weekly_mins)


def test_poll_payload_carries_f_fr_for_scoped_limit():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=FIXTURE)

    payload = to_payload(_run(claude.poll("tok", client=_client(handler), now=NOW)))
    assert payload["p"] == "claude"
    assert (payload["s"], payload["sr"]) == (17, 110)
    assert payload["w"] == 73
    assert payload["f"] == 1 and payload["fr"] == payload["wr"]
    assert payload["acct"] == "pro"
    assert payload["st"] == "allowed"
    assert payload["ok"] is True


def test_poll_without_model_scope_has_no_third_bar():
    body = {"limits": [item for item in FIXTURE["limits"] if item["kind"] != "weekly_scoped"]}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    res = _run(claude.poll("tok", client=_client(handler), now=NOW))
    assert len(res.bars) == 2
    payload = to_payload(res)
    assert "f" not in payload and "fr" not in payload


def test_poll_scoped_limit_without_model_is_ignored():
    body = json.loads(json.dumps(FIXTURE))
    body["limits"][2]["scope"] = {"model": None, "surface": "desktop"}

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    res = _run(claude.poll("tok", client=_client(handler), now=NOW))
    assert len(res.bars) == 2


def test_poll_expired_reset_reports_zero():
    late = _iso_epoch("2026-10-12T08:29:59Z") + 60  # session window already reset

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=FIXTURE)

    res = _run(claude.poll("tok", client=_client(handler), now=late))
    assert res.bars[0] == ("Current", 0, 0)
    assert res.bars[1][1] == 73  # weekly window still running


def test_poll_status_field_is_surfaced():
    body = json.loads(json.dumps(FIXTURE))
    body["limits"][0]["status"] = "rejected"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    res = _run(claude.poll("tok", client=_client(handler), now=NOW))
    assert res.status == "rejected"


@pytest.mark.parametrize("code", [401, 403])
def test_poll_auth_error_raises_token_expired(code):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(code, json={"error": "unauthorized"})

    with pytest.raises(claude.TokenExpired):
        _run(claude.poll("tok", client=_client(handler), now=NOW))


def test_poll_non_auth_4xx_raises_usage_unavailable():
    """A non-auth 4xx (Enterprise accounts without the usage endpoint) must let
    the caller fall back to the legacy rate-limit header probe."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not found"})

    with pytest.raises(claude.UsageUnavailable):
        _run(claude.poll("tok", client=_client(handler), now=NOW))


def test_poll_network_error_raises_usage_unavailable():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(claude.UsageUnavailable):
        _run(claude.poll("tok", client=_client(handler), now=NOW))


def test_main_module_poll_api_uses_usage_endpoint_and_keeps_fallback(monkeypatch):
    """`poll_api` keeps its signature (tests patch it) but now resolves through
    the provider first and falls back to the header probe on UsageUnavailable."""
    import daemon.claude_usage_daemon as mod

    assert mod.TokenExpired is claude.TokenExpired
    assert mod.API_HEADERS_TEMPLATE["User-Agent"] == claude.USER_AGENT

    async def fake_poll(token, client=None, now=None):
        raise claude.UsageUnavailable("404")

    async def fake_headers(token):
        return {"s": 1, "sr": 2, "w": 0, "wr": 0, "st": "allowed", "acct": "ent", "ok": True}

    monkeypatch.setattr(mod.claude_provider, "poll", fake_poll)
    monkeypatch.setattr(mod, "poll_api_headers", fake_headers)
    monkeypatch.setattr(mod, "CONFIG_FILE", Path("/nonexistent/config"))
    payload = _run(mod.poll_api("tok"))
    assert payload["acct"] == "ent"


@pytest.mark.parametrize("limits", [[], [FIXTURE["limits"][2]]])
def test_poll_without_session_or_weekly_raises_usage_unavailable(limits):
    """A 200 whose ``limits[]`` has neither ``session`` nor ``weekly_all`` (seen
    on Enterprise accounts) is not usable: it must not become 0/0 bars tagged
    ``acct: pro`` but let the caller fall back to the header probe."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"limits": limits})

    with pytest.raises(claude.UsageUnavailable):
        _run(claude.poll("tok", client=_client(handler), now=NOW))


def test_main_module_poll_api_falls_back_on_empty_limits(monkeypatch):
    """End to end through the real provider: ``limits: []`` -> header probe."""
    import daemon.claude_usage_daemon as mod

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"limits": []})

    async def fake_headers(token):
        return {"s": 1, "sr": 2, "w": 0, "wr": 0, "st": "allowed", "acct": "ent", "ok": True}

    # `claude.httpx` is the same module as `httpx` here: build the mock client
    # from the real class before patching it.
    real_client = httpx.AsyncClient
    monkeypatch.setattr(claude.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(mod, "poll_api_headers", fake_headers)
    monkeypatch.setattr(mod, "CONFIG_FILE", Path("/nonexistent/config"))
    payload = _run(mod.poll_api("tok"))
    assert payload["acct"] == "ent"
