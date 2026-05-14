"""get subcommand — download packages and their dependencies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from pkgeter.config import CONFIG_PATH, Config, parse_mirror_entry
from pkgeter.db.packages import download_package_db
from pkgeter.deps.resolver import Resolver
from pkgeter.deps.virtual import resolve_virtual_interactive
from pkgeter.downloader import Downloader
from pkgeter.models import RepoConfig

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
    parser.add_argument("--packages", "-p", nargs="+", required=True)
    parser.add_argument("--distro")
    parser.add_argument("--release", "-r")
    parser.add_argument("--arch", "-a")
    parser.add_argument("--mirror", "-m", action="append", dest="mirrors")
    parser.add_argument("--output", "-o", type=Path, default=Path("./output"))
    parser.add_argument("--config", type=Path, default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1

    config = Config(args.config)
    arch = args.arch or config.get("arch", "amd64")

    # Determine repos and backend
    if args.distro:
        from pkgeter.preset import get_preset
        preset = get_preset(args.distro)
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
            preset = get_preset("debian-bookworm")
            repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in preset["repos"]]
            backend_name = preset["backend"]
        else:
            repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in repos_dicts]
            backend_name = config.get_backend()

    # Instantiate backend
    if backend_name == "debian":
        from pkgeter.backend.debian import DebianBackend
        backend = DebianBackend()
    elif backend_name == "rpm":
        from pkgeter.backend.rpm import RpmBackend
        backend = RpmBackend()
    else:
        print(f"Error: unknown backend '{backend_name}'", file=sys.stderr)
        return 1

    # Download package DB
    print("Downloading package database...")
    package_db = backend.download_package_db(repos, arch)
    if not package_db:
        print("Error: no packages found from any repo", file=sys.stderr)
        return 1
    print(f"Found {len(package_db)} packages")

    # Resolve dependencies
    print("Resolving dependencies...")
    resolver = Resolver(
        all_pkgs=package_db,
        installed=set(),
        virtual_callback=(
            lambda v, p: resolve_virtual_interactive(v, p, package_db)
            if sys.stdin.isatty()
            else p[0]
        ),
    )
    needed = resolver.resolve(args.packages)
    print(f"Need to download {len(needed)} packages")

    # Build download info
    download_dir = args.output / ".downloads"
    repo_url = repos[0].url
    downloader = Downloader(
        mirror=repo_url,
        dest_dir=download_dir,
        progress_callback=lambda name, done, total: print(
            f"  [{done}/{total}] {name}"
        ),
    )
    pkg_info = {}
    for name in needed:
        info = package_db[name]
        pkg_info[name] = (info.filename, info.sha256, info.size)

    downloaded = downloader.download_all(pkg_info)
    files = [downloaded[name].name for name in needed]
    install_script = backend.generate_install_script(files, args.packages)

    # Output
    if backend_name == "debian":
        from pkgeter.output.deb_directory import DebDirectoryOutput
        fmt = DebDirectoryOutput()
    else:
        from pkgeter.output.rpm_directory import RpmDirectoryOutput
        fmt = RpmDirectoryOutput()
    result = fmt.execute(
        deb_files=downloaded,
        install_script=install_script,
        release=args.release or "",
        arch=arch,
        output_dir=args.output,
    )
    print(f"Output written to: {result}")
    return 0
