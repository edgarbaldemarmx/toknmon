# Changelog

All notable changes to ToknMon are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

Milestones are tracked in `docs/odd/` (one feature document per milestone,
H0–H8); the entries below summarize them.

## [Unreleased]

## [0.1.0] — 2026-10-12

First public release of the fork. Everything below is relative to upstream
[Clawdmeter](https://github.com/HermannBjorgvin/Clawdmeter) at commit `1f446fd`.

### Added

- **Configurable Bluetooth device name** (H1). The name is stored in NVS and
  survives reflashing; set it with `./flash-mac.sh <board> --name "<name>"`,
  `./flash-mac.sh --rename "<name>"` or the serial command `name <text>`
  (1–18 printable ASCII characters, no `#`). The daemon reads `device_name`
  from its config for the HID fallback and stale-bond repair.
- **Multi-provider monitoring** (H2): the macOS daemon polls Claude Code,
  OpenAI Codex CLI and Kimi Code and sends one BLE payload per provider
  (`"p"` field). The firmware keeps one usage slot per provider with
  per-slot freshness (90 s), shows them as a carousel (tap or swipe to page,
  8 s auto-rotate) and skips providers without data.
- **Claude usage from `GET /api/oauth/usage`** (H2): one request with the
  Claude Code OAuth token, no token spend, and the model-scoped weekly window
  (the **Fable** bar) when the subscription exposes one. The header-probe path
  remains as the Enterprise fallback.
- **Codex provider** (H2): reads `rate_limits` from the newest local
  `~/.codex/sessions/**/rollout-*.jsonl`; no network, no credentials.
- **Kimi provider** (H2, H5): reads `~/.kimi-code/credentials`, calls the
  Kimi Code usage API and **refreshes the OAuth token itself** when it is
  expired or about to expire, writing it back atomically (mode 0600), so the
  slot stays live without the Kimi CLI running. `kimi_token_url` config key.
- **Provider mascots** (H3): hand-drawn Codex (three dots) and Kimi (crescent
  moon) corner mascots with idle and act animations, a per-provider mascot
  spec in the splash engine, and the **text-grid animation pipeline**
  (`assets/animations/*.txt` → `tools/convert_grid_animations.js` →
  `firmware/src/custom_animations.h`) with validation and `--verify` PNG
  strips.
- **Mountain-bike animations** (H4) for Clawd, Codex and Kimi, playable as
  corner acts and as full-size splash animations.
- **Per-provider palettes** (H5): Claude clay, Codex teal, Kimi blue for
  titles, bars, reset labels and the status line.
- **Codex dot-grid screen** (H5): a 10×10 grid of dots fills to the weekly
  percentage, with a large percentage and reset time; a compact 5h bar
  appears only when the plan reports a short window.
- **Mascot mode** (H6): long-press the usage view to open the full-size
  mascot set of the provider on screen (idle, acts, bike, scenes) with the
  provider label; extra acts `codex.think` and `kimi.sleep`.
- **Ambient parade** (H6): after 5 minutes without input the device rotates
  the full-size mascots of every provider with live data every 20 s.
- **Full-screen scenes** (H7): `codex.scene.wave`, `codex.scene.rain`,
  `kimi.scene.night`, `kimi.scene.orbit`, authored by an AI agent through the
  grid pipeline.
- **Gesture navigation** (H7): swipe up/down toggles splash ↔ meter, swipe
  left/right steps providers (meter) or animations (splash), tap on the
  splash advances the animation, long-press on the meter opens mascot mode.
- **Serial QA commands**: `screen usage|splash [claude|codex|kimi]`,
  `slot <0-2>`, `next`, `splash next|prev`, `swipe up|down|left|right`,
  `parade on|off`; `./screenshot.sh --screen usage|splash[:provider]`.
- **Simulator hooks**: `SIM_SCENARIO`, `SIM_AUTOSHOT_MS`, `SIM_AUTOSHOT_PATH`,
  `SIM_SPLASH_PROVIDER`, `SIM_PARADE`, `SIM_NO_BATTERY`; multi-provider
  scenario and `firmware/sim/gallery.jsonl`.
- **Installer flags** (H8): `install-mac.sh --yes --providers <list>
  --device-name <name> --no-prime`; provider auto-detection
  (`providers = auto`, `claude_usage_daemon.py --detect`);
  `daemon/requirements-macos.txt`.
- **Gallery and media** (H8): animated GIF export
  (`convert_grid_animations.js --gif DIR`), `tools/make_gallery.sh`, and the
  screenshots and GIFs under `docs/media/`.
- **CI** (H8): GitHub Actions running the daemon tests, the tool tests, the
  converter idempotency check, the native simulator build and the
  `waveshare_amoled_216` firmware build (binary uploaded as an artifact).
- **Documentation** (H8): README, `docs/install-macos.md`, `docs/flashing.md`,
  `docs/providers.md`, `docs/controls.md`, `docs/animations.md`,
  `docs/troubleshooting.md`, `docs/development.md`, `LICENSE`, `NOTICE.md`,
  `CONTRIBUTING.md`.

### Changed

- **Rebranded to ToknMon** (H8): default device name `ToknMon`, config
  `~/.config/toknmon/config`, launchd label `com.toknmon.daemon`, logs
  `~/Library/Logs/toknmon.{out,err}.log`. The legacy names `TokenMon` and
  `Clawdmeter` are still accepted by the daemon; NVS namespaces are unchanged
  so bonds, brightness and the device name survive the upgrade.
- The firmware's BLE RX path is a 3-deep queue so back-to-back provider
  writes are not lost; head/tail indices use release/acquire atomics.
- The attention alert (Claude Code hooks) rides only on the Claude payload;
  alerts are dropped with a log line when Claude is not an enabled provider.
- Repository layout: milestone documents moved to `docs/odd/`, the simulator
  guide to `docs/simulator.md`; the scraped Clawd sources are no longer
  committed (`tools/fetch_official_clawd.sh` fetches them on demand).

### Fixed

- The "Period" pill never reverted to "Weekly" after an Enterprise payload
  (upstream bug).
- A tap that dismissed an attention alert also paged the carousel; the
  carousel no longer advances while an alert is showing.
- Alert flags could trigger a 5 s poll storm when Claude was failing or not
  enabled.
- Empty `limits[]` from the usage endpoint now falls through to the header
  probe instead of rendering an empty screen.

### Migration

- `install-mac.sh` stops the legacy `com.user.claude-usage-daemon` agent,
  parks its plist under `~/.config/toknmon/legacy/` and copies
  `~/.config/claude-usage-monitor/{config,ble-address}` to
  `~/.config/toknmon/` when the new files are absent (nothing is deleted).
- After renaming a board, unpair it in System Settings → Bluetooth and pair
  it again: macOS caches the advertised name with the bond.

### Known limitations

- Only the Waveshare ESP32-S3-Touch-AMOLED-2.16 is verified. The other board
  ports inherited from Clawdmeter compile but are untested with ToknMon.
- The Linux and Windows daemons are inherited, Claude-only and untested.
- The attention-hook flags still live under `~/.config/claude-usage-monitor`
  (shared with `daemon/attention-hook.sh`).

[Unreleased]: https://github.com/edgarbaldemarmx/toknmon/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/edgarbaldemarmx/toknmon/releases/tag/v0.1.0
