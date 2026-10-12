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


def test_poll_without_valid_token_is_not_ok_and_never_calls_usages(tmp_path, monkeypatch):
    """An expired token triggers exactly one refresh POST (see the refresh
    tests below); when that does not yield a token, /usages is never called."""
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _cred("tok-expired", NOW - 1)})
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=FIXTURE)   # not a token response

    res = _run(kimi.poll(client=_client(handler), now=NOW))
    assert res.ok is False
    assert [(r.method, r.url.path) for r in calls] == [("POST", "/api/oauth/token")]
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


# --- token refresh ---------------------------------------------------------
#
# The Kimi CLI refreshes through ``POST ${oauthHost}/api/oauth/token`` with a
# form body ``client_id``/``grant_type=refresh_token``/``refresh_token`` and
# writes the wire token back to the same credential file (see kimi.py).

TOKEN_URL = "https://auth.kimi.com/api/oauth/token"
REFRESHED = {"access_token": "tok-new", "refresh_token": "r-new", "expires_in": 900,
             "scope": "kimi-code", "token_type": "Bearer"}


def _refresh_cred(token: str, expires_at: float, refresh: str = "r-old") -> dict:
    blob = _cred(token, expires_at)
    blob["refresh_token"] = refresh
    blob["custom_key"] = {"kept": True}   # unknown keys must survive a rewrite
    return blob


def _router(seen: dict, refresh_status: int = 200, refresh_body: dict | None = None):
    """MockTransport handler serving both the refresh POST and the usages GET."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen.setdefault("posts", []).append({
                "url": str(request.url),
                "content_type": request.headers.get("content-type"),
                "body": dict(httpx.QueryParams(request.content.decode())),
            })
            return httpx.Response(refresh_status, json=REFRESHED if refresh_body is None else refresh_body)
        seen.setdefault("gets", []).append(request.headers.get("authorization"))
        return httpx.Response(200, json=FIXTURE)
    return handler


def test_poll_refreshes_expired_token_and_rewrites_file_atomically(tmp_path, monkeypatch):
    home = _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _refresh_cred("tok-old", NOW - 5)})
    path = home / "credentials" / "kimi-code.json"
    path.chmod(0o600)
    seen: dict = {}

    res = _run(kimi.poll(client=_client(_router(seen)), now=NOW))

    assert res.ok is True
    assert seen["posts"] == [{
        "url": TOKEN_URL,
        "content_type": "application/x-www-form-urlencoded",
        "body": {"client_id": kimi.CLIENT_ID, "grant_type": "refresh_token", "refresh_token": "r-old"},
    }]
    assert seen["gets"] == ["Bearer tok-new"]
    blob = json.loads(path.read_text())
    assert blob["access_token"] == "tok-new"
    assert blob["refresh_token"] == "r-new"
    assert blob["expires_at"] == int(NOW) + 900
    assert blob["expires_in"] == 900
    assert blob["scope"] == "kimi-code" and blob["token_type"] == "Bearer"
    assert blob["custom_key"] == {"kept": True}
    assert (path.stat().st_mode & 0o777) == 0o600
    assert sorted(p.name for p in (home / "credentials").iterdir()) == ["kimi-code.json"]  # no .tmp left


def test_poll_refreshes_token_expiring_within_60s(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _refresh_cred("tok-old", NOW + 59)})
    seen: dict = {}
    _run(kimi.poll(client=_client(_router(seen)), now=NOW))
    assert len(seen["posts"]) == 1
    assert seen["gets"] == ["Bearer tok-new"]


def test_poll_skips_refresh_when_token_is_valid(tmp_path, monkeypatch):
    home = _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _refresh_cred("tok-live", NOW + 61)})
    before = (home / "credentials" / "kimi-code.json").read_bytes()
    seen: dict = {}
    res = _run(kimi.poll(client=_client(_router(seen)), now=NOW))
    assert res.ok is True
    assert "posts" not in seen
    assert seen["gets"] == ["Bearer tok-live"]
    assert (home / "credentials" / "kimi-code.json").read_bytes() == before


def test_poll_refreshes_freshest_file_when_all_expired(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {
        "kimi-code.json": _refresh_cred("tok-stale", NOW - 10 ** 6, refresh="r-stale"),
        "kimi-code-env-aaaa.json": _refresh_cred("tok-recent", NOW - 10, refresh="r-recent"),
    })
    seen: dict = {}
    _run(kimi.poll(client=_client(_router(seen)), now=NOW))
    assert [p["body"]["refresh_token"] for p in seen["posts"]] == ["r-recent"]


def test_poll_refresh_http_error_is_not_ok_and_leaves_file_untouched(tmp_path, monkeypatch):
    home = _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _refresh_cred("tok-old", NOW - 5)})
    path = home / "credentials" / "kimi-code.json"
    before = path.read_bytes()
    seen: dict = {}

    res = _run(kimi.poll(client=_client(_router(seen, 401, {"error": "invalid_grant"})), now=NOW))

    assert res.ok is False
    assert "401" in res.extra["reason"]
    assert len(seen["posts"]) == 1          # exactly one attempt, no retry loop
    assert "gets" not in seen
    assert path.read_bytes() == before
    assert to_payload(res) == {"p": "kimi", "ok": False}


def test_poll_refresh_network_error_is_not_ok(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _refresh_cred("tok-old", NOW - 5)})

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    res = _run(kimi.poll(client=_client(handler), now=NOW))
    assert res.ok is False
    assert "refresh" in res.extra["reason"]


def test_poll_refresh_malformed_response_is_not_ok_and_leaves_file_untouched(tmp_path, monkeypatch):
    home = _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _refresh_cred("tok-old", NOW - 5)})
    path = home / "credentials" / "kimi-code.json"
    before = path.read_bytes()
    res = _run(kimi.poll(client=_client(_router({}, 200, {"token_type": "Bearer"})), now=NOW))
    assert res.ok is False
    assert path.read_bytes() == before


def test_poll_without_refresh_token_is_not_ok_and_makes_no_request(tmp_path, monkeypatch):
    blob = _cred("tok-old", NOW - 5)
    del blob["refresh_token"]
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": blob})
    seen: dict = {}
    res = _run(kimi.poll(client=_client(_router(seen)), now=NOW))
    assert res.ok is False
    assert seen == {}


def test_poll_refresh_honors_kimi_token_url_config(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _refresh_cred("tok-old", NOW - 5)})
    monkeypatch.setattr(kimi, "read_config", lambda key: "https://auth.example.test/oauth/token/"
                        if key == "kimi_token_url" else None)
    seen: dict = {}
    _run(kimi.poll(client=_client(_router(seen)), now=NOW))
    assert seen["posts"][0]["url"] == "https://auth.example.test/oauth/token/"


def test_poll_refresh_honors_oauth_host_env(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _refresh_cred("tok-old", NOW - 5)})
    monkeypatch.setenv("KIMI_CODE_OAUTH_HOST", "https://auth.kimi.ai/")
    seen: dict = {}
    _run(kimi.poll(client=_client(_router(seen)), now=NOW))
    assert seen["posts"][0]["url"] == "https://auth.kimi.ai/api/oauth/token"


def test_poll_refresh_refuses_plain_http_token_url(tmp_path, monkeypatch):
    _kimi_home(tmp_path, monkeypatch, {"kimi-code.json": _refresh_cred("tok-old", NOW - 5)})
    monkeypatch.setattr(kimi, "read_config", lambda key: "http://auth.example.test/token")
    seen: dict = {}
    res = _run(kimi.poll(client=_client(_router(seen)), now=NOW))
    assert res.ok is False
    assert seen == {}
