"""Grok (Grok Build CLI, ``grok``) provider: ``GET ${base}/billing?format=credits``.

Data dir: ``${GROK_HOME:-~/.grok}``. Base URL: ``${GROK_CLI_CHAT_PROXY_BASE_URL:-
https://cli-chat-proxy.grok.com/v1}``; an override that is not ``https://`` is
ignored (logged once) so the bearer never leaves over plain HTTP. The request
is the one the CLI makes for its own credits view (verified with a live call
on 2026-10-21, HTTP 200):

    GET /billing?format=credits
    Authorization: Bearer <key>
    x-grok-client-version: <$GROK_HOME/version.json "version", else DEFAULT_CLIENT_VERSION>
    x-grok-client-mode: cli
    Accept: application/json

The bearer is the ``key`` of the entry in ``$GROK_HOME/auth.json`` (a dict
keyed like ``https://auth.x.ai::<uuid>``; ``auth_mode`` is ``oidc`` and
``expires_at`` is ISO-8601). With several entries the one with a non-empty
``key`` and the latest ``expires_at`` wins. Tokens are never logged.

Response: ``{"config": {"creditUsagePercent": 5.0, "currentPeriod": {"type":
"USAGE_PERIOD_TYPE_WEEKLY", "start": ISO, "end": ISO}, "productUsage": [...],
"billingPeriodStart": ISO, "billingPeriodEnd": ISO, ...}}``. It maps to one bar
labelled ``"Weekly"`` (payload ``w``/``wr``): percent = ``creditUsagePercent``,
reset = minutes until ``currentPeriod.end`` (a past end reads 0 %, see
:func:`window_bar`). Grok has no 5-hour window, so there is no ``s``/``sr``.
A monthly ``currentPeriod`` also lands on ``"Weekly"``: the firmware has one
long-window slot and the countdown still comes from the real period end.

Token refresh (Grok's own protocol, so the slot stays live while Grok is
closed): when the chosen entry expires within ``REFRESH_MARGIN_S`` (Grok's
``GROK_AUTH_EARLY_INVALIDATION_SECS`` default), the daemon

1. takes Grok's cross-process lock, an exclusive non-blocking ``flock`` on
   ``$GROK_HOME/auth.json.lock`` holding ``<pid>:<epoch>``; a busy lock means
   Grok is refreshing right now, so this poll skips the refresh;
2. re-reads ``auth.json`` under the lock and adopts a token another process
   already stored (no request);
3. POSTs ``grant_type=refresh_token``, ``refresh_token``,
   ``client_id=<oidc_client_id>`` to the issuer's ``token_endpoint``
   (discovered from ``<oidc_issuer>/.well-known/openid-configuration``, cached
   per issuer; the ``grok_token_url`` config key overrides it; HTTPS only);
4. writes ``key``, the rotated ``refresh_token`` (when returned) and
   ``expires_at`` back atomically (temp file + rename, mode 0600), keeping
   every other entry, field and key order.

A 400/401 ``invalid_grant`` means the sign-in is gone: auth.json is left alone
and that refresh token is not tried again until it changes (``grok login``).
Any other failure also leaves auth.json untouched.

Fallback: when there is no usable token or the endpoint fails (network error,
HTTP error, malformed body), the newest ``"msg": "billing: fetched credits
config"`` line in ``$GROK_HOME/logs/unified.jsonl`` supplies
``ctx.config.creditUsagePercent`` and ``ctx.config.currentPeriod.end``, but
only when its ``ts`` is newer than ``LOG_MAX_AGE_S`` (6 h); an older value
yields ``ok=False`` so the slot drops out instead of showing it as live. The
log is scanned off the event loop, backwards in blocks, over at most the last
``LOG_MAX_BYTES`` (8 MiB). The live-endpoint failure is logged once per state
change.
"""

import asyncio
import datetime
import fcntl
import hashlib
import json
import math
import os
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from .base import DetectResult, ProviderResult, iso_to_epoch, tilde, window_bar

DEFAULT_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
BILLING_PATH = "/billing?format=credits"
DEFAULT_ISSUER = "https://auth.x.ai"
DISCOVERY_PATH = "/.well-known/openid-configuration"
# Sent when $GROK_HOME/version.json is missing or unreadable (CLI version the
# endpoint was verified against).
DEFAULT_CLIENT_VERSION = "1.0.62"
LOG_MSG = "billing: fetched credits config"
LOG_BLOCK = 64 * 1024
LOG_MAX_BYTES = 8 * 1024 * 1024
LOG_MAX_AGE_S = 6 * 3600
TIMEOUT = 10.0
# Refresh when the token expires within this many seconds (Grok's own
# GROK_AUTH_EARLY_INVALIDATION_SECS default).
REFRESH_MARGIN_S = 300
# After a transient refresh failure (network, HTTP, bad response, discovery)
# no new token request is sent for this long.
REFRESH_BACKOFF_S = 300
# Upper bound for the token POST, which runs while Grok's lock is held.
REFRESH_POST_BUDGET_S = 8.0
# Lifetime assumed when a successful refresh response carries no usable
# ``expires_in``; the new tokens are still persisted so a rotated refresh
# token is never lost.
DEFAULT_TOKEN_LIFETIME_S = 3600
SIGNIN_EXPIRED = "Grok sign-in expired; run `grok login`"
USER_AGENT = "toknmon-daemon"

# Config accessor injected by the main module (``read_config_value``), same
# hook as kimi.py. Default: no config.
read_config: Callable[[str], str | None] = lambda key: None


def _default_log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# Log sink (same line format as the daemon's ``log``); tests capture it.
log: Callable[[str], None] = _default_log

# In-process state: discovered token endpoint per issuer, the last live-path
# state that was logged, one-shot warnings, fingerprints of refresh tokens the
# issuer rejected with invalid_grant or already consumed in a successful
# refresh (never the tokens themselves), and rotated entries that could not be
# written back yet (kept so a consumed refresh token is never sent again).
_token_endpoints: dict[str, str] = {}
_live_state = ""
_warned: set[str] = set()
_dead_refresh_tokens: set[str] = set()
_used_refresh_tokens: set[str] = set()
_unsaved_entries: dict[str, dict] = {}
_refresh_backoff_until = 0.0
# Upper bound for a usable ``expires_in`` (30 days); anything else falls back
# to DEFAULT_TOKEN_LIFETIME_S.
MAX_TOKEN_LIFETIME_S = 30 * 86400


class RefreshError(Exception):
    """Token refresh did not happen or failed; auth.json was left untouched.
    The message is a log-safe reason (never a token)."""


def grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME") or (Path.home() / ".grok")).expanduser()


def _is_https(url) -> bool:
    return isinstance(url, str) and url.lower().startswith("https://")


def _warn_once(msg: str) -> None:
    if msg not in _warned:
        _warned.add(msg)
        log(msg)


def base_url() -> str:
    override = (os.environ.get("GROK_CLI_CHAT_PROXY_BASE_URL") or "").strip()
    if override:
        if _is_https(override):
            return override.rstrip("/")
        _warn_once(f"Grok: ignoring GROK_CLI_CHAT_PROXY_BASE_URL={override!r} (not https); "
                   f"using {DEFAULT_BASE_URL}")
    return DEFAULT_BASE_URL


def client_version(home: Path) -> str:
    try:
        version = json.loads((home / "version.json").read_text()).get("version")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_CLIENT_VERSION
    return version.strip() if isinstance(version, str) and version.strip() else DEFAULT_CLIENT_VERSION


def _load_auth(home: Path) -> dict | None:
    try:
        blob = json.loads((home / "auth.json").read_text())
    except (OSError, ValueError):
        return None
    return blob if isinstance(blob, dict) else None


def _select_entry(blob: dict) -> tuple[str, dict] | None:
    """(name, entry) with a non-empty ``key`` and the latest ``expires_at``."""
    best: tuple[float, str, dict] | None = None
    for name, entry in blob.items():
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        exp = iso_to_epoch(entry.get("expires_at"))
        rank = exp if exp is not None else float("-inf")
        if best is None or rank > best[0]:
            best = (rank, name, entry)
    return (best[1], best[2]) if best else None


def read_auth(home: Path | None = None) -> dict | None:
    """The ``auth.json`` entry with a non-empty ``key`` and the latest
    ``expires_at`` (expired or not), or None when there is none."""
    blob = _load_auth(home or grok_home())
    found = _select_entry(blob) if blob else None
    return found[1] if found else None


def read_token(now: float, home: Path | None = None) -> str | None:
    """The bearer key unless its ``expires_at`` is in the past (an entry
    without ``expires_at`` is tried; the endpoint decides). No refresh."""
    entry = read_auth(home)
    if entry is None:
        return None
    exp = iso_to_epoch(entry.get("expires_at"))
    if exp is not None and exp <= now:
        return None
    return entry["key"].strip()


def detect() -> DetectResult:
    """The Grok CLI is usable when ``$GROK_HOME/auth.json`` holds an entry with
    a non-empty ``key``; an expired one is fine because the daemon refreshes it
    with Grok's own protocol (and the log fallback still works)."""
    auth = grok_home() / "auth.json"
    shown = tilde(auth)
    if not auth.is_file():
        return DetectResult(False, f"Grok CLI not found: {shown} does not exist. Install the "
                                   "Grok CLI and run `grok login`.")
    if read_auth() is None:
        return DetectResult(False, f"Grok CLI not logged in: {shown} has no API key. "
                                   "Run `grok login`.")
    return DetectResult(True, f"Grok credentials found ({shown})")


# --- token refresh ----------------------------------------------------------

def _grok_iso(epoch: float) -> str:
    """``expires_at`` in Grok's format: UTC, microseconds, ``Z``."""
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _write_auth_atomic(path: Path, blob: dict) -> None:
    """Write ``blob`` as ``<path>.tmp.<pid>`` then rename over ``path``, mode
    0600 (same semantics as kimi.py's credential write). Grok's own layout:
    two-space indent, no trailing newline."""
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    data = json.dumps(blob, indent=2, ensure_ascii=False)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _AuthLock:
    """Grok's cross-process refresh lock: exclusive non-blocking ``flock`` on
    ``auth.json.lock`` with ``<pid>:<epoch>`` written while it is held."""

    def __init__(self, home: Path):
        self.path = home / "auth.json.lock"
        self.fd: int | None = None

    def __enter__(self):
        try:
            self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as e:
            raise RefreshError(f"refresh skipped: cannot open auth.json.lock ({type(e).__name__})") from e
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            os.close(self.fd)
            self.fd = None
            raise RefreshError("refresh skipped: auth.json.lock is held by another process") from e
        try:
            os.ftruncate(self.fd, 0)
            os.pwrite(self.fd, f"{os.getpid()}:{int(time.time())}".encode(), 0)
        except OSError:
            pass   # the lock itself is what coordinates; the content is informational
        return self

    def __exit__(self, *_exc):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None
        return False


async def _token_endpoint(client: httpx.AsyncClient, entry: dict) -> str:
    """``grok_token_url`` config key, else the issuer's discovered
    ``token_endpoint`` (cached per issuer). HTTPS only."""
    configured = (read_config("grok_token_url") or "").strip()
    if configured:
        if not _is_https(configured):
            raise RefreshError(f"refresh refused: grok_token_url is not https ({configured})")
        return configured
    issuer = (entry.get("oidc_issuer") or DEFAULT_ISSUER).rstrip("/")
    if not _is_https(issuer):
        raise RefreshError(f"refresh refused: oidc_issuer is not https ({issuer})")
    if issuer in _token_endpoints:
        return _token_endpoints[issuer]
    try:
        resp = await client.get(f"{issuer}{DISCOVERY_PATH}", headers={"Accept": "application/json"},
                                timeout=TIMEOUT)
    except httpx.HTTPError as e:
        raise RefreshError(f"OIDC discovery failed: {type(e).__name__}") from e
    if resp.status_code != 200:
        raise RefreshError(f"OIDC discovery HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as e:
        raise RefreshError("OIDC discovery response is not JSON") from e
    endpoint = body.get("token_endpoint") if isinstance(body, dict) else None
    if not isinstance(endpoint, str) or not endpoint:
        raise RefreshError("OIDC discovery has no token_endpoint")
    if not _is_https(endpoint):
        raise RefreshError(f"refresh refused: token_endpoint is not https ({endpoint})")
    _token_endpoints[issuer] = endpoint
    return endpoint


def _invalid_grant(resp: httpx.Response) -> bool:
    try:
        body = resp.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("error") == "invalid_grant"


async def refresh_access_token(home: Path, name: str, entry: dict, client: httpx.AsyncClient,
                               now: float) -> str:
    """Refresh the ``name`` entry of ``auth.json`` under Grok's lock and return
    the access token to use. Raises :class:`RefreshError` when no refresh
    happened (busy lock, refused URL, network/HTTP failure, rejected grant);
    auth.json is then untouched. At most one token request: never retried."""
    refresh = entry.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise RefreshError("no refresh_token in auth.json")
    if _fingerprint(refresh) in _dead_refresh_tokens:
        raise RefreshError(SIGNIN_EXPIRED)
    if _fingerprint(refresh) in _used_refresh_tokens:
        return _retry_unsaved(home, name, now)
    if now < _refresh_backoff_until:
        raise RefreshError("refresh paused after a failed attempt")
    try:
        return await _refresh_under_lock(home, name, entry, client, now)
    except _TransientRefreshError as e:
        _back_off(now)
        raise RefreshError(str(e)) from e


class _TransientRefreshError(RefreshError):
    """A refresh failure worth retrying only after REFRESH_BACKOFF_S."""


def _back_off(now: float) -> None:
    global _refresh_backoff_until
    _refresh_backoff_until = now + REFRESH_BACKOFF_S


async def _refresh_under_lock(home: Path, name: str, entry: dict, client: httpx.AsyncClient,
                              now: float) -> str:
    # Discovery happens before the lock so Grok never waits on it.
    try:
        url = await _token_endpoint(client, entry)
    except RefreshError as e:
        if str(e).startswith("refresh refused"):
            raise
        raise _TransientRefreshError(str(e)) from e
    path = home / "auth.json"
    with _AuthLock(home):
        blob = _load_auth(home)
        if blob is None:
            raise RefreshError("cannot read auth.json")
        current = blob.get(name)
        if not isinstance(current, dict) or not isinstance(current.get("key"), str):
            raise RefreshError("auth.json entry changed during refresh")
        exp = iso_to_epoch(current.get("expires_at"))
        if current["key"].strip() and (exp is None or exp > now + REFRESH_MARGIN_S):
            return current["key"].strip()     # another process already refreshed
        refresh = current.get("refresh_token")
        client_id = current.get("oidc_client_id")
        if not isinstance(refresh, str) or not refresh:
            raise RefreshError("no refresh_token in auth.json")
        if not isinstance(client_id, str) or not client_id:
            raise RefreshError("no oidc_client_id in auth.json")
        form = {"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id}
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        try:
            resp = await asyncio.wait_for(client.post(url, data=form, headers=headers, timeout=TIMEOUT),
                                          REFRESH_POST_BUDGET_S)
        except asyncio.TimeoutError as e:
            raise _TransientRefreshError("refresh request timed out") from e
        except httpx.HTTPError as e:
            raise _TransientRefreshError(f"refresh request failed: {type(e).__name__}") from e
        if resp.status_code in (400, 401) and _invalid_grant(resp):
            _dead_refresh_tokens.add(_fingerprint(refresh))
            raise RefreshError(SIGNIN_EXPIRED)
        if resp.status_code != 200:
            raise _TransientRefreshError(f"refresh HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as e:
            raise _TransientRefreshError("refresh response is not JSON") from e
        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise _TransientRefreshError("refresh response has no access_token")
        rotated = body.get("refresh_token")
        if isinstance(rotated, str) and rotated and rotated != refresh:
            # The issuer rotated it: the old refresh token is consumed and
            # must never be sent again, even if the write-back below fails.
            _used_refresh_tokens.add(_fingerprint(refresh))
        expires_in = _lifetime(body.get("expires_in"))
        updated = dict(current)   # same field order; only three values change
        updated["key"] = token
        if isinstance(body.get("refresh_token"), str) and body["refresh_token"]:
            updated["refresh_token"] = body["refresh_token"]
        updated["expires_at"] = _grok_iso(now + expires_in)
        blob[name] = updated      # same entry position
        try:
            _write_auth_atomic(path, blob)
            _unsaved_entries.pop(name, None)
        except OSError as e:
            # The issuer may have rotated the refresh token already: keep the
            # new entry in memory, use it, and retry the write on later polls.
            _unsaved_entries[name] = updated
            log(f"Grok: refreshed token could not be written to auth.json ({type(e).__name__}); will retry")
        return token


def _lifetime(value) -> int:
    """Seconds from a token response's ``expires_in``; non-numeric,
    non-finite, non-positive or absurd values use DEFAULT_TOKEN_LIFETIME_S."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_LIFETIME_S
    if not math.isfinite(seconds) or seconds <= 0 or seconds > MAX_TOKEN_LIFETIME_S:
        return DEFAULT_TOKEN_LIFETIME_S
    return int(seconds)


def _retry_unsaved(home: Path, name: str, now: float) -> str:
    """The on-disk refresh token was already consumed by this process: write
    the rotated entry kept in memory (under Grok's lock) and return its access
    token. Never contacts the issuer. If auth.json meanwhile holds a refresh
    token this process did not consume (Grok refreshed, or `grok login`), the
    disk wins and the pending entry is dropped. A busy lock skips the write
    but still returns the pending token."""
    pending = _unsaved_entries.get(name)
    if pending is None:
        raise RefreshError("refresh token already used; waiting for Grok to store a new one")
    try:
        lock = _AuthLock(home).__enter__()
    except RefreshError:
        lock = None   # busy: write on a later poll, the pending token is still valid
    if lock is not None:
        try:
            blob = _load_auth(home)
            current = blob.get(name) if isinstance(blob, dict) else None
            if isinstance(current, dict):
                stored = current.get("refresh_token")
                if not (isinstance(stored, str) and _fingerprint(stored) in _used_refresh_tokens):
                    _unsaved_entries.pop(name, None)
                    return _disk_key(current, now)
                blob[name] = {**current, **{k: pending[k] for k in ("key", "refresh_token", "expires_at")}}
                try:
                    _write_auth_atomic(home / "auth.json", blob)
                    _unsaved_entries.pop(name, None)
                except OSError as e:
                    log(f"Grok: refreshed token could not be written to auth.json ({type(e).__name__}); will retry")
        finally:
            lock.__exit__(None, None, None)
    exp = iso_to_epoch(pending.get("expires_at"))
    if exp is not None and exp <= now:
        raise RefreshError("unsaved refreshed token expired")
    return pending["key"]


def _disk_key(entry: dict, now: float) -> str:
    """Access token of an entry another process stored, if it is still valid."""
    key = entry.get("key")
    exp = iso_to_epoch(entry.get("expires_at"))
    if isinstance(key, str) and key.strip() and (exp is None or exp > now):
        return key.strip()
    raise RefreshError("auth.json changed during refresh; retrying on the next poll")


async def _resolve_token(client: httpx.AsyncClient, home: Path, now: float) -> tuple[str | None, str]:
    """(bearer, failure reason). Refreshes the chosen entry when it expires
    within ``REFRESH_MARGIN_S``; a token that is still valid is used even if
    that refresh could not happen."""
    blob = _load_auth(home)
    found = _select_entry(blob) if blob else None
    if found is None:
        return None, "no Grok credentials"
    name, entry = found
    key = entry["key"].strip()
    exp = iso_to_epoch(entry.get("expires_at"))
    if exp is None or exp > now + REFRESH_MARGIN_S:
        return key, ""
    try:
        return await refresh_access_token(home, name, entry, client, now), ""
    except RefreshError as e:
        if exp > now:
            return key, ""
        return None, f"token expired; {e}"


# --- billing endpoint and log fallback --------------------------------------

def _reverse_lines(path: Path):
    """Yield the lines of ``path`` last to first, reading ``LOG_BLOCK`` bytes
    at a time from the end and never more than ``LOG_MAX_BYTES`` in total (a
    line cut by that limit is dropped)."""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        floor = max(0, pos - LOG_MAX_BYTES)
        tail = b""
        while pos > floor:
            step = min(LOG_BLOCK, pos - floor)
            pos -= step
            fh.seek(pos)
            parts = (fh.read(step) + tail).split(b"\n")
            tail = parts[0]          # may continue in the previous block
            for line in reversed(parts[1:]):
                if line:
                    yield line
        if tail and floor == 0:
            yield tail


def latest_log_entry(home: Path | None = None) -> tuple[float | None, dict] | None:
    """(``ts`` epoch or None, ``ctx.config``) of the newest "billing: fetched
    credits config" line in ``logs/unified.jsonl``, or None. Blocking: poll()
    runs it in a worker thread."""
    path = (home or grok_home()) / "logs" / "unified.jsonl"
    needle = LOG_MSG.encode()
    try:
        for raw in _reverse_lines(path):
            if needle not in raw:
                continue
            try:
                line = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(line, dict) or line.get("msg") != LOG_MSG:
                continue
            ctx = line.get("ctx")
            config = ctx.get("config") if isinstance(ctx, dict) else None
            if isinstance(config, dict) and "creditUsagePercent" in config:
                return iso_to_epoch(line.get("ts")), config
    except OSError:
        return None
    return None


def latest_log_config(home: Path | None = None) -> dict | None:
    """``ctx.config`` of the newest billing line (see :func:`latest_log_entry`)."""
    found = latest_log_entry(home)
    return found[1] if found else None


def parse_config(config, now: float) -> ProviderResult | None:
    """Map a credits ``config`` object to the weekly bar, or None if malformed."""
    if not isinstance(config, dict):
        return None
    pct = config.get("creditUsagePercent")
    period = config.get("currentPeriod")
    if isinstance(pct, bool) or not isinstance(pct, (int, float, str)) or not isinstance(period, dict):
        return None
    try:
        pct = float(pct)
    except ValueError:
        return None
    end = iso_to_epoch(period.get("end"))
    if end is None:
        return None
    return ProviderResult(id="grok", bars=[window_bar("Weekly", pct, end, now)])


async def _fetch(client: httpx.AsyncClient, token: str, home: Path, now: float) -> tuple[ProviderResult | None, str]:
    headers = {
        "Authorization": f"Bearer {token}",
        "x-grok-client-version": client_version(home),
        "x-grok-client-mode": "cli",
        "Accept": "application/json",
    }
    try:
        resp = await client.get(f"{base_url()}{BILLING_PATH}", headers=headers)
    except httpx.HTTPError as e:
        return None, f"request failed: {type(e).__name__}"
    if resp.status_code >= 400:
        return None, f"HTTP {resp.status_code}"
    try:
        body = resp.json()
    except ValueError:
        return None, "invalid JSON"
    res = parse_config(body.get("config") if isinstance(body, dict) else None, now)
    return (res, "") if res else (None, "unexpected response shape")


def _note_live_state(reason: str) -> None:
    """Log the live-path outcome only when it changes (failure reason, or back
    to healthy)."""
    global _live_state
    if reason == _live_state:
        return
    if reason:
        log(f"Grok: live billing unavailable ({reason}); using the log fallback if it is fresh")
    else:
        log("Grok: live billing endpoint OK again")
    _live_state = reason


async def poll(client: httpx.AsyncClient | None = None, now: float | None = None) -> ProviderResult:
    """Billing endpoint first (refreshing the token when needed), then the
    log fallback when it is newer than 6 h. ``reason`` lands in ``extra`` only
    on failure (``to_payload`` drops it); it never holds a token."""
    now = time.time() if now is None else now
    home = grok_home()
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    res = None
    try:
        token, reason = await _resolve_token(client, home, now)
        if token:
            res, reason = await _fetch(client, token, home, now)
    finally:
        if own_client:
            await client.aclose()
    _note_live_state(reason)
    if res:
        return res
    found = await asyncio.to_thread(latest_log_entry, home)
    if found is None:
        detail = "no billing line in logs/unified.jsonl"
    else:
        ts, config = found
        fallback = parse_config(config, now)
        if ts is None or now - ts >= LOG_MAX_AGE_S:
            detail = "last billing line in logs/unified.jsonl is older than 6 h"
        elif fallback is None:
            detail = "malformed billing line in logs/unified.jsonl"
        else:
            return fallback
    return ProviderResult(id="grok", bars=[], ok=False, extra={"reason": f"{reason}; {detail}"})
