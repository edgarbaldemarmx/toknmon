"""Provider auto-detection: ``providers = auto`` (the default) polls only the
providers whose CLI is installed and logged in on this machine.

Detection is local and cheap (no network): Claude needs a readable OAuth token
source, Codex a ``rollout-*.jsonl`` under ``$CODEX_HOME/sessions``, Kimi a
credential file under ``$KIMI_CODE_HOME/credentials``, Grok an ``auth.json``
entry with a ``key`` under ``$GROK_HOME``. The installer runs the
same code through ``claude_usage_daemon.py --detect``.
"""

import asyncio
import json
import os
import time
from pathlib import Path

from daemon.providers import (
    AUTO, DETECTORS, PROVIDERS, DetectResult, ProviderResult, detect,
    parse_providers_setting, resolve_providers,
)
from daemon.providers import claude as claude_provider
import daemon.claude_usage_daemon as mod


def _run(coro):
    return asyncio.run(coro)


def _codex_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "codex"
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def _kimi_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "kimi"
    monkeypatch.setenv("KIMI_CODE_HOME", str(home))
    return home


def _grok_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "grok"
    monkeypatch.setenv("GROK_HOME", str(home))
    return home


def _claude_sources(monkeypatch, sources: dict[str, str | None], dirs: list[Path]):
    """Stand in for the daemon's token reader: ``dir name -> source label``."""
    monkeypatch.setattr(claude_provider, "config_dirs", lambda: dirs)
    monkeypatch.setattr(claude_provider, "token_source", lambda d: sources.get(d.name))


# --- per-provider detection ------------------------------------------------

def test_detect_codex_needs_a_rollout_log_of_any_age(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    res = detect("codex")
    assert res == DetectResult(False, res.reason)
    assert "Codex" in res.reason and "sessions" in res.reason and "run it once" in res.reason

    (home / "sessions").mkdir(parents=True)
    assert detect("codex").available is False

    log = home / "sessions" / "2025" / "01" / "01" / "rollout-old.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text("{}\n")
    old = time.time() - 400 * 86400          # far older than the 7-day poll window
    os.utime(log, (old, old))
    res = detect("codex")
    assert res.available is True
    assert "rollout" not in res.reason or "found" in res.reason.lower()


def test_detect_kimi_accepts_an_expired_credential_file(tmp_path, monkeypatch):
    home = _kimi_home(tmp_path, monkeypatch)
    res = detect("kimi")
    assert res.available is False
    assert "Kimi" in res.reason and "credentials" in res.reason and "log in" in res.reason

    (home / "credentials").mkdir(parents=True)
    assert detect("kimi").available is False

    (home / "credentials" / "kimi-code.json").write_text(json.dumps(
        {"access_token": "tok-expired", "refresh_token": "r", "expires_at": 1}))
    assert detect("kimi").available is True


def test_detect_kimi_rejects_a_credential_file_without_a_token(tmp_path, monkeypatch):
    home = _kimi_home(tmp_path, monkeypatch)
    (home / "credentials").mkdir(parents=True)
    (home / "credentials" / "kimi-code.json").write_text(json.dumps({"scope": "x"}))
    res = detect("kimi")
    assert res.available is False
    assert "access token" in res.reason


def test_detect_claude_uses_the_daemon_token_reader(monkeypatch):
    dirs = [Path("/x/.claude"), Path("/x/.claude-work")]
    _claude_sources(monkeypatch, {".claude": None, ".claude-work": None}, dirs)
    res = detect("claude")
    assert res.available is False
    assert "Claude Code" in res.reason and "claude login" in res.reason

    _claude_sources(monkeypatch, {".claude": None, ".claude-work": "/x/.claude-work/.credentials.json"}, dirs)
    res = detect("claude")
    assert res.available is True
    assert ".claude-work" in res.reason


def test_detect_never_exposes_a_token(monkeypatch):
    _claude_sources(monkeypatch, {".claude": "macOS Keychain"}, [Path("/x/.claude")])
    res = detect("claude")
    assert res.available is True
    assert "sk-ant" not in res.reason and "Keychain" in res.reason


def test_detect_unknown_provider_is_unavailable():
    res = detect("gemini")
    assert res.available is False and "gemini" in res.reason


def test_detect_grok_needs_an_auth_entry_with_a_key(tmp_path, monkeypatch):
    home = _grok_home(tmp_path, monkeypatch)
    res = detect("grok")
    assert res.available is False and "grok login" in res.reason

    home.mkdir()
    (home / "auth.json").write_text(json.dumps(
        {"https://auth.x.ai::u": {"key": "xai-secret", "expires_at": "2000-01-01T00:00:00Z"}}))
    res = detect("grok")
    assert res.available is True                 # expired is fine: Grok refreshes, log fallback
    assert "xai-secret" not in res.reason and "auth.json" in res.reason


def test_detectors_cover_the_registry():
    assert set(DETECTORS) == set(PROVIDERS) == {"claude", "codex", "kimi", "grok"}


# --- config parsing --------------------------------------------------------

def test_parse_providers_auto_is_the_default():
    assert parse_providers_setting(None) is AUTO
    assert parse_providers_setting("") is AUTO
    assert parse_providers_setting("auto") is AUTO
    assert parse_providers_setting("  Auto ") is AUTO


def test_parse_providers_explicit_list_still_works():
    assert parse_providers_setting("claude, codex") == ["claude", "codex"]
    assert parse_providers_setting("kimi") == ["kimi"]


def test_parse_providers_fully_unknown_falls_back_to_auto():
    logged = []
    assert parse_providers_setting("gemini", log=logged.append) is AUTO
    assert any("gemini" in line for line in logged)


# --- resolution ------------------------------------------------------------

def _fake_detect(monkeypatch, available: dict[str, bool]):
    """Fake detectors for ``available``; Grok defaults to unavailable so tests
    written for three providers never read the real ``~/.grok``."""
    available = {"grok": False, **available}
    for pid, ok in available.items():
        reason = f"{pid} ok" if ok else f"{pid.title()} CLI not found: fake reason."
        monkeypatch.setitem(DETECTORS, pid, lambda ok=ok, reason=reason: DetectResult(ok, reason))


def test_resolve_auto_keeps_registry_order_and_reports_skipped(monkeypatch):
    _fake_detect(monkeypatch, {"claude": True, "codex": True, "kimi": False})
    chosen, skipped = resolve_providers(AUTO)
    assert chosen == ["claude", "codex"]
    assert list(skipped) == ["kimi", "grok"] and "fake reason" in skipped["kimi"]


def test_resolve_explicit_list_ignores_detection(monkeypatch):
    _fake_detect(monkeypatch, {"claude": False, "codex": False, "kimi": False})
    assert resolve_providers(["claude", "kimi"]) == (["claude", "kimi"], {})


def test_resolve_auto_with_nothing_available_is_empty(monkeypatch):
    _fake_detect(monkeypatch, {"claude": False, "codex": False, "kimi": False})
    chosen, skipped = resolve_providers(AUTO)
    assert chosen == [] and set(skipped) == {"claude", "codex", "kimi", "grok"}


def test_read_providers_auto_logs_only_when_the_set_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")   # absent -> auto
    monkeypatch.setattr(mod, "_last_auto_resolution", None)
    logged = []
    monkeypatch.setattr(mod, "log", logged.append)
    _fake_detect(monkeypatch, {"claude": True, "codex": True, "kimi": False})
    assert mod.read_providers() == ["claude", "codex"]
    assert mod.read_providers() == ["claude", "codex"]
    assert len(logged) == 1
    assert logged[0].startswith("Providers (auto): claude, codex")
    assert "kimi skipped: Kimi CLI not found: fake reason." in logged[0]

    _fake_detect(monkeypatch, {"kimi": True, "grok": True})
    assert mod.read_providers() == ["claude", "codex", "kimi", "grok"]
    assert len(logged) == 2 and "skipped" not in logged[1]


def test_read_providers_explicit_config_bypasses_detection(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("providers = claude, kimi\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    _fake_detect(monkeypatch, {"claude": False, "codex": False, "kimi": False})
    assert mod.read_providers() == ["claude", "kimi"]


# --- collect_payloads with the resolved list ------------------------------

CLAUDE = {"p": "claude", "s": 17, "sr": 110, "w": 73, "wr": 860, "st": "allowed", "acct": "pro", "ok": True}


async def _ok(pid: str) -> ProviderResult:
    return ProviderResult(id=pid, bars=[("5h", 1, 10), ("Weekly", 2, 20)])


def test_auto_two_available_sends_both_tagged(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")
    monkeypatch.setattr(mod, "_last_auto_resolution", None)
    monkeypatch.setattr(mod, "log", lambda _m: None)
    _fake_detect(monkeypatch, {"claude": True, "codex": True, "kimi": False})
    polled = []
    monkeypatch.setitem(PROVIDERS, "codex", lambda: (polled.append("codex"), _ok("codex"))[1])
    monkeypatch.setitem(PROVIDERS, "kimi", lambda: (polled.append("kimi"), _ok("kimi"))[1])
    providers = mod.read_providers()
    payloads = _run(mod.collect_payloads(providers, dict(CLAUDE), False, {}))
    assert [p["p"] for p in payloads] == ["claude", "codex"]
    assert polled == ["codex"]                      # kimi was never polled


def test_auto_claude_only_omits_p_for_backward_compat(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_FILE", tmp_path / "config")
    monkeypatch.setattr(mod, "_last_auto_resolution", None)
    monkeypatch.setattr(mod, "log", lambda _m: None)
    _fake_detect(monkeypatch, {"claude": True, "codex": False, "kimi": False})
    providers = mod.read_providers()
    assert providers == ["claude"]
    payloads = _run(mod.collect_payloads(providers, dict(CLAUDE), False, {}))
    assert len(payloads) == 1 and "p" not in payloads[0]


def test_explicit_list_polls_undetected_provider_as_no_data(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    cfg.write_text("providers = claude, kimi\n")
    monkeypatch.setattr(mod, "CONFIG_FILE", cfg)
    monkeypatch.setattr(mod, "log", lambda _m: None)
    _fake_detect(monkeypatch, {"kimi": False})

    async def dead():
        return ProviderResult(id="kimi", bars=[], ok=False, extra={"reason": "no credentials"})
    monkeypatch.setitem(PROVIDERS, "kimi", dead)
    providers = mod.read_providers()
    payloads = _run(mod.collect_payloads(providers, dict(CLAUDE), False, {}))
    assert payloads[1] == {"p": "kimi", "ok": False}


# --- `--detect` CLI --------------------------------------------------------

def test_detection_lines_format(monkeypatch):
    _fake_detect(monkeypatch, {"claude": True, "codex": True, "kimi": False})
    lines = mod.detection_lines()
    assert lines == [
        "claude: available",
        "codex: available",
        "kimi: unavailable — Kimi CLI not found: fake reason.",
        "grok: unavailable — Grok CLI not found: fake reason.",
    ]


def test_print_detection_writes_one_line_per_provider(monkeypatch, capsys):
    _fake_detect(monkeypatch, {"claude": False, "codex": True, "kimi": True})
    rc = mod.print_detection()
    out = capsys.readouterr().out.splitlines()
    assert rc == 0
    assert out == ["claude: unavailable — Claude CLI not found: fake reason.",
                   "codex: available", "kimi: available",
                   "grok: unavailable — Grok CLI not found: fake reason."]
