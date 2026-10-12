"""Codex provider: rate limits from the local Codex CLI session logs.

Codex writes ``rate_limits`` into ``token_count`` events in
``${CODEX_HOME:-~/.codex}/sessions/**/rollout-*.jsonl``. We take the line with
the newest ``timestamp`` across files modified in the last 7 days. No network,
no auth. Bars are keyed by ``window_minutes`` (<= 10 h -> "5h", longer ->
"Weekly"), not by the primary/secondary slot, because weekly-only plans report
the weekly window as ``primary`` with ``secondary: null``. The mapping is
tolerant because Codex does not always report exactly 300/10080. A window the
plan does not report yields no bar at all (so no ``s/sr`` on weekly-only plans).
"""

import json
import os
import time
from pathlib import Path

from .base import ProviderResult, window_bar

MAX_AGE_DAYS = 7
# Windows up to this many minutes land on the short ("5h") bar, longer ones on
# the weekly bar. Nominal values are 300 and 10080.
SHORT_WINDOW_MAX_MINUTES = 600


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


async def poll(now: float | None = None) -> ProviderResult:
    now = time.time() if now is None else now
    limits = latest_rate_limits(codex_home() / "sessions", now)
    if limits is None:
        return ProviderResult(id="codex", bars=[], ok=False)
    return parse_rate_limits(limits, now)
