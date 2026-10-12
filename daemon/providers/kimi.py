"""Kimi (Kimi Code) provider: ``GET ${KIMI_CODE_BASE_URL}/usages``.

The bearer token is the freshest non-expired ``access_token`` among
``${KIMI_CODE_HOME:-~/.kimi-code}/credentials/*.json`` (``expires_at`` is epoch
seconds). We never refresh it. Response ``usages.limit_5h`` and
``usages.limit_7d`` carry ``used_ratio`` (0-1, int/float or numeric string)
and ``reset_time`` (ISO-8601 UTC).
"""

import json
import os
import time
from pathlib import Path

import httpx

from .base import ProviderResult, iso_to_epoch, window_bar

DEFAULT_BASE_URL = "https://api.kimi.com/coding/v1"
TIMEOUT = 10.0


def kimi_home() -> Path:
    return Path(os.environ.get("KIMI_CODE_HOME") or (Path.home() / ".kimi-code")).expanduser()


def base_url() -> str:
    return (os.environ.get("KIMI_CODE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def read_token(now: float, home: Path | None = None) -> str | None:
    """Freshest non-expired access token, or None."""
    creds_dir = (home or kimi_home()) / "credentials"
    best_exp = None
    best_tok = None
    try:
        files = sorted(creds_dir.glob("*.json"))
    except OSError:
        return None
    for path in files:
        try:
            blob = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(blob, dict):
            continue
        tok = blob.get("access_token")
        try:
            exp = float(blob.get("expires_at"))
        except (TypeError, ValueError):
            continue
        if exp > 1e12:  # defensively accept epoch milliseconds
            exp /= 1000.0
        if not tok or exp <= now:
            continue
        if best_exp is None or exp > best_exp:
            best_exp, best_tok = exp, tok
    return best_tok


def _ratio_pct(value) -> float:
    try:
        return float(value) * 100.0
    except (TypeError, ValueError):
        return 0.0


def parse_usages(body: dict, now: float) -> ProviderResult:
    usages = body.get("usages") if isinstance(body, dict) else None
    if not isinstance(usages, dict):
        return ProviderResult(id="kimi", bars=[], ok=False)

    def bar(label: str, key: str):
        item = usages.get(key) or {}
        if not isinstance(item, dict):
            item = {}
        return window_bar(label, _ratio_pct(item.get("used_ratio", 0)),
                          iso_to_epoch(item.get("reset_time")), now)

    return ProviderResult(id="kimi", bars=[bar("5h", "limit_5h"), bar("Weekly", "limit_7d")])


async def poll(client: httpx.AsyncClient | None = None, now: float | None = None) -> ProviderResult:
    """Fetch and map Kimi usage. Any failure (no live token, HTTP or network
    error, malformed body) yields ``ok=False``; ``last_error`` is recorded in
    ``extra`` for logging only (``to_payload`` drops it on failure)."""
    now = time.time() if now is None else now
    token = read_token(now)
    if not token:
        return ProviderResult(id="kimi", bars=[], ok=False, extra={"reason": "no valid token"})
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        try:
            resp = await client.get(f"{base_url()}/usages", headers=headers)
        except httpx.HTTPError as e:
            return ProviderResult(id="kimi", bars=[], ok=False, extra={"reason": f"request failed: {e}"})
    finally:
        if own_client:
            await client.aclose()
    if resp.status_code >= 400:
        return ProviderResult(id="kimi", bars=[], ok=False, extra={"reason": f"HTTP {resp.status_code}"})
    try:
        body = resp.json()
    except ValueError:
        return ProviderResult(id="kimi", bars=[], ok=False, extra={"reason": "invalid JSON"})
    return parse_usages(body, now)
