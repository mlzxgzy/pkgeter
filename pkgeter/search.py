"""search subcommand — query the package database for matching packages."""

from __future__ import annotations

import argparse
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict

from pkgeter.config import Config
from pkgeter.context import resolve_backend
from pkgeter.models import PackageInfo


def _search_db(
    package_db: Dict[str, PackageInfo],
    q: str,
    has_wildcards: bool,
    search_desc: bool,
) -> list[PackageInfo]:
    """Search a single package DB for packages matching *q* (in-memory fallback)."""
    results = []
    seen = set()
    for name, info in package_db.items():
        n = name.lower()
        matched = False
        if has_wildcards:
            if fnmatch(n, q):
                matched = True
        else:
            if q in n:
                matched = True
        if search_desc and not matched and info.description and q in info.description.lower():
            matched = True
        if matched and name not in seen:
            results.append(info)
            seen.add(name)
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

    try:
        ctx = resolve_backend(
            distro=args.distro,
            arch=args.arch,
            mirror=args.mirror,
            cn=args.cn,
            config=config,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    backend, repos, arch = ctx.backend, ctx.repos, ctx.arch
    preset_label = ctx.preset_name

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
