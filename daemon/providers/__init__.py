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
"""

from collections.abc import Callable

from .base import (  # noqa: F401  (re-exported)
    Bar, ProviderResult, clamp_pct, iso_to_epoch, minutes_until, to_payload, window_bar,
)
from . import claude, codex, kimi

DEFAULT_PROVIDERS = ["claude"]

PROVIDERS: dict[str, Callable] = {
    "claude": claude.poll,
    "codex": codex.poll,
    "kimi": kimi.poll,
}


def parse_providers_setting(value: str | None, log: Callable[[str], None] | None = None) -> list[str]:
    """Parse the ``providers`` config value: comma-separated, case-insensitive,
    de-duplicated, order preserved. Unknown names are dropped (and logged);
    an empty or fully unknown list falls back to ``["claude"]``."""
    if not value:
        return list(DEFAULT_PROVIDERS)
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
    return out or list(DEFAULT_PROVIDERS)
