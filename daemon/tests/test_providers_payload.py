"""Provider-agnostic payload contract, config parsing and the daemon's
per-provider payload collection (no BLE, no network)."""

import asyncio
import json
from pathlib import Path

from daemon.providers import (
    PROVIDERS, ProviderResult, parse_providers_setting, to_payload,
)
import daemon.claude_usage_daemon as mod


def _run(coro):
    return asyncio.run(coro)


# --- to_payload ------------------------------------------------------------

def test_to_payload_maps_bars_in_contract_order():
    res = ProviderResult(id="claude", bars=[("Current", 17, 110), ("Weekly", 73, 860), ("Fable", 1, 860)],
                         extra={"acct": "pro"})
    assert to_payload(res) == {
        "p": "claude", "s": 17, "sr": 110, "w": 73, "wr": 860, "f": 1, "fr": 860,
        "st": "allowed", "acct": "pro", "ok": True,
    }


def test_to_payload_two_bars_has_no_f():
    payload = to_payload(ProviderResult(id="codex", bars=[("5h", 12, 240), ("Weekly", 40, 5000)]))
    assert payload == {"p": "codex", "s": 12, "sr": 240, "w": 40, "wr": 5000, "st": "allowed", "ok": True}


def test_to_payload_failure_is_minimal():
    assert to_payload(ProviderResult(id="kimi", bars=[], ok=False)) == {"p": "kimi", "ok": False}


def test_to_payload_fits_ble_write_budget():
    res = ProviderResult(id="claude", bars=[("Current", 100, 99999), ("Weekly", 100, 99999), ("Fable", 100, 99999)],
                         status="rejected", extra={"acct": "pro"})
    payload = {**to_payload(res), "c": 1, "t": 1791788329, "tf": 24}
    assert len(json.dumps(payload, separators=(",", ":"))) <= mod.DEFAULT_MAX_WRITE


# --- parse_providers_setting ----------------------------------------------

def test_parse_providers_default_is_claude_only():
    assert parse_providers_setting(None) == ["claude"]
    assert parse_providers_setting("") == ["claude"]


def test_parse_providers_splits_lowercases_and_dedupes():
    assert parse_providers_setting("Claude, CODEX ,kimi, codex") == ["claude", "codex", "kimi"]


def test_parse_providers_ignores_unknown_names():
    logged = []
    assert parse_providers_setting("claude, gemini", log=logged.append) == ["claude"]
    assert any("gemini" in line for line in logged)


def test_parse_providers_all_unknown_falls_back_to_default():
    assert parse_providers_setting("gemini") == ["claude"]


def test_registry_has_all_three_providers():
    assert set(PROVIDERS) == {"claude", "codex", "kimi"}


# --- read_providers (config) ----------------------------------------------

def test_read_providers_from_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("providers = claude, kimi   # comment\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    assert mod.read_providers() == ["claude", "kimi"]


def test_read_providers_absent_config(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")
    assert mod.read_providers() == ["claude"]


# --- collect_payloads (daemon loop body) ---------------------------------

CLAUDE = {"p": "claude", "s": 17, "sr": 110, "w": 73, "wr": 860, "st": "allowed", "acct": "pro", "ok": True}


def test_collect_claude_only_omits_p_for_backward_compat(monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", Path("/nonexistent/config"))
    payloads = _run(mod.collect_payloads(["claude"], dict(CLAUDE), False, {"b": 1, "m": "hi"}))
    assert payloads == [{"s": 17, "sr": 110, "w": 73, "wr": 860, "st": "allowed", "acct": "pro", "ok": True,
                         "b": 1, "m": "hi"}]


def test_collect_claude_only_dead_token_is_plain_no_data(monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", Path("/nonexistent/config"))
    assert _run(mod.collect_payloads(["claude"], None, True, {"x": 1})) == [{"ok": False, "x": 1}]


def test_collect_claude_transient_failure_sends_nothing_for_claude(monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", Path("/nonexistent/config"))
    assert _run(mod.collect_payloads(["claude"], None, False, {})) == []


def test_collect_multi_provider_keeps_p_and_polls_others_in_order(monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", Path("/nonexistent/config"))

    async def fake_codex():
        return ProviderResult(id="codex", bars=[("5h", 12, 240), ("Weekly", 40, 5000)])

    async def fake_kimi():
        return ProviderResult(id="kimi", bars=[], ok=False)

    monkeypatch.setitem(PROVIDERS, "codex", fake_codex)
    monkeypatch.setitem(PROVIDERS, "kimi", fake_kimi)

    payloads = _run(mod.collect_payloads(["claude", "codex", "kimi"], dict(CLAUDE), False, {"b": 1}))
    assert payloads[0] == {**CLAUDE, "b": 1}          # extras ride only on Claude
    assert payloads[1] == {"p": "codex", "s": 12, "sr": 240, "w": 40, "wr": 5000, "st": "allowed", "ok": True}
    assert payloads[2] == {"p": "kimi", "ok": False}


def test_collect_multi_provider_dead_claude_token_tags_no_data(monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", Path("/nonexistent/config"))
    monkeypatch.setitem(PROVIDERS, "codex", lambda: _ok_codex())
    payloads = _run(mod.collect_payloads(["claude", "codex"], None, True, {}))
    assert payloads[0] == {"p": "claude", "ok": False}
    assert payloads[1]["p"] == "codex"


async def _ok_codex():
    return ProviderResult(id="codex", bars=[("5h", 1, 2), ("Weekly", 3, 4)])


def test_collect_provider_exception_becomes_not_ok(monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", Path("/nonexistent/config"))

    async def boom():
        raise RuntimeError("disk on fire")

    monkeypatch.setitem(PROVIDERS, "codex", boom)
    monkeypatch.setitem(PROVIDERS, "kimi", lambda: _ok_kimi())
    payloads = _run(mod.collect_payloads(["claude", "codex", "kimi"], dict(CLAUDE), False, {}))
    assert payloads[1] == {"p": "codex", "ok": False}
    assert payloads[2]["ok"] is True   # one failing provider never breaks the others


async def _ok_kimi():
    return ProviderResult(id="kimi", bars=[("5h", 3, 200), ("Weekly", 9, 6000)])


def test_collect_other_providers_get_clock_fields(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("clock = 24\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    monkeypatch.setitem(PROVIDERS, "kimi", lambda: _ok_kimi())
    payloads = _run(mod.collect_payloads(["claude", "kimi"], dict(CLAUDE), False, {}))
    assert payloads[1]["tf"] == 24 and "t" in payloads[1]


def test_collect_without_claude_polls_only_listed_providers(monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", Path("/nonexistent/config"))
    monkeypatch.setitem(PROVIDERS, "kimi", lambda: _ok_kimi())
    payloads = _run(mod.collect_payloads(["kimi"], None, True, {}))
    assert [p["p"] for p in payloads] == ["kimi"]


def test_providers_package_imports_as_script_sibling(monkeypatch):
    """launchd runs daemon/claude_usage_daemon.py as a script, so `providers`
    must also import as a top-level package from the daemon/ directory."""
    import importlib
    import sys

    daemon_dir = str(Path(mod.__file__).parent)
    monkeypatch.syspath_prepend(daemon_dir)
    for name in [n for n in sys.modules if n == "providers" or n.startswith("providers.")]:
        monkeypatch.delitem(sys.modules, name)
    pkg = importlib.import_module("providers")
    assert set(pkg.PROVIDERS) == {"claude", "codex", "kimi"}
