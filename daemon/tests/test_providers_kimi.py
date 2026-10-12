"""Kimi provider: GET ${KIMI_CODE_BASE_URL}/usages with the freshest
non-expired access token from ``${KIMI_CODE_HOME:-~/.kimi-code}/credentials/*.json``.
"""

import asyncio
import datetime
import json
from pathlib import Path

import httpx

from daemon.providers import kimi, to_payload

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "kimi_usages.json").read_text())


def _iso_epoch(ts: str) -> float:
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


# 200 minutes before the 5h reset in the fixture.
NOW = _iso_epoch("2026-10-12T08:29:59Z") - 200 * 60
WEEKLY_MINS = int(round((_iso_epoch("2026-10-16T00:00:00Z") - NOW) / 60))


def _run(coro):
    return asyncio.run(coro)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _kimi_home(tmp_path: Path, monkeypatch, creds: dict[str, dict]) -> Path:
    home = tmp_path / "kimi"
    (home / "credentials").mkdir(parents=True)
    for name, blob in creds.items():
        (home / "credentials" / name).write_text(json.dumps(blob))
    monkeypatch.setenv("KIMI_CODE_HOME", str(home))
    monkeypatch.delenv("KIMI_CODE_BASE_URL", raising=False)
    return home


def _cred(token: str, expires_at: float) -> dict:
    return {"access_token": token, "refresh_token": "r", "expires_at": int(expires_at),
            "scope": "kimi-code", "token_type": "Bearer", "expires_in": 1296000}


def test_poll_maps_5h_and_weekly_and_accepts_string_ratio(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _cred("tok-live", NOW + 3600)})
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=FIXTURE)

    res = _run(kimi.poll(client=_client(handler), now=NOW))

    assert seen["url"] == "https://api.kimi.com/coding/v1/usages"
    assert seen["auth"] == "Bearer tok-live"
    assert res.id == "kimi"
    assert res.ok is True
    assert res.bars == [("5h", 3, 200), ("Weekly", 9, WEEKLY_MINS)]
    payload = to_payload(res)
    assert (payload["p"], payload["s"], payload["sr"], payload["w"], payload["wr"]) == (
        "kimi", 3, 200, 9, WEEKLY_MINS)
    assert payload["st"] == "allowed"


def test_poll_prefers_freshest_non_expired_token(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {
        "kimi-code.json": _cred("tok-expired", NOW - 10),
        "kimi-code-env-aaaa.json": _cred("tok-older", NOW + 1000),
        "kimi-code-env-bbbb.json": _cred("tok-newest", NOW + 5000),
    })
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=FIXTURE)

    _run(kimi.poll(client=_client(handler), now=NOW))
    assert seen["auth"] == "Bearer tok-newest"


def test_poll_honors_base_url_override(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _cred("tok", NOW + 3600)})
    monkeypatch.setenv("KIMI_CODE_BASE_URL", "https://example.test/v9/")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=FIXTURE)

    _run(kimi.poll(client=_client(handler), now=NOW))
    assert seen["url"] == "https://example.test/v9/usages"


def test_poll_expired_reset_reports_zero(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _cred("tok", NOW + 10 ** 6)})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=FIXTURE)

    late = _iso_epoch("2026-10-12T08:29:59Z") + 60
    res = _run(kimi.poll(client=_client(handler), now=late))
    assert res.bars[0] == ("5h", 0, 0)
    assert res.bars[1][1] == 9


def test_poll_without_valid_token_is_not_ok_and_makes_no_request(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _cred("tok-expired", NOW - 1)})
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=FIXTURE)

    res = _run(kimi.poll(client=_client(handler), now=NOW))
    assert res.ok is False
    assert calls == []
    assert to_payload(res) == {"p": "kimi", "ok": False}


def test_poll_missing_credentials_dir_is_not_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("KIMI_CODE_HOME", str(tmp_path / "nope"))
    res = _run(kimi.poll(client=_client(lambda r: httpx.Response(200, json=FIXTURE)), now=NOW))
    assert res.ok is False


def test_poll_http_error_is_not_ok(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _cred("tok", NOW + 3600)})

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "expired"})

    assert _run(kimi.poll(client=_client(handler), now=NOW)).ok is False


def test_poll_network_error_is_not_ok(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _cred("tok", NOW + 3600)})

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    assert _run(kimi.poll(client=_client(handler), now=NOW)).ok is False
