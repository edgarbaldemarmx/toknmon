"""Codex reset credits: the three ``wham`` endpoints behind ``rc``/``ru``/``rm``.

The token comes from ``${CODEX_HOME:-~/.codex}/auth.json`` (read-only, never
refreshed); every request goes through an ``httpx.MockTransport`` so nothing
here touches the network. The local rollout usage keeps flowing whatever the
credit fetch does.
"""

import asyncio
import datetime
import json
import shutil
from pathlib import Path

import httpx
import pytest

from daemon import claude_usage_daemon as daemon
from daemon.providers import ProviderResult, codex, to_payload

FIXTURE = Path(__file__).parent / "fixtures" / "codex_rollout.jsonl"
NOW = 1792000000 - 240 * 60          # same instant as test_providers_codex.py
BASELINE = b'{"p":"codex","s":12,"sr":240,"w":40,"wr":6174,"st":"allowed","ok":true}'

TOKEN = "eyJ-test-access-token-000"
ACCOUNT = "acct-test-1234"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CREDITS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
HISTORY_URL = CREDITS_URL + "/history"


def _run(coro):
    return asyncio.run(coro)


def _iso(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).isoformat().replace("+00:00", "Z")


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(codex, "_warned", set())
    monkeypatch.setattr(codex, "_credits_cache", codex._empty_cache())
    monkeypatch.setattr(codex, "read_config", lambda key: None)
    monkeypatch.setattr(codex, "log", lines.append)
    return lines


@pytest.fixture
def logged(_fresh_state):
    return _fresh_state


def _codex_home(tmp_path: Path, monkeypatch, *, auth: dict | None = "chatgpt") -> Path:
    """A Codex home with the rollout fixture and, unless ``auth=None``, an
    ``auth.json`` (``"chatgpt"`` → OAuth mode, ``"apikey"`` → API-key mode,
    or a literal dict)."""
    home = tmp_path / "codex"
    day = home / "sessions" / "2026" / "10" / "11"
    day.mkdir(parents=True)
    shutil.copy(FIXTURE, day / "rollout-a.jsonl")
    monkeypatch.setenv("CODEX_HOME", str(home))
    if auth == "chatgpt":
        auth = {"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "last_refresh": _iso(NOW - 600),
                "tokens": {"access_token": TOKEN, "account_id": ACCOUNT,
                           "id_token": "id-token-xyz", "refresh_token": "refresh-token-xyz"}}
    elif auth == "apikey":
        auth = {"auth_mode": "apikey", "OPENAI_API_KEY": "sk-test-key", "tokens": None}
    if auth is not None:
        (home / "auth.json").write_text(json.dumps(auth))
    return home


USAGE_BODY = {"plan_type": "pro", "rate_limit": {}, "rate_limit_reset_credits": {"available_count": 2}}
CREDITS_BODY = {"credits": [
    {"id": "c1", "status": "used", "granted_at": _iso(NOW - 40 * 86400), "expires_at": _iso(NOW - 10 * 86400)},
    {"id": "c2", "status": "available", "granted_at": _iso(NOW - 20 * 86400), "expires_at": _iso(NOW + 10 * 86400)},
    {"id": "c3", "status": "available", "granted_at": _iso(NOW - 5 * 86400), "expires_at": _iso(NOW + 25 * 86400)},
]}
HISTORY_BODY = {"window_start": _iso(NOW - 30 * 86400), "as_of": _iso(NOW), "events": [
    {"kind": "granted", "occurred_at": _iso(NOW - 20 * 86400)},
    {"kind": "used", "occurred_at": _iso(NOW - 15 * 86400)},
    {"kind": "used", "occurred_at": _iso(NOW - 2 * 86400)},
    {"kind": "used", "occurred_at": _iso(NOW - 31 * 86400)},     # outside the trailing 30 days
    {"kind": "used"},                                            # no timestamp: inside the server window
]}


def _handler(seen: list, *, usage=USAGE_BODY, credits=CREDITS_BODY, history=HISTORY_BODY,
             status: dict[str, int] | None = None, raise_on: str | None = None):
    status = status or {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        url = str(request.url)
        if raise_on and url == raise_on:
            raise httpx.ReadTimeout("slow", request=request)
        body = {USAGE_URL: usage, CREDITS_URL: credits, HISTORY_URL: history}.get(url)
        if body is None:
            raise AssertionError(f"unexpected request to {url}")
        code = status.get(url, 200)
        if isinstance(body, (bytes, str)):
            return httpx.Response(code, content=body)
        return httpx.Response(code, json=body)
    return handler


# --- auth.json --------------------------------------------------------------

def test_read_auth_chatgpt_mode_returns_token_and_account_id(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    assert codex.read_auth(home) == (TOKEN, ACCOUNT)


def test_read_auth_api_key_mode_has_no_credits_token(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch, auth="apikey")
    assert codex.read_auth(home) is None


def test_read_auth_missing_file_is_none(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch, auth=None)
    assert codex.read_auth(home) is None


def test_missing_auth_logs_once_and_keeps_local_usage(tmp_path, monkeypatch, logged):
    _codex_home(tmp_path, monkeypatch, auth=None)
    seen: list = []
    client = _client(_handler(seen))
    first = _run(codex.poll(now=NOW, client=client))
    second = _run(codex.poll(now=NOW, client=client))
    assert seen == []
    assert json.dumps(to_payload(first), separators=(",", ":")).encode() == BASELINE
    assert json.dumps(to_payload(second), separators=(",", ":")).encode() == BASELINE
    assert len([l for l in logged if "reset credits" in l]) == 1
    assert TOKEN not in "".join(logged)


# --- the three fetches ------------------------------------------------------

def test_poll_attaches_held_used_and_soonest_expiry(tmp_path, monkeypatch):
    _codex_home(tmp_path, monkeypatch)
    seen: list = []
    res = _run(codex.poll(now=NOW, client=_client(_handler(seen))))
    assert [str(r.url) for r in seen] == [USAGE_URL, CREDITS_URL, HISTORY_URL]
    for r in seen:
        assert r.method == "GET"
        assert r.headers["Authorization"] == f"Bearer {TOKEN}"
        assert r.headers["ChatGPT-Account-Id"] == ACCOUNT
        assert r.headers["Accept"] == "application/json"
        assert r.headers["User-Agent"] == codex.USER_AGENT
    assert res.bars == [("5h", 12, 240), ("Weekly", 40, 6174)]
    payload = to_payload(res)
    # rc = available_count, ru = "used" events in the trailing 30 days (the
    # undated one counts, the 31-day-old one does not), rm = minutes to c2.
    assert (payload["rc"], payload["ru"], payload["rm"]) == (2, 3, 10 * 24 * 60)
    assert payload["ok"] is True and payload["p"] == "codex"


def test_rm_omitted_when_no_held_credit_has_an_expiry(tmp_path, monkeypatch):
    _codex_home(tmp_path, monkeypatch)
    credits = {"credits": [{"id": "c2", "status": "available", "granted_at": _iso(NOW)},
                           {"id": "c1", "status": "used", "expires_at": _iso(NOW + 86400)}]}
    res = _run(codex.poll(now=NOW, client=_client(_handler([], credits=credits))))
    payload = to_payload(res)
    assert (payload["rc"], payload["ru"]) == (2, 3)
    assert "rm" not in payload


def test_rm_omitted_when_nothing_is_held(tmp_path, monkeypatch):
    _codex_home(tmp_path, monkeypatch)
    usage = {"rate_limit_reset_credits": {"available_count": 0}}
    res = _run(codex.poll(now=NOW, client=_client(_handler([], usage=usage, credits={"credits": []}))))
    payload = to_payload(res)
    assert (payload["rc"], payload["ru"]) == (0, 3)
    assert "rm" not in payload


def test_credits_are_cached_for_one_hour_per_process(tmp_path, monkeypatch):
    _codex_home(tmp_path, monkeypatch)
    seen: list = []
    client = _client(_handler(seen))
    _run(codex.poll(now=NOW, client=client))
    later = _run(codex.poll(now=NOW + 3599, client=client))
    assert len(seen) == 3
    # The cached expiry still ages with the clock.
    assert to_payload(later)["rm"] == 10 * 24 * 60 - 60
    _run(codex.poll(now=NOW + 3600, client=client))
    assert len(seen) == 6


@pytest.mark.parametrize("kind", ["http", "timeout", "shape"])
def test_fetch_failure_omits_credits_keeps_usage_and_logs_once(tmp_path, monkeypatch, logged, kind):
    _codex_home(tmp_path, monkeypatch)
    seen: list = []
    if kind == "http":
        handler = _handler(seen, status={USAGE_URL: 401})
    elif kind == "timeout":
        handler = _handler(seen, raise_on=CREDITS_URL)
    else:
        handler = _handler(seen, history=b"<html>not json</html>")
    client = _client(handler)
    res = _run(codex.poll(now=NOW, client=client))
    payload = to_payload(res)
    assert not {"rc", "ru", "rm"} & payload.keys()
    assert json.dumps(payload, separators=(",", ":")).encode() == BASELINE
    _run(codex.poll(now=NOW + 60, client=client))
    assert len([l for l in logged if "reset credits unavailable" in l]) == 1
    assert TOKEN not in "".join(logged) and ACCOUNT not in "".join(logged)


def test_json_shape_failure_when_available_count_is_missing(tmp_path, monkeypatch, logged):
    _codex_home(tmp_path, monkeypatch)
    res = _run(codex.poll(now=NOW, client=_client(_handler([], usage={"plan_type": "pro"}))))
    assert not {"rc", "ru", "rm"} & to_payload(res).keys()
    assert any("reset credits unavailable" in l for l in logged)


# --- config -------------------------------------------------------------------

def test_codex_credits_off_skips_the_network(tmp_path, monkeypatch):
    _codex_home(tmp_path, monkeypatch)
    monkeypatch.setattr(codex, "read_config", lambda key: "off" if key == "codex_credits" else None)
    seen: list = []
    res = _run(codex.poll(now=NOW, client=_client(_handler(seen))))
    assert seen == []
    assert json.dumps(to_payload(res), separators=(",", ":")).encode() == BASELINE


def test_daemon_wires_codex_read_config(monkeypatch):
    monkeypatch.undo()   # drop the fixture's stub to see what the daemon installed
    assert codex.read_config is daemon.read_config_value


# --- payload contract -----------------------------------------------------------

def test_payload_without_credits_is_byte_identical_to_before(tmp_path, monkeypatch):
    _codex_home(tmp_path, monkeypatch, auth=None)
    res = _run(codex.poll(now=NOW))
    assert res.credits is None
    assert json.dumps(to_payload(res), separators=(",", ":")).encode() == BASELINE


def test_to_payload_emits_credit_keys_from_the_result():
    res = ProviderResult(id="codex", bars=[("Weekly", 40, 100)], credits=(2, 3, 1440))
    assert to_payload(res) == {"p": "codex", "w": 40, "wr": 100, "st": "allowed",
                               "rc": 2, "ru": 3, "rm": 1440, "ok": True}
    res = ProviderResult(id="codex", bars=[], credits=(0, 1, None))
    assert to_payload(res) == {"p": "codex", "st": "allowed", "rc": 0, "ru": 1, "ok": True}
    assert to_payload(ProviderResult(id="codex", bars=[], ok=False, credits=(2, 3, 1))) == {"p": "codex", "ok": False}


def test_encode_payload_drops_message_then_credits_then_label():
    payload = {"p": "codex", "s": 100, "sr": 99999, "w": 100, "wr": 99999, "f": 100, "fr": 99999,
               "fl": "Claude Fabl", "st": "allowed", "rc": 2, "ru": 3, "rm": 43200, "ok": True, "m": "hello"}
    enc = lambda p: json.dumps(p, separators=(",", ":")).encode()
    full = enc(payload)
    assert daemon.encode_payload(payload, len(full)) == full
    no_m = {k: v for k, v in payload.items() if k != "m"}
    assert json.loads(daemon.encode_payload(payload, len(enc(no_m)))) == no_m
    no_credits = {k: v for k, v in no_m.items() if k not in ("rc", "ru", "rm")}
    assert json.loads(daemon.encode_payload(payload, len(enc(no_m)) - 1)) == no_credits
    no_label = {k: v for k, v in no_credits.items() if k != "fl"}
    assert json.loads(daemon.encode_payload(payload, len(enc(no_credits)) - 1)) == no_label
