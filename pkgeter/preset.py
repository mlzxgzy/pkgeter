"""Distribution presets — loaded from presets.yaml, persisted in config dir."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from pkgeter.cli import resolve_subcmd
from pkgeter.config import CONFIG_PATH, Config
from pkgeter.models import RepoConfig

PRESET_ACTIONS = ["list", "apply"]

# ---- Data file paths ----

_PACKAGE_DIR = Path(__file__).parent
_BUILTIN_PRESETS = _PACKAGE_DIR / "data" / "presets.yaml"
_USER_PRESETS = CONFIG_PATH.parent / "presets.yaml"

# ---------------------------------------------------------------------------
# Lazy loading from YAML
# ---------------------------------------------------------------------------

_PRESETS_CACHE: dict[str, Any] | None = None


def _ensure_user_presets() -> Path:
    """Copy built-in presets to config dir if user file doesn't exist."""
    if not _USER_PRESETS.exists():
        _USER_PRESETS.parent.mkdir(parents=True, exist_ok=True)
        if _BUILTIN_PRESETS.exists():
            import shutil
            shutil.copy2(_BUILTIN_PRESETS, _USER_PRESETS)
        else:
            _USER_PRESETS.write_text("# pkgeter presets — add your own presets here\n")
    return _USER_PRESETS


def _load_presets() -> dict[str, Any]:
    """Load presets from user config dir (lazily cached)."""
    global _PRESETS_CACHE
    if _PRESETS_CACHE is not None:
        return _PRESETS_CACHE

    user_path = _ensure_user_presets()
    raw = yaml.safe_load(user_path.read_text(encoding="utf-8")) or {}

    presets: dict[str, Any] = {}
    for name, data in raw.items():
        if not isinstance(data, dict):
            continue
        repos = [RepoConfig.from_dict(r) for r in data.get("repos", [])]
        presets[name] = {
            "backend": data.get("backend", ""),
            "arch": data.get("arch", ""),
            "repos": repos,
        }

    _PRESETS_CACHE = presets
    return presets


def reload_presets() -> None:
    """Clear cache so presets are re-read from disk on next access."""
    global _PRESETS_CACHE
    _PRESETS_CACHE = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_presets() -> list[str]:
    """Return sorted list of available preset names."""
    return sorted(_load_presets().keys())


def get_preset(name: str) -> dict | None:
    """Return the preset dict for *name*, or ``None`` if unknown."""
    return _load_presets().get(name)


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
    """Handle ``preset list`` and ``preset apply <name>``."""
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
        print("Available presets (edit ~/.config/pkgeter/presets.yaml to add more):")
        for name in list_presets():
            print(f"  {name}")
        return

    if args.action == "apply":
        preset = get_preset(args.name)
        if preset is None:
            print(f"Error: unknown preset {args.name!r}", file=sys.stderr)
            sys.exit(1)
            return

        cfg = Config()
        cfg.set_backend(preset["backend"])
        cfg.set_repos([r.to_dict() for r in preset["repos"]])
        cfg.save()
        print(f"Applied preset {args.name!r} (backend: {preset['backend']}, "
              f"arch: {preset['arch']}, repos: {len(preset['repos'])})")
