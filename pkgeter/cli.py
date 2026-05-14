"""CLI argument parsing and headless orchestration."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

from pkgeter.config import CONFIG_PATH, Config, parse_mirror_entry
from pkgeter.db.dpkg_list import parse_dpkg_list_file
from pkgeter.db.packages import download_package_db
from pkgeter.deps.resolver import Resolver
from pkgeter.deps.virtual import resolve_virtual_interactive
from pkgeter.downloader import Downloader
from pkgeter.output.deb_directory import DebDirectoryOutput


def build_parser() -> argparse.ArgumentParser:
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


def run_headless(args: argparse.Namespace) -> int:
    """Execute CLI mode."""
    config = Config(args.config)

    release = args.release or config.get("release", "bookworm")
    arch = args.arch or config.get("arch", "amd64")
    output_dir = args.output

    target_packages = args.packages
    if not target_packages:
        print("Error: --packages is required")
        return 1

    # ----- 1. Resolve mirrors: CLI > config > default -----
    mirrors: list[str] = args.mirrors or config.get_mirrors()

    # ----- 2. Download package database (try mirrors in order) -----
    print(f"Downloading package database for {release}/{arch} ...")
    package_db, used_mirror = _try_load_package_db(mirrors, release, arch)
    if package_db is None:
        print(
            "Error: all mirrors failed — check your network or mirror URLs",
            file=sys.stderr,
        )
        return 1
    clean_mirror, _ = parse_mirror_entry(used_mirror)
    print(f"  Using mirror: {clean_mirror}")
    print(f"  Found {len(package_db)} packages in repository")

    # Persist successful mirror entry (with @ override if present) to config
    config.set_mirrors(_promote_mirror(mirrors, used_mirror))
    config.save()

    # ----- 3. Load installed packages -----
    installed = set()
    if args.dpkg_list:
        installed = parse_dpkg_list_file(args.dpkg_list)
        print(f"  Found {len(installed)} installed packages from dpkg -l")

    # ----- 4. Resolve dependencies -----
    print("Resolving dependencies...")
    resolver = Resolver(
        all_pkgs=package_db,
        installed=installed,
        virtual_callback=(
            lambda v, p: resolve_virtual_interactive(v, p, package_db)
            if sys.stdin.isatty()
            else p[0]
        ),
    )
    needed = resolver.resolve(target_packages)
    print(f"  Need to download {len(needed)} packages")

    # ----- 5. Download .deb files -----
    download_dir = output_dir / ".downloads"
    downloader = Downloader(
        mirror=clean_mirror,
        dest_dir=download_dir,
        progress_callback=lambda name, done, total: print(
            f"  [{done}/{total}] Downloaded {name}"
        ),
    )
    pkg_download_info = {}
    for name in needed:
        info = package_db[name]
        pkg_download_info[name] = (info.filename, info.sha256, info.size)
    downloaded = downloader.download_all(pkg_download_info)

    # ----- 6. Generate install script -----
    pkg_list = " ".join(target_packages)
    deb_names = [downloaded[name].name for name in needed]
    deb_cmds = "\n".join(
        f'sudo dpkg -i "{name}"' for name in deb_names
    )
    install_script = (
        "#!/bin/bash\n"
        "# pkgeter - Offline Debian package installation script\n"
        f"# Target packages: {pkg_list}\n"
        "#\n"
        "# Install packages one by one in dependency order.\n"
        "\n"
        'SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"\n'
        "cd \"$SCRIPT_DIR\"\n"
        f"{deb_cmds}\n"
    )

    # ----- 7. Write output -----
    fmt = DebDirectoryOutput()
    result = fmt.execute(
        deb_files=downloaded,
        install_script=install_script,
        release=release,
        arch=arch,
        output_dir=output_dir,
    )
    print(f"Output written to: {result}")
    return 0


def run_cli() -> None:
    """Main CLI entry point."""
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(run_headless(args))
