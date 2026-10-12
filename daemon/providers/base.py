"""Provider-agnostic result type and the BLE payload contract.

Every provider returns a :class:`ProviderResult`; :func:`to_payload` maps it to
the fixed JSON contract the firmware parses::

    {"p":"claude","s":17,"sr":110,"w":73,"wr":860,"f":1,"fr":860,"st":"allowed","ok":true, ...extra}
    {"p":"kimi","ok":false}

Bars are keyed by label, not position: ``"5h"``/``"Current"`` -> ``s/sr``
(current window), ``"Weekly"`` -> ``w/wr``, any other label -> ``f/fr``
(model-scoped weekly, e.g. Fable). A provider that has no such window simply
omits the bar and the keys are absent from the payload (a weekly-only Codex
plan sends ``w/wr`` and no ``s/sr``); the firmware treats a missing key as
"no window". Labels stay in the result for logging; the firmware owns display
text.
"""

import datetime
import time
from dataclasses import dataclass, field

Bar = tuple[str, int, int]  # (label, percent 0-100, minutes until reset)


@dataclass
class ProviderResult:
    id: str
    bars: list[Bar]
    status: str = "allowed"
    ok: bool = True
    extra: dict = field(default_factory=dict)


SESSION_KEYS = ("s", "sr")
WEEKLY_KEYS = ("w", "wr")
MODEL_KEYS = ("f", "fr")
_KEYS_BY_LABEL = {"5h": SESSION_KEYS, "Current": SESSION_KEYS, "Weekly": WEEKLY_KEYS}


def bar_keys(label: str) -> tuple[str, str]:
    """Payload keys for a bar label (see the module docstring)."""
    return _KEYS_BY_LABEL.get(label, MODEL_KEYS)


def to_payload(res: ProviderResult) -> dict:
    """Map a result to the BLE payload. A failed result is the minimal
    ``{"p": id, "ok": false}`` so the device can mark that provider stale.
    Only present bars emit keys; the first bar claiming a key pair wins."""
    if not res.ok:
        return {"p": res.id, "ok": False}
    payload: dict = {"p": res.id}
    for label, pct, reset_mins in res.bars:
        pct_key, reset_key = bar_keys(label)
        if pct_key in payload:
            continue
        payload[pct_key] = pct
        payload[reset_key] = reset_mins
    payload["st"] = res.status
    payload.update(res.extra)
    payload["ok"] = True
    return payload


def clamp_pct(value) -> int:
    """Coerce a percentage (int, float or numeric string) into 0..100."""
    try:
        pct = int(round(float(value)))
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, pct))


def minutes_until(reset_epoch: float | None, now: float | None = None) -> int:
    """Whole minutes from ``now`` to ``reset_epoch``, clamped at 0 (same
    rounding as the legacy header probe)."""
    if reset_epoch is None:
        return 0
    now = time.time() if now is None else now
    mins = (reset_epoch - now) / 60.0
    return int(round(mins)) if mins > 0 else 0


def iso_to_epoch(ts) -> float | None:
    """Parse an ISO-8601 timestamp (``Z`` or offset suffix) to epoch seconds."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def window_bar(label: str, pct, reset_epoch: float | None, now: float) -> Bar:
    """Build one bar; a window whose reset is already in the past reads 0%."""
    if reset_epoch is not None and reset_epoch < now:
        return (label, 0, 0)
    return (label, clamp_pct(pct), minutes_until(reset_epoch, now))
