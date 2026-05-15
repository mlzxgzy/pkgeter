"""tree subcommand — visualize package dependency trees."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

from pkgeter.config import Config
from pkgeter.deps.tree import build_dependency_tree
from pkgeter.models import RepoConfig
from pkgeter.output.tree_html import render_tree_html


def run_tree(argv: list[str]) -> int:
    """Tree subcommand — generate dependency tree visualization."""
    parser = argparse.ArgumentParser(prog="pkgeter tree")
    parser.add_argument("packages", nargs="*", help="Target packages (positional)")
    parser.add_argument("--distro")
    parser.add_argument("--release", "-r")
    parser.add_argument("--arch", "-a")
    parser.add_argument("--mirror", "-m", help="Mirror variant (default, cn, etc.)")
    parser.add_argument("--cn", action="store_true", help="Shortcut for --mirror cn")
    parser.add_argument("--force-update", action="store_true", help="Force cache refresh")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose/debug output")
    parser.add_argument("--output", "-o", type=Path, default=Path("./tree.html"))
    parser.add_argument("--config", type=Path, default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1

    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s: %(message)s",
            force=True,
        )

    if not args.packages:
        print("Error: specify packages to visualize", file=sys.stderr)
        return 1

    config = Config(args.config)
    arch = args.arch or config.get("arch", "amd64")
    mirror_variant = args.mirror or config.get_mirror_variant()
    if args.cn:
        mirror_variant = "cn"

    # Determine repos and backend
    if args.distro:
        from pkgeter.preset import get_preset
        preset = get_preset(args.distro, mirror_variant=mirror_variant)
        if not preset:
            print(f"Error: unknown preset '{args.distro}'", file=sys.stderr)
            return 1
        repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in preset["repos"]]
        backend_name = preset["backend"]
        arch = preset.get("arch", arch)
    else:
        repos_dicts = config.get_repos()
        if not repos_dicts:
            from pkgeter.preset import get_preset
            preset = get_preset("debian-bookworm", mirror_variant=mirror_variant)
            repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in preset["repos"]]
            backend_name = preset["backend"]
        else:
            repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in repos_dicts]
            backend_name = config.get_backend()

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

    # Download package DB
    print("Loading package database...")
    package_db = backend.download_package_db(repos, arch, force_update=args.force_update)
    if not package_db:
        print("Error: no packages found from any repo", file=sys.stderr)
        return 1
    logger.debug("Package DB loaded: %d packages", len(package_db))

    # Build dependency trees
    print("Building dependency tree...")
    trees = build_dependency_tree(args.packages, package_db)

    # Render HTML
    output_path = render_tree_html(trees, args.output)
    print(f"Dependency tree written to: {output_path}")
    return 0
