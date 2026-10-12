#!/usr/bin/env python3
"""Claude Usage Tracker Daemon (BLE) — macOS port of claude-usage-daemon.sh.

Polls Claude API rate-limit headers and writes a JSON payload to the
ESP32 "Clawdmeter" peripheral over a custom GATT service. Uses
bleak (CoreBluetooth backend on macOS).
"""

import asyncio
import calendar
import datetime
import getpass
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import httpx
from bleak import BleakClient
from bleak.exc import BleakError

# The providers package lives next to this file. Tests import this module as
# `daemon.claude_usage_daemon`; launchd runs it as a script (sys.path[0] is
# daemon/), so try the package-qualified import first and fall back to the
# sibling package.
try:
    from daemon.providers import PROVIDERS, parse_providers_setting, to_payload
    from daemon.providers import claude as claude_provider
except ImportError:  # running as a script from daemon/
    from providers import PROVIDERS, parse_providers_setting, to_payload
    from providers import claude as claude_provider

# BLE device name. The firmware default is "TokenMon"; users can rename their
# board (`name <text>` over USB serial, or via flash-mac.sh) and record the same
# name in the config as `device_name`. The daemon finds the device primarily by
# service UUID; the name only matters for the HID fallback and stale-bond repair,
# where any of accepted_device_names() is honored (configured + legacy names).
DEFAULT_DEVICE_NAME = "TokenMon"
LEGACY_DEVICE_NAMES = ("Clawdmeter",)
DEVICE_NAME_MAX_LEN = 18  # firmware advertising budget (bytes, printable ASCII)
SERVICE_UUID = "4c41555a-4465-7669-6365-000000000001"
RX_CHAR_UUID = "4c41555a-4465-7669-6365-000000000002"
REQ_CHAR_UUID = "4c41555a-4465-7669-6365-000000000004"

POLL_INTERVAL = 60
TICK = 5
CONNECT_TIMEOUT = 20.0

# macOS: token lives in Keychain (service "Claude Code-credentials").
# Linux: token lives in ~/.claude/.credentials.json.
KEYCHAIN_SERVICE = "Claude Code-credentials"
DEFAULT_CONFIG_DIR = Path.home() / ".claude"
SAVED_ADDR_FILE = Path.home() / ".config" / "claude-usage-monitor" / "ble-address"
CONFIG_FILE = Path.home() / ".config" / "claude-usage-monitor" / "config"
# Written by Claude Code hooks: `attention` holds {"m", "s"} (message, session
# id) when a session needs the user, and `clear-<session id>` is touched when
# that session moves on.
ATTENTION_DIR = Path.home() / ".config" / "claude-usage-monitor"
ATTENTION_FLAG = ATTENTION_DIR / "attention"
ATTENTION_MAX_AGE = 60
DEFAULT_MAX_WRITE = 180

API_URL = "https://api.anthropic.com/v1/messages"
API_HEADERS_TEMPLATE = {
    "anthropic-version": "2023-06-01",
    "anthropic-beta": "oauth-2025-04-20",
    "Content-Type": "application/json",
    "User-Agent": claude_provider.USER_AGENT,
}
API_BODY = {
    "model": "claude-haiku-4-5-20251001",
    "max_tokens": 1,
    "messages": [{"role": "user", "content": "hi"}],
}


# Raised by poll_api on a 401/403 — the access token is dead. The daemon never
# refreshes (pure free-ride: Claude Code owns refreshing), so the caller just
# signals "No data" to the device until the CLI re-seeds the token. Defined in
# the Claude provider so both the usage endpoint and the header probe share it.
TokenExpired = claude_provider.TokenExpired


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _extract_access_token(blob: str) -> str | None:
    """Pull the accessToken out of a credentials blob.

    Claude Code stores credentials as a JSON object; the blob may also be
    nested ({"claudeAiOauth": {"accessToken": "..."}}). Fall back to a
    regex match so unexpected shapes still work, and finally treat the
    blob as a raw token if nothing else matches.
    """
    blob = blob.strip()
    if not blob:
        return None
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, dict):
        # direct: {"accessToken": "..."}
        tok = data.get("accessToken")
        if isinstance(tok, str) and tok.strip():
            return tok
        # nested: {"claudeAiOauth": {"accessToken": "..."}}
        for v in data.values():
            if isinstance(v, dict):
                tok = v.get("accessToken")
                if isinstance(tok, str) and tok.strip():
                    return tok
    m = re.search(r'"accessToken"\s*:\s*"([^"]+)"', blob)
    if m:
        return m.group(1)
    # Raw token (no JSON wrapper) — must look plausible (sk-ant-... etc.)
    if re.fullmatch(r"[A-Za-z0-9_\-.~+/=]{20,}", blob):
        return blob
    return None


def _decode_keychain_blob(raw: str) -> str:
    """Transparently decode a hex-dumped Keychain secret back to text.

    ``security … -w`` prints the password as a continuous hex string whenever
    the stored bytes aren't cleanly printable (e.g. an embedded newline). A
    normal credentials blob is JSON, which is never valid hex (it contains
    '{', '"', …), so all-hex detection is unambiguous and safe.
    """
    s = raw.strip()
    if s and len(s) % 2 == 0 and re.fullmatch(r"[0-9a-fA-F]+", s):
        try:
            return bytes.fromhex(s).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return raw
    return raw


def _read_token_keychain() -> str | None:
    """Read the OAuth access token from the macOS Keychain, or None.

    ``security … -w`` may hex-dump the stored secret (see _decode_keychain_blob),
    so decode before extracting the access token.
    """
    try:
        out = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-a",
                getpass.getuser(),
                "-w",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except subprocess.CalledProcessError as e:
        log(f"Keychain read failed (rc={e.returncode}): {e.stderr.strip()}")
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        log(f"Keychain access error: {e}")
        return None
    return _extract_access_token(_decode_keychain_blob(out.stdout))


def read_config_dirs() -> list[Path]:
    """Claude config dirs to poll, from the `config_dirs` option (comma list).

    Defaults to [~/.claude] so existing single-plan setups are unchanged. ~ is
    expanded. Mirrors the Linux bash daemon's read_config_dirs.
    """
    raw = ""
    try:
        if CONFIG_FILE.exists():
            for line in CONFIG_FILE.read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip().lower() == "config_dirs":
                    raw = val.strip()
    except OSError:
        pass
    if not raw:
        return [DEFAULT_CONFIG_DIR]
    dirs = [Path(p.strip()).expanduser() for p in raw.split(",") if p.strip()]
    return dirs or [DEFAULT_CONFIG_DIR]


def _strip_comment(line: str) -> str:
    """Drop a trailing ``# comment``; a ``#`` inside a quoted value is kept."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def _unquote(val: str) -> str:
    """Strip one pair of matching surrounding quotes (``"..."`` or ``'...'``)."""
    if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
        return val[1:-1]
    return val


def read_config_value(key: str) -> str | None:
    """Return the raw (comment-stripped, trimmed, unquoted) value of one config key.

    Keys are matched case-insensitively; the last occurrence wins. Returns
    None when the file or the key is absent.
    """
    found = None
    try:
        if CONFIG_FILE.exists():
            for line in CONFIG_FILE.read_text().splitlines():
                line = _strip_comment(line).strip()
                if "=" not in line:
                    continue
                k, val = line.split("=", 1)
                if k.strip().lower() == key:
                    found = _unquote(val.strip())
    except OSError:
        pass
    return found


def is_valid_device_name(name) -> bool:
    """Firmware constraint for `device_name`: 1..DEVICE_NAME_MAX_LEN printable
    ASCII characters, no leading/trailing whitespace, no control characters and
    no ``#`` (every config reader treats it as a comment marker). Scripts that
    parse the config mirror these rules.
    """
    if not isinstance(name, str) or not 1 <= len(name) <= DEVICE_NAME_MAX_LEN:
        return False
    if not name.isascii() or not name.isprintable() or "#" in name:
        return False
    return name == name.strip()


def read_device_name() -> str:
    """Return the configured BLE device name (`device_name`), else the default.

    An invalid value (see :func:`is_valid_device_name`) falls back to
    DEFAULT_DEVICE_NAME with one log line.
    """
    val = read_config_value("device_name")
    if val is None:
        return DEFAULT_DEVICE_NAME
    if not is_valid_device_name(val):
        log(f"Invalid device_name {val!r} in config (1-{DEVICE_NAME_MAX_LEN} printable "
            f"ASCII, no '#'); using {DEFAULT_DEVICE_NAME!r}")
        return DEFAULT_DEVICE_NAME
    return val


def accepted_device_names() -> set[str]:
    """Names that identify our board: the configured one plus legacy names."""
    return {read_device_name(), *LEGACY_DEVICE_NAMES}


def is_device_name(name: str | None) -> bool:
    return name is not None and name in accepted_device_names()


def read_token_for(config_dir: Path) -> str | None:
    """Read the OAuth token for one config dir.

    Linux: each dir keeps its own ``<dir>/.credentials.json``. macOS: the default
    install stores the token in Keychain with no file, so for the default dir we
    fall back to Keychain when no file is present — preserving existing
    single-plan macOS behavior. Additional macOS dirs are read from their files;
    a work plan whose token lives only in the single Keychain entry can't be told
    apart there (documented follow-up).
    """
    cred = config_dir / ".credentials.json"
    try:
        if cred.exists():
            return _extract_access_token(cred.read_text())
    except OSError as e:
        log(f"Error reading credentials in {config_dir}: {e}")
    if sys.platform == "darwin" and config_dir == DEFAULT_CONFIG_DIR:
        return _read_token_keychain()
    return None


def load_cached_address() -> str | None:
    if not SAVED_ADDR_FILE.exists():
        return None
    addr = SAVED_ADDR_FILE.read_text().strip()
    # Accept both Linux MAC (AA:BB:CC:DD:EE:FF) and macOS CoreBluetooth UUID
    # (E621E1F8-C36C-495A-93FC-0C247A3E6E5F).
    if re.fullmatch(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", addr) or re.fullmatch(
        r"[0-9A-Fa-f]{8}-(?:[0-9A-Fa-f]{4}-){3}[0-9A-Fa-f]{12}", addr
    ):
        return addr
    log("Cached address malformed, discarding")
    SAVED_ADDR_FILE.unlink(missing_ok=True)
    return None


# --- macOS: recover a device the OS already holds as an HID keyboard --------
#
# The firmware advertises as a BLE HID keyboard so its buttons type into the
# Mac. macOS auto-connects to that HID, and CoreBluetooth then EXCLUDES the
# peripheral from BleakScanner.discover() results (already-connected devices
# never appear in scans). bleak's connect-by-address path also scans
# internally, so a cached address can't help either. The documented escape
# hatch is retrieveConnectedPeripheralsWithServices_, which returns
# peripherals the system is already connected to. We wrap the result in a
# BLEDevice carrying the live (peripheral, manager) details so BleakClient
# connects to it directly without scanning. CoreBluetooth shares the single
# physical link, so this rides the existing HID connection — the keyboard
# keeps working.
_cb_manager = None  # reused CentralManagerDelegate (CoreBluetooth)


async def _get_cb_manager():
    """Lazily create and ready a shared CoreBluetooth central manager."""
    global _cb_manager
    if _cb_manager is None:
        from bleak.backends.corebluetooth.CentralManagerDelegate import (
            CentralManagerDelegate,
        )

        mgr = CentralManagerDelegate()
        await mgr.wait_until_ready()  # raises if Bluetooth is unauthorized/off
        _cb_manager = mgr
    return _cb_manager


async def retrieve_connected_macos(skip_addr: str | None = None):
    """Return a BLEDevice for a system-connected 'Clawdmeter', or None.

    Two-step lookup, strongest signal first:

    1. Peripherals connected under our CUSTOM service UUID. Membership in
       that service is unambiguous (no other device exposes it), so we accept
       by service alone — the peripheral's name can be None on macOS.
    2. Fall back to the generic HID service 0x1812, but ONLY trust a
       peripheral whose name is one of accepted_device_names(). 0x1812 also matches
       unrelated keyboards/mice, so picking blindly here could grab the
       wrong device.

    ``skip_addr`` skips a peripheral whose UUID just failed to connect, so a
    stale CoreBluetooth handle can't trap us into never trying a fresh scan.
    """
    from CoreBluetooth import CBUUID
    from bleak.backends.device import BLEDevice

    try:
        manager = await _get_cb_manager()
    except Exception as e:  # BleakBluetoothNotAvailableError etc.
        log(f"CoreBluetooth unavailable: {e}")
        return None

    cm = manager.central_manager

    def _wrap(p):
        addr = p.identifier().UUIDString()
        log(f"Found system-connected peripheral: {p.name()!r} [{addr}]")
        return BLEDevice(addr, p.name(), (p, manager))

    def _ok(p) -> bool:
        return not (skip_addr and p.identifier().UUIDString() == skip_addr)

    # 1. Custom service — accept by service membership alone.
    custom = cm.retrieveConnectedPeripheralsWithServices_(
        [CBUUID.UUIDWithString_(SERVICE_UUID)]
    )
    for p in custom or []:
        if _ok(p):
            return _wrap(p)

    # 2. Generic HID service — require an exact name match (configured or legacy).
    hid = cm.retrieveConnectedPeripheralsWithServices_(
        [CBUUID.UUIDWithString_("1812")]
    )
    for p in hid or []:
        if _ok(p) and is_device_name(p.name()):
            return _wrap(p)

    return None


async def discover_target(skip_addr: str | None = None):
    """Return a connectable target, or None.

    The daemon only ever targets the device this system already holds — it
    never scans for a nearby device by name, so it can't grab a stranger's or
    the wrong nearby unit. On macOS that's the system-connected peripheral (the
    firmware advertises as an HID keyboard, so once paired the OS auto-connects
    and holds it — HID-grabbed devices are invisible to scans anyway). On other
    platforms it's a previously-pinned address in the cache file. If the device
    isn't held/pinned, we log and wait rather than scanning. ``skip_addr`` skips
    a peripheral whose handle just failed to connect.
    """
    if sys.platform == "darwin":
        dev = await retrieve_connected_macos(skip_addr=skip_addr)
        if dev is None:
            log("Device not held by OS; waiting (not scanning by name)")
        return dev

    address = load_cached_address()
    if not address:
        log("No pinned address cached; waiting (not scanning by name)")
    return address


def read_onoff_setting(name: str) -> str:
    """Read an off|on option from the config file.

    Defaults to "off" (the device stays silent) so existing setups are
    unaffected until the user opts in.
    """
    try:
        if CONFIG_FILE.exists():
            for line in CONFIG_FILE.read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip().lower() == name:
                    val = val.strip().lower()
                    if val in ("off", "on"):
                        return val
    except OSError:
        pass
    return "off"


def read_chime_setting() -> str:
    """Read the `chime` option (session-reset chime). One of: off|on."""
    return read_onoff_setting("chime")


def read_clock_setting() -> str:
    """Read the `clock` option from the config file. One of: off|auto|12|24.

    Defaults to "off" (no clock; the device keeps showing "Usage") so existing
    setups are unaffected until the user opts in.
    """
    try:
        if CONFIG_FILE.exists():
            for line in CONFIG_FILE.read_text().splitlines():
                line = line.split("#", 1)[0].strip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                if key.strip().lower() == "clock":
                    val = val.strip().lower()
                    if val in ("off", "auto", "12", "24"):
                        return val
    except OSError:
        pass
    return "off"


def add_chime_field(payload: dict) -> None:
    """Add "c":1 to the payload when the config opts in, so the firmware may
    sound the session-reset chime. Omitted entirely when chime is off."""
    if read_chime_setting() == "on":
        payload["c"] = 1


def detect_hour_format() -> int:
    """Best-effort 12h/24h detection for the host. Returns 12 or 24 (default 24)."""
    # macOS: the explicit System Settings toggle lives in NSGlobalDomain.
    for key, result in (("AppleICUForce24HourTime", 24), ("AppleICUForce12HourTime", 12)):
        try:
            out = subprocess.run(["defaults", "read", "-g", key],
                                 capture_output=True, text=True, timeout=3)
            if out.stdout.strip() == "1":
                return result
        except (OSError, subprocess.SubprocessError):
            pass
    # Fallback to the C locale's time format (may be C/24h under launchd).
    try:
        import locale
        locale.setlocale(locale.LC_TIME, "")
        fmt = locale.nl_langinfo(locale.T_FMT)
        if "%p" in fmt or "%r" in fmt or "%I" in fmt:
            return 12
    except (ImportError, locale.Error, AttributeError):
        pass
    return 24


def add_clock_fields(payload: dict) -> None:
    """Add wall-clock fields to the payload when the config opts in.

    "t"  = local wall-clock epoch (UTC epoch shifted by the tz offset) so the
           device can show the time without an RTC.
    "tf" = 12 or 24, the hour format the device should render.
    """
    clock = read_clock_setting()
    if clock == "off":
        return
    tf = 24 if clock == "24" else 12 if clock == "12" else detect_hour_format()
    payload["t"] = int(time.time()) + time.localtime().tm_gmtoff
    payload["tf"] = tf


def read_providers() -> list[str]:
    """Providers to poll this cycle (`providers = claude, codex, kimi`).

    Default (unset) is `["claude"]`, which keeps the single-provider payload
    byte-for-byte compatible with older firmware (no `p` field).
    """
    return parse_providers_setting(read_config_value("providers"), log=log)


def should_poll_now(elapsed: float, *, alert_pending: bool, refresh_requested: bool,
                    claude_enabled: bool, alert_poll_used: bool) -> bool:
    """Main-loop decision: poll the providers this tick?

    The poll interval and a device refresh request always win. A pending
    alert/clear may shortcut the interval once — the flags are cleared only by
    a successful Claude write, so without the ``alert_poll_used`` guard a
    transiently failing Claude would force a full provider poll every TICK.
    With Claude disabled the alert can never be delivered (see
    :func:`drop_undeliverable_alert`), so it never shortcuts the interval.
    """
    if refresh_requested or elapsed >= POLL_INTERVAL:
        return True
    return alert_pending and claude_enabled and not alert_poll_used


def drop_undeliverable_alert(providers: list[str], alert_pending: bool) -> bool:
    """True when a pending alert/clear must be dropped because Claude is not an
    enabled provider (alert extras ride only on the Claude payload). Logs once
    per dropped alert."""
    if not alert_pending or "claude" in providers:
        return False
    log("Alert dropped: Claude is not an enabled provider (alerts ride on the Claude payload)")
    return True


async def poll_api(token: str) -> dict | None:
    """Claude usage payload for one access token.

    Resolves through the OAuth usage endpoint first (sees the model-scoped
    weekly window the header probe cannot) and falls back to the legacy
    rate-limit header probe when that endpoint is unavailable for the account
    (Enterprise) or transiently failing. Raises TokenExpired on 401/403.
    """
    try:
        result = await claude_provider.poll(token)
    except claude_provider.UsageUnavailable as e:
        log(f"Usage endpoint unavailable ({e}); falling back to header probe")
        return await poll_api_headers(token)
    payload = to_payload(result)
    add_chime_field(payload)   # adds "c":1 iff the config opts in
    add_clock_fields(payload)   # adds "t" + "tf" iff the config opts in
    return payload


async def poll_api_headers(token: str) -> dict | None:
    """Legacy probe: a 1-token Haiku call whose rate-limit headers carry the
    5h/7d utilization (Pro/Max) or the spending-limit model (Enterprise)."""
    headers = dict(API_HEADERS_TEMPLATE)
    headers["Authorization"] = f"Bearer {token}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as http:
            resp = await http.post(API_URL, headers=headers, json=API_BODY)
    except httpx.HTTPError as e:
        log(f"API call failed: {e}")
        return None
    if resp.status_code in (401, 403):
        log(f"API HTTP {resp.status_code} (token expired/invalid)")
        raise TokenExpired()
    if resp.status_code >= 400:
        log(f"API HTTP {resp.status_code}: {resp.text[:200]}")
        return None

    def hdr(name: str, default: str = "0") -> str:
        return resp.headers.get(name, default)

    now = time.time()

    def reset_minutes(reset_ts: str) -> int:
        try:
            r = float(reset_ts)
        except ValueError:
            return 0
        mins = (r - now) / 60.0
        return int(round(mins)) if mins > 0 else 0

    def pct(util: str) -> int:
        try:
            return int(round(float(util) * 100))
        except ValueError:
            return 0

    # Pro/Max accounts expose 5h/7d windows; Enterprise/overage use a single
    # spending-limit model reported via overage-utilization.
    if resp.headers.get("anthropic-ratelimit-unified-5h-utilization"):
        payload = {
            "s": pct(hdr("anthropic-ratelimit-unified-5h-utilization")),
            "sr": reset_minutes(hdr("anthropic-ratelimit-unified-5h-reset")),
            "w": pct(hdr("anthropic-ratelimit-unified-7d-utilization")),
            "wr": reset_minutes(hdr("anthropic-ratelimit-unified-7d-reset")),
            "st": hdr("anthropic-ratelimit-unified-5h-status", "unknown"),
            "acct": "pro",
            "ok": True,
        }
    else:
        reset_ts = hdr("anthropic-ratelimit-unified-overage-reset")
        payload = {
            "s": pct(hdr("anthropic-ratelimit-unified-overage-utilization")),
            "sr": reset_minutes(reset_ts),
            "w": 0,
            "wr": 0,
            "st": hdr("anthropic-ratelimit-unified-status", "unknown"),
            "acct": "ent",
            **_billing_period_info(now, reset_ts),
            "ok": True,
        }
    payload["p"] = "claude"
    add_chime_field(payload)   # adds "c":1 iff the config opts in
    add_clock_fields(payload)   # adds "t" + "tf" iff the config opts in
    return payload


def _billing_period_info(now: float, reset_ts: str) -> dict:
    """Fraction of billing period elapsed (tp, 0-100) and period length in days (pd).

    Billing periods are assumed calendar-monthly: period_end is the reset
    timestamp, period_start is the same day/time one calendar month earlier.

    The rate-limit headers expose only the reset timestamp, not the period
    length, so the monthly window is an assumption — but a documented one:
    Enterprise spend-limit `period` "the only value today is monthly"
    (Claude Enterprise Admin API reference). The doc notes period is an open
    string that may gain other values later; revisit this if so.
    """
    try:
        period_end = float(reset_ts)
    except ValueError:
        return {"tp": 0, "pd": 30}
    if period_end <= 0:
        # reset_ts defaults to "0" when the overage-reset header is absent.
        # fromtimestamp(0) is 1970; stepping a month back lands in 1969, and
        # datetime.timestamp() raises OSError for pre-1970 dates on Windows.
        # Benign on macOS/Linux, but guard here too to keep the daemons parallel.
        return {"tp": 0, "pd": 30}
    dt_end = datetime.datetime.fromtimestamp(period_end)
    prev_month = dt_end.month - 1 or 12
    prev_year = dt_end.year if dt_end.month > 1 else dt_end.year - 1
    prev_day = min(dt_end.day, calendar.monthrange(prev_year, prev_month)[1])
    dt_start = dt_end.replace(year=prev_year, month=prev_month, day=prev_day)
    period_start = dt_start.timestamp()
    period_len = period_end - period_start
    if period_len <= 0:
        return {"tp": 0, "pd": 30}
    pct_val = (now - period_start) / period_len * 100
    total_days = int(round(period_len / 86400))
    rd = f"{dt_end.strftime('%b')} {dt_end.day}"
    return {
        "tp": max(0, min(100, int(round(pct_val)))),
        "pd": total_days,
        "rd": rd,
    }


class PlanSelector:
    """Decide which config dir's plan is "active" across polls.

    "Active" = the plan whose session % rose most recently (recent API activity).
    A rise stamps a monotonic poll counter, so the choice is sticky and a window
    reset (a drop to 0) isn't mistaken for use. Before any rise is seen (startup)
    the highest current session % wins. Mirrors the Linux bash daemon.
    """

    def __init__(self) -> None:
        self.prev_s: dict[Path, int] = {}
        self.last_active: dict[Path, int] = {}
        self.seq = 0

    def choose(self, sessions: dict[Path, int]) -> Path:
        """Update state from this cycle's {dir: session_pct} and return the active dir."""
        self.seq += 1
        for d, s in sessions.items():
            if d in self.prev_s and s > self.prev_s[d]:
                self.last_active[d] = self.seq
            self.prev_s[d] = s
        # Most recent activity wins; ties (and the startup case) break by highest %.
        return max(sessions, key=lambda d: (self.last_active.get(d, 0), sessions[d]))


# Module-level so the active-plan state survives reconnects.
_SELECTOR = PlanSelector()


async def poll_active(selector: PlanSelector = _SELECTOR) -> tuple[dict | None, bool]:
    """Poll every configured config dir; return ``(active_payload, all_dead)``.

    ``active_payload`` — the active plan's payload dict, or None when no dir
    yields a usable payload this cycle. A single configured dir (the default)
    collapses to exactly the old single-poll path.

    ``all_dead`` — True when *every* configured dir lacked a usable token this
    cycle (file/Keychain empty, or a 401/expired token), so the caller can
    signal "No data". False when at least one token authenticated — including a
    transient non-auth poll failure worth retrying silently rather than idling.

    Pure free-ride: a 401 (TokenExpired) means that dir's token has expired and
    only Claude Code (its owner) can re-seed it — we never refresh it ourselves.
    """
    dirs = read_config_dirs()
    payloads: dict[Path, dict] = {}
    sessions: dict[Path, int] = {}
    any_live = False
    for d in dirs:
        token = read_token_for(d)
        if not token:
            log(f"No token in {d}; skipping")
            continue
        try:
            payload = await poll_api(token)
        except TokenExpired:
            log(f"Token in {d} expired/invalid; skipping")
            continue
        # Authenticated: a transient None here isn't an auth failure, so the
        # dir counts as live and we stay silent rather than idling the device.
        any_live = True
        if payload is not None:
            payloads[d] = payload
            sessions[d] = int(payload.get("s", 0) or 0)
    if not payloads:
        return None, not any_live
    active = selector.choose(sessions)
    if len(dirs) > 1:
        log(f"Active plan: {active} (s={sessions[active]})")
    return payloads[active], False


async def poll_active_payload(selector: PlanSelector = _SELECTOR) -> dict | None:
    """The active plan's payload, or None when no dir yields one this cycle.

    Thin wrapper over :func:`poll_active` for callers that don't need the
    all-dead flag.
    """
    payload, _dead = await poll_active(selector)
    return payload


async def collect_payloads(providers: list[str], claude_payload: dict | None,
                           claude_dead: bool, extra: dict) -> list[dict]:
    """Build the ordered list of payloads to write this cycle, one per provider.

    ``claude_payload``/``claude_dead`` come from :func:`poll_active` (polled by
    the caller so the token/plan logic stays in one place). Alert extras
    (``b``/``m``/``x``) ride only on the Claude payload. With the default
    ``providers = claude`` the payload has no ``p`` field, matching older
    firmware byte-for-byte; otherwise every payload is tagged.

    Other providers are polled here; a provider that raises or reports
    ``ok=False`` yields ``{"p": id, "ok": false}`` and never affects the rest.
    """
    claude_only = providers == ["claude"]
    payloads: list[dict] = []
    for pid in providers:
        if pid == "claude":
            if claude_payload is not None:
                payload = {**claude_payload, **extra}
            elif claude_dead:
                payload = {"p": "claude", "ok": False, **extra}
            else:
                continue  # transient failure: stay silent for Claude this cycle
            if claude_only:
                payload.pop("p", None)
            payloads.append(payload)
            continue
        try:
            result = await PROVIDERS[pid]()
            payload = to_payload(result)
            if not result.ok:
                reason = result.extra.get("reason")
                log(f"Provider {pid}: no data" + (f" ({reason})" if reason else ""))
        except Exception as e:  # one provider must never break the others
            log(f"Provider {pid} failed: {e!r}")
            payload = {"p": pid, "ok": False}
        if payload.get("ok"):
            add_clock_fields(payload)
        payloads.append(payload)
    return payloads


def to_ascii(text: str, limit: int) -> str:
    """The device fonts are ASCII only: drop accents, collapse whitespace, cap."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def take_attention_flag() -> dict | None:
    """Consume the attention file. Only a fresh one counts, so a file written
    while the device was away doesn't beep on reconnect. A bare `touch` with no
    JSON still beeps, just without a card."""
    try:
        mtime = ATTENTION_FLAG.stat().st_mtime
        raw = ATTENTION_FLAG.read_text()
        ATTENTION_FLAG.unlink()
    except FileNotFoundError:
        return None
    if time.time() - mtime >= ATTENTION_MAX_AGE:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        data = {}
    return {
        "m": to_ascii(str(data.get("m") or ""), 120),
        "s": str(data.get("s") or ""),
        "t": mtime,
    }


def take_clears() -> dict[str, float]:
    """Consume every clear-<session id> file and return {session id: mtime}."""
    clears = {}
    for f in ATTENTION_DIR.glob("clear-*"):
        try:
            clears[f.name.removeprefix("clear-")] = f.stat().st_mtime
            f.unlink()
        except FileNotFoundError:
            pass
    return clears


def encode_payload(payload: dict, limit: int) -> bytes:
    """JSON-encode for one write-without-response of at most `limit` bytes.
    Shortens the alert message, then drops it, until it fits."""
    data = json.dumps(payload, separators=(",", ":")).encode()
    msg = payload.get("m", "")
    while len(data) > limit and msg:
        msg = msg[: max(0, len(msg) - (len(data) - limit) - 3)].rstrip()
        payload = {**payload, "m": msg + "..." if msg else ""}
        data = json.dumps(payload, separators=(",", ":")).encode()
    if len(data) > limit:
        payload = {k: v for k, v in payload.items() if k != "m"}
        data = json.dumps(payload, separators=(",", ":")).encode()
    return data


class Session:
    def __init__(self, client: BleakClient) -> None:
        self.client = client
        self.refresh_requested = asyncio.Event()
        rx = client.services.get_characteristic(RX_CHAR_UUID)
        self.max_write = rx.max_write_without_response_size if rx else DEFAULT_MAX_WRITE
        log(f"Max write size: {self.max_write} bytes")

    def _on_refresh(self, _char, _data: bytearray) -> None:
        log("Refresh requested by device")
        self.refresh_requested.set()

    async def setup_refresh_subscription(self) -> None:
        # start_notify awaits CoreBluetooth's CCCD-write confirmation, which
        # never arrives if the peripheral doesn't ACK the subscribe (a
        # half-open link after the OS auto-connects the HID). Unbounded, that
        # await wedges the whole daemon between "Connected" and the first poll
        # — the device then shows nothing until a manual restart. Bound it: the
        # subscription is only an optional device-initiated refresh nudge (we
        # poll every POLL_INTERVAL regardless), so on timeout we proceed.
        try:
            await asyncio.wait_for(
                self.client.start_notify(REQ_CHAR_UUID, self._on_refresh),
                timeout=10,
            )
        except (BleakError, ValueError) as e:
            log(f"Refresh subscription unavailable: {e}")
        except asyncio.TimeoutError:
            log("Refresh subscription timed out; polling without it")

    async def write_payload(self, payload: dict, tag: str | None = None) -> bool:
        data = encode_payload(payload, self.max_write)
        log(f"Sending[{tag}]: {data.decode()}" if tag else f"Sending: {data.decode()}")
        try:
            await self.client.write_gatt_char(RX_CHAR_UUID, data, response=False)
            return True
        except BleakError as e:
            log(f"Write failed: {e}")
            return False


def _is_encryption_error(exc: BaseException) -> bool:
    """True if a connect error is a macOS bonding/encryption mismatch.

    macOS reports a stale bond as CBErrorDomain Code=15 ("Failed to encrypt
    the connection..."). Match on the message text so we don't depend on how
    bleak wraps the underlying CoreBluetooth error.
    """
    s = str(exc).lower()
    return "code=15" in s or "encrypt" in s


# blueutil talks to Bluetooth via IOBluetooth, which on recent macOS needs its
# OWN Bluetooth TCC grant (separate from the daemon's CoreBluetooth grant).
# Without it, blueutil *hangs* instead of erroring — so every call is bounded
# by a timeout and a hang is reported as a permission problem, not a crash.
BLUEUTIL_TIMEOUT = 8


def _blueutil(*args: str) -> str | None:
    """Run `blueutil <args>`, returning stdout, or None on failure/timeout.

    A timeout almost always means blueutil lacks Bluetooth permission (it
    blocks rather than failing), so we surface that cause explicitly.
    """
    try:
        return subprocess.run(
            ["blueutil", *args],
            capture_output=True, text=True,
            timeout=BLUEUTIL_TIMEOUT, check=True,
        ).stdout
    except subprocess.TimeoutExpired:
        log(f"blueutil {' '.join(args)} timed out — it likely lacks Bluetooth "
            "permission. Grant it under System Settings > Privacy & Security > "
            "Bluetooth (run `blueutil --paired` once from Terminal to prompt).")
        return None
    except (subprocess.SubprocessError, OSError) as e:
        log(f"blueutil {' '.join(args)} failed: {e}")
        return None


def unpair_macos() -> bool:
    """Forget a stale macOS bond for our device so it can re-pair.

    A Code=15 "failed to encrypt" connect error means macOS holds bonding
    keys that no longer match the ESP32's (e.g. after a firmware reflash or
    the on-device bond-clear gesture). The firmware pairs "just works" (no
    MITM), so once the stale bond is gone the next connect re-bonds silently
    with no GUI prompt.

    CoreBluetooth exposes no unpair API, so we shell out to `blueutil`. The
    daemon only knows the peripheral's CoreBluetooth UUID, not the BD_ADDR
    that blueutil needs, so we map by name via `blueutil --paired`. Returns
    True if a bond was removed. Mirrors the Linux daemon's `bluetoothctl
    remove` self-heal.
    """
    device_name = read_device_name()
    if not shutil.which("blueutil"):
        log("Stale bond detected but `blueutil` is not installed; cannot "
            "auto-recover. Run `brew install blueutil`, or forget "
            f"'{device_name}' in System Settings > Bluetooth and reconnect.")
        return False

    out = _blueutil("--paired")
    if out is None:
        return False

    # Each line looks like:
    #   address: aa-bb-cc-dd-ee-04, ... name: "TokenMon", ...
    # Accept the configured name and legacy names (boards flashed before the
    # rename still advertise "Clawdmeter").
    names = accepted_device_names()
    addr = None
    matched = None
    for line in out.splitlines():
        for n in names:
            if f'name: "{n}"' in line:
                m = re.search(r"address:\s*([0-9a-fA-F:-]+)", line)
                if m:
                    addr = m.group(1)
                    matched = n
                break
        if addr:
            break
    if not addr:
        log(f"No paired '{device_name}' found to unpair (already forgotten?)")
        return False

    if _blueutil("--unpair", addr) is None:
        return False
    log(f"Unpaired stale bond for '{matched}' [{addr}]; re-pairing on "
        "next connect")
    return True


async def connect_and_run(target, stop_event: asyncio.Event) -> bool:
    """Connect to a target and poll until disconnected or stopped.

    ``target`` is either an address string (Linux) or a BLEDevice carrying
    live CoreBluetooth details (macOS). Returns True if the connection was
    used successfully (so the caller keeps the cached address), False if the
    connection failed and the cache should be invalidated.
    """
    display = target if isinstance(target, str) else target.address
    log(f"Connecting to {display}...")
    client = BleakClient(target)
    try:
        # Bound the connect the same way #84 bounded the refresh subscribe.
        # On macOS the OS auto-connects the firmware's HID link, so
        # CoreBluetooth can hand us a half-open peripheral whose GATT connect
        # handshake never completes. BleakClient's own timeout governs
        # discovery, not connectPeripheral, so an unbounded await here wedges
        # the single-threaded daemon forever at "Connecting..." (observed ~13h,
        # device stuck on stale data). wait_for raises TimeoutError, which the
        # handler below already treats as a connection failure -> drop the
        # cached address and rescan.
        await asyncio.wait_for(client.connect(), timeout=CONNECT_TIMEOUT)
    except (BleakError, asyncio.TimeoutError) as e:
        log(f"Connection failed: {e}")
        if sys.platform == "darwin" and _is_encryption_error(e):
            log("Encryption failed — likely a stale macOS bond; self-healing")
            unpair_macos()
        return False

    if not client.is_connected:
        log("Connection failed (no error but not connected)")
        return False

    log("Connected")
    ATTENTION_FLAG.unlink(missing_ok=True)
    take_clears()
    session = Session(client)
    await session.setup_refresh_subscription()

    last_poll = 0.0
    used_successfully = False
    alert = None            # latest alert, kept to match its session's clear
    alert_unsent = False
    clear_unsent = False
    alert_poll_used = False  # the pending alert already got its early poll
    try:
        while client.is_connected and not stop_event.is_set():
            now = time.time()
            elapsed = now - last_poll
            # The firmware treats every write as a full payload, so alerts and
            # clears go out with a fresh poll, never on their own.
            # One alert slot, latest wins: two sessions alerting in the same tick
            # keep only the last one.
            new_alert = take_attention_flag()
            # A session that is still waiting can notify twice (AskUserQuestion
            # fires PreToolUse, then a permission_prompt). Keep the first card
            # and beep once until that session clears.
            repeat = new_alert and alert and alert["s"] and new_alert["s"] == alert["s"]
            if new_alert is not None and not repeat:
                alert, alert_unsent, clear_unsent = new_alert, True, False
                alert_poll_used = False
            clears = take_clears()
            if alert and clears.get(alert["s"], 0) > alert["t"]:
                clear_unsent = not alert_unsent   # never shown, nothing to clear
                alert, alert_unsent = None, False
                alert_poll_used = False
            providers = read_providers()
            if drop_undeliverable_alert(providers, alert_unsent or clear_unsent):
                alert, alert_unsent, clear_unsent = None, False, False
            if should_poll_now(elapsed, alert_pending=alert_unsent or clear_unsent,
                               refresh_requested=session.refresh_requested.is_set(),
                               claude_enabled="claude" in providers,
                               alert_poll_used=alert_poll_used):
                session.refresh_requested.clear()
                alert_poll_used = alert_unsent or clear_unsent
                # Pure free-ride: read whatever access token(s) Claude Code
                # currently holds across the configured config dirs and NEVER
                # refresh them ourselves. Claude Code (the token's owner) does all
                # refreshing; refreshing here would race its rotation and feed the
                # OAuth endpoint's rate limit (429). When no dir has a usable token
                # we signal "No data" so the device idles instead of holding stale
                # numbers until the CLI re-seeds it.
                payload, dead = (None, False)
                if "claude" in providers:
                    payload, dead = await poll_active()
                    if payload is None and dead:
                        # No live token in any config dir (missing, or a 401/expired
                        # token) -> show "No data" now instead of stale numbers.
                        log("No usable token; signalling no-data to device — run "
                            "`claude login` or use the CLI to let Claude Code renew it")
                    elif payload is None:
                        # Transient poll failure (a live token that didn't answer this
                        # cycle) -> stay silent for Claude and retry next tick.
                        log("No usable config dir this cycle")
                extra = {}
                if alert_unsent:
                    if read_onoff_setting("beep") == "on":
                        extra["b"] = 1
                    if alert["m"]:
                        extra["m"] = alert["m"]
                if clear_unsent:
                    extra["x"] = 1
                # One payload per enabled provider, written back-to-back with a
                # short gap so the firmware's RX queue never drops one. Guard
                # last_poll on the write result (like before) so a failed beat
                # retries next tick instead of throttling a healthy link for a
                # full POLL_INTERVAL.
                payloads = await collect_payloads(providers, payload, dead, extra)
                for i, item in enumerate(payloads):
                    if i:
                        await asyncio.sleep(0.35)
                    pid = item.get("p", "claude")
                    if not await session.write_payload(item, tag=pid):
                        continue
                    last_poll = time.time()
                    if pid == "claude":
                        # Alert extras ride on the Claude payload; only a
                        # successful Claude write counts them as delivered.
                        alert_unsent = clear_unsent = alert_poll_used = False
                        if item.get("ok"):
                            used_successfully = True
                    elif item.get("ok"):
                        used_successfully = True

            try:
                await asyncio.wait_for(session.refresh_requested.wait(), timeout=TICK)
            except asyncio.TimeoutError:
                pass
    finally:
        try:
            await client.disconnect()
        except BleakError:
            pass

    log("Device disconnected" if not stop_event.is_set() else "Stopping")
    return used_successfully


async def main() -> None:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _stop(*_args: object) -> None:
        log("Daemon stopping")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, _stop)

    log("=== Claude Usage Tracker Daemon (BLE, macOS) ===")
    log(f"Poll interval: {POLL_INTERVAL}s")

    backoff = 1
    skip_addr: str | None = None  # macOS: a peripheral to skip for one cycle
    while not stop_event.is_set():
        # Apply any pending skip exactly once, then clear it so the next
        # cycle re-tries retrieveConnected (the device may have recovered).
        target = await discover_target(skip_addr=skip_addr)
        skip_addr = None
        if not target:
            log(f"Device not found, retrying in {backoff}s...")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 60)
            continue

        addr = target if isinstance(target, str) else target.address
        ok = await connect_and_run(target, stop_event)
        if not ok:
            if sys.platform == "darwin":
                # No string cache to drop; instead skip this stale handle on
                # the next retrieveConnected so the scan fallback is reachable.
                skip_addr = addr
            else:
                log("Invalidating cached address")
                SAVED_ADDR_FILE.unlink(missing_ok=True)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, 60)
        else:
            backoff = 1


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
