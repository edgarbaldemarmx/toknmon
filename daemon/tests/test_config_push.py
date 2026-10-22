"""Config push to the device (H13 S1.1): the ``apps`` key, the ``state.json``
record of what was last sent, change detection and the per-connection resend.

The daemon sends one extra BLE write ``{"p":"cfg", ...}`` before the provider
payloads whenever the effective ``apps`` or ``device_name`` differs from what
it last sent (persisted in ``~/.config/toknmon/state.json``), and once per new
BLE connection regardless. Today's firmware ignores unknown provider ids, so
``p:"cfg"`` is harmless until the H12 firmware consumes it.

Run: python -m pytest daemon/tests/test_config_push.py -q
"""
import json
import os

import pytest

import daemon.claude_usage_daemon as mod
from daemon.claude_usage_daemon import (
    DEFAULT_APPS,
    DEFAULT_DEVICE_NAME,
    ConfigPusher,
    parse_apps,
    push_device_name,
    read_apps,
)


# ---------------------------------------------------------------------------
# apps parsing / normalisation
# ---------------------------------------------------------------------------

def test_default_apps_is_meter_and_focus():
    assert DEFAULT_APPS == "meter,focus"
    assert parse_apps(None) == "meter,focus"
    assert parse_apps("") == "meter,focus"


def test_apps_meter_only():
    assert parse_apps("meter") == "meter"


def test_apps_normalises_spaces_case_and_order():
    assert parse_apps(" Focus , METER ") == "meter,focus"
    assert parse_apps("meter,focus") == "meter,focus"


def test_apps_meter_always_included():
    assert parse_apps("focus") == "meter,focus"


def test_apps_unknown_names_ignored_with_one_log_line():
    lines: list[str] = []
    assert parse_apps("meter,timer,focus", log=lines.append) == "meter,focus"
    assert len(lines) == 1 and "timer" in lines[0]


def test_read_apps_logs_unknown_once_per_value(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("apps = meter, bogus\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    monkeypatch.setattr(mod, "_last_apps_warning", None)
    lines: list[str] = []
    monkeypatch.setattr(mod, "log", lines.append)
    assert read_apps() == "meter"
    assert read_apps() == "meter"           # same value: no second line
    assert len(lines) == 1 and "bogus" in lines[0]


def test_read_apps_defaults_when_key_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")
    assert read_apps() == DEFAULT_APPS


# ---------------------------------------------------------------------------
# state.json round trip
# ---------------------------------------------------------------------------

def test_state_round_trip_atomic_and_private(tmp_path):
    state_file = tmp_path / "state.json"
    pusher = ConfigPusher(state_file)
    pusher.mark_sent({"p": "cfg", "ap": "meter", "n": "Desk 2"})
    assert json.loads(state_file.read_text()) == {"ap": "meter", "n": "Desk 2"}
    assert oct(state_file.stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]   # no temp leftovers
    again = ConfigPusher(state_file)
    assert again.state == {"ap": "meter", "n": "Desk 2"}


def test_state_corrupt_file_reads_as_empty(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text("{not json")
    assert ConfigPusher(state_file).state == {}


def test_state_missing_dir_is_created(tmp_path):
    state_file = tmp_path / "nested" / "state.json"
    ConfigPusher(state_file).mark_sent({"p": "cfg", "ap": "meter"})
    assert json.loads(state_file.read_text()) == {"ap": "meter"}


# ---------------------------------------------------------------------------
# change detection
# ---------------------------------------------------------------------------

def _settled(tmp_path, ap="meter,focus", n="ToknMon"):
    """A pusher whose state already matches and whose connection already got
    its payload (nothing pending)."""
    pusher = ConfigPusher(tmp_path / "state.json")
    pusher.on_connect()
    pusher.mark_sent({"p": "cfg", "ap": ap, "n": n})
    return pusher


def test_nothing_pending_when_unchanged(tmp_path):
    pusher = _settled(tmp_path)
    assert pusher.pending("meter,focus", "ToknMon") is None


def test_only_changed_keys_are_sent(tmp_path):
    pusher = _settled(tmp_path)
    assert pusher.pending("meter", "ToknMon") == {"p": "cfg", "ap": "meter"}
    assert pusher.pending("meter,focus", "Desk 2") == {"p": "cfg", "n": "Desk 2"}
    assert pusher.pending("meter", "Desk 2") == {"p": "cfg", "ap": "meter", "n": "Desk 2"}


def test_cfg_payload_has_p_first_and_fits_one_write(tmp_path):
    pusher = _settled(tmp_path)
    payload = pusher.pending("meter", "A" * 18)
    data = mod.encode_payload(payload, mod.DEFAULT_MAX_WRITE)
    assert data.startswith(b'{"p":"cfg",')
    assert len(data) <= mod.DEFAULT_MAX_WRITE


def test_mark_sent_updates_state_so_next_poll_is_silent(tmp_path):
    pusher = _settled(tmp_path)
    payload = pusher.pending("meter", "ToknMon")
    pusher.mark_sent(payload)
    assert pusher.pending("meter", "ToknMon") is None
    assert pusher.state == {"ap": "meter", "n": "ToknMon"}


def test_new_connection_resends_full_config_once(tmp_path):
    pusher = _settled(tmp_path)
    pusher.on_connect()                     # the board may have been re-flashed
    assert pusher.pending("meter,focus", "ToknMon") == {
        "p": "cfg", "ap": "meter,focus", "n": "ToknMon"}
    pusher.mark_sent(pusher.pending("meter,focus", "ToknMon"))
    assert pusher.pending("meter,focus", "ToknMon") is None


def test_failed_write_keeps_payload_pending(tmp_path):
    pusher = _settled(tmp_path)
    assert pusher.pending("meter", "ToknMon") is not None
    # no mark_sent: the write failed
    assert pusher.pending("meter", "ToknMon") == {"p": "cfg", "ap": "meter"}


def test_invalid_name_is_not_sent(tmp_path):
    pusher = _settled(tmp_path)
    assert pusher.pending("meter", None) == {"p": "cfg", "ap": "meter"}
    pusher.on_connect()
    assert pusher.pending("meter,focus", None) == {"p": "cfg", "ap": "meter,focus"}


# ---------------------------------------------------------------------------
# device name for the push
# ---------------------------------------------------------------------------

def test_push_device_name_unset_is_not_pushed(tmp_path, monkeypatch):
    """No `device_name` in the config: the board keeps its serial-set name
    instead of being renamed to the default on the first link."""
    cfg = tmp_path / "config"
    cfg.write_text("providers = auto\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    assert push_device_name() is None


def test_push_device_name_reads_valid_value(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("device_name = Desk 2\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    assert push_device_name() == "Desk 2"


@pytest.mark.parametrize("bad", ["X" * 19, "", "café"])
def test_push_device_name_invalid_logs_once_and_returns_none(tmp_path, monkeypatch, bad):
    cfg = tmp_path / "config"
    cfg.write_text(f"device_name = {bad}\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    monkeypatch.setattr(mod, "_last_name_warning", None)
    lines: list[str] = []
    monkeypatch.setattr(mod, "log", lines.append)
    assert push_device_name() is None
    assert push_device_name() is None
    assert len(lines) == 1 and "device_name" in lines[0]


# ---------------------------------------------------------------------------
# loop wiring: the cfg write goes out before the provider payloads
# ---------------------------------------------------------------------------

def test_cycle_payloads_puts_cfg_first(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("apps = meter\ndevice_name = Desk 2\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    pusher = ConfigPusher(tmp_path / "state.json")
    pusher.on_connect()
    providers = [{"p": "claude", "ok": True, "s": 1}, {"p": "codex", "ok": True}]
    out = mod.with_config_payload(pusher, providers)
    assert out[0] == {"p": "cfg", "ap": "meter", "n": "Desk 2"}
    assert out[1:] == providers
    pusher.mark_sent(out[0])
    assert mod.with_config_payload(pusher, providers) == providers   # settled: untouched


def test_existing_provider_payloads_are_byte_identical(tmp_path, monkeypatch):
    """The provider payloads themselves never change: the config rides in its
    own write (older firmware ignores it)."""
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")
    pusher = ConfigPusher(tmp_path / "state.json")
    pusher.on_connect()
    claude_only = [{"ok": True, "s": 12, "sr": 30}]
    out = mod.with_config_payload(pusher, claude_only)
    assert out[-1] is claude_only[0]
    assert mod.encode_payload(out[-1], 180) == b'{"ok":true,"s":12,"sr":30}'
