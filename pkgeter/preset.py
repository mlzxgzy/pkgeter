"""Distribution presets — quick configuration for known distros/releases."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from pkgeter.cli import resolve_subcmd
from pkgeter.config import Config
from pkgeter.models import RepoConfig

PRESET_ACTIONS = ["list", "apply"]

# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

PRESETS: dict[str, Any] = {
    "debian-bookworm": {
        "backend": "debian",
        "arch": "amd64",
        "repos": [
            RepoConfig(
                name="main",
                type="deb",
                url="https://deb.debian.org/debian",
                release="bookworm",
                components=["main"],
            ),
            RepoConfig(
                name="security",
                type="deb",
                url="https://security.debian.org/debian-security",
                release="bookworm-security",
                components=["main"],
            ),
            RepoConfig(
                name="updates",
                type="deb",
                url="https://deb.debian.org/debian",
                release="bookworm-updates",
                components=["main"],
            ),
        ],
    },
    "debian-bullseye": {
        "backend": "debian",
        "arch": "amd64",
        "repos": [
            RepoConfig(
                name="main",
                type="deb",
                url="https://deb.debian.org/debian",
                release="bullseye",
                components=["main"],
            ),
            RepoConfig(
                name="security",
                type="deb",
                url="https://security.debian.org/debian-security",
                release="bullseye-security",
                components=["main"],
            ),
            RepoConfig(
                name="updates",
                type="deb",
                url="https://deb.debian.org/debian",
                release="bullseye-updates",
                components=["main"],
            ),
        ],
    },
    "centos-9": {
        "backend": "rpm",
        "arch": "x86_64",
        "repos": [
            RepoConfig(
                name="baseos",
                type="rpm",
                url="https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os",
            ),
            RepoConfig(
                name="appstream",
                type="rpm",
                url="https://mirror.stream.centos.org/9-stream/AppStream/x86_64/os",
            ),
            RepoConfig(
                name="epel",
                type="rpm",
                url="https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64",
            ),
        ],
    },
}


def list_presets() -> list[str]:
    """Return sorted list of available preset names."""
    return sorted(PRESETS.keys())


def get_preset(name: str) -> dict | None:
    """Return the preset dict for *name*, or ``None`` if unknown."""
    return PRESETS.get(name)


# ---------------------------------------------------------------------------
# CLI entry point for preset management
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pkgeter preset")
    sub = parser.add_subparsers(dest="action")

    sub.add_parser("list", help="List available presets")

    apply_parser = sub.add_parser("apply", help="Apply a preset to the config")
    apply_parser.add_argument("name", help="Preset name (e.g. debian-bookworm)")

    return parser


def run_preset(argv: list[str] | None = None) -> None:
    """Handle ``preset list`` and ``preset apply <name>``.

    Called from the CLI or directly.
    """
    parser = _build_parser()
    if argv:
        expanded = resolve_subcmd(argv[0], PRESET_ACTIONS)
        if expanded:
            argv = [expanded] + argv[1:]
    args = parser.parse_args(argv)
    if not args.action:
        parser.print_help()
        return

    if args.action == "list":
        print("Available presets:")
        for name in list_presets():
            print(f"  {name}")
        return

    if args.action == "apply":
        preset = get_preset(args.name)
        if preset is None:
            print(f"Error: unknown preset {args.name!r}", file=sys.stderr)
            sys.exit(1)
            return  # unreachable in practice; placates mocked-sys.exit tests

        cfg = Config()
        cfg.set_backend(preset["backend"])
        cfg.set_repos([r.to_dict() for r in preset["repos"]])
        cfg.save()
        print(f"Applied preset {args.name!r} (backend: {preset['backend']}, "
              f"arch: {preset['arch']}, repos: {len(preset['repos'])})")
