"""get subcommand — download packages and their dependencies."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

import httpx

from pkgeter.config import CONFIG_PATH, Config, parse_mirror_entry
from pkgeter.context import resolve_backend
from pkgeter.db.packages import download_package_db
from pkgeter.deps.resolver import Resolver
from pkgeter.deps.virtual import resolve_virtual_interactive
from pkgeter.downloader import Downloader

# ---------------------------------------------------------------------------
# Legacy parser and helpers (kept for backward compat with existing tests)
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser (legacy top-level parser, now the get subcommand).

    Retained for backward compatibility with existing tests.
    """
    parser = argparse.ArgumentParser(
        prog="pkgeter",
        description="Offline Debian package downloader",
    )
    parser.add_argument(
        "--packages", "-p",
        nargs="+",
        help="Target package names to download",
    )
    parser.add_argument(
        "--mirror", "-m",
        action="append",
        dest="mirrors",
        help=(
            "Debian mirror URL (repeatable, tried in order). "
            "Defaults to the last-used mirror from config."
        ),
    )
    parser.add_argument(
        "--release", "-r",
        help="Debian release name (e.g., bookworm, bullseye)",
    )
    parser.add_argument(
        "--arch", "-a",
        help="Architecture (e.g., amd64, arm64)",
    )
    parser.add_argument(
        "--dpkg-list",
        type=Path,
        help="Path to dpkg -l output file (to skip already-installed packages)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("./output"),
        help="Output directory (default: ./output)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=f"Config file path (default: {CONFIG_PATH})",
    )
    return parser


def _try_load_package_db(
    mirrors: list[str],
    release: str,
    arch: str,
    timeout: int = 60,
) -> tuple[dict, str] | tuple[None, None]:
    """Try each mirror in order until one yields a package database.

    Each mirror entry may carry an ``@release`` override suffix.
    Returns ``(package_db, used_entry)`` or ``(None, None)``,
    where *used_entry* is the original entry (with ``@`` if present).
    """
    for entry in mirrors:
        mirror_url, release_override = parse_mirror_entry(entry)
        effective_release = release_override or release
        try:
            label = mirror_url
            if release_override:
                label += f"  (release: {effective_release})"
            print(f"  Trying mirror: {label}")
            package_db = download_package_db(
                mirror_url, effective_release, arch,
                use_cache=True, timeout=timeout,
            )
            if package_db:
                return package_db, entry
        except httpx.HTTPError as exc:
            print(f"  Mirror failed: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"  Mirror error: {exc}", file=sys.stderr)
    return None, None


def _promote_mirror(mirrors: list[str], winner: str) -> list[str]:
    """Move *winner* to the front of the list, preserving relative order of the rest."""
    result = [m for m in mirrors if m != winner]
    return [winner] + result


# ---------------------------------------------------------------------------
# run_get — main get subcommand handler
# ---------------------------------------------------------------------------


def run_get(argv: list[str]) -> int:
    """Get subcommand — download packages and their dependencies.

    Parses the argument list, resolves the package manager backend,
    downloads the package database, resolves dependencies, downloads
    packages, and generates the output.
    """
    parser = argparse.ArgumentParser(prog="pkgeter get")
    parser.add_argument("packages", nargs="*", help="Target packages (positional)")
    parser.add_argument("--packages", "-p", nargs="+", dest="opt_packages", help="Target packages")
    parser.add_argument("--distro")
    parser.add_argument("--release", "-r")
    parser.add_argument("--arch", "-a")
    parser.add_argument("--mirror", "-m", help="Mirror variant (default, cn, etc.)")
    parser.add_argument("--cn", action="store_true", help="Shortcut for --mirror cn")
    parser.add_argument("--force-update", action="store_true", help="Force cache refresh")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose/debug output")
    parser.add_argument("--output", "-o", type=Path, default=Path("./output"))
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
        logger.debug("Verbose mode enabled")

    packages = args.packages or args.opt_packages
    if not packages:
        print("Error: specify packages to get", file=sys.stderr)
        return 1
    config = Config(args.config)
    logger.debug("Config loaded from: %s", config.path)

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
    mirror_variant = ctx.mirror_variant

    # Download package DB
    print("Loading package database...")
    logger.debug("force_update=%s", args.force_update)
    package_db = backend.download_package_db(repos, arch, force_update=args.force_update)
    if not package_db:
        print("Error: no packages found from any repo", file=sys.stderr)
        return 1
    logger.debug("Package DB loaded: %d packages", len(package_db))

    # Resolve dependencies
    print("Resolving dependencies...")
    def _resolve_virtual(name: str, providers: list[str]) -> str:
        if len(providers) == 1:
            print(f"Virtual package '{name}' is provided by '{providers[0]}'")
            return providers[0]
        if sys.stdin.isatty():
            return resolve_virtual_interactive(name, providers, package_db)
        return providers[0]

    provides_index = getattr(backend, "provides_index", None)
    if provides_index is not None:
        logger.debug("Provides index: %d entries", len(provides_index))

    resolver = Resolver(
        all_pkgs=package_db,
        installed=set(),
        virtual_callback=_resolve_virtual,
        provides_index=provides_index,
    )
    needed = resolver.resolve(packages)
    logger.debug("Packages requested: %s", packages)
    logger.debug("Packages to download: %s", needed)
    print(f"Need to download {len(needed)} packages")

    if resolver.skipped:
        total = sum(len(v) for v in resolver.skipped.values())
        print(f"\nWarning: {total} dependencies could not be found in the "
              f"repository and were skipped (assumed system-provided):")
        for pkg, deps in resolver.skipped.items():
            for dep in deps:
                print(f"  {pkg} -> {dep}")
        print()

    # Build download info with per-package URLs
    download_dir = args.output / ".downloads"
    downloader = Downloader(
        mirror="",
        dest_dir=download_dir,
        progress_callback=lambda name, done, total: print(
            f"  [{done}/{total}] {name}"
        ),
    )
    logger.debug("Download destination: %s", download_dir)
    pkg_info = {}
    for name in needed:
        info = package_db[name]
        url = backend.build_download_url(info.base_url or repos[0].url, info)
        pkg_info[name] = (url, info.sha256, info.size)
        logger.debug("  %s -> %s", name, url)

    downloaded = downloader.download_all(pkg_info)
    files = [downloaded[name].name for name in needed]
    install_script = backend.generate_install_script(files, packages)

    # Output
    if backend.name in ("apt", "debian"):
        from pkgeter.output.deb_directory import DebDirectoryOutput
        fmt = DebDirectoryOutput()
    else:
        from pkgeter.output.rpm_directory import RpmDirectoryOutput
        fmt = RpmDirectoryOutput()
    logger.debug("Output format: %s", type(fmt).__name__)
    result = fmt.execute(
        deb_files=downloaded,
        install_script=install_script,
        release=args.release or "",
        arch=arch,
        output_dir=args.output,
    )
    # Save mirror_variant choice and preset name to config
    config.set_mirror_variant(mirror_variant)
    if args.distro:
        config.set_preset_name(args.distro)
    config.save()

    print(f"Output written to: {result}")
    return 0
