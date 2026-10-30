# ToknMon — fix: macOS daemon venv broken by `brew upgrade`, menu-bar restart that works

Objective: a `brew upgrade` of Python must not silently kill the macOS daemon, and the menu-bar app must be able to bring it back or say why it cannot. Branch `fix/mac-venv-brew-upgrade` from `main` `c6f4520`; delivery: one PR (forecast ≈ 300 authored lines, under the 400-line budget); runners `daemon/.venv/bin/python -m pytest daemon/tests -q`, `bash tools/test/shell/<test>.sh`, `node --test tools/test/`.

## Specs

- **S1** — Installer interpreter choice (accepted proposal, point 1; user L4: "Si, hay que hacer la corrección"). `install-mac.sh` picks a Python ≥ 3.10 that is **not a virtualenv**, checking every `python3.13` … `python3.10` on `PATH` (not only the first), so `daemon/.venv` links to the base install (Homebrew's stable `opt/` path) instead of a versioned `Cellar/python@3.x/<patch>` keg that `brew upgrade` deletes. When no virtualenv interpreter is on `PATH`, the pick is the same as before.
- **S2** — Self-heal on re-run (point 2). Re-running `install-mac.sh` rebuilds an existing `daemon/.venv` whose `pyvenv.cfg` `home` points into a Homebrew `Cellar/` keg, before it breaks; a venv whose Python no longer runs or is older than 3.10 is still rebuilt as before (same message).
- **S3** — Docs (point 3). A Troubleshooting row in `README.md` and `docs/troubleshooting.md`: the board stopped updating after `brew upgrade` → re-run `./install-mac.sh`; CHANGELOG `[Unreleased]` → `Fixed`.
- **S4** — Menu "Restart daemon" (point 4a; user L3: "y desde el menu se puede relanzar el daemon?"). Reloads the agent with `launchctl bootout` + `bootstrap` (falling back to `load -w`, like the installer), with timeouts and without freezing the menu, then checks that the daemon is running; otherwise an alert names the cause (the venv's Python is missing → re-run `./install-mac.sh`; launchctl refused; the daemon exited with code N → Open logs). `docs/gui.md` updated.
- **S5** — Daemon state line (point 4b). The menu shows `Daemon: running`, `Daemon: stopped · exit N`, `Daemon: stopped · Python missing` or `Daemon: not loaded`, read from `launchctl print gui/$UID/com.toknmon.daemon`, separate from the `Device:` line.
- Out of scope: a "Repair…" button that rebuilds the venv, a device-side "no data since" heartbeat, pinning Homebrew Python on the user's machine.

## Tasks

| ID | Specs | Route | Status | Commit |
| --- | --- | --- | --- | --- |
| T1 | S1, S2, S3 | inline | done (L6) | first commit on the branch |
| T2 | S4, S5 (+ CHANGELOG line) | inline | pending | — |
| T3 | verify S1–S5 (Risk item 5: installer and launchd service handling) | independent verifier | pending | — |

Route evidence: Writer trigger not met. T1 is about 100 changed lines (inline by rule) and T2 is the only larger unit, so there is no pair of parallel units; the parent writes inline.

## Log

- **L1** (2026-10-30, user, verbatim): "Revisa en mi equipo si algo esta mal con el motor de envío porque el device no muestra consumos"
- **L2** (user, verbatim): "Para efectos de lo que tenemos en github ¿afecta a quien lo descargue y lo instale en su device? ¿cómo podemos corregir esto en el repo?"
- **L3** (user, verbatim): "y desde el menu se puede relanzar el daemon?"
- **L4** (user, verbatim): "Si, hay que hacer la corrección" — accepts installer points 1–3 and menu points 4a–4b.
- **L5** Diagnosis (user's Mac): Homebrew upgraded `python@3.13` 3.13.16 → 3.13.18 on 2026-10-28 and removed 3.13.16. The install clone's venv had been created by `~/.platformio/penv/bin/python3.13` (first `python3.13` on `PATH`, picked by `install-mac.sh:517-521`), so it linked to `Cellar/python@3.13/3.13.16/...`. The running daemon kept sending until 2026-10-30 12:23, crashed at 12:24 (`PermissionError` creating an SSL context), and launchd could not respawn it (`last exit code = 78: EX_CONFIG`, stuck in `spawn scheduled`; `kickstart -k` hung). Repaired by rebuilding the venv from `/opt/homebrew/bin/python3.13` and `bootout` + `bootstrap`. Experiment: a venv made from the PlatformIO penv gets `home = …/Cellar/python@3.13/3.13.18/…`; one made from `/opt/homebrew/bin/python3.13` gets `home = /opt/homebrew/opt/python@3.13/bin`.
- **L6** T1 evidence. Baseline: `pytest daemon/tests -q` 392 passed, 2 skipped (the dev tree's own venv was broken the same way and was rebuilt from `/opt/homebrew/bin/python3.13`). RED: `bash tools/test/shell/test_install_python.sh` → `FAIL: no py_is_venv() in install-mac.sh`. GREEN under macOS `/bin/bash` 3.2: 6/6 pass; `test_install_apps.sh` and `test_device_name_validator.sh` still pass; `bash -n install-mac.sh` OK; CI step added. Differential check of the pick against `c6f4520`: on the user's PATH old = `~/.platformio/penv/bin/python3.13`, new = `/opt/homebrew/bin/python3.13`; on `/opt/homebrew/bin:/usr/bin:/bin` both = `/opt/homebrew/bin/python3.13`. Real venvs: a penv-made venv (`home = …/Cellar/python@3.13/3.13.18/…`) is flagged by `venv_pinned_to_keg`; a venv made from the new pick gets the `opt/` home, is kept, and imports `bleak`/`httpx` after `pip install -r daemon/requirements-macos.txt`. The full `[2/7]` block was not executed as a unit (its `rm -rf "$VENV_DIR"` is blocked by the session's safety check); its two branches are covered by the pieces above.
