# Changelog

All notable changes to ToknMon are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

Milestones are tracked in `docs/odd/` (one feature document per milestone,
H0–H10); the entries below summarize them.

## [Unreleased]

### Added

- **Codex reset credits** (H11): the daemon reads OpenAI's reset credits with
  the Codex CLI login (`rc` held, `ru` used in the last 30 days, `rm` minutes
  to the soonest expiry; one fetch per hour, `codex_credits = off` disables
  it) and the Codex page shows them as a "Resets" ledger above the dot grid.
- **Codex pets** (H11): the eight ChatGPT pets (Bsod, Codex, Dewey, Fireball,
  Null Signal, Rocky, Seedy, Stacky) join Codex's full-screen splash set;
  `tools/fetch_codex_pets.sh` + `tools/convert_pet_spritesheet.py` build the
  grids from the sprite sheets (not committed, see `NOTICE.md`).
- **App center and Focus timer** (H12): the side button opens an app center
  with a tile per enabled app. Focus runs deep-work blocks of 5–120 minutes
  in 5-minute steps (default 25), rings the bell three times at the end,
  counts the blocks of the day (NVS, day from the daemon clock) and starts
  the next block with one tap. Serial: `screen apps|focus`, `focus …`,
  `apps`, `sidebtn apps|hid`; sim: `SIM_SCREEN`, `SIM_FOCUS`.
- **BLE config packets** (H12/H13): the daemon sends `{"p":"cfg","ap":…,"n":…}`
  when the `apps` or `device_name` config changes (and once per link); the
  board stores the app list and renames itself without a USB cable.
- **macOS menu-bar app** (H13): `ToknMon.app` (Python, rumps, built with
  py2app) shows each provider's last numbers and the link state from the
  daemon's new `~/.config/toknmon/status.json`, and edits the config in
  place: device name, apps, providers, chime/beep, clock; restart daemon,
  open config/logs. `install-mac.sh` builds and starts it (`--no-gui`
  skips); CI publishes a DMG.
- `install-mac.sh --apps meter|suite` and the `apps` config key choose
  between the usage meter alone and the full suite (meter + Focus timer).

- **Design system** (H14): usage pages, the app center and Focus follow one
  visual system (dark `#0B0F14` background, Inter type, full-width usage
  bars, a credit panel for Codex, `CURRENT · 5H` block for Claude and Kimi,
  footer status dot) with the provider mascots kept in the header; Fable
  shows its model-scoped window as a 5×4 grid of Clawds (one per 5 %); Focus
  gets the amber ring, −5/+5 cards, Pause/Resume, a Paused state and
  "Start next" back to setup. The Bsod pet is Codex's corner avatar and opens
  its splash set. New Inter faces (OFL) in `firmware/src/font_inter_*.c`.

### Changed

- The side button (GPIO18 on the 2.16) now opens the app center; its
  Shift+Tab HID key is opt-in (`sidebtn hid`).
- A device name equal to the stored one is ignored instead of restarting the
  board (the config packet is replayed on every link).

## [1.0.0] — 2026-10-21

Four providers on one desk meter: Grok Build CLI joins Claude Code, Codex CLI
and Kimi Code, the meter stays on the provider you pick, Claude's
model-scoped weekly limit gets its own Fable page, and Codex, Kimi and Grok
get new corner icons. Verified on the Waveshare ESP32-S3-Touch-AMOLED-2.16.

### Added

- **Grok Build CLI provider** (H9): the daemon polls Grok's weekly credit
  window from `https://cli-chat-proxy.grok.com/v1/billing?format=credits`
  with the token Grok keeps in `~/.grok/auth.json`, falling back to the
  newest billing line in Grok's log when it is under 6 h old. The
  firmware gets a fourth slot (`grok`, `slot 3`) with a silver dot grid, an
  original Grokbot-style mascot (a white ball with capsule eyes: idle, look,
  bike, and the full-screen scenes `grok.scene.stars` and `grok.scene.build`)
  and a deeper BLE receive queue so four back-to-back payloads fit. The
  daemon refreshes Grok's token itself through Grok's own `auth.json.lock`
  so the slot stays live while Grok is closed.

- `tools/check_pii.sh` scans every tracked file for personal or hardware
  identifiers (home paths, hostnames, e-mail addresses, non-documentation MAC
  addresses, credential-looking strings, scratch paths) and runs in CI as the
  `pii-check` job.

- **Fable view** (H10): Claude's model-scoped weekly limit gets its own page
  after Claude, a 10×10 grid of small Clawds filled to the percentage, so
  Claude's page keeps two full-size bars. The daemon sends the model name
  as `fl`. Boards without the dot canvas keep the third bar.

- **Corner icons** (H10): Codex, Kimi and Grok get Clawd-sized corner icons
  with more detail, shading and a blink (`<provider>.icon`); the full-screen
  animations and scenes are unchanged.

- `tools/test/shell/test_sim_sticky_view.sh` runs the simulator headless and
  checks that the usage view stays where the user left it (also in CI).

### Changed

- The meter no longer rotates between providers every 8 s (H10): it stays
  on the provider you picked, even when its data goes stale, and the pick
  survives a reboot. A tap or swipe still pages away from a stale pick as
  long as another view is live. Serial `slot` accepts `0-4` (4 = Fable), the
  serial log prints `UI: picked view N` / `UI: restored picked view N` /
  `UI: showing view N`, and the simulator takes `SIM_SLOT=0-4`.

- README hero and provider shots are fresh hardware captures of the H10
  screens (Claude with two bars, Grok with its corner icon).

- The parade no longer starts after 5 minutes without input: the meter stays
  on screen until you touch it, and the animations only play on a tap, swipe
  or long-press (serial `parade on` still starts the parade).

- `screenshot.sh` retries a stalled transfer up to three times and accepts
  `--screen usage:<provider>`; `install-mac.sh` uses `launchctl bootout` /
  `bootstrap` with a documented fallback; `flash-mac.sh` prints usage and a
  hint when called without arguments.

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

[Unreleased]: https://github.com/edgarbaldemarmx/toknmon/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/edgarbaldemarmx/toknmon/compare/v0.1.0...v1.0.0
[0.1.0]: https://github.com/edgarbaldemarmx/toknmon/releases/tag/v0.1.0
