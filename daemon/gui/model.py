"""Pure view-model for the ToknMon menu-bar app.

Everything the menu shows or writes is decided here from plain dicts and
strings, so it is unit-testable without AppKit; ``menubar.py`` only wires
these functions to ``rumps``. Inputs are the daemon's ``status.json``
(see ``build_status`` in ``claude_usage_daemon.py``) and the ``key = value``
config read through ``ConfigStore``.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

APP_NAME = "ToknMon"
DEFAULT_DEVICE_NAME = "ToknMon"
DEVICE_NAME_MAX_LEN = 18
# Registry order of the daemon's providers (also the menu order).
PROVIDERS = ("claude", "codex", "kimi", "grok")
PROVIDER_NAMES = {"claude": "Claude", "codex": "Codex", "kimi": "Kimi", "grok": "Grok"}
# status.json older than this means the daemon stopped writing: show offline.
STALE_AFTER = 180
SEP = " · "

SOUND_KEYS = {"Chime": "chime", "Beep": "beep"}
CLOCK_LABELS = ("Off", "Auto", "12h", "24h")
_CLOCK_VALUES = {"Off": "off", "Auto": "auto", "12h": "12", "24h": "24"}


# ---------------------------------------------------------------------------
# status lines
# ---------------------------------------------------------------------------

def provider_name(pid: str) -> str:
    return PROVIDER_NAMES.get(pid, pid.capitalize())


def provider_line(pid: str, data: dict | None) -> str:
    """``"Claude · 5h 32% · week 61%"``; only the windows present in the
    payload are shown, a failed or empty payload reads ``"<Name> · no data"``."""
    parts: list[str] = []
    if data and data.get("ok"):
        if "s" in data:
            parts.append(f"5h {data['s']}%")
        if "w" in data:
            parts.append(f"week {data['w']}%")
        if "f" in data:
            parts.append(f"{data.get('fl') or 'model'} {data['f']}%")
        if "rc" in data:
            parts.append(f"resets {data['rc']} held")
    if not parts:
        parts.append("no data")
    return SEP.join([provider_name(pid), *parts])


def provider_lines(status: dict | None) -> list[str]:
    """One line per provider present in ``status["providers"]``, registry
    order first, unknown ids after."""
    providers = (status or {}).get("providers") or {}
    order = [p for p in PROVIDERS if p in providers] + \
            [p for p in providers if p not in PROVIDERS]
    return [provider_line(pid, providers[pid]) for pid in order]


def is_connected(status: dict | None, now: float | None = None) -> bool:
    if not status or not status.get("connected"):
        return False
    now = time.time() if now is None else now
    return (now - float(status.get("ts") or 0)) <= STALE_AFTER


def device_line(status: dict | None, *, now: float | None = None,
                config_name: str | None = None) -> str:
    name = (status or {}).get("device_name") or config_name or DEFAULT_DEVICE_NAME
    state = "connected" if is_connected(status, now) else "offline"
    return f"Device: {name}{SEP}{state}"


# ---------------------------------------------------------------------------
# device name
# ---------------------------------------------------------------------------

def is_valid_device_name(name) -> bool:
    """Same rule as the daemon and the installer: 1..18 printable ASCII, no
    ``#`` (comment marker), no surrounding whitespace."""
    if not isinstance(name, str) or not 1 <= len(name) <= DEVICE_NAME_MAX_LEN:
        return False
    if not name.isascii() or not name.isprintable() or "#" in name:
        return False
    return name == name.strip()


# ---------------------------------------------------------------------------
# apps
# ---------------------------------------------------------------------------

def focus_enabled(apps: str | None) -> bool:
    if apps is None or not apps.strip():
        return True   # unset = daemon default = meter,focus
    return "focus" in {p.strip().lower() for p in apps.split(",")}


def apps_value(*, focus: bool) -> str:
    return "meter,focus" if focus else "meter"


# ---------------------------------------------------------------------------
# providers submenu
# ---------------------------------------------------------------------------

def _provider_list(setting: str | None) -> list[str]:
    if setting is None or setting.strip().lower() in ("", "auto"):
        return []
    wanted = {p.strip().lower() for p in setting.split(",") if p.strip()}
    return [p for p in PROVIDERS if p in wanted]


def provider_states(setting: str | None) -> dict[str, bool]:
    chosen = _provider_list(setting)
    return {"auto": not chosen, **{p: p in chosen for p in PROVIDERS}}


def toggle_provider(setting: str | None, pid: str) -> str:
    """New ``providers`` value after (un)checking ``pid``. Leaving ``auto``
    starts an explicit list with just that provider; emptying the list goes
    back to ``auto``."""
    chosen = set(_provider_list(setting))
    chosen ^= {pid}
    ordered = [p for p in PROVIDERS if p in chosen]
    return ", ".join(ordered) if ordered else "auto"


def select_auto() -> str:
    return "auto"


# ---------------------------------------------------------------------------
# sound and clock
# ---------------------------------------------------------------------------

def onoff(enabled: bool) -> str:
    return "on" if enabled else "off"


def sound_states(config: dict) -> dict[str, bool]:
    return {label: (config.get(key) or "").strip().lower() == "on"
            for label, key in SOUND_KEYS.items()}


def clock_states(value: str | None) -> dict[str, bool]:
    current = (value or "off").strip().lower()
    if current not in _CLOCK_VALUES.values():
        current = "off"
    return {label: _CLOCK_VALUES[label] == current for label in CLOCK_LABELS}


def clock_value(label: str) -> str:
    return _CLOCK_VALUES[label]


# ---------------------------------------------------------------------------
# about
# ---------------------------------------------------------------------------

def read_version(path: str | os.PathLike[str]) -> str:
    try:
        text = Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return "dev"
    return text or "dev"


def about_text(version: str) -> str:
    return (f"{APP_NAME} {version}\n\n"
            "Desk-side usage monitor for Claude Code, Codex CLI, Kimi Code and "
            "Grok Build CLI.\n"
            "Derived from Clawdmeter by Hermann Bjorgvin.\n\n"
            "This menu edits ~/.config/toknmon/config; the daemon re-reads it on "
            "its next poll.")
