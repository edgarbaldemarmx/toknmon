#!/usr/bin/env python3
"""Unit tests for the macOS/Linux daemon's configurable BLE device name.

Covers read_device_name (config parsing + default), accepted_device_names
(configured + legacy fallback), is_device_name, and the name matching used by
unpair_macos.

Run: python -m pytest daemon/tests/test_device_name.py -x -q
"""
import daemon.claude_usage_daemon as mod
from daemon.claude_usage_daemon import (
    DEFAULT_DEVICE_NAME,
    LEGACY_DEVICE_NAMES,
    accepted_device_names,
    is_device_name,
    read_device_name,
)


# ---------------------------------------------------------------------------
# read_device_name
# ---------------------------------------------------------------------------

def test_default_name_is_tokenmon():
    assert DEFAULT_DEVICE_NAME == "TokenMon"
    assert "Clawdmeter" in LEGACY_DEVICE_NAMES


def test_device_name_defaults_when_config_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")  # absent
    assert read_device_name() == DEFAULT_DEVICE_NAME


def test_device_name_defaults_when_key_absent(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("clock = auto\nchime = on\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    assert read_device_name() == DEFAULT_DEVICE_NAME


def test_device_name_parses_value_with_spaces_and_comment(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("device_name = ToknMon Desk One   # office board\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    assert read_device_name() == "ToknMon Desk One"


def test_device_name_key_is_case_insensitive(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("Device_Name = Desk-2\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    assert read_device_name() == "Desk-2"


def test_device_name_rejects_too_long_value(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("device_name = " + "X" * 19 + "\n")  # > 18 bytes
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    assert read_device_name() == DEFAULT_DEVICE_NAME


def test_device_name_rejects_empty_value(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("device_name =\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    assert read_device_name() == DEFAULT_DEVICE_NAME


# ---------------------------------------------------------------------------
# accepted_device_names / is_device_name
# ---------------------------------------------------------------------------

def test_accepted_names_include_configured_and_legacy(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("device_name = ToknMon Desk One\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    names = accepted_device_names()
    assert "ToknMon Desk One" in names
    assert "Clawdmeter" in names


def test_accepted_names_default_include_legacy(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")
    names = accepted_device_names()
    assert names >= {"TokenMon", "Clawdmeter"}


def test_is_device_name_matches_configured_and_legacy_only(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("device_name = Desk-2\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    assert is_device_name("Desk-2")
    assert is_device_name("Clawdmeter")
    assert not is_device_name("TokenMon")       # default is not implied once configured
    assert not is_device_name("Magic Keyboard")
    assert not is_device_name(None)


# ---------------------------------------------------------------------------
# unpair_macos matches by any accepted name
# ---------------------------------------------------------------------------

def _stub_blueutil(monkeypatch, paired_output: str):
    calls: list[tuple[str, ...]] = []

    def fake_blueutil(*args: str):
        calls.append(args)
        if args == ("--paired",):
            return paired_output
        return ""  # --unpair succeeded

    monkeypatch.setattr(mod, "_blueutil", fake_blueutil)
    monkeypatch.setattr(mod.shutil, "which", lambda _: "/opt/homebrew/bin/blueutil")
    return calls


def test_unpair_finds_configured_name(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("device_name = ToknMon Desk One\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    calls = _stub_blueutil(monkeypatch,
        'address: 11-22-33-44-55-66, connected, name: "Magic Keyboard", paired\n'
        'address: aa-bb-cc-dd-ee-01, not connected, name: "ToknMon Desk One", paired\n')
    assert mod.unpair_macos() is True
    assert ("--unpair", "aa-bb-cc-dd-ee-01") in calls


def test_unpair_finds_legacy_name(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")  # default name
    calls = _stub_blueutil(monkeypatch,
        'address: aa-bb-cc-dd-ee-01, not connected, name: "Clawdmeter", paired\n')
    assert mod.unpair_macos() is True
    assert ("--unpair", "aa-bb-cc-dd-ee-01") in calls


def test_unpair_ignores_unrelated_devices(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")
    calls = _stub_blueutil(monkeypatch,
        'address: 11-22-33-44-55-66, connected, name: "Magic Keyboard", paired\n')
    assert mod.unpair_macos() is False
    assert all(c[0] != "--unpair" for c in calls)
