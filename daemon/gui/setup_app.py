"""py2app setup for ToknMon.app (the menu-bar app).

Run through ``tools/build_mac_app.sh``, which picks the venv interpreter and
an output directory outside the repository:

    daemon/.venv/bin/python daemon/gui/setup_app.py py2app \
        --dist-dir "$OUT/dist" --bdist-base "$OUT/build"

The bundle is a background app (``LSUIElement``): no Dock icon, no main
window. It never opens Bluetooth, so no usage-description keys are needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

from setuptools import setup

HERE = Path(__file__).resolve().parent          # daemon/gui
DAEMON = HERE.parent                            # daemon/
sys.path.insert(0, str(DAEMON))                 # so modulegraph finds `gui`

_version_file = DAEMON / "VERSION"
VERSION = _version_file.read_text().strip() if _version_file.exists() else "0.0.0"

PLIST = {
    "LSUIElement": True,
    "CFBundleIdentifier": "com.toknmon.menubar",
    "CFBundleName": "ToknMon",
    "CFBundleDisplayName": "ToknMon",
    "CFBundleShortVersionString": VERSION,
    "CFBundleVersion": VERSION,
    "NSHumanReadableCopyright": "ToknMon contributors. Derived from Clawdmeter.",
    "LSMinimumSystemVersion": "12.0",
}

OPTIONS = {
    "plist": PLIST,
    "packages": ["gui", "rumps"],
    # Nothing in the app needs lzma, and py2app's relinked copy of Homebrew's
    # liblzma.5.dylib carries trailing bytes past LC_CODE_SIGNATURE, which no
    # codesign invocation accepts. Leave it out so the bundle signs cleanly.
    "excludes": ["_lzma", "lzma"],
    "argv_emulation": False,
    "strip": True,
    "optimize": 0,
}
if _version_file.exists():
    OPTIONS["resources"] = [str(_version_file)]

setup(
    name="ToknMon",
    version=VERSION,
    app=[str(HERE / "ToknMon.py")],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
