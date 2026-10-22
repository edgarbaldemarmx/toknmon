"""Generate the menu-bar template icon (``assets/toknmon-menubar.png``).

A template image is monochrome: macOS reads only the alpha channel and tints
it for light/dark menu bars. The glyph is a small original pixel critter
(rounded body, two eye holes, four legs) standing on a one-pixel meter bar.
``toknmon-menubar.png`` is the 18x18 glyph; ``toknmon-menubar-2x.png`` is the
same glyph at 36x36 for retina menu bars (rumps scales the icon to 20 pt).
Run from ``daemon/``: ``.venv/bin/python -m gui.make_icon``.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent / "assets"
ICON = ASSETS / "toknmon-menubar.png"
ICON_2X = ASSETS / "toknmon-menubar-2x.png"

# 18x18 cells: '#' = ink, '.' = transparent.
GLYPH = """
..................
..................
.....########.....
....##########....
...############...
...###..####..##..
...###..####..##..
...############...
...############...
....##########....
.....##.##.##.....
.....##.##.##.....
..................
..##############..
..##############..
..................
..................
..................
""".strip("\n").splitlines()


def render(scale: int = 1) -> Image.Image:
    size = len(GLYPH) * scale
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(GLYPH):
        for x, cell in enumerate(row):
            if cell == "#":
                for dy in range(scale):
                    for dx in range(scale):
                        px[x * scale + dx, y * scale + dy] = (0, 0, 0, 255)
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    render(1).save(ICON)
    render(2).save(ICON_2X)
    print(f"wrote {ICON} (18x18) and {ICON_2X} (36x36)")


if __name__ == "__main__":
    main()
