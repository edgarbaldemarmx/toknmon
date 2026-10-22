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
from pathlib import Path

Bar = tuple[str, int, int]  # (label, percent 0-100, minutes until reset)


# (credits held, credits used in the trailing 30 days, minutes until the
# soonest held credit expires or None when unknown) -> ``rc``/``ru``/``rm``.
ResetCredits = tuple[int, int, int | None]


@dataclass
class ProviderResult:
    id: str
    bars: list[Bar]
    status: str = "allowed"
    ok: bool = True
    extra: dict = field(default_factory=dict)
    # Codex reset credits; None when the provider has none or the fetch failed
    # (the keys are then absent from the payload).
    credits: ResetCredits | None = None


@dataclass(frozen=True)
class DetectResult:
    """Outcome of a cheap, local, network-free check for one provider: is its
    CLI installed and logged in on this machine? ``reason`` is a one-line,
    human-readable explanation suitable for the installer and the daemon log
    (where to look, how to enable the provider). It never contains a token."""
    available: bool
    reason: str


def tilde(path: Path) -> str:
    """Render a path under the home directory as ``~/...`` for messages."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


SESSION_KEYS = ("s", "sr")
WEEKLY_KEYS = ("w", "wr")
MODEL_KEYS = ("f", "fr")
MODEL_LABEL_KEY = "fl"
MODEL_LABEL_MAX = 11   # the firmware's label buffer holds 11 chars + NUL
CREDIT_KEYS = ("rc", "ru", "rm")   # held, used (30 days), minutes to soonest expiry
_KEYS_BY_LABEL = {"5h": SESSION_KEYS, "Current": SESSION_KEYS, "Weekly": WEEKLY_KEYS}


def bar_keys(label: str) -> tuple[str, str]:
    """Payload keys for a bar label (see the module docstring)."""
    return _KEYS_BY_LABEL.get(label, MODEL_KEYS)


def model_label(label: str) -> str:
    """The model bar's label as ``fl``: printable ASCII, whitespace collapsed,
    at most MODEL_LABEL_MAX characters ("" when nothing is left)."""
    ascii_only = "".join(c for c in label if 32 <= ord(c) < 127)
    return " ".join(ascii_only.split())[:MODEL_LABEL_MAX].rstrip()


def to_payload(res: ProviderResult) -> dict:
    """Map a result to the BLE payload. A failed result is the minimal
    ``{"p": id, "ok": false}`` so the device can mark that provider stale.
    Only present bars emit keys; the first bar claiming a key pair wins. The
    model-scoped bar also sends its label as ``fl``. Reset credits, when the
    result carries them, go out as ``rc``/``ru`` and ``rm`` (the latter only
    when the expiry is known)."""
    if not res.ok:
        return {"p": res.id, "ok": False}
    payload: dict = {"p": res.id}
    for label, pct, reset_mins in res.bars:
        pct_key, reset_key = bar_keys(label)
        if pct_key in payload:
            continue
        payload[pct_key] = pct
        payload[reset_key] = reset_mins
        if (pct_key, reset_key) == MODEL_KEYS and model_label(label):
            payload[MODEL_LABEL_KEY] = model_label(label)
    payload["st"] = res.status
    if res.credits is not None:
        held, used, expires_mins = res.credits
        payload["rc"] = held
        payload["ru"] = used
        if expires_mins is not None:
            payload["rm"] = expires_mins
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
