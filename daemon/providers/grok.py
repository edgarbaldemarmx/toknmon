"""Grok (Grok Build CLI, ``grok``) provider: ``GET ${base}/billing?format=credits``.

Data dir: ``${GROK_HOME:-~/.grok}``. Base URL: ``${GROK_CLI_CHAT_PROXY_BASE_URL:-
https://cli-chat-proxy.grok.com/v1}``. The request is the one the CLI makes
for its own credits view (verified with a live call on 2026-10-21, HTTP 200):

    GET /billing?format=credits
    Authorization: Bearer <key>
    x-grok-client-version: <$GROK_HOME/version.json "version", else DEFAULT_CLIENT_VERSION>
    x-grok-client-mode: cli
    Accept: application/json

The bearer is the ``key`` of the entry in ``$GROK_HOME/auth.json`` (a dict
keyed like ``https://auth.x.ai::<uuid>``; ``auth_mode`` is ``oidc`` and
``expires_at`` is ISO-8601). With several entries the one with a non-empty
``key`` and the latest ``expires_at`` wins. The token is never logged.

Response: ``{"config": {"creditUsagePercent": 5.0, "currentPeriod": {"type":
"USAGE_PERIOD_TYPE_WEEKLY", "start": ISO, "end": ISO}, "productUsage": [...],
"billingPeriodStart": ISO, "billingPeriodEnd": ISO, ...}}``. It maps to one bar
labelled ``"Weekly"`` (payload ``w``/``wr``): percent = ``creditUsagePercent``,
reset = minutes until ``currentPeriod.end`` (a past end reads 0 %, see
:func:`window_bar`). Grok has no 5-hour window, so there is no ``s``/``sr``.
A monthly ``currentPeriod`` also lands on ``"Weekly"``: the firmware has one
long-window slot and the countdown still comes from the real period end.

No token refresh. The daemon never reads or sends ``refresh_token`` and never
writes ``auth.json``: Grok refreshes its own token and re-reads the file, and a
second refresher could rotate the refresh token out from under it. An expired
``expires_at`` therefore skips the endpoint entirely.

Fallback: when the token is missing or expired, or the endpoint fails (network
error, HTTP error, malformed body), the newest ``"msg": "billing: fetched
credits config"`` line in ``$GROK_HOME/logs/unified.jsonl`` supplies
``ctx.config.creditUsagePercent`` and ``ctx.config.currentPeriod.end`` (the CLI
logs that line each time it fetches credits, so it is only as fresh as the last
Grok run). The log is read backwards in blocks so a large file stays cheap.
Neither source -> ``ok=False``.
"""

import json
import os
import time
from pathlib import Path

import httpx

from .base import DetectResult, ProviderResult, iso_to_epoch, tilde, window_bar

DEFAULT_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
BILLING_PATH = "/billing?format=credits"
# Sent when $GROK_HOME/version.json is missing or unreadable (CLI version the
# endpoint was verified against).
DEFAULT_CLIENT_VERSION = "1.0.62"
LOG_MSG = "billing: fetched credits config"
LOG_BLOCK = 64 * 1024
TIMEOUT = 10.0


def grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME") or (Path.home() / ".grok")).expanduser()


def base_url() -> str:
    return (os.environ.get("GROK_CLI_CHAT_PROXY_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def client_version(home: Path) -> str:
    try:
        version = json.loads((home / "version.json").read_text()).get("version")
    except (OSError, ValueError, AttributeError):
        return DEFAULT_CLIENT_VERSION
    return version.strip() if isinstance(version, str) and version.strip() else DEFAULT_CLIENT_VERSION


def read_auth(home: Path | None = None) -> dict | None:
    """The ``auth.json`` entry with a non-empty ``key`` and the latest
    ``expires_at`` (expired or not), or None when there is none."""
    try:
        blob = json.loads(((home or grok_home()) / "auth.json").read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(blob, dict):
        return None
    best: tuple[float, dict] | None = None
    for entry in blob.values():
        if not isinstance(entry, dict):
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key.strip():
            continue
        exp = iso_to_epoch(entry.get("expires_at"))
        rank = exp if exp is not None else float("-inf")
        if best is None or rank > best[0]:
            best = (rank, entry)
    return best[1] if best else None


def read_token(now: float, home: Path | None = None) -> str | None:
    """The bearer key unless its ``expires_at`` is in the past (an entry
    without ``expires_at`` is tried; the endpoint decides)."""
    entry = read_auth(home)
    if entry is None:
        return None
    exp = iso_to_epoch(entry.get("expires_at"))
    if exp is not None and exp <= now:
        return None
    return entry["key"].strip()


def detect() -> DetectResult:
    """The Grok CLI is usable when ``$GROK_HOME/auth.json`` holds an entry with
    a non-empty ``key``; an expired one is fine because the log fallback still
    works and Grok refreshes the token itself the next time it runs."""
    auth = grok_home() / "auth.json"
    shown = tilde(auth)
    if not auth.is_file():
        return DetectResult(False, f"Grok CLI not found: {shown} does not exist. Install the "
                                   "Grok CLI and run `grok login`.")
    if read_auth() is None:
        return DetectResult(False, f"Grok CLI not logged in: {shown} has no API key. "
                                   "Run `grok login`.")
    return DetectResult(True, f"Grok credentials found ({shown})")


def _reverse_lines(path: Path):
    """Yield the lines of ``path`` last to first, reading ``LOG_BLOCK`` bytes
    at a time from the end."""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        tail = b""
        while pos > 0:
            step = min(LOG_BLOCK, pos)
            pos -= step
            fh.seek(pos)
            parts = (fh.read(step) + tail).split(b"\n")
            tail = parts[0]          # may continue in the previous block
            for line in reversed(parts[1:]):
                if line:
                    yield line
        if tail:
            yield tail


def latest_log_config(home: Path | None = None) -> dict | None:
    """``ctx.config`` of the newest "billing: fetched credits config" line in
    ``logs/unified.jsonl``, or None."""
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
                return config
    except OSError:
        return None
    return None


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


async def poll(client: httpx.AsyncClient | None = None, now: float | None = None) -> ProviderResult:
    """Billing endpoint first, then the log fallback. ``reason`` lands in
    ``extra`` only on failure (``to_payload`` drops it); it never holds the token."""
    now = time.time() if now is None else now
    home = grok_home()
    token = read_token(now, home)
    reason = "no valid token" if token is None else ""
    if token:
        own_client = client is None
        client = client or httpx.AsyncClient(timeout=TIMEOUT)
        try:
            res, reason = await _fetch(client, token, home, now)
        finally:
            if own_client:
                await client.aclose()
        if res:
            return res
    fallback = parse_config(latest_log_config(home), now)
    if fallback:
        return fallback
    return ProviderResult(id="grok", bars=[], ok=False,
                          extra={"reason": f"{reason}; no billing line in logs/unified.jsonl"})
