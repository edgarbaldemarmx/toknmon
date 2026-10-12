"""Codex provider: rate limits from the local Codex CLI session logs.

Codex writes ``rate_limits`` into ``token_count`` events in
``${CODEX_HOME:-~/.codex}/sessions/**/rollout-*.jsonl``. We take the line with
the newest ``timestamp`` across files modified in the last 7 days. No network,
no auth. Bars are keyed by ``window_minutes`` (300 -> "5h", 10080 -> "Weekly"),
not by the primary/secondary slot, because weekly-only plans report the
weekly window as ``primary`` with ``secondary: null``.
"""

import json
import os
import time
from pathlib import Path

from .base import ProviderResult, window_bar

MAX_AGE_DAYS = 7
WINDOW_5H = 300
WINDOW_WEEKLY = 10080


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()


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
    return best


def parse_rate_limits(limits: dict, now: float) -> ProviderResult:
    windows: dict[int, dict] = {}
    for slot in ("primary", "secondary"):
        w = limits.get(slot)
        if isinstance(w, dict) and w.get("window_minutes") is not None:
            try:
                windows.setdefault(int(w["window_minutes"]), w)
            except (TypeError, ValueError):
                continue

    def bar(label: str, minutes: int):
        w = windows.get(minutes)
        if w is None:
            return (label, 0, 0)
        reset = w.get("resets_at")
        try:
            reset_epoch = float(reset) if reset is not None else None
        except (TypeError, ValueError):
            reset_epoch = None
        return window_bar(label, w.get("used_percent", 0), reset_epoch, now)

    bars = [bar("5h", WINDOW_5H), bar("Weekly", WINDOW_WEEKLY)]
    status = "allowed"
    if limits.get("rate_limit_reached_type"):
        status = str(limits["rate_limit_reached_type"])
    return ProviderResult(id="codex", bars=bars, status=status)


async def poll(now: float | None = None) -> ProviderResult:
    now = time.time() if now is None else now
    limits = latest_rate_limits(codex_home() / "sessions", now)
    if limits is None:
        return ProviderResult(id="codex", bars=[], ok=False)
    return parse_rate_limits(limits, now)
