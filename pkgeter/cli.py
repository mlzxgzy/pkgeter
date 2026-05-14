"""CLI entry point — dispatch to subcommands or REPL."""

from __future__ import annotations

import sys

COMMANDS = {"get": "get", "repo": "repo", "preset": "preset", "help": "help", "exit": "exit"}
_ALIASES = {"quit": "exit", "bye": "exit", "h": "help", "g": "get", "r": "repo"}


def _resolve(cmd: str) -> str | None:
    """Resolve a command string to a canonical command name.

    Supports prefix matching (e.g. ``ge`` → ``get``) and aliases.
    Returns ``None`` when the command is unknown or ambiguous.
    """
    candidates = [k for k in COMMANDS if k.startswith(cmd)]
    if cmd in _ALIASES:
        return _ALIASES[cmd]
    if len(candidates) == 1:
        return COMMANDS[candidates[0]]
    if len(candidates) > 1:
        print(f"Ambiguous command '{cmd}': {', '.join(candidates)}", file=sys.stderr)
    return None


def resolve_subcmd(cmd: str, choices: list[str]) -> str | None:
    """Resolve a subcommand prefix to a unique choice.

    Example: ``resolve_subcmd("l", ["list", "add", "remove"])`` → ``"list"``

    Returns ``None`` when the prefix is unknown or ambiguous.
    """
    candidates = [c for c in choices if c.startswith(cmd)]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        print(f"Ambiguous subcommand '{cmd}': {', '.join(candidates)}", file=sys.stderr)
    return None


def run_cli() -> None:
    """Main CLI entry point — parse first argument and dispatch to subcommand."""
    if len(sys.argv) == 1:
        from pkgeter.repl import run_repl
        run_repl()
        return

    cmd = sys.argv[1]
    resolved = _resolve(cmd)
    if resolved is None:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Available: get, repo, preset, help, exit", file=sys.stderr)
        sys.exit(1)

    if resolved == "get":
        from pkgeter.get import run_get
        sys.exit(run_get(sys.argv[2:]))
    elif resolved == "repo":
        from pkgeter.repo import run_repo
        sys.exit(run_repo(sys.argv[2:]))
    elif resolved == "preset":
        from pkgeter.preset import run_preset
        sys.exit(run_preset(sys.argv[2:]))
    elif resolved == "help":
        print("pkgeter — Offline package downloader")
        print("Commands: get, repo, preset, help, exit")
        sys.exit(0)
    elif resolved == "exit":
        sys.exit(0)
