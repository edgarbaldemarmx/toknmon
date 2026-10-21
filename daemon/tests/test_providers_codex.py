"""Codex provider: newest ``rate_limits`` line in the local rollout logs.

No network and no auth: the provider scans
``${CODEX_HOME:-~/.codex}/sessions/**/rollout-*.jsonl`` modified in the last
7 days and picks the ``rate_limits`` line with the highest ``timestamp``.
"""

import asyncio
import json
import os
import shutil
import time
from pathlib import Path

from daemon.providers import codex, to_payload

FIXTURE = Path(__file__).parent / "fixtures" / "codex_rollout.jsonl"

# The fixture's 5h window resets at 1792000000; 240 minutes before that.
NOW = 1792000000 - 240 * 60
WEEKLY_MINS = int(round((1792356040 - NOW) / 60))


def _run(coro):
    return asyncio.run(coro)


def _codex_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "codex"
    (home / "sessions" / "2026" / "10" / "11").mkdir(parents=True)
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


def test_poll_picks_latest_rate_limits_line(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    shutil.copy(FIXTURE, home / "sessions" / "2026" / "10" / "11" / "rollout-2026-10-11T22-00-00-abc.jsonl")

    res = _run(codex.poll(now=NOW))

    assert res.id == "codex"
    assert res.ok is True
    assert res.bars == [("5h", 12, 240), ("Weekly", 40, WEEKLY_MINS)]
    payload = to_payload(res)
    assert payload["p"] == "codex"
    assert (payload["s"], payload["sr"], payload["w"], payload["wr"]) == (12, 240, 40, WEEKLY_MINS)
    assert "f" not in payload


def test_poll_newest_timestamp_wins_across_files(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    day = home / "sessions" / "2026" / "10" / "11"
    shutil.copy(FIXTURE, day / "rollout-a.jsonl")
    newer = {
        "timestamp": "2026-10-11T23:00:00.000Z",
        "type": "event_msg",
        "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 55.5, "window_minutes": 300, "resets_at": 1792000000},
            "secondary": {"used_percent": 70.0, "window_minutes": 10080, "resets_at": 1792356040},
        }},
    }
    (day / "rollout-b.jsonl").write_text(json.dumps(newer) + "\n")
    # Make the older-content file the most recently modified one: content
    # timestamp must win over mtime.
    os.utime(day / "rollout-a.jsonl", (time.time() + 10, time.time() + 10))

    res = _run(codex.poll(now=NOW))
    assert res.bars[0] == ("5h", 56, 240)
    assert res.bars[1] == ("Weekly", 70, WEEKLY_MINS)


def test_poll_expired_reset_reports_zero(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    shutil.copy(FIXTURE, home / "sessions" / "2026" / "10" / "11" / "rollout-a.jsonl")

    res = _run(codex.poll(now=1792000000 + 30))  # 5h window has reset, weekly has not
    assert res.bars[0] == ("5h", 0, 0)
    assert res.bars[1][1] == 40


def test_poll_weekly_only_account_omits_5h_bar(tmp_path, monkeypatch):
    """Live shape seen on a weekly-only plan: primary is the 10080 window and
    secondary is null. Bars are keyed by window, not by primary/secondary slot,
    and a window the plan does not report is omitted rather than sent as 0."""
    home = _codex_home(tmp_path, monkeypatch)
    line = {
        "timestamp": "2026-10-11T22:40:17.951Z",
        "type": "event_msg",
        "payload": {"type": "token_count", "rate_limits": {
            "primary": {"used_percent": 18.0, "window_minutes": 10080, "resets_at": 1792356040},
            "secondary": None,
            "plan_type": "prolite",
        }},
    }
    (home / "sessions" / "2026" / "10" / "11" / "rollout-a.jsonl").write_text(json.dumps(line) + "\n")

    res = _run(codex.poll(now=NOW))
    assert res.ok is True
    assert res.bars == [("Weekly", 18, WEEKLY_MINS)]
    payload = to_payload(res)
    assert (payload["w"], payload["wr"]) == (18, WEEKLY_MINS)
    assert "s" not in payload and "sr" not in payload


def test_poll_no_sessions_dir_is_not_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))
    res = _run(codex.poll(now=NOW))
    assert res.ok is False
    assert to_payload(res) == {"p": "codex", "ok": False}


def test_poll_files_without_rate_limits_is_not_ok(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    (home / "sessions" / "2026" / "10" / "11" / "rollout-a.jsonl").write_text(
        json.dumps({"timestamp": "2026-10-11T22:00:00Z", "type": "session_meta", "payload": {}}) + "\n"
    )
    assert _run(codex.poll(now=NOW)).ok is False


def test_poll_ignores_files_older_than_7_days(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    old = home / "sessions" / "2026" / "10" / "11" / "rollout-old.jsonl"
    shutil.copy(FIXTURE, old)
    stale = NOW - 8 * 86400
    os.utime(old, (stale, stale))
    assert _run(codex.poll(now=NOW)).ok is False


def test_poll_skips_malformed_lines(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    f = home / "sessions" / "2026" / "10" / "11" / "rollout-a.jsonl"
    f.write_text('{"rate_limits": not json\n' + FIXTURE.read_text())
    assert _run(codex.poll(now=NOW)).bars[0] == ("5h", 12, 240)


def _write_limits(home: Path, primary: dict | None, secondary: dict | None) -> None:
    line = {
        "timestamp": "2026-10-11T22:40:17.951Z",
        "type": "event_msg",
        "payload": {"type": "token_count", "rate_limits": {"primary": primary, "secondary": secondary}},
    }
    (home / "sessions" / "2026" / "10" / "11" / "rollout-a.jsonl").write_text(json.dumps(line) + "\n")


def test_poll_maps_non_canonical_windows_tolerantly(tmp_path, monkeypatch):
    """Codex does not always report exactly 300/10080: anything up to 10 h is
    the short bar, anything longer the weekly bar."""
    home = _codex_home(tmp_path, monkeypatch)
    _write_limits(home,
                  {"used_percent": 9.0, "window_minutes": 299, "resets_at": 1792000000},
                  {"used_percent": 33.0, "window_minutes": 1440, "resets_at": 1792356040})

    res = _run(codex.poll(now=NOW))
    assert res.ok is True
    assert res.bars == [("5h", 9, 240), ("Weekly", 33, WEEKLY_MINS)]


def test_poll_two_windows_same_bucket_keep_shorter_5h_and_longer_weekly(tmp_path, monkeypatch):
    home = _codex_home(tmp_path, monkeypatch)
    _write_limits(home,
                  {"used_percent": 50.0, "window_minutes": 600, "resets_at": 1792000000},
                  {"used_percent": 20.0, "window_minutes": 60, "resets_at": 1792000000})
    assert _run(codex.poll(now=NOW)).bars == [("5h", 20, 240)]

    _write_limits(home,
                  {"used_percent": 70.0, "window_minutes": 1440, "resets_at": 1792356040},
                  {"used_percent": 40.0, "window_minutes": 10080, "resets_at": 1792356040})
    assert _run(codex.poll(now=NOW)).bars == [("Weekly", 40, WEEKLY_MINS)]
