"""search subcommand — query the package database for matching packages."""

from __future__ import annotations

import argparse
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict

from pkgeter.config import Config
from pkgeter.models import PackageInfo, RepoConfig


def _search_db(
    package_db: Dict[str, PackageInfo],
    q: str,
    has_wildcards: bool,
    search_desc: bool,
) -> list[PackageInfo]:
    """Search a single package DB for packages matching *q*."""
    results = []
    for name, info in package_db.items():
        n = name.lower()
        if has_wildcards:
            if fnmatch(n, q):
                results.append(info)
        else:
            if q in n:
                results.append(info)
        if search_desc and info.description and q in info.description.lower():
            results.append(info)
    return results


def run_search(argv: list[str]) -> int:
    """Search subcommand — query the package database.

    Downloads repository metadata (same as ``get``) and searches for
    packages whose **name** matches the given pattern(s).  Matching is
    case-insensitive and fuzzy (substring by default, wildcard when
    ``*`` / ``?`` is used).  Results are annotated with the repository
    name they came from.
    """
    parser = argparse.ArgumentParser(prog="pkgeter search")
    parser.add_argument("queries", nargs="*", help="Search pattern(s)")
    parser.add_argument("--distro")
    parser.add_argument("--release", "-r")
    parser.add_argument("--arch", "-a")
    parser.add_argument("--mirror", "-m", help="Mirror variant (default, cn, etc.)")
    parser.add_argument("--cn", action="store_true", help="Shortcut for --mirror cn")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--force-update", action="store_true", help="Force cache refresh")
    parser.add_argument("--desc", action="store_true", help="Also search descriptions")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1

    if not args.queries:
        print("Error: specify search query", file=sys.stderr)
        return 1

    config = Config(args.config)
    arch = args.arch or config.get("arch", "amd64")
    mirror_variant = args.mirror or config.get_mirror_variant()
    if args.cn:
        mirror_variant = "cn"

    # Determine repos and backend
    if args.distro:
        from pkgeter.preset import get_preset
        distro = args.distro
        if "@" not in distro and mirror_variant != "default":
            distro = f"{distro}@{mirror_variant}"
        preset = get_preset(distro)
        if not preset:
            print(f"Error: unknown preset '{args.distro}'", file=sys.stderr)
            return 1
        repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in preset["repos"]]
        backend_name = preset["backend"]
        arch = preset.get("arch", arch or "amd64")
        preset_label = args.distro
    else:
        repos_dicts = config.get_repos()
        if not repos_dicts:
            from pkgeter.preset import get_preset
            fallback = "debian-bookworm"
            if mirror_variant != "default":
                fallback = f"debian-bookworm@{mirror_variant}"
            preset = get_preset(fallback)
            repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in preset["repos"]]
            backend_name = preset["backend"]
            preset_label = "debian-bookworm"
        else:
            repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in repos_dicts]
            backend_name = config.get_backend()
            preset_label = config.get_preset_name() or None

    # Instantiate backend
    if backend_name in ("apt", "debian"):
        from pkgeter.backend.debian import DebianBackend
        backend = DebianBackend()
    elif backend_name == "dnf":
        from pkgeter.backend.rpm import DnfBackend
        backend = DnfBackend()
    elif backend_name == "rpm":
        from pkgeter.backend.rpm import RpmBackend
        backend = RpmBackend()
    else:
        print(f"Error: unknown backend '{backend_name}'", file=sys.stderr)
        return 1

    # Download AND search per-repo so results show the origin repo
    repo_dbs: list[tuple[str, Dict[str, PackageInfo]]] = []
    for repo in repos:
        try:
            print(f"  Loading {repo.name}...", end="", flush=True)
            db = backend.download_package_db([repo], arch, force_update=args.force_update)
            if db:
                repo_dbs.append((repo.name, db))
                print(f" {len(db)} packages")
            else:
                print(" (empty)")
        except Exception:
            print(" (failed)")
            continue

    if not repo_dbs:
        print("Error: no packages found from any repo", file=sys.stderr)
        return 1

    total = sum(len(db) for _, db in repo_dbs)
    print(f"Found {total} packages across {len(repo_dbs)} repos\n")

    # Search
    for query in args.queries:
        q = query.lower()
        has_wildcards = "*" in q or "?" in q
        found_any = False

        for repo_name, package_db in repo_dbs:
            results = _search_db(package_db, q, has_wildcards, args.desc)
            if not results:
                continue

            if not found_any:
                print(f"Results for '{query}':")
                found_any = True

            header = f"{preset_label} / {repo_name}" if preset_label else repo_name
            print(f"  [{header}]")
            for info in results:
                size_str = _format_size(info.size) if info.size else ""
                desc = (info.description or "").split("\n")[0][:80]
                print(f"    {info.package} {info.version:>20}  {info.arch:>8}  {size_str:>8}  {desc}")
            print()

        if not found_any:
            print(f"No matches for '{query}'\n")

    return 0


def _format_size(size_bytes: int) -> str:
    """Format byte count to a human-readable string."""
    if size_bytes >= 1_000_000:
        return f"{size_bytes / 1_000_000:.1f} MB"
    if size_bytes >= 1_000:
        return f"{size_bytes / 1_000:.0f} kB"
    return f"{size_bytes} B"
