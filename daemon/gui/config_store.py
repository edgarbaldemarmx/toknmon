"""In-place editor for the `key = value` config shared with the daemon.

The daemon (`claude_usage_daemon.py`) and the installer (`install-mac.sh`)
read the file as: one `key = value` per line, `#` starts a comment, the last
occurrence of a key wins, surrounding whitespace is trimmed. This store keeps
comments and unrelated lines untouched, rewrites the last occurrence of a key
in place, appends missing keys, and writes atomically (temp file + rename).
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_line(line: str) -> tuple[str, str] | None:
    """Return (key, value) for a `key = value` line, else None."""
    body = line.split("#", 1)[0].strip()
    if "=" not in body:
        return None
    key, value = body.split("=", 1)
    key = key.strip()
    if not _KEY_RE.match(key):
        return None
    return key, value.strip()


class ConfigStore:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)

    # -- reading -----------------------------------------------------------
    def _lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()

    def as_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for line in self._lines():
            parsed = _parse_line(line)
            if parsed:
                out[parsed[0]] = parsed[1]
        return out

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.as_dict().get(key, default)

    # -- writing -----------------------------------------------------------
    @staticmethod
    def _validate(key: str, value: str) -> None:
        if not _KEY_RE.match(key):
            raise ValueError(f"invalid config key: {key!r}")
        if "\n" in value or "\r" in value:
            raise ValueError("config values cannot span lines")
        if "#" in value:
            raise ValueError("config values cannot contain '#' (comment marker)")

    def set(self, key: str, value: str) -> None:
        self.set_many({key: value})

    def set_many(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            self._validate(key, str(value))
        lines = self._lines()
        for key, value in values.items():
            value = str(value).strip()
            positions = [i for i, line in enumerate(lines)
                         if (p := _parse_line(line)) and p[0] == key]
            if positions:
                last = positions[-1]
                lines[last] = f"{key} = {value}"
                # Earlier duplicates would be shadowed anyway; drop them so the
                # file has one line per key.
                for i in reversed(positions[:-1]):
                    del lines[i]
            else:
                lines.append(f"{key} = {value}")
        self._write("\n".join(lines) + "\n")

    def _write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".config.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
