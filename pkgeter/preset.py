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
# Template expansion helpers
# ---------------------------------------------------------------------------


def _substitute_version(repos_raw: list[dict], version: str) -> list[dict]:
    """Replace ``{version}`` placeholders in all string values of repo dicts."""
    result = []
    for repo in repos_raw:
        new_repo = {}
        for key, val in repo.items():
            if isinstance(val, str):
                new_repo[key] = val.replace("{version}", version)
            else:
                new_repo[key] = list(val) if isinstance(val, list) else val
        result.append(new_repo)
    return result


def _apply_mirror_variant(repos: list[RepoConfig], url_map: dict[str, str]) -> list[RepoConfig]:
    """Return a copy of *repos* with URLs replaced per *url_map* (keyed by repo name)."""
    result = []
    for repo in repos:
        if repo.name in url_map:
            result.append(RepoConfig(
                name=repo.name,
                type=repo.type,
                url=url_map[repo.name],
                release=repo.release,
                components=list(repo.components),
                arch=repo.arch,
            ))
        else:
            result.append(repo)
    return result


def _expand_system(system_name: str, data: dict) -> dict[str, dict]:
    """Expand a single system entry into flat ``name -> preset`` pairs.

    Handles both template mode (``versions`` is a list) and explicit mode
    (``versions`` is a dict with per-version repos).
    """
    versions = data["versions"]
    backend = data.get("backend", "")
    arch = data.get("arch", "")
    presets: dict[str, dict] = {}

    if isinstance(versions, list):
        repos_template = data.get("repos", [])
        mirrors_raw = data.get("mirrors", {})
        for ver in versions:
            ver_str = str(ver)
            key = f"{system_name}-{ver_str}"
            repos = _substitute_version(repos_template, ver_str)
            mirrors: dict[str, dict[str, str]] = {}
            for variant_name, url_map in mirrors_raw.items():
                mirrors[variant_name] = {
                    repo_name: url.replace("{version}", ver_str)
                    for repo_name, url in url_map.items()
                }
            presets[key] = {
                "backend": backend,
                "arch": arch,
                "repos": [RepoConfig.from_dict(r) for r in repos],
                "mirrors": mirrors,
            }
    else:
        system_mirrors = data.get("mirrors", {})
        for ver, ver_data in versions.items():
            ver_str = str(ver)
            key = f"{system_name}-{ver_str}"
            repos_raw = ver_data.get("repos", [])
            ver_mirrors = ver_data.get("mirrors", system_mirrors)
            presets[key] = {
                "backend": backend,
                "arch": arch,
                "repos": [RepoConfig.from_dict(r) for r in repos_raw],
                "mirrors": ver_mirrors,
            }

    return presets


# ---------------------------------------------------------------------------
# Lazy loading from YAML (built-in + user merged)
# ---------------------------------------------------------------------------

_PRESETS_CACHE: dict[str, Any] | None = None
_SYSTEMS_CACHE: dict[str, dict] | None = None


def _load_presets() -> dict[str, Any]:
    """Load presets from hierarchical YAML, expanding into a flat mapping.

    Built-in presets come from ``pkgeter/data/presets.yaml``.
    User presets live in ``~/.config/pkgeter/presets.yaml`` and override
    built-in entries of the same system name.
    """
    global _PRESETS_CACHE, _SYSTEMS_CACHE
    if _PRESETS_CACHE is not None:
        return _PRESETS_CACHE

    # 1. Read built-in presets
    builtin: dict[str, Any] = {}
    if _BUILTIN_PRESETS.exists():
        builtin = yaml.safe_load(_BUILTIN_PRESETS.read_text(encoding="utf-8")) or {}

    # 2. Read (or create) user presets
    if not _USER_PRESETS.exists():
        _USER_PRESETS.parent.mkdir(parents=True, exist_ok=True)
        if _BUILTIN_PRESETS.exists():
            import shutil
            shutil.copy2(_BUILTIN_PRESETS, _USER_PRESETS)
        user_raw: dict[str, Any] = {}
    else:
        user_raw = yaml.safe_load(_USER_PRESETS.read_text(encoding="utf-8")) or {}

    # 3. Merge: user overrides built-in (keyed by system name)
    merged = {**builtin, **user_raw}

    # 4. Expand hierarchical entries into flat preset mapping
    presets: dict[str, Any] = {}
    systems: dict[str, dict] = {}

    for system_name, data in merged.items():
        if not isinstance(data, dict) or "versions" not in data:
            continue
        expanded = _expand_system(system_name, data)
        presets.update(expanded)

        # Build system info for list_presets()
        versions_raw = data["versions"]
        if isinstance(versions_raw, list):
            versions_list = [str(v) for v in versions_raw]
            variants = sorted(data.get("mirrors", {}).keys())
        else:
            versions_list = [str(v) for v in versions_raw.keys()]
            all_variants: set[str] = set()
            for ver_data in versions_raw.values():
                if isinstance(ver_data, dict):
                    all_variants.update(ver_data.get("mirrors", {}).keys())
            if not all_variants:
                all_variants.update(data.get("mirrors", {}).keys())
            variants = sorted(all_variants)

        systems[system_name] = {
            "versions": versions_list,
            "variants": variants,
        }

    _PRESETS_CACHE = presets
    _SYSTEMS_CACHE = systems
    return presets


def reload_presets() -> None:
    """Clear cache so presets are re-read from disk on next access."""
    global _PRESETS_CACHE, _SYSTEMS_CACHE
    _PRESETS_CACHE = None
    _SYSTEMS_CACHE = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_presets() -> dict[str, dict]:
    """Return preset info grouped by system.

    Returns ``{"debian": {"versions": ["bookworm", ...], "variants": ["cn"]}, ...}``.
    """
    _load_presets()
    return dict(_SYSTEMS_CACHE) if _SYSTEMS_CACHE else {}


def list_systems() -> list[str]:
    """Return sorted list of system names."""
    _load_presets()
    return sorted(_SYSTEMS_CACHE.keys()) if _SYSTEMS_CACHE else []


def all_preset_names() -> list[str]:
    """Return sorted flat list of all valid preset names including @variant forms."""
    result = []
    for system, info in list_presets().items():
        for ver in info["versions"]:
            result.append(f"{system}-{ver}")
            for variant in info["variants"]:
                result.append(f"{system}-{ver}@{variant}")
    return sorted(result)


def complete_preset_name(text: str) -> list[str]:
    """Hierarchical TAB completion for preset names.

    - No hyphen yet -> complete system prefix (``deb`` -> ``debian-``)
    - Has hyphen -> complete full preset names including ``@variant``
    """
    presets_info = list_presets()

    if "-" not in text:
        return sorted(f"{s}-" for s in presets_info if s.startswith(text))

    return sorted(n for n in all_preset_names() if n.startswith(text))


def get_preset(name: str, mirror_variant: str = "default") -> dict | None:
    """Return the preset dict for *name*, or ``None`` if unknown.

    *name* may contain an ``@variant`` suffix (e.g. ``debian-bookworm@cn``).
    Priority: ``@variant`` in name > *mirror_variant* parameter.
    """
    if "@" in name:
        base_name, variant = name.rsplit("@", 1)
    else:
        base_name = name
        variant = mirror_variant

    raw = _load_presets().get(base_name)
    if raw is None:
        return None

    preset = {
        "backend": raw["backend"],
        "arch": raw.get("arch", ""),
        "repos": list(raw.get("repos", [])),
    }

    if variant != "default":
        mirrors = raw.get("mirrors", {})
        if variant in mirrors:
            preset["repos"] = _apply_mirror_variant(preset["repos"], mirrors[variant])
        else:
            print(
                f"Warning: mirror variant '{variant}' not found "
                f"in preset '{base_name}', using default",
                file=sys.stderr,
            )

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
        for name in all_preset_names():
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
