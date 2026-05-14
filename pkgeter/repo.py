"""repo subcommand — manage configured repositories."""

from __future__ import annotations

import argparse
import sys

from pkgeter.cli import resolve_subcmd
from pkgeter.config import Config

REPO_ACTIONS = ["list", "add", "remove"]


def build_repo_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pkgeter repo")
    sub = p.add_subparsers(dest="action")
    sub.add_parser("list", help="List configured repositories")

    add_p = sub.add_parser("add", help="Add a repository")
    add_p.add_argument("--name", required=True)
    add_p.add_argument("--type", required=True, choices=["deb", "rpm"])
    add_p.add_argument("--url", required=True)
    add_p.add_argument("--release")
    add_p.add_argument("--components")
    add_p.add_argument("--arch")

    rm_p = sub.add_parser("remove", help="Remove a repository")
    rm_p.add_argument("name")

    return p


def run_repo(argv: list[str]) -> int:
    parser = build_repo_parser()
    if argv:
        expanded = resolve_subcmd(argv[0], REPO_ACTIONS)
        if expanded:
            argv = [expanded] + argv[1:]
    args = parser.parse_args(argv)
    if not args.action:
        parser.print_help()
        return 0
    config = Config()

    if args.action == "list":
        repos = config.get_repos()
        if not repos:
            print("No repositories configured.")
            return 0
        for r in repos:
            print(f"  {r.get('name', ''):<20} {r.get('type', ''):<6} {r.get('url', '')}")
        return 0

    elif args.action == "add":
        entry = {"name": args.name, "type": args.type, "url": args.url}
        if args.release:
            entry["release"] = args.release
        if args.components:
            entry["components"] = [c.strip() for c in args.components.split(",")]
        if args.arch:
            entry["arch"] = args.arch
        repos = config.get_repos()
        repos.append(entry)
        config.set_repos(repos)
        print(f"Added repository '{args.name}'")
        return 0

    elif args.action == "remove":
        repos = config.get_repos()
        filtered = [r for r in repos if r.get("name") != args.name]
        if len(filtered) == len(repos):
            print(f"Repository '{args.name}' not found", file=sys.stderr)
            return 1
        config.set_repos(filtered)
        print(f"Removed repository '{args.name}'")
        return 0

    return 0
