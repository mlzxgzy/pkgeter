"""Configuration management - persists user preferences to config.yaml."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path.home() / ".config" / "pkgeter" / "config.yaml"

DEFAULT_CONFIG: dict[str, Any] = {
    "release": "bookworm",
    "arch": "amd64",
    "mirror": "https://deb.debian.org/debian",
    "virtual_packages": {},
    "output_dir": "./output",
}


def _is_linux_with_apt() -> bool:
    """Check if running on Linux with dpkg available."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        subprocess.run(
            ["which", "dpkg"],
            capture_output=True,
            check=True,
        )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _detect_release() -> str | None:
    """Detect Debian release codename from /etc/os-release."""
    os_release = Path("/etc/os-release")
    if not os_release.exists():
        return None
    try:
        with open(os_release, encoding="utf-8") as f:
            for line in f:
                if line.startswith("VERSION_CODENAME="):
                    return line.strip().split("=", 1)[1].strip('"')
    except OSError:
        return None
    return None


def _detect_arch() -> str | None:
    """Detect architecture via dpkg --print-architecture."""
    try:
        result = subprocess.run(
            ["dpkg", "--print-architecture"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return None


class Config:
    """Load/save persistent configuration."""

    def __init__(self, path: Path | None = None):
        self.path = path or CONFIG_PATH
        self.data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        merged = DEFAULT_CONFIG.copy()
        if self.path.exists():
            with open(self.path, encoding="utf-8") as f:
                merged.update(yaml.safe_load(f) or {})
        else:
            # No config file — auto-detect on apt-based Linux
            if _is_linux_with_apt():
                release = _detect_release()
                arch = _detect_arch()
                if release:
                    merged["release"] = release
                if arch:
                    merged["arch"] = arch
                self.data = merged
                self.save()
                return
        self.data = merged

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(self.data, f, default_flow_style=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
