"""``~/.config/toknmon/status.json`` (H13 S1.1): the daemon's cheap status
mirror for the menu-bar app, written atomically after every poll cycle.

Run: python -m pytest daemon/tests/test_status_file.py -q
"""
import json
import os

import daemon.claude_usage_daemon as mod
from daemon.claude_usage_daemon import STATUS_KEYS, build_status, write_status

PAYLOADS = [
    {"p": "claude", "ok": True, "s": 32, "sr": 118, "w": 61, "wr": 4000, "f": 10, "fr": 4000,
     "fl": "Fable", "st": "allowed", "b": 1, "m": "Session needs you"},
    {"p": "codex", "ok": True, "w": 37, "wr": 900, "rc": 2, "ru": 1, "rm": 3000, "st": "ok"},
    {"p": "kimi", "ok": False},
]


def test_status_keys_cover_the_payload_contract():
    assert set(STATUS_KEYS) == {"ok", "s", "sr", "w", "wr", "f", "fr", "fl", "rc", "ru", "rm", "st"}


def test_build_status_shape():
    status = build_status(True, "Desk 2", "meter,focus", PAYLOADS, now=1700000000.5, pid=4242)
    assert status["ts"] == 1700000000
    assert status["connected"] is True
    assert status["device_name"] == "Desk 2"
    assert status["apps"] == "meter,focus"
    assert status["daemon_pid"] == 4242
    assert set(status["providers"]) == {"claude", "codex", "kimi"}


def test_build_status_keeps_only_payload_keys_present():
    status = build_status(True, "Desk 2", "meter", PAYLOADS, now=0, pid=1)
    assert status["providers"]["claude"] == {
        "ok": True, "s": 32, "sr": 118, "w": 61, "wr": 4000, "f": 10, "fr": 4000,
        "fl": "Fable", "st": "allowed"}
    assert status["providers"]["codex"] == {
        "ok": True, "w": 37, "wr": 900, "rc": 2, "ru": 1, "rm": 3000, "st": "ok"}
    assert status["providers"]["kimi"] == {"ok": False}


def test_build_status_drops_alert_extras():
    """The attention card text (``m``) is user content; ``b``/``x`` are
    one-shot flags. None of them belong in the status mirror."""
    status = build_status(True, "Desk 2", "meter", PAYLOADS, now=0, pid=1)
    for data in status["providers"].values():
        assert not {"b", "m", "x", "p"} & set(data)


def test_build_status_untagged_payload_is_claude():
    status = build_status(True, "ToknMon", "meter", [{"ok": True, "s": 5, "sr": 10}], now=0, pid=1)
    assert status["providers"] == {"claude": {"ok": True, "s": 5, "sr": 10}}


def test_build_status_skips_cfg_payload():
    status = build_status(True, "ToknMon", "meter", [{"p": "cfg", "ap": "meter"}], now=0, pid=1)
    assert status["providers"] == {}


def test_write_status_atomic_private_and_json(tmp_path, monkeypatch):
    status_file = tmp_path / "status.json"
    monkeypatch.setattr(mod, "STATUS_FILE", status_file)
    write_status(True, "Desk 2", "meter,focus", PAYLOADS)
    data = json.loads(status_file.read_text())
    assert data["connected"] is True and data["device_name"] == "Desk 2"
    assert data["daemon_pid"] == os.getpid()
    assert abs(data["ts"] - mod.time.time()) < 5
    assert oct(status_file.stat().st_mode & 0o777) == "0o600"
    assert [p.name for p in tmp_path.iterdir()] == ["status.json"]


def test_write_status_offline_keeps_last_providers(tmp_path, monkeypatch):
    """On disconnect the GUI still shows the last numbers, flagged offline."""
    status_file = tmp_path / "status.json"
    monkeypatch.setattr(mod, "STATUS_FILE", status_file)
    write_status(True, "Desk 2", "meter", PAYLOADS)
    write_status(False, "Desk 2", "meter", None)
    data = json.loads(status_file.read_text())
    assert data["connected"] is False
    assert set(data["providers"]) == {"claude", "codex", "kimi"}


def test_write_status_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "STATUS_FILE", tmp_path)   # a directory: unwritable
    lines: list[str] = []
    monkeypatch.setattr(mod, "log", lines.append)
    write_status(True, "Desk 2", "meter", PAYLOADS)     # must not raise
    assert lines and "status" in lines[0].lower()


def test_status_contains_no_token_like_strings(tmp_path, monkeypatch):
    status_file = tmp_path / "status.json"
    monkeypatch.setattr(mod, "STATUS_FILE", status_file)
    write_status(True, "Desk 2", "meter", PAYLOADS + [{"p": "grok", "ok": True, "w": 1,
                                                        "token": "sk-ant-secret-token"}])
    text = status_file.read_text()
    assert "sk-ant" not in text and "token" not in text
