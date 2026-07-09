"""Distribution presets — loaded from flat-format presets.yaml."""

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
_CUSTOM_PRESETS = CONFIG_PATH.parent / "custom-presets.yaml"


# ---------------------------------------------------------------------------
# Mirror variant replacement
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Lazy loading from flat YAML (built-in + user merged)
# ---------------------------------------------------------------------------

_PRESETS_CACHE: dict[str, Any] | None = None
_SYSTEMS_CACHE: dict[str, dict] | None = None


def _merge_preset_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge one preset override into a built-in preset.

    Scalar fields are replaced. Repos and mirrors are merged by ``name`` so user
    presets can add or override individual entries without copying the whole
    built-in preset definition.
    """
    merged = dict(base)

    for key in ("system", "backend", "arch"):
        if key in override:
            merged[key] = override[key]

    if "repos" in override:
        base_repos = {
            item.get("name", ""): item
            for item in base.get("repos", [])
            if isinstance(item, dict) and item.get("name")
        }
        for item in override.get("repos", []):
            if isinstance(item, dict) and item.get("name"):
                base_repos[item["name"]] = item
        merged["repos"] = list(base_repos.values())

    if "mirrors" in override:
        base_mirrors = {
            item.get("name", ""): item
            for item in base.get("mirrors", [])
            if isinstance(item, dict) and item.get("name")
        }
        for item in override.get("mirrors", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = item["name"]
            existing = base_mirrors.get(name, {}) if isinstance(base_mirrors.get(name), dict) else {}
            merged_mirror = dict(existing)
            merged_mirror.update({k: v for k, v in item.items() if k != "urls"})
            urls = dict(existing.get("urls", {})) if isinstance(existing.get("urls"), dict) else {}
            urls.update(item.get("urls", {}))
            merged_mirror["urls"] = urls
            base_mirrors[name] = merged_mirror
        merged["mirrors"] = list(base_mirrors.values())

    return merged


def _load_presets() -> dict[str, Any]:
    """Load presets from flat-format YAML files into a flat :attr:`name → data` mapping.

    Built-in presets live in ``pkgeter/data/presets.yaml``.
    Custom presets live in ``~/.config/pkgeter/custom-presets.yaml`` and
    extend or override built-in entries of the same preset key.
    """
    global _PRESETS_CACHE, _SYSTEMS_CACHE
    if _PRESETS_CACHE is not None:
        return _PRESETS_CACHE

    # 1. Read built-in presets
    builtin: dict[str, Any] = {}
    if _BUILTIN_PRESETS.exists():
        builtin_raw = yaml.safe_load(_BUILTIN_PRESETS.read_text(encoding="utf-8")) or {}
        builtin = {k: v for k, v in builtin_raw.items()
                   if isinstance(v, dict)}

    # 2. Read optional custom presets
    if not _CUSTOM_PRESETS.exists():
        user_raw = {}
    else:
        user_file = _CUSTOM_PRESETS.read_text(encoding="utf-8")
        user_candidate = yaml.safe_load(user_file) or {}
        user_raw = {k: v for k, v in user_candidate.items()
                    if isinstance(v, dict)}

    # 3. Merge: user presets extend built-ins by preset key
    merged = dict(builtin)
    for key, value in user_raw.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_preset_dicts(merged[key], value)
        else:
            merged[key] = value

    # 4. Build systems index for grouped listing
    systems: dict[str, dict] = {}

    for key, data in merged.items():
        system_name = data.get("system", key.split("-", 1)[0] if "-" in key else key)

        if system_name not in systems:
            systems[system_name] = {"versions": [], "variants": []}

        # Extract version (part after first hyphen)
        if "-" in key:
            ver = key.split("-", 1)[1]
            if ver not in systems[system_name]["versions"]:
                systems[system_name]["versions"].append(ver)

        # Collect mirror variant names
        for mirror in data.get("mirrors", []):
            if isinstance(mirror, dict):
                vname = mirror.get("name", "")
                if vname and vname not in systems[system_name]["variants"]:
                    systems[system_name]["variants"].append(vname)

    _PRESETS_CACHE = merged
    _SYSTEMS_CACHE = systems
    return merged


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
        "repos": [RepoConfig.from_dict(r) for r in raw.get("repos", [])],
    }

    if variant != "default":
        mirrors = raw.get("mirrors", [])
        found = False
        for m in mirrors:
            if isinstance(m, dict) and m.get("name") == variant:
                url_map = m.get("urls", {})
                preset["repos"] = _apply_mirror_variant(preset["repos"], url_map)
                found = True
                break
        if not found:
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
        print("Available presets:")
        for system, info in sorted(list_presets().items()):
            versions = ", ".join(info["versions"])
            variants = info["variants"]
            suffix = f"  (@{', @'.join(variants)})" if variants else ""
            print(f"  {system + ':':14s} {versions}{suffix}")
        print()
        print("Usage: preset apply debian-bookworm")
        print("       preset apply debian-bookworm@cn")
        return

    if args.action == "apply":
        preset = get_preset(args.name)
        if preset is None:
            print(f"Error: unknown preset {args.name!r}", file=sys.stderr)
            sys.exit(1)
            return

        if "@" in args.name:
            _, variant = args.name.rsplit("@", 1)
        else:
            variant = "default"

        cfg = Config()
        cfg.set_backend(preset["backend"])
        cfg.set_repos([r.to_dict() for r in preset["repos"]])
        cfg.set_mirror_variant(variant)
        cfg.set_preset_name(args.name)
        cfg.save()
        print(f"Applied preset {args.name!r} (backend: {preset['backend']}, "
              f"arch: {preset['arch']}, repos: {len(preset['repos'])})")
