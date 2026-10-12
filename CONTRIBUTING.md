# Contributing to ToknMon

ToknMon is a personal project maintained in spare time. Issues and pull
requests are welcome; there is no support commitment and no release schedule.
This page tells you what helps and how the repository is organized.

## Before you open an issue

- Search existing issues first. Hardware reports (other boards, other hosts)
  are especially welcome because only the Waveshare ESP32-S3 Touch AMOLED 2.16
  on macOS is verified.
- Use the issue templates under `.github/ISSUE_TEMPLATE/`. For bugs include
  the board, the host OS version, `./flash-mac.sh` / `./install-mac.sh`
  output, and the relevant lines from `~/Library/Logs/toknmon.err.log` with
  tokens and your device name removed.
- For firmware UI problems a screenshot from `./screenshot.sh out.png [port]`
  or from the simulator (`docs/simulator.md`) is worth more than a description.

## Development setup

Requirements: macOS 13+ (the daemon is macOS-only), Python 3.10+, PlatformIO
CLI, Node 18+, ImageMagick for the art tools, SDL2 for the desktop simulator.
`docs/development.md` has the full list and the project layout.

```bash
git clone https://github.com/edgarbaldemarmx/toknmon.git
cd toknmon
python3 -m venv daemon/.venv && daemon/.venv/bin/pip install -r daemon/requirements-macos.txt
brew install platformio sdl2 imagemagick     # or pip install platformio
pio run -d firmware -e sim && (cd firmware && .pio/build/sim/program)
```

## Tests to run before a pull request

```bash
daemon/.venv/bin/python -m pytest daemon/tests -q          # host daemon
node --test tools/test/                                     # asset converters
bash tools/test/shell/test_device_name_validator.sh         # install/flash name validator
node tools/convert_grid_animations.js && git diff --exit-code firmware/src/custom_animations.h
pio run -d firmware -e sim                                  # simulator build
pio run -d firmware -e waveshare_amoled_216                 # target firmware
```

CI (`.github/workflows/ci.yml`) runs the same set on every push and pull
request. Firmware changes that touch panels, touch or rotation also need a
check on real hardware; say in the PR what you flashed and what you saw.

## Conventions

- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`,
  `ci:` with an optional scope (`feat(daemon): …`). One reviewable work unit
  per commit, with its tests and docs in the same commit.
- **No `#ifdef BOARD_*` in shared firmware code**: add a `BoardCaps` field or a
  per-board file instead (`docs/porting/capability-flags.md`).
- **Generated files are not hand-edited**: `firmware/src/splash_animations.h`
  and `firmware/src/custom_animations.h` come from the tools in `tools/`.
- **Documentation and code are in English**, neutral register.
- **Never commit** tokens, personal emails, real device names or absolute
  home paths (use `~` and `<Your name>` in docs).
- Feature-sized work is tracked in `docs/odd/<feature>.md` (objective, scope,
  checklist, verification evidence). Read the latest one before picking up a
  milestone, and update it when you change behavior.

## Adding art

The Codex and Kimi mascots are text grids under `assets/animations/`. New
animations only need a new `.txt` file and a converter run; the format, the
rules the converter enforces and how to wire an animation into a provider set
are in `docs/animations.md`. Original art only: do not add material you do not
have the right to redistribute (see `NOTICE.md`).

## Adding a provider or a board

- Providers live in `daemon/providers/` (`base.py` defines `ProviderResult`
  and the payload mapping). `docs/providers.md` describes the contract and the
  payload keys; add fixtures and tests under `daemon/tests/`.
- Board ports live in `firmware/src/boards/<name>/` plus a `[env:...]` block in
  `firmware/platformio.ini`; see `docs/porting/adding-a-board.md`. Check for an
  existing pull request for your board before opening a new one.

## License

By contributing you agree that your contribution is licensed under the MIT
License in `LICENSE`. Third-party assets bundled in the repository are not
covered by it; see `NOTICE.md`.
