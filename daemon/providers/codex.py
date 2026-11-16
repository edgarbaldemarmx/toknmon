"""Codex provider: rate limits from ChatGPT's ``wham/usage`` endpoint, with the
local Codex CLI session logs as the fallback.

Live usage: with the Codex CLI's own OAuth token from ``$CODEX_HOME/auth.json``
(``auth_mode: chatgpt``; read-only, never refreshed) the daemon asks
``wham/usage`` for the account's ``rate_limit`` windows every 5 minutes. This
works whether or not Codex ran lately: current Codex releases compress finished
sessions to ``rollout-*.jsonl.zst``, and an idle account writes no log at all.

Local logs: Codex writes ``rate_limits`` into ``token_count`` events in
``${CODEX_HOME:-~/.codex}/sessions/**/rollout-*.jsonl``. We take the line with
the newest ``timestamp`` across uncompressed files modified in the last 7 days.
They cover an API-key login (no live usage) and a failed fetch, and when both
sources exist the newer one wins, so a turn logged after the last fetch shows
at once.

Both sources go through the same mapping. Bars are keyed by the window length
(<= 10 h -> "5h", longer -> "Weekly"), not by the primary/secondary slot,
because weekly-only plans report the weekly window as ``primary`` with
``secondary: null``. The mapping is tolerant because Codex does not always
report exactly 300/10080 minutes. A window the plan does not report yields no
bar at all (so no ``s/sr`` on weekly-only plans).

Reset credits (``rc``/``ru``/``rm``) come from the same ``wham/usage`` body plus
two more ``wham`` endpoints: how many credits the account holds, how many it
spent in the trailing 30 days and when the soonest held one expires. That
answer is cached for an hour per process. Any failure is logged once and
omits what it affects; the token never reaches a log. ``codex_credits = off``
in the config skips every network call: local logs only.
"""

import json
import math
import os
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from .base import (
    DetectResult, ProviderResult, ResetCredits, iso_to_epoch, minutes_until, tilde, window_bar,
)

MAX_AGE_DAYS = 7
# Windows up to this many minutes land on the short ("5h") bar, longer ones on
# the weekly bar. Nominal values are 300 and 10080.
SHORT_WINDOW_MAX_MINUTES = 600

USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CREDITS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
HISTORY_URL = CREDITS_URL + "/history"
USER_AGENT = "toknmon-daemon"
# The wham endpoints are slow even when healthy (3-4 s measured upstream); they
# run at most every few minutes, so a generous timeout costs little.
TIMEOUT = 20.0
CREDITS_TTL_S = 3600
# Live usage (``wham/usage``) is fetched at most this often.
USAGE_TTL_S = 300
# Only "used" events this recent count towards ``ru``.
USED_WINDOW_S = 30 * 86400
CONFIG_KEY = "codex_credits"
OFF_VALUES = {"off", "false", "no", "0"}

# Config accessor injected by the main module (``read_config_value``), same
# hook as kimi.py / grok.py. Default: no config.
read_config: Callable[[str], str | None] = lambda key: None


def _default_log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# Log sink (same line format as the daemon's ``log``); tests capture it.
log: Callable[[str], None] = _default_log
_warned: set[str] = set()


def _warn_once(msg: str) -> None:
    if msg not in _warned:
        _warned.add(msg)
        log(msg)


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()


def detect() -> DetectResult:
    """The Codex CLI is usable when ``$CODEX_HOME/sessions`` holds at least one
    session log of any age, plain ``rollout-*.jsonl`` or the compressed
    ``rollout-*.jsonl.zst`` current releases leave behind."""
    sessions = codex_home() / "sessions"
    shown = tilde(sessions)
    if not sessions.is_dir():
        return DetectResult(False, f"Codex CLI not found: {shown} does not exist. Install the "
                                   "Codex CLI and run it once to create a session log.")
    found = None
    try:
        for p in sessions.rglob("rollout-*.jsonl*"):
            if p.name.endswith((".jsonl", ".jsonl.zst")):
                found = p
                break
    except OSError:
        found = None
    if found is None:
        return DetectResult(False, f"Codex CLI not found: {shown} has no session logs "
                                   "(rollout-*.jsonl). Install the Codex CLI and run it once.")
    return DetectResult(True, f"Codex session logs found ({shown})")


def _recent_rollouts(root: Path, now: float) -> list[Path]:
    cutoff = now - MAX_AGE_DAYS * 86400
    out = []
    try:
        for p in root.rglob("rollout-*.jsonl"):
            try:
                if p.stat().st_mtime >= cutoff:
                    out.append(p)
            except OSError:
                continue
    except OSError:
        return []
    return out


def latest_rate_limits(root: Path, now: float) -> dict | None:
    """Return the ``rate_limits`` dict from the newest matching line, or None."""
    snapshot = latest_snapshot(root, now)
    return snapshot[1] if snapshot is not None else None


def latest_snapshot(root: Path, now: float) -> tuple[float, dict] | None:
    """``(epoch of the line's timestamp, rate_limits)`` for the newest matching
    line, or None. An unparsable timestamp counts as the oldest possible."""
    best_ts = ""
    best: dict | None = None
    for path in _recent_rollouts(root, now):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if '"rate_limits"' not in line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    payload = obj.get("payload") if isinstance(obj, dict) else None
                    limits = payload.get("rate_limits") if isinstance(payload, dict) else None
                    if not isinstance(limits, dict):
                        continue
                    ts = str(obj.get("timestamp") or "")
                    # ISO-8601 UTC timestamps sort lexicographically.
                    if best is None or ts > best_ts:
                        best_ts, best = ts, limits
        except OSError:
            continue
    if best is None:
        return None
    return iso_to_epoch(best_ts) or 0.0, best


def live_rate_limits(usage: dict, fetched_at: float) -> dict | None:
    """Map a ``wham/usage`` body to the rollout ``rate_limits`` shape so
    :func:`parse_rate_limits` handles both sources alike. ``limit_window_seconds``
    becomes ``window_minutes``; a missing ``reset_at`` falls back to
    ``reset_after_seconds`` counted from the fetch. None when no window is
    usable."""
    rate_limit = usage.get("rate_limit")
    if not isinstance(rate_limit, dict):
        return None
    out: dict = {}
    for src, dst in (("primary_window", "primary"), ("secondary_window", "secondary")):
        w = rate_limit.get(src)
        if not isinstance(w, dict):
            continue
        pct, seconds = w.get("used_percent"), w.get("limit_window_seconds")
        if not _is_number(pct) or not _is_number(seconds) or seconds <= 0:
            continue
        reset = w.get("reset_at")
        if not _is_number(reset):
            after = w.get("reset_after_seconds")
            reset = fetched_at + after if _is_number(after) else None
        out[dst] = {"used_percent": pct, "window_minutes": int(seconds) // 60, "resets_at": reset}
    if not out:
        return None
    reached = usage.get("rate_limit_reached_type")
    if isinstance(reached, str) and reached:
        out["rate_limit_reached_type"] = reached
    return out


def _is_number(value) -> bool:
    # ``json.loads`` accepts NaN and Infinity; neither is a usable figure.
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_rate_limits(limits: dict, now: float) -> ProviderResult:
    windows: list[tuple[int, dict]] = []
    for slot in ("primary", "secondary"):
        w = limits.get(slot)
        if isinstance(w, dict) and w.get("window_minutes") is not None:
            try:
                windows.append((int(w["window_minutes"]), w))
            except (TypeError, ValueError):
                continue
    # Two windows in the same bucket: the shorter one is the "5h" bar, the
    # longer one the weekly bar.
    short = [x for x in windows if x[0] <= SHORT_WINDOW_MAX_MINUTES]
    long = [x for x in windows if x[0] > SHORT_WINDOW_MAX_MINUTES]

    def bar(label: str, w: dict):
        reset = w.get("resets_at")
        try:
            reset_epoch = float(reset) if reset is not None else None
        except (TypeError, ValueError):
            reset_epoch = None
        return window_bar(label, w.get("used_percent", 0), reset_epoch, now)

    # A window the plan does not report is omitted (no bar, no payload keys)
    # rather than sent as 0%, so the device can hide it.
    bars = []
    if short:
        bars.append(bar("5h", min(short, key=lambda x: x[0])[1]))
    if long:
        bars.append(bar("Weekly", max(long, key=lambda x: x[0])[1]))
    status = "allowed"
    if limits.get("rate_limit_reached_type"):
        status = str(limits["rate_limit_reached_type"])
    return ProviderResult(id="codex", bars=bars, status=status)


# --- reset credits -----------------------------------------------------------

def credits_enabled() -> bool:
    """``codex_credits`` config key; absent or anything but off/false/no/0 is on."""
    value = read_config(CONFIG_KEY)
    return value is None or value.strip().lower() not in OFF_VALUES


def read_auth(home: Path) -> tuple[str, str | None] | None:
    """``(access_token, account_id)`` from ``auth.json`` when the Codex CLI is
    signed in with ChatGPT (``auth_mode == "chatgpt"``); None for an API-key
    login, a missing or unreadable file, or a missing token. The file is only
    ever read."""
    try:
        blob = json.loads((home / "auth.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(blob, dict) or blob.get("auth_mode") != "chatgpt":
        return None
    tokens = blob.get("tokens")
    if not isinstance(tokens, dict):
        return None
    token = tokens.get("access_token")
    if not isinstance(token, str) or not token:
        return None
    account = tokens.get("account_id")
    return token, account if isinstance(account, str) and account else None


def _headers(token: str, account_id: str | None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "OpenAI-Beta": "codex-1",
        "originator": "Codex Desktop",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id
    return headers


class _FetchError(Exception):
    """One failed endpoint; the message is a log-safe reason (never a token)."""


async def _get_json(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> dict:
    name = url.removeprefix(CREDITS_URL.rsplit("/", 1)[0] + "/")
    try:
        resp = await client.get(url, headers=headers)
    except httpx.HTTPError as e:
        raise _FetchError(f"{name}: request failed: {type(e).__name__}") from None
    except UnicodeError:
        # A non-ASCII token (corrupted auth.json) cannot go into a header, and
        # the encoding error's text carries the header: never let it escape.
        raise _FetchError(f"{name}: request failed: the token is not ASCII") from None
    if resp.status_code >= 400:
        raise _FetchError(f"{name}: HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        raise _FetchError(f"{name}: invalid JSON") from None
    if not isinstance(body, dict):
        raise _FetchError(f"{name}: unexpected response shape")
    return body


def _event_epoch(event: dict) -> float | None:
    for key in ("occurred_at", "created_at", "used_at", "timestamp", "at"):
        epoch = iso_to_epoch(event.get(key))
        if epoch is not None:
            return epoch
    return None


def parse_credits(usage: dict, credits: dict, history: dict, now: float) -> tuple[int, int, float | None]:
    """``(held, used in the trailing 30 days, soonest expiry epoch or None)``
    from the three endpoint bodies. Raises :class:`_FetchError` when the usage
    body lacks the count; the other two tolerate missing lists."""
    bucket = usage.get("rate_limit_reset_credits")
    try:
        held = int((bucket or {}).get("available_count"))
    except (TypeError, ValueError, AttributeError):
        raise _FetchError("usage: unexpected response shape (no available_count)") from None
    expiries = []
    items = credits.get("credits")
    for c in items if isinstance(items, list) else []:
        if isinstance(c, dict) and c.get("status") == "available":
            epoch = iso_to_epoch(c.get("expires_at"))
            if epoch is not None:
                expiries.append(epoch)
    used = 0
    events = history.get("events")
    for e in events if isinstance(events, list) else []:
        if not isinstance(e, dict) or e.get("kind") != "used":
            continue
        when = _event_epoch(e)
        # An undated event is inside the server's own trailing window.
        if when is None or now - when <= USED_WINDOW_S:
            used += 1
    return held, used, (min(expiries) if held > 0 and expiries else None)


async def fetch_reset_credits(client: httpx.AsyncClient, token: str, account_id: str | None,
                              now: float, usage: dict) -> tuple[int, int, float | None]:
    """The two GETs behind ``ru``/``rm``, joined with the already fetched
    ``wham/usage`` body that holds ``rc``; raises :class:`_FetchError`."""
    headers = _headers(token, account_id)
    credits = await _get_json(client, CREDITS_URL, headers)
    history = await _get_json(client, HISTORY_URL, headers)
    return parse_credits(usage, credits, history, now)


def _empty_cache() -> dict:
    # ``at``: epoch of the last fetch (success or failure); ``value``: the
    # parsed result, or None after a failure (``error`` then holds the
    # log-safe reason). Held for CREDITS_TTL_S or USAGE_TTL_S.
    return {"at": None, "value": None, "error": None}


_credits_cache: dict = _empty_cache()
_usage_cache: dict = _empty_cache()


async def _fetch_usage(client: httpx.AsyncClient | None, auth: tuple[str, str | None],
                       now: float) -> tuple[float, dict]:
    """``(fetch epoch, wham/usage body)``, fetched at most every USAGE_TTL_S
    (a failure is held as long); raises :class:`_FetchError`."""
    cache = _usage_cache
    if cache["at"] is None or now - cache["at"] >= USAGE_TTL_S:
        token, account_id = auth
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            cache["value"], cache["error"] = await _get_json(client, USAGE_URL, _headers(token, account_id)), None
        except _FetchError as e:
            cache["value"], cache["error"] = None, str(e)
        finally:
            if own_client:
                await client.aclose()
        cache["at"] = now
    if cache["value"] is None:
        raise _FetchError(cache["error"] or "usage: unavailable")
    return cache["at"], cache["value"]


async def live_usage(client: httpx.AsyncClient | None, home: Path, now: float) -> tuple[float, dict] | None:
    """``(fetch epoch, rate_limits)`` from ``wham/usage``, or None when
    ``codex_credits = off``, without a ChatGPT sign-in, after a failure
    (logged once) or when the body has no usable window."""
    if not credits_enabled():
        return None
    auth = read_auth(home)
    if auth is None:
        return None
    try:
        fetched_at, body = await _fetch_usage(client, auth, now)
    except _FetchError as e:
        _warn_once(f"Codex: live usage unavailable ({e}); using local session logs")
        return None
    limits = live_rate_limits(body, fetched_at)
    return (fetched_at, limits) if limits is not None else None


async def reset_credits(client: httpx.AsyncClient | None, home: Path, now: float) -> ResetCredits | None:
    """Cached reset credits for the payload, or None when disabled, signed out
    or failed (each reason logged once). ``rm`` is derived from the cached
    expiry at call time so it keeps aging between fetches."""
    if not credits_enabled():
        return None
    auth = read_auth(home)
    if auth is None:
        _warn_once(f"Codex: reset credits unavailable ({tilde(home / 'auth.json')} has no ChatGPT "
                   "sign-in); showing local usage only")
        return None
    cache = _credits_cache
    if cache["at"] is None or now - cache["at"] >= CREDITS_TTL_S:
        token, account_id = auth
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            _, usage = await _fetch_usage(client, auth, now)
            value = await fetch_reset_credits(client, token, account_id, now, usage)
        except _FetchError as e:
            _warn_once(f"Codex: reset credits unavailable ({e}); showing usage without them")
            value = None
        finally:
            if own_client:
                await client.aclose()
        cache["at"], cache["value"] = now, value
    if cache["value"] is None:
        return None
    held, used, expires_epoch = cache["value"]
    return held, used, (minutes_until(expires_epoch, now) if expires_epoch is not None else None)


async def poll(now: float | None = None, client: httpx.AsyncClient | None = None) -> ProviderResult:
    now = time.time() if now is None else now
    home = codex_home()
    local = latest_snapshot(home / "sessions", now)
    live = await live_usage(client, home, now)
    # The newer source wins; on a tie the live fetch does.
    newest = max((s for s in (live, local) if s is not None), key=lambda s: s[0], default=None)
    if newest is None:
        return ProviderResult(id="codex", bars=[], ok=False)
    limits = newest[1]
    res = parse_rate_limits(limits, now)
    res.credits = await reset_credits(client, home, now)
    return res
