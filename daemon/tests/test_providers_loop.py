"""Main-loop poll cadence: alert flags must not turn into a poll storm.

The BLE loop wakes every ``TICK`` seconds and decides whether to poll the
providers now. Alert/clear flags are only cleared by a successful Claude
write, so without a guard they would force a full provider poll (Kimi HTTP +
Codex log scan) on every tick whenever Claude is disabled or failing. The
decision lives in the pure helper :func:`should_poll_now`.
"""

import daemon.claude_usage_daemon as mod
from daemon.claude_usage_daemon import POLL_INTERVAL, TICK, should_poll_now


def test_interval_elapsed_polls():
    assert should_poll_now(POLL_INTERVAL, alert_pending=False, refresh_requested=False,
                           claude_enabled=True, alert_poll_used=False)


def test_refresh_request_polls_early():
    assert should_poll_now(TICK, alert_pending=False, refresh_requested=True,
                           claude_enabled=True, alert_poll_used=False)


def test_no_flags_waits_for_interval():
    assert not should_poll_now(TICK, alert_pending=False, refresh_requested=False,
                               claude_enabled=True, alert_poll_used=False)


def test_alert_without_claude_does_not_poll_early():
    """``providers = codex, kimi``: alert extras ride on the Claude payload, so
    a pending alert can never be delivered and must not shortcut the interval."""
    assert not should_poll_now(TICK, alert_pending=True, refresh_requested=False,
                               claude_enabled=False, alert_poll_used=False)


def test_alert_with_claude_polls_early_once():
    assert should_poll_now(TICK, alert_pending=True, refresh_requested=False,
                           claude_enabled=True, alert_poll_used=False)
    # Claude failed transiently, the flag is still pending: no second shortcut.
    assert not should_poll_now(TICK, alert_pending=True, refresh_requested=False,
                               claude_enabled=True, alert_poll_used=True)


def test_claude_failing_with_alert_polls_at_most_once_before_interval():
    """Drive the helper the way the loop does: one tick after another with a
    pending alert that never gets delivered (Claude keeps failing)."""
    polls = 0
    alert_poll_used = False
    last_poll = 0.0
    for tick in range(1, 12):           # 11 ticks = 55 s < POLL_INTERVAL
        now = tick * TICK
        if should_poll_now(now - last_poll, alert_pending=True, refresh_requested=False,
                           claude_enabled=True, alert_poll_used=alert_poll_used):
            polls += 1
            alert_poll_used = True
            last_poll = now                 # other providers wrote fine
    assert polls == 1


def test_drop_alert_flags_without_claude_logs_once(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(mod, "log", lines.append)
    assert mod.drop_undeliverable_alert(["codex", "kimi"], alert_pending=True) is True
    assert mod.drop_undeliverable_alert(["claude", "codex"], alert_pending=True) is False
    assert mod.drop_undeliverable_alert(["codex"], alert_pending=False) is False   # nothing to drop
    assert len(lines) == 1 and "Claude" in lines[0]
