"""Grok provider: GET ${GROK_CLI_CHAT_PROXY_BASE_URL}/billing?format=credits
with the ``key`` from ``${GROK_HOME:-~/.grok}/auth.json`` (refreshed with
Grok's own OIDC protocol when it expires), falling back to the newest
"billing: fetched credits config" line in ``logs/unified.jsonl`` when that line
is newer than 6 h.
"""

import asyncio
import datetime
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from daemon.providers import detect, grok, to_payload

FIXTURES = Path(__file__).parent / "fixtures"
BILLING = json.loads((FIXTURES / "grok_billing.json").read_text())
PERIOD_END = "2026-10-27T05:00:00+00:00"   # same end in both fixtures
LOG_22_TS = "2026-10-25T01:00:01.000Z"     # newest billing line in the log fixture

SECRET = "xai-test-access-key-123"
REFRESH = "xai-test-refresh-token-456"
NEW_KEY = "xai-test-new-access-key-789"
NEW_REFRESH = "xai-test-new-refresh-token-012"
CLIENT_ID = "test-client-id-0000"
ISSUER = "https://auth.x.ai"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
TOKEN_URL = f"{ISSUER}/oauth2/token"
BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
ENTRY = "https://auth.x.ai::0000-fake"
OTHER_ENTRY = "https://auth.x.ai::1111-other"


def _iso_epoch(ts: str) -> float:
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


# 3000 minutes before the weekly period ends (2 h after the newest log line).
NOW = _iso_epoch(PERIOD_END) - 3000 * 60


def _run(coro):
    return asyncio.run(coro)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _grok_iso(epoch: float) -> str:
    """The format Grok writes ``expires_at`` in: UTC, microseconds, ``Z``."""
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@pytest.fixture(autouse=True)
def _fresh_module_state(monkeypatch):
    """Per-test module state: empty discovery cache, no logged state, no
    remembered dead refresh token, no daemon config; log lines are captured."""
    monkeypatch.setattr(grok, "_token_endpoints", {})
    monkeypatch.setattr(grok, "_live_state", "")
    monkeypatch.setattr(grok, "_warned", set())
    monkeypatch.setattr(grok, "_dead_refresh_tokens", set())
    monkeypatch.setattr(grok, "_used_refresh_tokens", set(), raising=False)
    monkeypatch.setattr(grok, "_unsaved_entries", {}, raising=False)
    monkeypatch.setattr(grok, "_refresh_backoff_until", 0.0, raising=False)
    monkeypatch.setattr(grok, "read_config", lambda key: None)
    lines: list[str] = []
    monkeypatch.setattr(grok, "log", lines.append)
    return lines


@pytest.fixture
def logged(_fresh_module_state):
    return _fresh_module_state


def _entry(key: str, expires_at: float | None, refresh: str = REFRESH) -> dict:
    entry = {"key": key, "auth_mode": "oidc", "create_time": "2026-10-01T00:00:00.000000Z",
             "user_id": "user-0000", "email": "user@example.com", "first_name": "Test",
             "principal_type": "user", "coding_data_retention_opt_out": False,
             "refresh_token": refresh}
    if expires_at is not None:
        entry["expires_at"] = _grok_iso(expires_at)
    entry["oidc_issuer"] = ISSUER
    entry["oidc_client_id"] = CLIENT_ID
    return entry


def _write_auth(home: Path, blob: dict) -> None:
    (home / "auth.json").write_text(json.dumps(blob, indent=2))
    os.chmod(home / "auth.json", 0o600)


def _grok_home(tmp_path: Path, monkeypatch, *, key: str | None = SECRET, expires_at: float | None = NOW + 3600,
               log: bool = False, version: str | None = "9.9.9", other: bool = False) -> Path:
    home = tmp_path / "grok"
    home.mkdir()
    if key is not None:
        blob = {ENTRY: _entry(key, expires_at)}
        if other:   # an older second account that must survive a rewrite untouched
            blob[OTHER_ENTRY] = _entry("tok-other", NOW - 10 ** 6, refresh="refresh-other")
        _write_auth(home, blob)
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


def _oidc_handler(seen: list, *, token_status: int = 200, token_body: dict | None = None,
                  token_endpoint: str = TOKEN_URL, billing_status: int = 200):
    """Discovery, token endpoint and billing endpoint in one mock transport."""
    if token_body is None:
        token_body = {"access_token": NEW_KEY, "refresh_token": NEW_REFRESH, "expires_in": 43200,
                      "token_type": "Bearer"}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        if url == DISCOVERY_URL:
            return httpx.Response(200, json={"issuer": ISSUER, "token_endpoint": token_endpoint,
                                             "grant_types_supported": ["authorization_code", "refresh_token"]})
        if request.method == "POST":
            return httpx.Response(token_status, json=token_body)
        if url == BILLING_URL:
            return httpx.Response(billing_status, json=BILLING)
        raise AssertionError(f"unexpected request to {url}")
    return handler


def _no_secret(*texts: str) -> None:
    for text in texts:
        for secret in (SECRET, REFRESH, NEW_KEY, NEW_REFRESH):
            assert secret not in text


# --- live endpoint ----------------------------------------------------------

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
    assert str(req.url) == BILLING_URL
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


def test_non_https_base_override_is_ignored_and_logged_once(tmp_path, monkeypatch, logged):
    _grok_home(tmp_path, monkeypatch)
    monkeypatch.setenv("GROK_CLI_CHAT_PROXY_BASE_URL", "http://example.test/v9")
    seen: list[httpx.Request] = []
    for _ in range(2):
        res = _run(grok.poll(client=_client(_ok_handler(seen)), now=NOW))
        assert res.ok is True
    assert [str(r.url) for r in seen] == [BILLING_URL, BILLING_URL]
    warnings = [line for line in logged if "GROK_CLI_CHAT_PROXY_BASE_URL" in line]
    assert len(warnings) == 1 and "https" in warnings[0]


def test_still_valid_token_makes_no_refresh_traffic(tmp_path, monkeypatch):
    """A token valid beyond the 300 s margin goes straight to billing: no
    discovery, no token request, no lock file, auth.json byte-identical."""
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW + grok.REFRESH_MARGIN_S + 1, log=True)
    before = (home / "auth.json").read_bytes()
    seen: list[httpx.Request] = []
    res = _run(grok.poll(client=_client(_ok_handler(seen)), now=NOW))
    assert res.bars == [("Weekly", 37, 3000)]
    assert [str(r.url) for r in seen] == [BILLING_URL]
    assert (home / "auth.json").read_bytes() == before
    assert sorted(p.name for p in home.iterdir()) == ["auth.json", "logs", "version.json"]


# --- token refresh (S3.2) -----------------------------------------------------

@pytest.mark.parametrize("expires_at", [NOW - 1, NOW + 299], ids=["expired", "within-300s"])
def test_expiring_token_is_refreshed_and_written_back(tmp_path, monkeypatch, logged, expires_at):
    home = _grok_home(tmp_path, monkeypatch, expires_at=expires_at, other=True)
    before = json.loads((home / "auth.json").read_text())
    seen: list[httpx.Request] = []
    res = _run(grok.poll(client=_client(_oidc_handler(seen)), now=NOW))

    assert res.ok is True and res.bars == [("Weekly", 37, 3000)]
    assert [(r.method, str(r.url)) for r in seen] == [
        ("GET", DISCOVERY_URL), ("POST", TOKEN_URL), ("GET", BILLING_URL)]
    form = parse_qs(seen[1].content.decode())
    assert form == {"grant_type": ["refresh_token"], "refresh_token": [REFRESH], "client_id": [CLIENT_ID]}
    assert seen[1].headers["content-type"] == "application/x-www-form-urlencoded"
    assert seen[2].headers["authorization"] == f"Bearer {NEW_KEY}"

    raw = (home / "auth.json").read_text()
    after = json.loads(raw)
    assert list(after) == list(before)                       # entry order kept
    assert after[OTHER_ENTRY] == before[OTHER_ENTRY]         # other account untouched
    new = after[ENTRY]
    assert list(new) == list(before[ENTRY])                  # field order kept
    assert new["key"] == NEW_KEY and new["refresh_token"] == NEW_REFRESH
    assert new["expires_at"] == _grok_iso(NOW + 43200)
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z", new["expires_at"])
    for field in set(new) - {"key", "refresh_token", "expires_at"}:
        assert new[field] == before[ENTRY][field]
    assert stat.S_IMODE((home / "auth.json").stat().st_mode) == 0o600
    assert sorted(p.name for p in home.iterdir()) == ["auth.json", "auth.json.lock", "version.json"]
    assert re.fullmatch(rf"{os.getpid()}:\d+", (home / "auth.json.lock").read_text())
    _no_secret(json.dumps(res.extra), *logged)


def test_unsaved_rotated_tokens_are_kept_and_the_used_refresh_token_never_resent(tmp_path, monkeypatch):
    """A refresh whose write-back fails must not leave the daemon replaying
    the refresh token the issuer already consumed: the rotated tokens are kept
    in memory, used, and written once auth.json is writable again."""
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    real_write = grok._write_auth_atomic
    failing = {"on": True}

    def flaky_write(path, blob):
        if failing["on"]:
            raise OSError("read-only file system")
        real_write(path, blob)

    monkeypatch.setattr(grok, "_write_auth_atomic", flaky_write)
    seen: list[httpx.Request] = []
    client = _client(_oidc_handler(seen))
    for _ in range(2):   # first poll refreshes, second must not POST again
        res = _run(grok.poll(client=client, now=NOW))
        assert res.ok is True
    posts = [r for r in seen if r.method == "POST"]
    assert len(posts) == 1
    assert [r.headers["authorization"] for r in seen if str(r.url) == BILLING_URL] == [f"Bearer {NEW_KEY}"] * 2
    assert json.loads((home / "auth.json").read_text())[ENTRY]["refresh_token"] == REFRESH

    failing["on"] = False
    res = _run(grok.poll(client=client, now=NOW))
    assert res.ok is True
    assert len([r for r in seen if r.method == "POST"]) == 1
    stored = json.loads((home / "auth.json").read_text())[ENTRY]
    assert stored["key"] == NEW_KEY and stored["refresh_token"] == NEW_REFRESH


@pytest.mark.parametrize("expires_in", [1e20, "Infinity", "NaN", -5], ids=["huge", "inf", "nan", "negative"])
def test_unusable_expires_in_still_persists_the_rotated_tokens(tmp_path, monkeypatch, expires_in):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    body = {"access_token": NEW_KEY, "refresh_token": NEW_REFRESH, "expires_in": expires_in}
    res = _run(grok.poll(client=_client(_oidc_handler([], token_body=body)), now=NOW))
    assert res.ok is True
    stored = json.loads((home / "auth.json").read_text())[ENTRY]
    assert stored["key"] == NEW_KEY and stored["refresh_token"] == NEW_REFRESH
    assert stored["expires_at"] == _grok_iso(NOW + grok.DEFAULT_TOKEN_LIFETIME_S)


def test_rotated_refresh_token_absent_keeps_the_old_one(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    seen: list[httpx.Request] = []
    handler = _oidc_handler(seen, token_body={"access_token": NEW_KEY, "expires_in": 3600})
    res = _run(grok.poll(client=_client(handler), now=NOW))
    assert res.ok is True
    entry = json.loads((home / "auth.json").read_text())[ENTRY]
    assert entry["key"] == NEW_KEY
    assert entry["refresh_token"] == REFRESH
    assert entry["expires_at"] == _grok_iso(NOW + 3600)


def test_fresh_token_stored_by_a_sibling_under_the_lock_skips_refresh(tmp_path, monkeypatch):
    """Grok refreshed while we waited for the lock: the re-read under the lock
    sees its fresh token, so no token request is made and its file is kept."""
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    sibling = {ENTRY: _entry("tok-from-sibling", NOW + 7200, refresh="refresh-from-sibling")}
    real_flock = fcntl.flock

    def flock_then_sibling_wrote(fd, op):
        real_flock(fd, op)
        if op & fcntl.LOCK_EX:
            _write_auth(home, sibling)

    monkeypatch.setattr(grok.fcntl, "flock", flock_then_sibling_wrote)
    seen: list[httpx.Request] = []
    res = _run(grok.poll(client=_client(_oidc_handler(seen)), now=NOW))
    assert res.ok is True
    assert [r.method for r in seen if r.method == "POST"] == []
    billing = [r for r in seen if str(r.url) == BILLING_URL]
    assert billing[0].headers["authorization"] == "Bearer tok-from-sibling"
    assert json.loads((home / "auth.json").read_text()) == sibling


def test_busy_lock_skips_refresh_and_falls_back_to_log(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1, log=True)
    before = (home / "auth.json").read_bytes()
    lock_path = home / "auth.json.lock"
    lock_path.write_text("99999:1700000000")
    with lock_path.open("r+") as held:          # another process holds Grok's lock
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        seen: list[httpx.Request] = []
        res = _run(grok.poll(client=_client(_oidc_handler(seen)), now=NOW))
    assert to_payload(res) == {"p": "grok", "w": 22, "wr": 3000, "st": "allowed", "ok": True}
    assert [r.method for r in seen if r.method == "POST"] == []
    assert (home / "auth.json").read_bytes() == before
    assert lock_path.read_text() == "99999:1700000000"


@pytest.mark.parametrize("status", [400, 401])
def test_invalid_grant_leaves_auth_json_untouched_and_asks_for_grok_login(tmp_path, monkeypatch, logged, status):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    before = (home / "auth.json").read_bytes()
    seen: list[httpx.Request] = []
    handler = _oidc_handler(seen, token_status=status,
                            token_body={"error": "invalid_grant", "error_description": "token revoked"})
    res = _run(grok.poll(client=_client(handler), now=NOW))
    assert to_payload(res) == {"p": "grok", "ok": False}
    assert "grok login" in res.extra["reason"]
    assert (home / "auth.json").read_bytes() == before
    _no_secret(json.dumps(res.extra), *logged)

    # The dead refresh token is not retried on the next poll.
    posts = len([r for r in seen if r.method == "POST"])
    res = _run(grok.poll(client=_client(handler), now=NOW + 60))
    assert len([r for r in seen if r.method == "POST"]) == posts == 1
    assert "grok login" in res.extra["reason"]


def test_failed_refresh_leaves_auth_json_untouched_and_falls_back_to_log(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1, log=True)
    before = (home / "auth.json").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json={"token_endpoint": TOKEN_URL})
        raise httpx.ConnectError("offline", request=request)

    res = _run(grok.poll(client=_client(handler), now=NOW))
    assert to_payload(res) == {"p": "grok", "w": 22, "wr": 3000, "st": "allowed", "ok": True}
    assert (home / "auth.json").read_bytes() == before


@pytest.mark.parametrize("case", ["issuer", "discovered", "configured"])
def test_non_https_issuer_or_token_endpoint_is_refused(tmp_path, monkeypatch, case):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    if case == "issuer":
        blob = json.loads((home / "auth.json").read_text())
        blob[ENTRY]["oidc_issuer"] = "http://auth.x.ai"
        _write_auth(home, blob)
    if case == "configured":
        monkeypatch.setattr(grok, "read_config",
                            lambda key: "http://evil.test/token" if key == "grok_token_url" else None)
    before = (home / "auth.json").read_bytes()
    seen: list[httpx.Request] = []
    endpoint = "http://auth.x.ai/oauth2/token" if case == "discovered" else TOKEN_URL
    res = _run(grok.poll(client=_client(_oidc_handler(seen, token_endpoint=endpoint)), now=NOW))
    assert res.ok is False and "https" in res.extra["reason"]
    assert [r for r in seen if r.method == "POST"] == []
    if case != "discovered":
        assert seen == []
    assert (home / "auth.json").read_bytes() == before


def test_configured_token_url_skips_discovery(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    monkeypatch.setattr(grok, "read_config",
                        lambda key: "https://override.test/oauth2/token" if key == "grok_token_url" else None)
    seen: list[httpx.Request] = []
    res = _run(grok.poll(client=_client(_oidc_handler(seen)), now=NOW))
    assert res.ok is True
    assert [(r.method, str(r.url)) for r in seen] == [
        ("POST", "https://override.test/oauth2/token"), ("GET", BILLING_URL)]


def test_discovery_is_cached_per_issuer(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    seen: list[httpx.Request] = []
    handler = _oidc_handler(seen, token_body={"access_token": NEW_KEY, "expires_in": 100})
    _run(grok.poll(client=_client(handler), now=NOW))
    _run(grok.poll(client=_client(handler), now=NOW + 60))   # 100 s token: refreshes again
    assert [str(r.url) for r in seen].count(DISCOVERY_URL) == 1
    assert [r.method for r in seen].count("POST") == 2
    assert json.loads((home / "auth.json").read_text())[ENTRY]["key"] == NEW_KEY


# --- fallback (S2.3, S3.3, S3.4) ----------------------------------------------

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


def test_endpoint_failure_is_logged_once_per_state_change(tmp_path, monkeypatch, logged):
    _grok_home(tmp_path, monkeypatch, log=True)
    statuses = iter([500, 500, 200, 200, 503])

    def handler(_request: httpx.Request) -> httpx.Response:
        code = next(statuses)
        return httpx.Response(code, json=BILLING if code == 200 else {})

    for _ in range(5):
        _run(grok.poll(client=_client(handler), now=NOW))
    assert len(logged) == 3
    assert "HTTP 500" in logged[0] and "HTTP 503" in logged[2]
    assert "HTTP" not in logged[1]
    _no_secret(*logged)


@pytest.mark.parametrize("age, ok", [(6 * 3600 - 1, True), (6 * 3600 + 1, False)], ids=["fresh", "stale"])
def test_log_fallback_is_used_only_when_newer_than_6_hours(tmp_path, monkeypatch, age, ok):
    _grok_home(tmp_path, monkeypatch, key=None, log=True)
    now = _iso_epoch(LOG_22_TS) + age
    res = _run(grok.poll(client=_client(_fail_if_called), now=now))
    assert res.ok is ok
    if ok:
        assert res.bars[0][1] == 22
    else:
        assert to_payload(res) == {"p": "grok", "ok": False}
        assert "6 h" in res.extra["reason"]


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


def test_log_scan_runs_off_the_event_loop_and_reads_at_most_8_mib(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, key=None, log=True)
    log_path = home / "logs" / "unified.jsonl"
    filler = (json.dumps({"msg": "noise", "ctx": {"pad": "x" * 1000}}) + "\n").encode()
    with log_path.open("ab") as fh:     # the only matches now sit beyond the last 8 MiB
        fh.write(filler * (8 * 1024 * 1024 // len(filler) + 2))
    assert log_path.stat().st_size > 8 * 1024 * 1024

    offloaded: list[str] = []
    real_to_thread = asyncio.to_thread

    async def spy(func, *args, **kwargs):
        offloaded.append(func.__name__)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(grok.asyncio, "to_thread", spy)
    res = _run(grok.poll(client=_client(_fail_if_called), now=NOW))
    assert to_payload(res) == {"p": "grok", "ok": False}
    assert "no billing line" in res.extra["reason"]
    assert offloaded == ["latest_log_entry"]


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
        "https://auth.x.ai::a": {"key": "tok-older", "expires_at": _iso(NOW + 1000)},
        "https://auth.x.ai::b": {"key": "", "expires_at": _iso(NOW + 9000)},
        "https://auth.x.ai::c": {"key": "tok-newest", "expires_at": _iso(NOW + 5000)},
    }))
    seen: list[httpx.Request] = []
    _run(grok.poll(client=_client(_ok_handler(seen)), now=NOW))
    assert seen[0].headers["authorization"] == "Bearer tok-newest"


# --- detection ------------------------------------------------------------------

def test_detect_available_with_a_key_and_never_shows_it(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, expires_at=NOW - 10 ** 6)   # expired is fine: the daemon refreshes it
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


def test_daemon_wires_grok_config_hook():
    """The daemon points the Grok provider at its config reader, so the
    optional `grok_token_url` key takes effect (Kimi is wired the same way)."""
    # A fresh interpreter: this module's autouse fixture replaces read_config.
    code = ("import daemon.claude_usage_daemon as m, daemon.providers.grok as g; "
            "assert g.read_config is m.read_config_value")
    root = Path(__file__).resolve().parents[2]
    subprocess.run([sys.executable, "-c", code], cwd=root, check=True)


@pytest.mark.parametrize("kind", ["500", "403", "400-other", "network", "not-json", "no-token", "list-body"])
def test_every_refresh_failure_leaves_auth_json_byte_identical_and_releases_the_lock(tmp_path, monkeypatch, kind):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    before = (home / "auth.json").read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json={"issuer": ISSUER, "token_endpoint": TOKEN_URL})
        if request.method == "POST":
            if kind == "network":
                raise httpx.ConnectError("boom", request=request)
            return {
                "500": httpx.Response(500, json={}),
                "403": httpx.Response(403, json={"error": "forbidden"}),
                "400-other": httpx.Response(400, json={"error": "invalid_request"}),
                "not-json": httpx.Response(200, text="{not json"),
                "no-token": httpx.Response(200, json={}),
                "list-body": httpx.Response(200, json=[1, 2]),
            }[kind]
        raise AssertionError(f"unexpected request to {request.url}")

    res = _run(grok.poll(client=_client(handler), now=NOW))
    assert res.ok is False
    assert (home / "auth.json").read_bytes() == before
    fd = os.open(home / "auth.json.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # released on the failure path
    finally:
        os.close(fd)


def test_invalid_grant_is_not_retried_until_the_refresh_token_changes(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    seen: list[httpx.Request] = []
    client = _client(_oidc_handler(seen, token_status=400, token_body={"error": "invalid_grant"}))
    for _ in range(3):
        assert _run(grok.poll(client=client, now=NOW)).ok is False
    assert [r.method for r in seen].count("POST") == 1
    blob = json.loads((home / "auth.json").read_text())
    blob[ENTRY]["refresh_token"] = "xai-test-relogin-refresh"
    _write_auth(home, blob)
    _run(grok.poll(client=client, now=NOW))
    assert [r.method for r in seen].count("POST") == 2



def _fail_writes_once(monkeypatch):
    real_write = grok._write_auth_atomic
    state = {"failing": True}

    def flaky_write(path, blob):
        if state["failing"]:
            raise OSError("read-only file system")
        real_write(path, blob)

    monkeypatch.setattr(grok, "_write_auth_atomic", flaky_write)
    return state


def test_unsaved_tokens_never_overwrite_credentials_stored_after_a_new_sign_in(tmp_path, monkeypatch):
    """A `grok login` between the failed write-back and the retry wins: the
    retry must not merge the stale in-memory tokens over the new sign-in."""
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    writes = _fail_writes_once(monkeypatch)
    seen: list[httpx.Request] = []
    client = _client(_oidc_handler(seen))
    _run(grok.poll(client=client, now=NOW))                    # refresh ok, write fails
    writes["failing"] = False
    real_enter = grok._AuthLock.__enter__

    def sign_in_first(lock):
        # The user runs `grok login` after the daemon read auth.json but
        # before it takes the lock.
        blob = json.loads((home / "auth.json").read_text())
        blob[ENTRY].update(key="xai-test-relogin-key", refresh_token="xai-test-relogin-refresh",
                           expires_at=_grok_iso(NOW + 3600))
        _write_auth(home, blob)
        monkeypatch.setattr(grok._AuthLock, "__enter__", real_enter)
        return real_enter(lock)

    monkeypatch.setattr(grok._AuthLock, "__enter__", sign_in_first)
    res = _run(grok.poll(client=client, now=NOW))
    assert res.ok is True
    stored = json.loads((home / "auth.json").read_text())[ENTRY]
    assert stored["key"] == "xai-test-relogin-key"
    assert stored["refresh_token"] == "xai-test-relogin-refresh"
    assert [r.headers["authorization"] for r in seen if str(r.url) == BILLING_URL][-1] == "Bearer xai-test-relogin-key"


def test_busy_lock_still_uses_the_unsaved_refreshed_token(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    _fail_writes_once(monkeypatch)
    seen: list[httpx.Request] = []
    client = _client(_oidc_handler(seen))
    _run(grok.poll(client=client, now=NOW))
    fd = os.open(home / "auth.json.lock", os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)                             # Grok holds the lock
    try:
        other = os.open(home / "auth.json.lock", os.O_RDWR)   # separate open file: conflicts
        os.close(other)
        res = _run(grok.poll(client=client, now=NOW))
    finally:
        os.close(fd)
    assert res.ok is True
    assert [r.headers["authorization"] for r in seen if str(r.url) == BILLING_URL] == [f"Bearer {NEW_KEY}"] * 2
    assert [r.method for r in seen].count("POST") == 1


def test_transient_refresh_failure_backs_off_before_the_next_token_request(tmp_path, monkeypatch):
    _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    seen: list[httpx.Request] = []
    client = _client(_oidc_handler(seen, token_status=503, token_body={}))
    _run(grok.poll(client=client, now=NOW))
    _run(grok.poll(client=client, now=NOW + 60))               # inside the back-off: no POST
    assert [r.method for r in seen].count("POST") == 1
    _run(grok.poll(client=client, now=NOW + grok.REFRESH_BACKOFF_S + 1))
    assert [r.method for r in seen].count("POST") == 2


def test_slow_token_endpoint_is_abandoned_within_the_budget_and_releases_the_lock(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    before = (home / "auth.json").read_bytes()
    monkeypatch.setattr(grok, "REFRESH_POST_BUDGET_S", 0.05, raising=False)

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json={"issuer": ISSUER, "token_endpoint": TOKEN_URL})
        await asyncio.sleep(5)
        return httpx.Response(200, json={})

    started = time.monotonic()
    res = _run(grok.poll(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), now=NOW))
    assert time.monotonic() - started < 2
    assert res.ok is False
    assert (home / "auth.json").read_bytes() == before
    fd = os.open(home / "auth.json.lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(fd)



def test_expired_credentials_from_another_process_drop_the_unsaved_tokens_and_refresh_with_the_new_grant(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch, expires_at=NOW - 1)
    writes = _fail_writes_once(monkeypatch)
    seen: list[httpx.Request] = []
    client = _client(_oidc_handler(seen))
    _run(grok.poll(client=client, now=NOW))                    # refresh ok, write fails
    writes["failing"] = False
    real_enter = grok._AuthLock.__enter__

    def store_expired_first(lock):
        blob = json.loads((home / "auth.json").read_text())
        blob[ENTRY].update(key="xai-test-other-key", refresh_token="xai-test-other-refresh",
                           expires_at=_grok_iso(NOW - 10))
        _write_auth(home, blob)
        monkeypatch.setattr(grok._AuthLock, "__enter__", real_enter)
        return real_enter(lock)

    monkeypatch.setattr(grok._AuthLock, "__enter__", store_expired_first)
    second = _run(grok.poll(client=client, now=NOW))
    assert second.ok is False                                  # neither stale nor expired token is used
    assert json.loads((home / "auth.json").read_text())[ENTRY]["refresh_token"] == "xai-test-other-refresh"
    third = _run(grok.poll(client=client, now=NOW))
    assert third.ok is True
    posts = [parse_qs(r.content.decode()) for r in seen if r.method == "POST"]
    assert [p["refresh_token"] for p in posts] == [[REFRESH], ["xai-test-other-refresh"]]
