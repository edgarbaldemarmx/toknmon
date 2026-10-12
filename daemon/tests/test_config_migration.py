#!/usr/bin/env python3
"""Unit tests for the one-time legacy config migration (Clawdmeter -> ToknMon).

migrate_legacy_config() copies `config` and `ble-address` from the legacy
~/.config/claude-usage-monitor dir into ~/.config/toknmon when the new file is
absent, logs one line per copy, and never deletes the legacy files.

Run: python -m pytest daemon/tests/test_config_migration.py -x -q
"""
import daemon.claude_usage_daemon as mod


def _dirs(tmp_path, monkeypatch):
    new = tmp_path / "toknmon"
    legacy = tmp_path / "claude-usage-monitor"
    monkeypatch.setattr(mod, "CONFIG_DIR", new)
    monkeypatch.setattr(mod, "LEGACY_CONFIG_DIR", legacy)
    monkeypatch.setattr(mod, "CONFIG_FILE", new / "config")
    monkeypatch.setattr(mod, "SAVED_ADDR_FILE", new / "ble-address")
    return new, legacy


def _logs(monkeypatch):
    lines = []
    monkeypatch.setattr(mod, "log", lines.append)
    return lines


def test_paths_live_under_toknmon_dir():
    assert mod.CONFIG_DIR.name == "toknmon"
    assert mod.CONFIG_FILE == mod.CONFIG_DIR / "config"
    assert mod.SAVED_ADDR_FILE == mod.CONFIG_DIR / "ble-address"
    assert mod.LEGACY_CONFIG_DIR.name == "claude-usage-monitor"


def test_copies_legacy_config_when_new_is_absent(tmp_path, monkeypatch):
    new, legacy = _dirs(tmp_path, monkeypatch)
    legacy.mkdir()
    (legacy / "config").write_text("device_name = Desk-2\nproviders = claude, codex\n")
    lines = _logs(monkeypatch)

    assert mod.migrate_legacy_config() == ["config"]
    assert (new / "config").read_text() == "device_name = Desk-2\nproviders = claude, codex\n"
    assert (legacy / "config").exists(), "legacy file must never be deleted"
    assert len(lines) == 1 and "migration" in lines[0].lower()
    assert mod.read_device_name() == "Desk-2"


def test_copies_cached_ble_address_too(tmp_path, monkeypatch):
    new, legacy = _dirs(tmp_path, monkeypatch)
    legacy.mkdir()
    (legacy / "config").write_text("clock = auto\n")
    (legacy / "ble-address").write_text("AA:BB:CC:DD:EE:FF\n")
    _logs(monkeypatch)

    assert mod.migrate_legacy_config() == ["config", "ble-address"]
    assert (new / "ble-address").read_text() == "AA:BB:CC:DD:EE:FF\n"
    assert (legacy / "ble-address").exists()


def test_never_overwrites_an_existing_new_file(tmp_path, monkeypatch):
    new, legacy = _dirs(tmp_path, monkeypatch)
    legacy.mkdir()
    new.mkdir()
    (legacy / "config").write_text("device_name = Old\n")
    (new / "config").write_text("device_name = New\n")
    lines = _logs(monkeypatch)

    assert mod.migrate_legacy_config() == []
    assert (new / "config").read_text() == "device_name = New\n"
    assert lines == []


def test_noop_without_legacy_dir(tmp_path, monkeypatch):
    new, _legacy = _dirs(tmp_path, monkeypatch)
    lines = _logs(monkeypatch)
    assert mod.migrate_legacy_config() == []
    assert not new.exists()
    assert lines == []


def test_second_run_is_silent(tmp_path, monkeypatch):
    new, legacy = _dirs(tmp_path, monkeypatch)
    legacy.mkdir()
    (legacy / "config").write_text("beep = on\n")
    lines = _logs(monkeypatch)
    assert mod.migrate_legacy_config() == ["config"]
    assert mod.migrate_legacy_config() == []
    assert len(lines) == 1
