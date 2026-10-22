"""Tests for daemon/gui/config_store.py: in-place edits of the `key = value`
config file shared with the daemon and the installer."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui.config_store import ConfigStore  # noqa: E402

SAMPLE = """# ToknMon config
device_name = Desk 2   # the board
providers = auto

chime = on
apps = meter,focus
"""


def test_read_returns_last_value_without_comments(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(SAMPLE + "chime = off\n")
    store = ConfigStore(cfg)
    assert store.get("device_name") == "Desk 2"
    assert store.get("chime") == "off"
    assert store.get("missing") is None
    assert store.get("missing", "dflt") == "dflt"


def test_set_replaces_in_place_and_keeps_comments(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(SAMPLE)
    ConfigStore(cfg).set("device_name", "Lab")
    text = cfg.read_text()
    assert text.startswith("# ToknMon config\n")
    assert "device_name = Lab\n" in text
    assert "Desk 2" not in text
    assert text.count("device_name") == 1
    assert text.index("device_name") < text.index("providers")


def test_set_appends_when_missing(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(SAMPLE)
    ConfigStore(cfg).set("clock", "24")
    assert cfg.read_text().endswith("apps = meter,focus\nclock = 24\n")


def test_set_creates_file_and_parent(tmp_path):
    cfg = tmp_path / "nested" / "config"
    ConfigStore(cfg).set("apps", "meter")
    assert cfg.read_text() == "apps = meter\n"


def test_set_many_is_one_write(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(SAMPLE)
    ConfigStore(cfg).set_many({"chime": "off", "beep": "on"})
    text = cfg.read_text()
    assert "chime = off\n" in text and "beep = on\n" in text
    assert text.count("chime") == 1


def test_set_rejects_newlines_and_hash(tmp_path):
    cfg = tmp_path / "config"
    store = ConfigStore(cfg)
    with pytest.raises(ValueError):
        store.set("device_name", "a\nb")
    with pytest.raises(ValueError):
        store.set("device_name", "Desk #1")
    with pytest.raises(ValueError):
        store.set("bad key", "x")


def test_duplicate_keys_collapse_to_last_value_position(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("chime = on\nproviders = auto\nchime = off\n")
    ConfigStore(cfg).set("chime", "on")
    assert cfg.read_text() == "providers = auto\nchime = on\n"


def test_as_dict(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(SAMPLE)
    assert ConfigStore(cfg).as_dict() == {
        "device_name": "Desk 2",
        "providers": "auto",
        "chime": "on",
        "apps": "meter,focus",
    }
