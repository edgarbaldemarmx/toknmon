"""Claude provider: ``GET https://api.anthropic.com/api/oauth/usage``.

Reads the OAuth usage summary Claude Code itself shows (``/usage``), which
exposes the 5h session window, the all-models weekly window and any
model-scoped weekly window (e.g. Fable) — the latter is invisible to the
legacy rate-limit header probe. The token comes from the caller (keychain or
``.credentials.json``, resolved by the main module); this module never
refreshes it.
"""

import httpx

from .base import DetectResult, ProviderResult, iso_to_epoch, tilde, window_bar
import time
from collections.abc import Callable
from pathlib import Path

USAGE_URL = "https://api.anthropic.com/api/oauth/usage"
# Newer endpoints reject old client versions (2.1.5 is refused); keep current.
USER_AGENT = "claude-code/2.1.296"
HEADERS_TEMPLATE = {
    "anthropic-beta": "oauth-2025-04-20",
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}
TIMEOUT = 20.0


# Detection hooks injected by the main module (the package cannot import it):
# ``config_dirs()`` lists the Claude config dirs to check and
# ``token_source(dir)`` names where a usable OAuth token for that dir lives
# ("macOS Keychain" or the ``.credentials.json`` path) or returns None. The
# defaults make detection fail closed when nothing is injected.
config_dirs: Callable[[], list[Path]] = lambda: [Path.home() / ".claude"]
token_source: Callable[[Path], str | None] = lambda config_dir: None


def detect() -> DetectResult:
    """Claude Code is usable when any configured dir has an OAuth token source.
    Local and cheap: reads the Keychain/credentials file through the injected
    hook, never logs and never returns the token itself."""
    dirs = config_dirs() or [Path.home() / ".claude"]
    for config_dir in dirs:
        source = token_source(config_dir)
        if source:
            return DetectResult(True, f"Claude Code credentials found ({source})")
    where = " or ".join(f"{tilde(d)}/.credentials.json" for d in dirs)
    return DetectResult(
        False,
        "Claude Code CLI not found: no OAuth token in the macOS Keychain "
        f'("Claude Code-credentials") or in {where}. Install Claude Code and run '
        "`claude login` once.")


class TokenExpired(Exception):
    """Raised on a 401/403 — the access token is dead. The daemon never
    refreshes (pure free-ride: Claude Code owns refreshing), so the caller just
    signals "No data" to the device until the CLI re-seeds the token."""


class UsageUnavailable(Exception):
    """The usage endpoint did not answer with a usable body (non-auth 4xx such
    as Enterprise accounts, 5xx, network error). Callers fall back to the
    legacy rate-limit header probe."""


def _status_of(items: list[dict]) -> str:
    for item in items:
        for key in ("status", "state"):
            val = item.get(key)
            if isinstance(val, str) and val and val != "allowed":
                return val
    return "allowed"


def parse_usage(body: dict, now: float | None = None) -> ProviderResult:
    """Map the ``limits[]`` array to bars: session -> 0, weekly_all -> 1, and
    the first model-scoped weekly limit -> 2 (label = model display name).

    Raises :class:`UsageUnavailable` when neither ``session`` nor
    ``weekly_all`` is present (e.g. an Enterprise account answering 200 with
    ``limits: []``) so the caller falls back to the header probe instead of
    showing 0/0 bars tagged as a Pro account.
    """
    now = time.time() if now is None else now
    limits = body.get("limits") or []
    by_kind: dict[str, dict] = {}
    scoped: dict | None = None
    for item in limits:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        if kind == "weekly_scoped":
            model = (item.get("scope") or {}).get("model") or {}
            if scoped is None and model.get("display_name"):
                scoped = item
        elif kind in ("session", "weekly_all") and kind not in by_kind:
            by_kind[kind] = item
    if not by_kind:
        raise UsageUnavailable("limits[] has no session or weekly_all window")

    def bar(label: str, item: dict | None):
        item = item or {}
        return window_bar(label, item.get("percent", 0), iso_to_epoch(item.get("resets_at")), now)

    bars = [bar("Current", by_kind.get("session")), bar("Weekly", by_kind.get("weekly_all"))]
    if scoped is not None:
        bars.append(bar(str(scoped["scope"]["model"]["display_name"]), scoped))
    status = _status_of([i for i in (by_kind.get("session"), by_kind.get("weekly_all")) if i])
    return ProviderResult(id="claude", bars=bars, status=status, extra={"acct": "pro"})


async def poll(token: str, client: httpx.AsyncClient | None = None,
               now: float | None = None) -> ProviderResult:
    """Fetch and map the usage summary for one access token.

    Raises :class:`TokenExpired` on 401/403 and :class:`UsageUnavailable` on
    any other failure so the caller can decide how to degrade.
    """
    headers = dict(HEADERS_TEMPLATE)
    headers["Authorization"] = f"Bearer {token}"
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        try:
            resp = await client.get(USAGE_URL, headers=headers)
        except httpx.HTTPError as e:
            raise UsageUnavailable(f"request failed: {e}") from e
    finally:
        if own_client:
            await client.aclose()
    if resp.status_code in (401, 403):
        raise TokenExpired()
    if resp.status_code >= 400:
        raise UsageUnavailable(f"HTTP {resp.status_code}: {resp.text[:120]}")
    try:
        body = resp.json()
    except ValueError as e:
        raise UsageUnavailable(f"invalid JSON: {e}") from e
    if not isinstance(body, dict) or "limits" not in body:
        raise UsageUnavailable("response has no limits[]")
    return parse_usage(body, now)
