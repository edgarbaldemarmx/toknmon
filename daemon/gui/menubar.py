"""ToknMon menu-bar app: a thin ``rumps`` shell over ``gui.model``.

It never opens Bluetooth. It shows the daemon's ``status.json`` and edits
``~/.config/toknmon/config`` through ``ConfigStore``; the daemon re-reads the
config on its next poll, so only a provider change suggests a restart.
Run from ``daemon/``: ``.venv/bin/python -m gui.menubar``.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import rumps

from gui import model
from gui.config_store import ConfigStore

CONFIG_DIR = Path.home() / ".config" / "toknmon"
CONFIG_FILE = CONFIG_DIR / "config"
STATUS_FILE = CONFIG_DIR / "status.json"
LOG_FILE = Path.home() / "Library" / "Logs" / "toknmon.err.log"
DAEMON_LABEL = "com.toknmon.daemon"
HERE = Path(__file__).resolve().parent
# The 36x36 variant renders crisply on retina menu bars (rumps scales the
# template icon to 20 pt); the 18x18 glyph is the fallback.
ICON = next((p for p in (HERE / "assets" / "toknmon-menubar-2x.png",
                         HERE / "assets" / "toknmon-menubar.png") if p.exists()),
            HERE / "assets" / "toknmon-menubar.png")
REFRESH_SECONDS = 10


def _version_file() -> Path:
    """``daemon/VERSION`` from the checkout, or the copy py2app put in the
    bundle's Resources (``RESOURCEPATH``)."""
    bundled = os.environ.get("RESOURCEPATH")
    if bundled and (Path(bundled) / "VERSION").exists():
        return Path(bundled) / "VERSION"
    return HERE.parent / "VERSION"


def read_status() -> dict | None:
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _run(*cmd: str) -> None:
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        rumps.alert("ToknMon", f"Could not run {' '.join(cmd)}: {e}")


class ToknMonApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(model.APP_NAME, icon=str(ICON), template=True, quit_button="Quit")
        self.store = ConfigStore(CONFIG_FILE)
        self.status_items: list[rumps.MenuItem] = []
        # rumps keys the menu by the title an item had when it was added, and
        # changing `.title` later does not re-key it, so keep the original key
        # for insert_before() while the visible text follows the status.
        self.device_item = rumps.MenuItem("Device")
        self.device_key = self.device_item.title
        self._build_menu()
        self.refresh(None)
        rumps.Timer(self.refresh, REFRESH_SECONDS).start()

    # -- menu ---------------------------------------------------------------
    def _build_menu(self) -> None:
        self.focus_item = rumps.MenuItem("Focus", callback=self.toggle_focus)
        meter_item = rumps.MenuItem("Meter")          # no callback: disabled
        meter_item.state = 1
        apps_menu = rumps.MenuItem("Apps")
        apps_menu.update([meter_item, self.focus_item])

        self.auto_item = rumps.MenuItem("Auto", callback=self.select_auto)
        self.provider_items = {
            pid: rumps.MenuItem(model.provider_name(pid), callback=self.toggle_provider)
            for pid in model.PROVIDERS}
        providers_menu = rumps.MenuItem("Providers")
        providers_menu.update([self.auto_item, None, *self.provider_items.values()])

        self.sound_items = {label: rumps.MenuItem(label, callback=self.toggle_sound)
                            for label in model.SOUND_KEYS}
        sound_menu = rumps.MenuItem("Sound")
        sound_menu.update(list(self.sound_items.values()))

        self.clock_items = {label: rumps.MenuItem(label, callback=self.select_clock)
                            for label in model.CLOCK_LABELS}
        clock_menu = rumps.MenuItem("Clock")
        clock_menu.update(list(self.clock_items.values()))

        self.menu = [
            self.device_item,
            None,
            rumps.MenuItem("Device name…", callback=self.rename_device),
            apps_menu,
            providers_menu,
            sound_menu,
            clock_menu,
            None,
            rumps.MenuItem("Restart daemon", callback=self.restart_daemon),
            rumps.MenuItem("Open config file", callback=self.open_config),
            rumps.MenuItem("Open logs", callback=self.open_logs),
            rumps.MenuItem("About ToknMon", callback=self.about),
        ]

    # -- refresh ------------------------------------------------------------
    def refresh(self, _sender) -> None:
        status = read_status()
        config = self.store.as_dict()
        lines = model.provider_lines(status)
        if [item.title for item in self.status_items] != lines:
            for item in self.status_items:
                del self.menu[item.title]
            self.status_items = [rumps.MenuItem(line) for line in lines]
            for item in self.status_items:
                self.menu.insert_before(self.device_key, item)
        self.device_item.title = model.device_line(status, config_name=config.get("device_name"))
        self.focus_item.state = int(model.focus_enabled(config.get("apps")))
        for pid_or_auto, checked in model.provider_states(config.get("providers")).items():
            item = self.auto_item if pid_or_auto == "auto" else self.provider_items[pid_or_auto]
            item.state = int(checked)
        for label, checked in model.sound_states(config).items():
            self.sound_items[label].state = int(checked)
        for label, checked in model.clock_states(config.get("clock")).items():
            self.clock_items[label].state = int(checked)

    # -- actions ------------------------------------------------------------
    def _set(self, key: str, value: str) -> None:
        try:
            self.store.set(key, value)
        except (OSError, ValueError) as e:
            rumps.alert("ToknMon", f"Could not write {CONFIG_FILE}: {e}")
        self.refresh(None)

    def rename_device(self, _sender) -> None:
        current = self.store.get("device_name") or model.DEFAULT_DEVICE_NAME
        window = rumps.Window(
            message=f"1-{model.DEVICE_NAME_MAX_LEN} printable ASCII characters, no '#'. "
                    "The daemon pushes the new name to the board on its next poll.",
            title="Device name", default_text=current, ok="Save", cancel="Cancel",
            dimensions=(320, 24))
        response = window.run()
        if not response.clicked:
            return
        name = response.text.strip()
        if not model.is_valid_device_name(name):
            rumps.alert("Invalid device name",
                        f"Use 1-{model.DEVICE_NAME_MAX_LEN} printable ASCII characters "
                        "without '#'.")
            return
        self._set("device_name", name)

    def toggle_focus(self, sender) -> None:
        self._set("apps", model.apps_value(focus=not sender.state))

    def select_auto(self, _sender) -> None:
        self._set("providers", model.select_auto())

    def toggle_provider(self, sender) -> None:
        pid = next(p for p, item in self.provider_items.items() if item is sender)
        self._set("providers", model.toggle_provider(self.store.get("providers"), pid))

    def toggle_sound(self, sender) -> None:
        self._set(model.SOUND_KEYS[sender.title], model.onoff(not sender.state))

    def select_clock(self, sender) -> None:
        self._set("clock", model.clock_value(sender.title))

    def restart_daemon(self, _sender) -> None:
        _run("launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{DAEMON_LABEL}")

    def open_config(self, _sender) -> None:
        if not CONFIG_FILE.exists():
            self.store.set_many({})   # creates an empty file so the editor opens
        _run("open", "-t", str(CONFIG_FILE))

    def open_logs(self, _sender) -> None:
        _run("open", str(LOG_FILE))

    def about(self, _sender) -> None:
        rumps.alert("About ToknMon", model.about_text(model.read_version(_version_file())))


def main() -> None:
    if sys.platform != "darwin":
        sys.exit("ToknMon menu-bar app runs on macOS only")
    ToknMonApp().run()


if __name__ == "__main__":
    main()
