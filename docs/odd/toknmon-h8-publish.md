# ToknMon — H8 Rebrand and publish

## Objective
Publish the fork as **ToknMon** at `github.com/edgarbaldemarmx/toknmon`: a personal project anyone can flash on a Waveshare ESP32-S3 Touch AMOLED 2.16 and run from a Mac, with complete English documentation, a feature/animation gallery, a license posture that credits Clawdmeter and warns about bundled Anthropic assets, and CI.

## Problem / Why
The repo still says Clawdmeter everywhere (install label, config dir, device default, docs); README documents upstream's single-provider product; there is no gallery, license, CI, or contributor-facing requirements list; scraped Anthropic GIFs under `research/` add exposure without being needed at runtime (the generated headers are committed).

## Scope
### T1 — Rebrand + cleanup (writer A)
- Name: **ToknMon** (code identifiers `toknmon`). Keep "Clawdmeter" only in attribution and in legacy-compatibility constants.
- Daemon: `DEFAULT_DEVICE_NAME = "ToknMon"`, `LEGACY_DEVICE_NAMES = ("TokenMon", "Clawdmeter")`; config dir `~/.config/toknmon/config` with one-time migration from `~/.config/claude-usage-monitor/config` (copy if the new one is absent; log once); logs `~/Library/Logs/toknmon.{out,err}.log`; launchd label `com.toknmon.daemon` — `install-mac.sh` boots out the legacy `com.user.claude-usage-daemon` if present and removes its plist (say so in output). Plist template renamed `daemon/com.toknmon.daemon.plist`. Add `daemon/requirements-macos.txt` (bleak, httpx, pillow, pytest) and make `install-mac.sh` use it. Non-interactive flags for `install-mac.sh`: `--yes` (defaults), `--providers <list>`, `--device-name <name>`, `--no-prime`.
- Firmware: `BLE_DEFAULT_DEVICE_NAME "ToknMon"`; sim `ble_get_device_name()` → `"ToknMon (sim)"`; NVS namespaces unchanged (bond/brightness/name survive reflash). Serial banner "ToknMon" where the firmware prints its name.
- Scripts: `flash-mac.sh`, `screenshot.sh`, `install-mac.sh` help text; `install.sh`/`install-windows.ps1`/Linux+Windows daemons stay as "inherited from Clawdmeter, Claude-only, untested in ToknMon" with a one-line header comment — no functional rebrand there.
- Repo layout: move `odd/tasks/*` → `docs/odd/` (design log); delete `research/clawd-official/` and update `tools/convert_official_clawd.js` header + `CLAUDE.md` to say the official sources are fetched on demand by `fetch.sh` (keep `fetch.sh` as `tools/fetch_official_clawd.sh` with its probe list) — the generated `splash_animations.h` stays committed; delete `SIM-USAGE.md` if its content is folded into `docs/simulator.md`, else keep; `.gitignore` covers `daemon/.venv`, `firmware/.pio`, `*.bmp`, `sim-autoshot*`.
- `CLAUDE.md`: rebrand, update paths, keep the upstream hardware notes (credit them), replace the "User profile" paragraph with ToknMon maintainer notes.
### T2 — Gallery media (worker B)
- `tools/convert_grid_animations.js --gif DIR`: one animated GIF per custom animation (frames scaled ×6, per-frame delay from holds, loop) via ImageMagick; test added. Output committed under `docs/media/animations/<name>.gif` (13 files).
- Screens captured from the **sim** headless at 480×480 (deterministic, no personal data): `claude-usage.png` (3 bars incl. Fable), `codex-dots.png`, `kimi-usage.png`, `splash-claude.png`, `mascot-codex.png`, `mascot-kimi.png`, `scene-codex-rain.png`, `scene-kimi-night.png`, `parade.png`, `bluetooth-screen.png` → `docs/media/screens/`. Plus two real hardware photos/screenshots renamed from the scratchpad (`hw-claude.png`, `hw-codex.png`) — no names/tokens visible.
- A `docs/media/README.md` listing each file and how to regenerate (`tools/make_gallery.sh` that runs the sim autoshots + GIF export).
### T3 — Documentation (writer C, after T1+T2)
- `README.md` (English, detailed): hero image, one-paragraph pitch, Features (bulleted, with inline screenshots), Animation gallery (table of GIFs per provider: idle, act, think/sleep, bike, scenes), Supported hardware (2.16 verified ✅; other Clawdmeter boards: inherited, untested ⚠️), Requirements (macOS 13+, Python ≥3.10, PlatformIO CLI, Node ≥18, ImageMagick for art, Homebrew list, accounts: Claude Code login, Codex CLI, Kimi Code CLI), Quick start (clone → flash & name → pair → install daemon → choose providers), Using the device (tap/swipe/long-press/PWR, mascot mode, parade, carousel, Fable bar, Codex dot grid), Configuration (`~/.config/toknmon/config` keys), Custom animations (grid format, converter, authoring with an AI agent — the Kimi/the multiplexer workflow in brief), Serial QA commands, Troubleshooting (TCC/Documents, port names, Kimi token refresh, legacy daemon conflict, re-pair after rename), Development (sim, tests, CI), Project structure, Roadmap, Credits (Clawdmeter by Hermann Bjorgvin with link; Anthropic Clawd art/fonts), License.
- `docs/install-macos.md`, `docs/flashing.md`, `docs/providers.md`, `docs/animations.md`, `docs/simulator.md` (from SIM-USAGE.md), `docs/troubleshooting.md` — README links to them; keep README self-sufficient for quick start.
- `LICENSE` (MIT, Edgar Ramos, 2026) + `NOTICE.md` (Clawdmeter attribution; Anthropic fonts Tiempos/Styrene and Clawd mascot are proprietary and not covered; Codex/Kimi mascots are original art); `CHANGELOG.md` (0.1.0 with the H1–H7 feature list); `CONTRIBUTING.md` short (personal project, issues welcome).
### T4 — CI (worker D)
- `.github/workflows/ci.yml`: jobs `daemon-tests` (ubuntu, Python 3.12, `pip install -r daemon/requirements-macos.txt`, `python -m pytest daemon/tests -q`), `tools-tests` (Node 20: `node --test tools/test/`, `bash tools/test/shell/test_device_name_validator.sh`, converter idempotency: run and `git diff --exit-code firmware/src/custom_animations.h`), `firmware-sim` (ubuntu, `libsdl2-dev`, PlatformIO cache, `pio run -d firmware -e sim`), `firmware-2.16` (`pio run -d firmware -e waveshare_amoled_216`, upload `firmware.bin` as artifact). Badge in README (T3 adds it).
### T5 — Publish (parent)
- Rewrite author of the fork's own commits (everything after upstream `1f446fd`) to `Edgar Ramos <<author email>>`; set repo-local `user.email`.
- `gh auth switch -u edgarbaldemarmx` → `gh repo create edgarbaldemarmx/toknmon --public --source . --remote origin --push` with `main` = H8 head; rename the upstream remote to `upstream`; switch back to `<other account>`. Ask the user before the push.
- Reinstall the daemon on this Mac with the new label (migration path exercised); confirm device still connects.

## Constraints
- Branch `feat/toknmon-h8-publish` from H7 (`22a0f52`).
- All artifacts in English. Credit Clawdmeter (Hermann Bjorgvin, github.com/HermannBjorgvin/Clawdmeter) in README, NOTICE and CLAUDE.md.
- Never commit tokens, personal emails other than the git author, device names of the user, or absolute home paths in docs (use `~`).
- Disjoint edit surfaces per worker (listed in each prompt).

## Delivery strategy
`ask-on-risk`. Forecast ~1500 authored changed lines (docs-heavy). Single branch, work-unit commits per task.

## Tasks
- [x] T1 — Rebrand + cleanup (writer A). Route: delegated writer A (multi-file; mapping done inline by the writer). Evidence below; uncommitted in the working tree except the layout moves, which landed in `834e3d5` (see note).
- [x] T2 — Gallery media + GIF export (worker B). Route: delegated writer B (converter + test + script + scenario + media, mapping done inline by the writer). Files: `tools/convert_grid_animations.js` (`--gif DIR`), `tools/test/convert_grid_animations_gif.test.js`, `tools/make_gallery.sh`, `firmware/sim/gallery.jsonl`, `docs/media/README.md`, `docs/media/animations/*.gif` (13), `docs/media/screens/*.png` (9 sim + 3 hardware). `bluetooth-screen.png` not produced (no such screen in this fork). Evidence below; uncommitted.
- [x] T4 — CI workflow (worker D). Route: delegated writer D; files `.github/workflows/ci.yml`, `.github/dependabot.yml`, `.github/ISSUE_TEMPLATE/{bug_report,feature_request}.yml`; local dry run green, GitHub run pending (uncommitted).
- [ ] T3 — README + docs + LICENSE/NOTICE/CHANGELOG (writer C, after T1+T2).
- [ ] T5 — Author rewrite, repo creation, push, daemon reinstall (parent, with user confirmation before push).

## Verification
- `daemon/.venv/bin/python -m pytest daemon/tests -q`; `node --test tools/test/`; shell validator test
- `pio run -d firmware -e sim`, `pio run -d firmware -e waveshare_amoled_216`; flash; device advertises "ToknMon …"
- `install-mac.sh --yes --providers claude,codex,kimi --device-name "<name>"` migrates config, replaces the legacy agent, daemon connects
- CI green on the published repo

## Verification evidence
(pending)

### CI evidence (T4, local dry run on macOS, 2026-10-12)
- `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`: ok (also dependabot.yml and both issue templates)
- `actionlint`: not installed locally, skipped
- `daemon/.venv/bin/python -m pytest daemon/tests -q`: 212 passed, 2 skipped (the 2 skips are Linux-only subprocess tests in `test_windows_token.py`; they run on ubuntu CI)
- `node --test tools/test/`: 8 tests, 8 pass, 0 fail
- `bash tools/test/shell/test_device_name_validator.sh`: all passed, exit 0
- `node tools/convert_grid_animations.js && git diff --exit-code -- firmware/src/custom_animations.h`: no diff (idempotent; ImageMagick only needed with `--verify`)
- `pio run -d firmware -e sim`: 1 succeeded
- Headless smoke `SDL_VIDEODRIVER=dummy SIM_AUTOSHOT_MS=3000 SIM_AUTOSHOT_PATH=... .pio/build/sim/program` from `firmware/`: exit 0, 480x480 24-bit BMP written
- Only confirmable on GitHub: `libsdl2-dev` providing `sdl2-config` for `[env:sim]`, `pip install -r daemon/requirements-macos.txt` (file authored by T1), PlatformIO cache hit rates, `waveshare_amoled_216` build on ubuntu runners.

### T1 evidence (writer A, macOS, 2026-10-12)
- Daemon: `DEFAULT_DEVICE_NAME = "ToknMon"`, `LEGACY_DEVICE_NAMES = ("TokenMon", "Clawdmeter")`; `CONFIG_DIR = ~/.config/toknmon` (`config`, `ble-address`), `LEGACY_CONFIG_DIR` kept; `migrate_legacy_config()` runs at startup, copies `config` and `ble-address` when the new file is absent, logs one line per copy, never deletes. `ATTENTION_DIR` stays at the legacy path on purpose (shared with `daemon/attention-hook.sh`, outside T1's surface; flags are transient). Plist template renamed `daemon/com.toknmon.daemon.plist` (label `com.toknmon.daemon`); `daemon/requirements-macos.txt` added; `daemon/config.example` updated; Linux/Windows daemons and installers carry the two-line "inherited from Clawdmeter" header, no functional change.
- `install-mac.sh`: label/plist/logs (`~/Library/Logs/toknmon.{out,err}.log`) renamed; `pip install -r daemon/requirements-macos.txt`; mirrors the config migration before the prompts; `retire_legacy_agent` boots out `com.user.claude-usage-daemon` (failure ignored) and moves its plist to `~/.config/toknmon/legacy/`; flags `--yes/-y`, `--providers <list>`, `--device-name <name>`, `--no-prime`, `-h/--help`; interactive path unchanged when flags are absent; bash 3.2 compatible (no `declare -A`, no `${var,,}`).
- Firmware: `BLE_DEFAULT_DEVICE_NAME "ToknMon"`; sim `ble_get_device_name()` → `"ToknMon (sim)"`, sim window title "ToknMon sim"; NVS namespaces `clawdmeter`/`clawd` unchanged with comments in `ble.h`/`ble.cpp` explaining why (name and bond survive reflash). `main.cpp`/`ble.cpp` print no brand string at boot (only `board_caps().name`), so nothing to rename there.
- Layout: `odd/tasks/*` → `docs/odd/`, `SIM-USAGE.md` → `docs/simulator.md` (stale `"ss"` session-payload paragraph replaced; `SIM_SCENARIO`, `SIM_AUTOSHOT_MS`, `SIM_AUTOSHOT_PATH`, `SIM_SPLASH_PROVIDER`, `SIM_PARADE`, `SIM_NO_BATTERY` documented), `research/clawd-official/` removed, `fetch.sh` → `tools/fetch_official_clawd.sh` (now takes `[DEST_DIR]`, default `research/clawd-official`, which is git-ignored), `tools/convert_official_clawd.js --src DIR` (`--in` alias, `--help`), `tools/README.md` and `CLAUDE.md` updated; `.gitignore` adds `.pytest_cache/`, `research/`, `*.bmp`, `sim-autoshot*` (`daemon/.venv/`, `firmware/.pio/`, `__pycache__/` were already there).
- `CLAUDE.md`: ToknMon project context with Clawdmeter attribution and inherited hardware notes; "Maintainer notes" replaces the user-profile section; daemon section rewritten around the macOS daemon; technical sections intact.
- Note: the layout moves were staged with `git mv`/`git rm` and were swept into the T4 commit `834e3d5 ci: …` (44 files, all pure renames/deletions). Everything else from T1 is uncommitted in the working tree.
- Tests: `daemon/.venv/bin/python -m pytest daemon/tests -q` → 218 passed, 2 skipped (baseline 212 + 6 new in `daemon/tests/test_config_migration.py`; written together with the implementation, so no RED run was observed). `bash tools/test/shell/test_device_name_validator.sh` → "All device-name validator tests passed." `bash -n install-mac.sh flash-mac.sh screenshot.sh tools/fetch_official_clawd.sh` → ok. `./install-mac.sh --help` prints the flags; `--providers`/`--device-name` without value and unknown options exit 2 before any side effect.
- Builds: `pio run -d firmware -e sim` → SUCCESS; `-e waveshare_amoled_216` → SUCCESS (not flashed).
- Brand audit (`grep -rni 'clawdmeter\|claude-usage-monitor\|TokenMon'`, excluding `.git/.pio/.venv`, `docs/odd/`, `splash_animations.h`): 147 hits. Remaining: attribution and legacy-compat constants/comments (CLAUDE.md, daemon, ble.h/ble.cpp, brightness.cpp NVS, config.example, install-mac.sh legacy handling, tests of the legacy names), inherited Linux/Windows files (`install.sh`, `install-windows.ps1`, `daemon/claude-usage-daemon.sh`, `daemon/*_windows.py`, `daemon/README-windows.md`, `daemon/tests/test_windows_*`), generator command lines in `font_*.c`, and `README.md` (T3). Outside T1's surface and still carrying the old name: `firmware/src/boards/sim/display.cpp` (window title "Clawdmeter sim"), `firmware/src/boards/sim/sim_main.cpp` (usage text), `docs/porting/adding-a-board.md` (title), `daemon/test_macos_connect.py` (docstring), `daemon/attention-hook.sh` (legacy dir, intentional), `firmware/src/clawd_still.h` / `splash_animations.h` headers (generated; mention `research/clawd-official/`).

### Gallery evidence (T2, worker B, macOS, 2026-10-12)
- Headless usage view: the sim boots on the splash, `Serial.available()` is hard-wired to 0 in `boards/sim/shim/Arduino.h` and the SDL dummy driver has no touch, so no env var or stdin command reaches `SCREEN_USAGE`. `ui_show_alert()` (`ui.cpp`) switches splash → usage on a payload with `"m"`, and `"x":true` on the next payload clears it; `firmware/sim/gallery.jsonl` uses that (Claude+alert → Claude+clear → Codex weekly-only → Kimi, all chained with `hold_ms:0`), then the 8 s carousel (`CAROUSEL_MS`) gives Claude at 4 s, Codex at 12 s, Kimi at 20 s. No sim source was changed.
- Scenes are timed from the holds (entry = intro + 6 s loop + outro; `SCENE_LOOP_MS`): Codex rain window ≈ 36.7–38.2 s (shot at 37.5 s), Kimi night ≈ 29.7–31.8 s (shot at 30.7 s); parade at 31 s = Codex `dots` after the first 20 s rotation. Verified by reading every PNG: three usage views (Claude with Fable bar, Codex 10×10 dot grid at 54 %, Kimi two bars), Clawd splash, both mascots with provider label, both scenes, parade.
- Hardware shots copied from the scratchpad after visual screening (percentages + provider names only, no device name/token): `hw-claude.png` (H5), `hw-codex.png` (H5), `hw-kimi-night.png` (H7).
- Not produced: `bluetooth-screen.png` — `ui.h` has only `SCREEN_SPLASH`/`SCREEN_USAGE`; pairing state is a status line in the usage view. Noted in `docs/media/README.md`.
- `node --test tools/test/`: 10 tests, 10 pass, 0 fail (8 existing + 2 new: PPM frame rendering; GIF exists/non-empty/`GIF89a`/byte-identical on a second run/scratch frames cleaned; skips with a message when ImageMagick is absent).
- `node tools/convert_grid_animations.js && git diff --stat firmware/src/custom_animations.h`: empty (default run byte-identical).
- GIF export run twice into two scratch dirs: sha256 of all 13 GIFs identical. Sizes 0.4–12.0 KB (max `kimi.scene.night.gif`), far under the 300 KB limit at ×6; `ls docs/media/animations | wc -l` → 13; `du -sh docs/media` → 204K.
- `SKIP_BUILD=1 bash tools/make_gallery.sh`: end to end in 38.5 s (9 captures run concurrently, then GIF export), "done: 12 screens, 13 GIFs"; full run (with `pio run -e sim`) also exercised at the start. Second run: GIFs and static screens byte-identical; `claude-usage.png` (status spinner glyph), both scenes and `parade.png` differ in frame phase only — documented in the README.
- Test-first exception: the GIF test was written with the implementation (no runnable RED for a new CLI flag); the PPM assertions are pure and the GIF assertions ran GREEN on first run.

## Next step
Branch, then launch A, B, D in parallel; C after A and B.
