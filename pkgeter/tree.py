"""tree subcommand — visualize package dependency trees."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

from pkgeter.config import Config
from pkgeter.context import resolve_backend
from pkgeter.deps.tree import build_dependency_tree, build_install_order_trees
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

    # Download package DB
    print("Loading package database...")
    package_db = backend.download_package_db(repos, arch, force_update=args.force_update)
    if not package_db:
        print("Error: no packages found from any repo", file=sys.stderr)
        return 1
    logger.debug("Package DB loaded: %d packages", len(package_db))

    # Build dependency trees
    print("Building dependency tree...")
    provides_index = getattr(backend, "provides_index", None)
    trees = build_dependency_tree(args.packages, package_db,
                                  external_index=provides_index)

    # Build install-order trees
    install_trees = build_install_order_trees(trees)

    # Render HTML (embeds both full and install-order datasets)
    output_path = render_tree_html(trees, args.output, install_trees=install_trees)
    print(f"Dependency tree written to: {output_path}")
    return 0
