"""Usage providers for the ToknMon daemon.

Importable both as ``daemon.providers`` (tests) and ``providers`` (launchd runs
``claude_usage_daemon.py`` as a script with ``daemon/`` as ``sys.path[0]``);
only relative imports are used inside the package for that reason.

``PROVIDERS`` maps a provider id to an async ``poll() -> ProviderResult``
callable for the providers that need no per-call input. Claude is polled
through :func:`claude.poll` with the token the main module already resolves,
so its registry entry is a token-less stub that the main module replaces.

Payload contract (see :mod:`.base`): bars map to ``s/sr``, ``w/wr``, ``f/fr``
by label, and a bar a provider does not have is simply absent from the payload.
Providers that need daemon config (Kimi's ``kimi_token_url``) read it through
``kimi.read_config``, which the main module points at ``read_config_value``.

Detection (``providers = auto``, the default): :func:`detect` answers "is this
provider's CLI installed and logged in here?" from local files only — no
network — and :func:`resolve_providers` turns the config setting into the list
to poll. Claude's detector reads the token through hooks the main module
injects (``claude.config_dirs`` / ``claude.token_source``).
"""

from collections.abc import Callable

from .base import (  # noqa: F401  (re-exported)
    Bar, DetectResult, ProviderResult, clamp_pct, iso_to_epoch, minutes_until, to_payload,
    window_bar,
)
from . import claude, codex, kimi


class _Auto:
    """Sentinel for ``providers = auto``: poll whatever :func:`detect` finds."""

    def __repr__(self) -> str:
        return "AUTO"


AUTO = _Auto()
AUTO_KEYWORD = "auto"

PROVIDERS: dict[str, Callable] = {
    "claude": claude.poll,
    "codex": codex.poll,
    "kimi": kimi.poll,
}

# Same keys as PROVIDERS; each returns a DetectResult without touching the
# network. Tests swap entries to simulate machines with other CLIs installed.
DETECTORS: dict[str, Callable[[], DetectResult]] = {
    "claude": claude.detect,
    "codex": codex.detect,
    "kimi": kimi.detect,
}


def detect(provider_id: str) -> DetectResult:
    """Cheap local availability check for one provider (see :data:`DETECTORS`).
    An unknown id or a detector that raises is reported as unavailable."""
    detector = DETECTORS.get(provider_id)
    if detector is None:
        return DetectResult(False, f"unknown provider '{provider_id}' (known: {', '.join(PROVIDERS)})")
    try:
        return detector()
    except Exception as e:  # detection must never take the daemon down
        return DetectResult(False, f"{provider_id} detection failed: {e!r}")


def resolve_providers(setting) -> tuple[list[str], dict[str, str]]:
    """Turn a parsed ``providers`` setting into ``(providers to poll, skipped)``.

    An explicit list is honored as-is, even for providers detection would
    reject (the user asked for them; they report ``ok: false`` when polled).
    :data:`AUTO` keeps the available providers in registry order and maps each
    skipped id to its detection reason.
    """
    if setting is not AUTO:
        return list(setting), {}
    chosen: list[str] = []
    skipped: dict[str, str] = {}
    for pid in PROVIDERS:
        res = detect(pid)
        if res.available:
            chosen.append(pid)
        else:
            skipped[pid] = res.reason
    return chosen, skipped


def parse_providers_setting(value: str | None, log: Callable[[str], None] | None = None):
    """Parse the ``providers`` config value.

    Absent, empty or ``auto`` (case-insensitive) yields the :data:`AUTO`
    sentinel. Otherwise: comma-separated, case-insensitive, de-duplicated,
    order preserved. Unknown names are dropped (and logged); a fully unknown
    list falls back to :data:`AUTO`.
    """
    if not value or value.strip().lower() == AUTO_KEYWORD:
        return AUTO
    out: list[str] = []
    for raw in value.split(","):
        name = raw.strip().lower()
        if not name:
            continue
        if name not in PROVIDERS:
            if log:
                log(f"Unknown provider '{name}' in config (known: {', '.join(PROVIDERS)}); ignoring")
            continue
        if name not in out:
            out.append(name)
    return out or AUTO
