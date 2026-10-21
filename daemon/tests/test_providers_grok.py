"""Grok provider: GET ${GROK_CLI_CHAT_PROXY_BASE_URL}/billing?format=credits
with the ``key`` from ``${GROK_HOME:-~/.grok}/auth.json``, falling back to the
newest "billing: fetched credits config" line in ``logs/unified.jsonl``.
"""

import asyncio
import datetime
import json
import shutil
from pathlib import Path

import httpx

from daemon.providers import detect, grok, to_payload

FIXTURES = Path(__file__).parent / "fixtures"
BILLING = json.loads((FIXTURES / "grok_billing.json").read_text())
PERIOD_END = "2026-10-27T05:00:00+00:00"   # same end in both fixtures

SECRET = "xai-test-access-key-123"
REFRESH = "xai-test-refresh-token-456"


def _iso_epoch(ts: str) -> float:
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


# 3000 minutes before the weekly period ends.
NOW = _iso_epoch(PERIOD_END) - 3000 * 60


def _run(coro):
    return asyncio.run(coro)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _grok_home(tmp_path: Path, monkeypatch, *, key: str | None = SECRET, expires_at: float | None = NOW + 3600,
               log: bool = False, version: str | None = "9.9.9") -> Path:
    home = tmp_path / "grok"
    home.mkdir()
    if key is not None:
        entry = {"auth_mode": "oidc", "key": key, "refresh_token": REFRESH, "email": "user@example.test"}
        if expires_at is not None:
            entry["expires_at"] = _iso(expires_at)
        (home / "auth.json").write_text(json.dumps({"https://auth.x.ai::0000-fake": entry}))
    if version is not None:
        (home / "version.json").write_text(json.dumps({"version": version, "stable_version": version}))
    if log:
        (home / "logs").mkdir()
        shutil.copy(FIXTURES / "grok_unified.jsonl", home / "logs" / "unified.jsonl")
    monkeypatch.setenv("GROK_HOME", str(home))
    monkeypatch.delenv("GROK_CLI_CHAT_PROXY_BASE_URL", raising=False)
    return home


def _ok_handler(seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=BILLING)
    return handler


def _fail_if_called(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected request to {request.url}")


def test_poll_maps_credit_percent_and_period_end_to_weekly_payload(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch)
    res = _run(grok.poll(client=_client(_ok_handler([])), now=NOW))
    assert res.ok is True and res.id == "grok"
    assert res.bars == [("Weekly", 37, 3000)]
    assert to_payload(res) == {"p": "grok", "w": 37, "wr": 3000, "st": "allowed", "ok": True}


def test_request_hits_billing_credits_with_bearer_and_grok_headers(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch)
    seen: list[httpx.Request] = []
    _run(grok.poll(client=_client(_ok_handler(seen)), now=NOW))
    assert len(seen) == 1
    req = seen[0]
    assert req.method == "GET"
    assert str(req.url) == "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
    assert req.headers["authorization"] == f"Bearer {SECRET}"
    assert req.headers["x-grok-client-version"] == "9.9.9"
    assert req.headers["x-grok-client-mode"] == "cli"
    assert req.headers["accept"] == "application/json"


def test_client_version_defaults_when_version_json_is_missing(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, version=None)
    seen: list[httpx.Request] = []
    _run(grok.poll(client=_client(_ok_handler(seen)), now=NOW))
    assert seen[0].headers["x-grok-client-version"] == grok.DEFAULT_CLIENT_VERSION


def test_base_url_override(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch)
    monkeypatch.setenv("GROK_CLI_CHAT_PROXY_BASE_URL", "https://example.test/v9/")
    seen: list[httpx.Request] = []
    _run(grok.poll(client=_client(_ok_handler(seen)), now=NOW))
    assert str(seen[0].url) == "https://example.test/v9/billing?format=credits"


def test_expired_token_skips_network_and_uses_log_fallback(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1, log=True)
    res = _run(grok.poll(client=_client(_fail_if_called), now=NOW))
    assert to_payload(res) == {"p": "grok", "w": 22, "wr": 3000, "st": "allowed", "ok": True}


def test_http_error_falls_back_to_log(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, log=True)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    res = _run(grok.poll(client=_client(handler), now=NOW))
    assert to_payload(res) == {"p": "grok", "w": 22, "wr": 3000, "st": "allowed", "ok": True}


def test_network_error_and_malformed_body_fall_back_to_log(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, log=True)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    assert _run(grok.poll(client=_client(boom), now=NOW)).bars == [("Weekly", 22, 3000)]

    def garbage(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": True})

    assert _run(grok.poll(client=_client(garbage), now=NOW)).bars == [("Weekly", 22, 3000)]


def test_newest_matching_log_line_wins(tmp_path, monkeypatch):
    """The fixture holds an older 11 % line, unrelated and malformed lines, and
    a newer 22 % line followed by an unrelated one; the 22 % line wins."""
    home = _grok_home(tmp_path, monkeypatch, key=None, log=True)
    config = grok.latest_log_config(home)
    assert config["creditUsagePercent"] == 22.0
    assert config["currentPeriod"]["end"] == PERIOD_END


def test_log_fallback_finds_the_last_match_across_read_blocks(tmp_path, monkeypatch):
    """A large log is read from the end in blocks; a match far from the end and
    lines that straddle block boundaries are still parsed correctly."""
    home = _grok_home(tmp_path, monkeypatch, key=None, log=True)
    log_path = home / "logs" / "unified.jsonl"
    filler = json.dumps({"msg": "noise", "ctx": {"pad": "x" * 997}}) + "\n"
    with log_path.open("a") as fh:
        fh.write(filler * 300)
    res = _run(grok.poll(client=_client(_fail_if_called), now=NOW))
    assert res.bars == [("Weekly", 22, 3000)]


def test_past_period_end_reads_zero(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, expires_at=NOW + 10 ** 7)
    late = _iso_epoch(PERIOD_END) + 60
    res = _run(grok.poll(client=_client(_ok_handler([])), now=late))
    assert to_payload(res) == {"p": "grok", "w": 0, "wr": 0, "st": "allowed", "ok": True}


def test_no_source_is_not_ok(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, key=None)
    res = _run(grok.poll(client=_client(_fail_if_called), now=NOW))
    assert res.ok is False
    assert to_payload(res) == {"p": "grok", "ok": False}


def test_endpoint_failure_without_log_is_not_ok(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    res = _run(grok.poll(client=_client(handler), now=NOW))
    assert to_payload(res) == {"p": "grok", "ok": False}
    assert SECRET not in json.dumps(res.extra)


def test_freshest_entry_with_a_key_is_used(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch)
    (home / "auth.json").write_text(json.dumps({
        "https://auth.x.ai::a": {"key": "tok-older", "expires_at": _iso(NOW + 100)},
        "https://auth.x.ai::b": {"key": "", "expires_at": _iso(NOW + 9000)},
        "https://auth.x.ai::c": {"key": "tok-newest", "expires_at": _iso(NOW + 5000)},
    }))
    seen: list[httpx.Request] = []
    _run(grok.poll(client=_client(_ok_handler(seen)), now=NOW))
    assert seen[0].headers["authorization"] == "Bearer tok-newest"


def test_refresh_token_is_never_sent_and_auth_json_is_untouched(tmp_path, monkeypatch):
    for expires_at in (NOW + 3600, NOW - 1):   # live token, then expired token
        case = tmp_path / str(int(expires_at))
        case.mkdir()
        home = _grok_home(case, monkeypatch, expires_at=expires_at, log=True)
        before = (home / "auth.json").read_bytes()
        seen: list[httpx.Request] = []
        _run(grok.poll(client=_client(_ok_handler(seen)), now=NOW))
        for req in seen:
            blob = str(req.url) + json.dumps(dict(req.headers)) + req.content.decode(errors="replace")
            assert REFRESH not in blob
            assert "auth.x.ai" not in str(req.url)
        assert (home / "auth.json").read_bytes() == before
        assert sorted(p.name for p in home.iterdir()) == ["auth.json", "logs", "version.json"]


def test_detect_available_with_a_key_and_never_shows_it(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, expires_at=NOW - 10 ** 6)   # expired is fine: log fallback
    res = detect("grok")
    assert res.available is True
    assert SECRET not in res.reason and REFRESH not in res.reason
    assert "auth.json" in res.reason


def test_detect_unavailable_without_auth_or_key(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, key=None)
    res = detect("grok")
    assert res.available is False and "grok login" in res.reason

    (home / "auth.json").write_text(json.dumps({"https://auth.x.ai::x": {"key": "", "refresh_token": REFRESH}}))
    res = detect("grok")
    assert res.available is False and "grok login" in res.reason
    assert REFRESH not in res.reason

    (home / "auth.json").write_text("{not json")
    assert detect("grok").available is False
