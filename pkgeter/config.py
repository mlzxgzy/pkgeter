"""Configuration management - persists user preferences to config.yaml."""

import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path.home() / ".config" / "pkgeter" / "config.yaml"

_DEFAULT_MIRROR = "https://deb.debian.org/debian"

DEFAULT_CONFIG: dict[str, Any] = {
    "release": "bookworm",
    "arch": "amd64",
    "mirror": _DEFAULT_MIRROR,
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


def parse_mirror_entry(entry: str) -> tuple[str, str | None]:
    """Parse a mirror entry, extracting an optional ``@release`` override.

    Examples::

        >>> parse_mirror_entry("https://deb.debian.org/debian")
        ("https://deb.debian.org/debian", None)

        >>> parse_mirror_entry("https://security.debian.org/debian-security@bookworm-security")
        ("https://security.debian.org/debian-security", "bookworm-security")
    """
    # rsplit on "@".  A valid release override has no "/" and is non-empty.
    parts = entry.rsplit("@", 1)
    if len(parts) == 2 and parts[1] and "/" not in parts[1]:
        return parts[0], parts[1]
    return entry, None


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

        # ----- reconcile mirror <-> mirrors -----
        self._sync_mirror_fields(merged)
        self.data = merged

    @staticmethod
    def _sync_mirror_fields(cfg: dict[str, Any]) -> None:
        """Ensure ``mirror`` and ``mirrors`` are consistent after loading."""
        mirror: str | None = cfg.get("mirror")
        mirrors: list[str] | None = cfg.get("mirrors")

        if mirrors:
            cfg["mirror"] = mirrors[0]
        elif mirror:
            cfg["mirrors"] = [mirror]
        else:
            cfg["mirror"] = _DEFAULT_MIRROR
            cfg["mirrors"] = [_DEFAULT_MIRROR]

    def save(self) -> None:
        # Keep mirror and mirrors in sync
        mirrors = self.data.get("mirrors")
        if mirrors:
            self.data["mirror"] = mirrors[0]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            yaml.dump(self.data, f, default_flow_style=False)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    def get_mirrors(self) -> list[str]:
        """Return the list of configured mirrors."""
        mirrors = self.data.get("mirrors")
        if isinstance(mirrors, list) and mirrors:
            return mirrors
        mirror = self.data.get("mirror")
        if mirror:
            return [mirror]
        return ["https://deb.debian.org/debian"]

    def set_mirrors(self, mirrors: list[str]) -> None:
        """Set the mirrors list (keeps mirror in sync)."""
        if not mirrors:
            return
        self.data["mirrors"] = mirrors
        self.data["mirror"] = mirrors[0]

    def get_repos(self) -> list[dict]:
        """Return the list of configured repositories."""
        return list(self.data.get("repos", []))

    def set_repos(self, repos: list[dict]) -> None:
        """Set the list of configured repositories."""
        self.data["repos"] = list(repos)

    def get_backend(self) -> str:
        """Return the configured package-manager backend (default: 'debian')."""
        return str(self.data.get("backend", "debian"))

    def set_backend(self, backend: str) -> None:
        """Set the package-manager backend."""
        self.data["backend"] = backend
