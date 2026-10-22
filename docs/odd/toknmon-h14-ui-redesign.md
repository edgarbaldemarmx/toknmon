# ToknMon — H14 UI redesign: full-width meters, Codex palette, Focus layout, Codex pet avatar

Objective: the Fable, Codex and Grok pages and the Focus screens use the whole 480×480 panel with larger elements; Codex gets a new palette; the Codex corner avatar becomes one of the new pets. Prototypes first (Codex agent on `gpt-6-astra`), implementation after the user approves them. Branch `feat/suite-h11-h13` (PR #1 stays open until this lands), runners as in H11–H13.

## Specs

- **S1** — User (2026-10-22, verbatim): "Hay que cambiar el avatar de codex por alguno de los nuevos, el robotsito azul me gusta."
  - **S1.1** The Codex corner mascot (`codex.icon`, H10) is replaced by the chosen pet's idle pose scaled to the corner envelope (≤ 28×21 cells, Clawd-sized ~24×18), with its blink/idle motion as the corner act; the pet's full-size clip stays in the splash set. Candidate pets with a blue robot: `bsod` (light-blue robot, white body, antenna) and `codex` (dark-blue hooded robot); the user picks (L2).
  - **S1.2** The Codex splash set starts with that pet (first entry) so mascot mode opens on it.
- **S2** — User (verbatim): "Necesitamos diseñar las pantallas para que se aproveche mejor el espacio y no se vean tan pequeños los elementos (la de fable, codex, grok) que todo sea full width. La de codex, no me gustan los colores."
  - **S2.1** Dot-grid pages (Codex, Grok) and the Fable Clawd grid span the full content width (20 px margins for the rounded corners): larger dots/glyphs and pitch, header and the "Resets" ledger laid out so nothing shrinks the grid; the big percentage and the reset time stay readable at arm's length.
  - **S2.2** New Codex palette (not the current teal/green): proposed by the prototypes, chosen by the user; the accent is applied consistently (dots, ledger, pill, status line, corner mascot tint if any) and must contrast with Claude clay, Kimi blue and Grok silver.
  - **S2.3** Layouts are produced for the 480×480 2.16; other boards keep working (compute_layout breakpoints) but are not redesigned.
- **S3** — User (verbatim): "El diseño de la pantalla de focus es el mismo caso, como aprovechamos mejor el espacio de la pantalla".
  - **S3.1** Focus setup/running/done use the full panel: larger ring and countdown, the hint, the "N blocks today" line and the Start/Start next button sized to the space, same interactions as H12 (tap halves ±5, swipe, PWR).
- **S4** — Process (user, verbatim): "Si requieres apoyarte con un agente de codex para que haga el diseño visual, prototipos adelante (utiliza astra 6) y ya que aprobemos prototipos, los construyes."
  - **S4.1** A Codex agent (`gpt-6-astra`, via Herdr) renders 480×480 PNG prototypes with real data states: Codex (with and without credits), Grok, Fable, Focus setup/running/done, plus two or three Codex palette options. They are written outside the repo (`~/Desktop/ToknMon-prototypes/`) for the user to open; nothing is implemented until the user approves.
  - **S4.2** After approval the firmware is implemented inline/delegated as usual, verified in the sim and on hardware, and the README/docs media refreshed.

## Tasks

| ID | Specs | Route | Status | Commit |
| --- | --- | --- | --- | --- |
| T1 | S4.1 prototypes | Codex agent `designer` (Herdr) | v1 delivered; v2 (OpenAI palette, padding) requested | — |
| T2 | S1 pet avatar (`bsod`) | delegated writer F | done | `a3b01f3` |
| T3 | S2 full-width meters + palette (after prototype approval) | writer (ui.cpp, theme.h, sim captures) | open | |
| T4 | S3 Focus layout (approved on v1) | delegated writer G (ui.cpp Focus functions) | in progress | |
| T5 | hardware flash, screenshots, docs/media, CHANGELOG, PR update | inline (parent) | open | |

## Log

- **L1** (2026-10-22, user, verbatim): "Antes de hacer el merge y publicar, tengo algunos requerimientos de cambio. 1. Hay que cambiar el avatar de codex por alguno de los nuevos, el robotsito azul me gusta. 2. Necesitamos diseñar las pantallas para que se aproveche mejor el espacio y no se vean tan pequeños los elementos (la de fable, codex, grok) que todo sea full width. La de codex, no me gustan los colores. 3. El diseño de la pantalla de focus es el mismo caso, como aprovechamos mejor el espacio de la pantalla. Si requieres apoyarte con un agente de codex para que haga el diseño visual, prototipos adelante (utiliza astra 6) y ya que aprobemos prototipos, los construyes."
- **L2** "astra 6" = the Codex model `gpt-6-astra` (the user's default in `~/.codex/config.toml`). Two blue robots exist among the pets (`bsod`, `codex`); the parent asked the user which one.
- **L3** (2026-10-22, user): "Bsod (azul claro)" — the Codex avatar is the `bsod` pet. Codex designer agent `designer` started in Herdr pane wJ:p4 on `gpt-6-astra` (folder-trust dialog accepted by the parent, as the user asked for a Codex agent on this repo); brief in `/tmp/h14/brief.md`, outputs expected in `~/Desktop/ToknMon-prototypes/v1/`. Writer F started on T2 (icon mode of the pet converter, Bsod first in the Codex set).
- **L4** T1 v1 (designer, `gpt-6-astra`): `~/Desktop/ToknMon-prototypes/v1/{codex-A,codex-B,codex-C,codex-nocredits,grok,fable,focus-setup,focus-running,focus-done}.png`, `notes.md` (pixel geometry, fonts, hex palettes), `render.py`. Full-width 10×10 grids (dots Ø24 px, pitch 46×25, region 20,178–460,427), ledger as a text block top-right, Focus ring 340 px / countdown 76 px with the action inside the ring.
- **L5** (2026-10-22, user, verbatim) palette: "Toma los colores que use OpenAI para que sea relacionado, itera para paletas así"; meters: "Itera con cambios, si hay que hacer full width pero mantener un poco es pacios tipo padding entre cada elemento para que no se vea saturado, debe verse limpio pero aprovechar el espacio de pantalla."; Focus: "Aprobado, constrúyelo". → v2 requested from the designer (OpenAI-related palettes, padding between elements); writer G builds the Focus layout from v1 `notes.md`.
- **L6** T2 evidence (writer F): `--icon bsod` mode in the pet converter; Bsod's idle is 116×180 px so the 21-row envelope caps the icon at 14×21 cells (not the 22–24 wide of the brief; a wider icon would need 34 rows); 6 idle frames at 330 ms as idle + only act; `PROVIDER_SETS` Codex starts with `codex.pet-bsod`; tests 8 passed; sim captures show the Bsod corner icon on the Codex view and mascot mode opening on Bsod; Flash 75.6 %. Risk: item 3 (set order), other providers unchanged.
