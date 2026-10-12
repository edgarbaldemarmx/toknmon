"""Kimi (Kimi Code) provider: ``GET ${KIMI_CODE_BASE_URL}/usages``.

The bearer token is the freshest ``access_token`` among
``${KIMI_CODE_HOME:-~/.kimi-code}/credentials/*.json`` (``expires_at`` is epoch
seconds). Kimi access tokens live ~15 minutes and the CLI only refreshes them
while it runs, so when no token is valid (or the freshest one expires within
``REFRESH_MARGIN_S``) the daemon refreshes it the same way the CLI does and
writes the result back to the same credential file.

Refresh contract, read out of the Kimi CLI bundle (``~/.kimi-code/bin/kimi``
v2.1.1, ``packages/oauth/src/oauth.ts``): ``POST
${KIMI_CODE_OAUTH_HOST:-https://auth.kimi.com}/api/oauth/token`` with an
``application/x-www-form-urlencoded`` body ``client_id=<CLIENT_ID>``,
``grant_type=refresh_token``, ``refresh_token=<token>``; the 200 response is
JSON ``access_token``, ``refresh_token``, ``expires_in`` (seconds), ``scope``,
``token_type``, persisted as ``expires_at = now + expires_in``. The CLI writes
the file via ``<name>.json.tmp.*`` + rename with mode 0600; we do the same.
The URL can be overridden with the ``kimi_token_url`` config key.

Response ``usages.limit_5h`` and ``usages.limit_7d`` carry ``used_ratio`` (0-1,
int/float or numeric string) and ``reset_time`` (ISO-8601 UTC).
"""

import json
import os
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from .base import DetectResult, ProviderResult, iso_to_epoch, tilde, window_bar

DEFAULT_BASE_URL = "https://api.kimi.com/coding/v1"
DEFAULT_OAUTH_HOST = "https://auth.kimi.com"
TOKEN_PATH = "/api/oauth/token"
# OAuth client id of the Kimi Code CLI (KIMI_CODE_FLOW_CONFIG in the bundle).
CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"
TIMEOUT = 10.0
# Refresh when the freshest token expires within this many seconds.
REFRESH_MARGIN_S = 60
USER_AGENT = "toknmon-daemon"

# Config accessor injected by the main module (``read_config_value``); the
# providers package cannot import the daemon module. Default: no config.
read_config: Callable[[str], str | None] = lambda key: None


class RefreshError(Exception):
    """Token refresh failed; the credential file was left untouched."""


def kimi_home() -> Path:
    return Path(os.environ.get("KIMI_CODE_HOME") or (Path.home() / ".kimi-code")).expanduser()


def base_url() -> str:
    return (os.environ.get("KIMI_CODE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def token_url() -> str:
    """Refresh endpoint: ``kimi_token_url`` config key, else the CLI's own
    ``KIMI_CODE_OAUTH_HOST``/``KIMI_OAUTH_HOST`` env override, else the default."""
    configured = (read_config("kimi_token_url") or "").strip()
    if configured:
        return configured
    host = (os.environ.get("KIMI_CODE_OAUTH_HOST") or os.environ.get("KIMI_OAUTH_HOST")
            or DEFAULT_OAUTH_HOST).rstrip("/")
    return f"{host}{TOKEN_PATH}"


def _expires_at(blob: dict) -> float | None:
    try:
        exp = float(blob.get("expires_at"))
    except (TypeError, ValueError):
        return None
    if exp > 1e12:  # defensively accept epoch milliseconds
        exp /= 1000.0
    return exp


def read_credentials(home: Path | None = None) -> tuple[Path, dict] | None:
    """The credential file with the latest ``expires_at`` (expired or not) and
    its parsed content, or None when there is no usable file."""
    creds_dir = (home or kimi_home()) / "credentials"
    best: tuple[float, Path, dict] | None = None
    try:
        files = sorted(creds_dir.glob("*.json"))
    except OSError:
        return None
    for path in files:
        try:
            blob = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if not isinstance(blob, dict) or not blob.get("access_token"):
            continue
        exp = _expires_at(blob)
        if exp is None:
            continue
        if best is None or exp > best[0]:
            best = (exp, path, blob)
    return (best[1], best[2]) if best else None


def detect() -> DetectResult:
    """The Kimi Code CLI is usable when a credential file with an access token
    exists under ``$KIMI_CODE_HOME/credentials``; an expired token is fine
    because the daemon refreshes it the way the CLI does."""
    creds_dir = kimi_home() / "credentials"
    shown = tilde(creds_dir)
    try:
        files = sorted(creds_dir.glob("*.json")) if creds_dir.is_dir() else []
    except OSError:
        files = []
    if not files:
        return DetectResult(False, f"Kimi Code CLI not found: {shown} has no credential files. "
                                   "Install the Kimi Code CLI and run it once to log in.")
    if read_credentials() is None:
        return DetectResult(False, f"Kimi Code CLI not usable: no credential file in {shown} "
                                   "has an access token. Run the Kimi Code CLI once to log in.")
    return DetectResult(True, f"Kimi Code credentials found ({shown})")


def read_token(now: float, home: Path | None = None) -> str | None:
    """Freshest non-expired access token, or None (no refresh)."""
    found = read_credentials(home)
    if found is None:
        return None
    _path, blob = found
    exp = _expires_at(blob)
    return blob["access_token"] if exp is not None and exp > now else None


def _write_credentials_atomic(path: Path, blob: dict) -> None:
    """Write ``blob`` as ``<path>.tmp.<pid>`` then rename over ``path``,
    keeping mode 0600 (the CLI's own write semantics)."""
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    data = json.dumps(blob, indent=2) + "\n"
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
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


async def refresh_access_token(cred_path: Path, client: httpx.AsyncClient | None = None,
                               now: float | None = None, url: str | None = None) -> dict:
    """POST the refresh grant for ``cred_path`` and persist the new token set
    back to the same file. Returns the updated credential dict. Raises
    :class:`RefreshError` on any failure (nothing is written in that case).
    Exactly one request: callers never retry within a poll."""
    now = time.time() if now is None else now
    url = url or token_url()
    if not url.lower().startswith("https://"):
        raise RefreshError(f"refresh refused: token URL is not https ({url})")
    try:
        blob = json.loads(cred_path.read_text())
    except (OSError, ValueError) as e:
        raise RefreshError(f"cannot read credentials: {e}") from e
    if not isinstance(blob, dict) or not blob.get("refresh_token"):
        raise RefreshError("no refresh_token in credentials")
    form = {"client_id": CLIENT_ID, "grant_type": "refresh_token", "refresh_token": blob["refresh_token"]}
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        try:
            resp = await client.post(url, data=form, headers=headers)
        except httpx.HTTPError as e:
            raise RefreshError(f"refresh request failed: {e}") from e
    finally:
        if own_client:
            await client.aclose()
    if resp.status_code != 200:
        raise RefreshError(f"refresh HTTP {resp.status_code}")
    try:
        body = resp.json()
    except ValueError as e:
        raise RefreshError("refresh response is not JSON") from e
    token = body.get("access_token") if isinstance(body, dict) else None
    try:
        expires_in = int(float(body.get("expires_in"))) if isinstance(body, dict) else 0
    except (TypeError, ValueError):
        expires_in = 0
    if not isinstance(token, str) or not token or expires_in <= 0:
        raise RefreshError("refresh response missing access_token/expires_in")
    updated = dict(blob)
    updated["access_token"] = token
    updated["expires_at"] = int(now) + expires_in
    updated["expires_in"] = expires_in
    if isinstance(body.get("refresh_token"), str) and body["refresh_token"]:
        updated["refresh_token"] = body["refresh_token"]
    for key in ("scope", "token_type"):
        if isinstance(body.get(key), str) and body[key]:
            updated[key] = body[key]
    try:
        _write_credentials_atomic(cred_path, updated)
    except OSError as e:
        raise RefreshError(f"cannot write credentials: {e}") from e
    return updated


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


async def _resolve_token(client: httpx.AsyncClient, now: float) -> tuple[str | None, str]:
    """(access token, failure reason). Refreshes the freshest credential file
    when its token is expired or expires within ``REFRESH_MARGIN_S``."""
    found = read_credentials()
    if found is None:
        return None, "no credentials"
    path, blob = found
    exp = _expires_at(blob)
    if exp is not None and exp > now + REFRESH_MARGIN_S:
        return blob["access_token"], ""
    try:
        updated = await refresh_access_token(path, client, now)
    except RefreshError as e:
        return None, f"token expired and {e}"
    return updated["access_token"], ""


async def poll(client: httpx.AsyncClient | None = None, now: float | None = None) -> ProviderResult:
    """Fetch and map Kimi usage. Any failure (no live token and refresh failed,
    HTTP or network error, malformed body) yields ``ok=False``; ``reason`` is
    recorded in ``extra`` for logging only (``to_payload`` drops it on failure)."""
    now = time.time() if now is None else now
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=TIMEOUT)
    try:
        token, reason = await _resolve_token(client, now)
        if not token:
            return ProviderResult(id="kimi", bars=[], ok=False, extra={"reason": reason})
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
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
