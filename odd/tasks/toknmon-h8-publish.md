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
- [ ] T1 — Rebrand + cleanup (writer A).
- [ ] T2 — Gallery media + GIF export (worker B).
- [ ] T4 — CI workflow (worker D).
- [ ] T3 — README + docs + LICENSE/NOTICE/CHANGELOG (writer C, after T1+T2).
- [ ] T5 — Author rewrite, repo creation, push, daemon reinstall (parent, with user confirmation before push).

## Verification
- `daemon/.venv/bin/python -m pytest daemon/tests -q`; `node --test tools/test/`; shell validator test
- `pio run -d firmware -e sim`, `pio run -d firmware -e waveshare_amoled_216`; flash; device advertises "ToknMon …"
- `install-mac.sh --yes --providers claude,codex,kimi --device-name "<name>"` migrates config, replaces the legacy agent, daemon connects
- CI green on the published repo

## Verification evidence
(pending)

## Next step
Branch, then launch A, B, D in parallel; C after A and B.
