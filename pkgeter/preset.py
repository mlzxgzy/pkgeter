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
# Lazy loading from YAML (built-in + user merged)
# ---------------------------------------------------------------------------

_PRESETS_CACHE: dict[str, Any] | None = None


def _load_presets() -> dict[str, Any]:
    """Load presets, merging built-in defaults with user overrides.

    Built-in presets come from ``pkgeter/data/presets.yaml``.
    User presets live in ``~/.config/pkgeter/presets.yaml`` and override
    built-in entries of the same name.  User-only entries are preserved.
    """
    global _PRESETS_CACHE
    if _PRESETS_CACHE is not None:
        return _PRESETS_CACHE

    # 1. Read built-in presets
    builtin: dict[str, Any] = {}
    if _BUILTIN_PRESETS.exists():
        raw = yaml.safe_load(_BUILTIN_PRESETS.read_text(encoding="utf-8")) or {}
        for name, data in raw.items():
            if isinstance(data, dict):
                builtin[name] = data

    # 2. Read (or create) user presets
    if not _USER_PRESETS.exists():
        _USER_PRESETS.parent.mkdir(parents=True, exist_ok=True)
        if _BUILTIN_PRESETS.exists():
            import shutil
            shutil.copy2(_BUILTIN_PRESETS, _USER_PRESETS)
        user_raw = {}
    else:
        user_raw = yaml.safe_load(_USER_PRESETS.read_text(encoding="utf-8")) or {}

    # 3. Merge: user overrides built-in
    merged = {**builtin, **user_raw}

    # 4. Parse into internal format (RepoConfig objects)
    presets: dict[str, Any] = {}
    for name, data in merged.items():
        if not isinstance(data, dict):
            continue
        repos = [RepoConfig.from_dict(r) for r in data.get("repos", [])]
        presets[name] = {
            "backend": data.get("backend", ""),
            "arch": data.get("arch", ""),
            "repos": repos,
            "mirrors": data.get("mirrors"),
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


def get_preset(name: str, mirror_variant: str = "default") -> dict | None:
    """Return the preset dict for *name*, or ``None`` if unknown.

    If the preset defines a ``mirrors`` map and *mirror_variant* is
    present inside it the variant's repos are used.  When the variant
    is unknown a warning is printed and the ``default`` variant is used
    as fallback.
    """
    raw = _load_presets().get(name)
    if raw is None:
        return None

    preset = {
        "backend": raw["backend"],
        "arch": raw.get("arch", ""),
        "repos": raw.get("repos", []),
    }

    mirrors: dict | None = raw.get("mirrors")
    if mirrors:
        if mirror_variant in mirrors:
            variant = mirrors[mirror_variant]
            preset["repos"] = [RepoConfig.from_dict(r) for r in variant.get("repos", [])]
        elif mirror_variant != "default":
            print(
                f"Warning: mirror variant '{mirror_variant}' not found "
                f"in preset '{name}', falling back to 'default'",
                file=sys.stderr,
            )
            # default variant inside mirrors takes precedence over top-level repos
            if "default" in mirrors:
                preset["repos"] = [RepoConfig.from_dict(r) for r in mirrors["default"].get("repos", [])]
        else:
            # mirror_variant == "default" but mirrors dict exists —
            # use default variant from mirrors if present, else top-level repos
            if "default" in mirrors:
                preset["repos"] = [RepoConfig.from_dict(r) for r in mirrors["default"].get("repos", [])]

    return preset


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
        cfg.set_mirror_variant("default")
        cfg.set_preset_name(args.name)
        cfg.save()
        print(f"Applied preset {args.name!r} (backend: {preset['backend']}, "
              f"arch: {preset['arch']}, repos: {len(preset['repos'])})")
