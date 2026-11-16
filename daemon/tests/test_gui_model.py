"""Tests for daemon/gui/model.py: every label and menu state of the menu-bar
app is computed here from plain dicts, so the AppKit wiring in menubar.py has
nothing to decide."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui import model  # noqa: E402

STATUS = {
    "ts": 1700000000, "connected": True, "device_name": "Desk 2", "apps": "meter,focus",
    "daemon_pid": 4242,
    "providers": {
        "claude": {"ok": True, "s": 32, "sr": 118, "w": 61, "wr": 4000, "st": "allowed"},
        "codex": {"ok": True, "w": 37, "wr": 900, "rc": 2, "ru": 1, "st": "ok"},
        "kimi": {"ok": False},
    },
}


# ---------------------------------------------------------------------------
# provider lines
# ---------------------------------------------------------------------------

def test_provider_line_claude():
    assert model.provider_line("claude", STATUS["providers"]["claude"]) == \
        "Claude · 5h 32% · week 61%"


def test_provider_line_codex_with_credits():
    assert model.provider_line("codex", STATUS["providers"]["codex"]) == \
        "Codex · week 37% · resets 2 held"


def test_provider_line_no_data():
    assert model.provider_line("kimi", {"ok": False}) == "Kimi · no data"
    assert model.provider_line("grok", {}) == "Grok · no data"
    assert model.provider_line("grok", None) == "Grok · no data"


def test_provider_line_missing_fields_are_skipped():
    assert model.provider_line("grok", {"ok": True, "w": 12}) == "Grok · week 12%"
    assert model.provider_line("claude", {"ok": True, "s": 3}) == "Claude · 5h 3%"
    assert model.provider_line("claude", {"ok": True}) == "Claude · no data"


def test_provider_line_model_window_uses_its_label():
    data = {"ok": True, "s": 1, "w": 2, "f": 80, "fl": "Fable"}
    assert model.provider_line("claude", data) == "Claude · 5h 1% · week 2% · Fable 80%"


def test_provider_line_unknown_provider_is_capitalised():
    assert model.provider_line("newbie", {"ok": True, "w": 1}) == "Newbie · week 1%"


def test_provider_lines_follow_registry_order_and_hide_absent():
    assert model.provider_lines(STATUS) == [
        "Claude · 5h 32% · week 61%",
        "Codex · week 37% · resets 2 held",
        "Kimi · no data",
    ]
    assert model.provider_lines(None) == []
    assert model.provider_lines({"providers": {}}) == []


# ---------------------------------------------------------------------------
# device line
# ---------------------------------------------------------------------------

def test_device_line_connected():
    assert model.device_line(STATUS, now=1700000005) == "Device: Desk 2 · connected"


def test_device_line_offline():
    assert model.device_line({**STATUS, "connected": False}, now=1700000005) == \
        "Device: Desk 2 · offline"


def test_device_line_stale_status_counts_as_offline():
    """A daemon that stopped writing (crashed, unloaded) is offline even if
    its last file said connected."""
    assert model.device_line(STATUS, now=1700000000 + model.STALE_AFTER + 1) == \
        "Device: Desk 2 · offline"


def test_device_line_without_status_uses_config_name():
    assert model.device_line(None, config_name="Desk 9") == "Device: Desk 9 · offline"
    assert model.device_line(None) == "Device: ToknMon · offline"


# ---------------------------------------------------------------------------
# device name validation (same rule as the daemon and the installer)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["ToknMon", "Desk 2", "A", "X" * 18, "a-b_c.d"])
def test_valid_device_names(name):
    assert model.is_valid_device_name(name)


@pytest.mark.parametrize("name", ["", "X" * 19, "bad#name", "café", " lead", "trail ",
                                  "tab\tin", None])
def test_invalid_device_names(name):
    assert not model.is_valid_device_name(name)


def test_device_name_rule_matches_daemon():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from daemon.claude_usage_daemon import is_valid_device_name as daemon_rule
    for name in ["ToknMon", "", "X" * 18, "X" * 19, "bad#name", "café", " x", "x y"]:
        assert model.is_valid_device_name(name) == daemon_rule(name), name


# ---------------------------------------------------------------------------
# apps toggle
# ---------------------------------------------------------------------------

def test_focus_enabled_from_apps_value():
    assert model.focus_enabled("meter,focus") is True
    assert model.focus_enabled(None) is True          # unset = default = suite
    assert model.focus_enabled("meter") is False
    assert model.focus_enabled(" Meter , FOCUS ") is True


def test_apps_value_for_focus_toggle():
    assert model.apps_value(focus=True) == "meter,focus"
    assert model.apps_value(focus=False) == "meter"


# ---------------------------------------------------------------------------
# providers submenu
# ---------------------------------------------------------------------------

def test_provider_states_auto():
    assert model.provider_states(None) == {"auto": True, "claude": False, "codex": False,
                                           "kimi": False, "grok": False}
    assert model.provider_states("auto") == model.provider_states(None)


def test_provider_states_explicit_list():
    states = model.provider_states("codex, claude")
    assert states == {"auto": False, "claude": True, "codex": True, "kimi": False, "grok": False}


def test_toggle_provider_from_auto_starts_an_explicit_list():
    assert model.toggle_provider("auto", "codex") == "codex"
    assert model.toggle_provider(None, "kimi") == "kimi"


def test_toggle_provider_adds_and_removes_in_registry_order():
    assert model.toggle_provider("codex", "claude") == "claude, codex"
    assert model.toggle_provider("claude, codex", "codex") == "claude"


def test_toggle_provider_removing_last_one_falls_back_to_auto():
    assert model.toggle_provider("claude", "claude") == "auto"


def test_select_auto():
    assert model.select_auto() == "auto"


# ---------------------------------------------------------------------------
# sound and clock
# ---------------------------------------------------------------------------

def test_sound_states():
    assert model.sound_states({"chime": "on", "beep": "off"}) == {"Chime": True, "Beep": False}
    assert model.sound_states({}) == {"Chime": False, "Beep": False}
    assert model.sound_states({"chime": "ON"}) == {"Chime": True, "Beep": False}


def test_sound_key_and_value():
    assert model.SOUND_KEYS == {"Chime": "chime", "Beep": "beep"}
    assert model.onoff(True) == "on" and model.onoff(False) == "off"


def test_clock_states_radio():
    assert model.clock_states("auto") == {"Off": False, "Auto": True, "12h": False, "24h": False}
    assert model.clock_states(None) == {"Off": True, "Auto": False, "12h": False, "24h": False}
    assert model.clock_states("12") == {"Off": False, "Auto": False, "12h": True, "24h": False}
    assert model.clock_states("garbage") == {"Off": True, "Auto": False, "12h": False, "24h": False}


def test_clock_value_for_label():
    assert [model.clock_value(l) for l in ("Off", "Auto", "12h", "24h")] == \
        ["off", "auto", "12", "24"]


# ---------------------------------------------------------------------------
# about / version
# ---------------------------------------------------------------------------

def test_read_version(tmp_path):
    assert model.read_version(tmp_path / "VERSION") == "dev"
    (tmp_path / "VERSION").write_text("1.2.3\n")
    assert model.read_version(tmp_path / "VERSION") == "1.2.3"


def test_about_text_mentions_version_and_upstream():
    text = model.about_text("1.2.3")
    assert "ToknMon 1.2.3" in text and "Clawdmeter" in text


# ---------------------------------------------------------------------------
# daemon (launchd)
# ---------------------------------------------------------------------------

# Trimmed from real `launchctl print gui/501/com.toknmon.daemon` output:
# top-level fields sit one tab deep, nested blocks two.
LAUNCHCTL_RUNNING = """gui/501/com.toknmon.daemon = {
\tactive count = 1
\tpath = /opt/toknmon-test/Library/LaunchAgents/com.toknmon.daemon.plist
\ttype = LaunchAgent
\tstate = running

\tprogram = /opt/toknmon-test/toknmon/daemon/.venv/bin/python
\targuments = {
\t\t/opt/toknmon-test/toknmon/daemon/.venv/bin/python
\t\t/opt/toknmon-test/toknmon/daemon/claude_usage_daemon.py
\t}

\tenvironment = {
\t\tstate = not-a-top-level-field
\t}

\truns = 1
\tpid = 23558
\tlast exit code = (never exited)
}
"""
LAUNCHCTL_EXIT_78 = (LAUNCHCTL_RUNNING
                     .replace("state = running", "state = spawn scheduled")
                     .replace("\tpid = 23558\n", "")
                     .replace("(never exited)", "78: EX_CONFIG"))


def test_parse_launchctl_print_reads_top_level_fields_only():
    info = model.parse_launchctl_print(LAUNCHCTL_RUNNING)
    assert info["state"] == "running"
    assert info["pid"] == "23558"
    assert info["program"] == "/opt/toknmon-test/toknmon/daemon/.venv/bin/python"
    assert info["last exit code"] == "(never exited)"
    assert "arguments" not in info and "environment" not in info


def test_last_exit_code():
    assert model.last_exit_code(model.parse_launchctl_print(LAUNCHCTL_EXIT_78)) == 78
    assert model.last_exit_code(model.parse_launchctl_print(LAUNCHCTL_RUNNING)) is None
    assert model.last_exit_code(None) is None


@pytest.mark.parametrize("text, program_exists, expected", [
    (LAUNCHCTL_RUNNING, True, "Daemon: running"),
    (LAUNCHCTL_EXIT_78, False, "Daemon: stopped · Python missing"),
    (LAUNCHCTL_EXIT_78, True, "Daemon: stopped · exit 78"),
    (LAUNCHCTL_EXIT_78.replace("78: EX_CONFIG", "(never exited)"), True, "Daemon: stopped"),
    (None, True, "Daemon: not loaded"),
])
def test_daemon_line(text, program_exists, expected):
    info = model.parse_launchctl_print(text) if text is not None else None
    assert model.daemon_line(info, program_exists=program_exists) == expected


def test_restart_problem_is_none_when_running():
    info = model.parse_launchctl_print(LAUNCHCTL_RUNNING)
    assert model.restart_problem(info) is None


def test_restart_problem_names_missing_python_and_the_installer():
    info = model.parse_launchctl_print(LAUNCHCTL_EXIT_78)
    text = model.restart_problem(info, program_exists=False)
    assert "/opt/toknmon-test/toknmon/daemon/.venv/bin/python" in text
    assert "./install-mac.sh" in text


def test_restart_problem_reports_the_exit_code_and_logs():
    info = model.parse_launchctl_print(LAUNCHCTL_EXIT_78)
    text = model.restart_problem(info)
    assert "78" in text and "Open logs" in text


def test_restart_problem_when_launchd_refused_the_plist():
    text = model.restart_problem(None, load_error="Bootstrap failed: 5: Input/output error")
    assert "Bootstrap failed: 5" in text and "./install-mac.sh" in text


def test_restart_problem_when_not_installed():
    text = model.restart_problem(None, installed=False)
    assert "not installed" in text and "./install-mac.sh" in text
