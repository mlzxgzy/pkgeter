"""Interactive REPL for pkgeter (like a switch CLI)."""

from __future__ import annotations

import cmd
import shlex
import sys


class PkgeterREPL(cmd.Cmd):
    intro = "\n    pkgeter — Offline package downloader\n    Type ? or help\n\n"
    prompt = "pkgeter> "

    CORE_CMDS = {"get", "repo", "preset", "help", "exit"}
    ALIASES = {"quit": "exit", "bye": "exit", "h": "help", "g": "get", "r": "repo"}

    def _resolve(self, cmd: str) -> str | None:
        candidates = [c for c in self.CORE_CMDS if c.startswith(cmd)]
        if cmd in self.ALIASES:
            return self.ALIASES[cmd]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            print(f"Ambiguous command '{cmd}': {', '.join(sorted(candidates))}")
        return None

    def default(self, line: str) -> bool:
        parts = shlex.split(line)
        if not parts:
            return False
        raw_cmd, *args = parts
        resolved = self._resolve(raw_cmd)
        if resolved is None:
            print(f"Unknown command: {raw_cmd}. Type help.")
            return False

        if resolved == "exit":
            print("Bye.")
            return True
        elif resolved == "help":
            self.do_help("")
            return False
        elif resolved == "get":
            from pkgeter.get import run_get
            run_get(args)
        elif resolved == "repo":
            from pkgeter.repo import run_repo
            run_repo(args)
        elif resolved == "preset":
            from pkgeter.preset import run_preset
            run_preset(args)
        return False

    def do_help(self, _: str) -> None:
        print("Commands (prefix matching: g=get, r=repo, pr=preset):")
        print("  get (g)    <options>   Download packages with dependencies")
        print("  repo (r)   <command>   Manage repositories (list/add/remove)")
        print("  preset     <command>   List/apply distribution presets")
        print("  help (h)               Show this help")
        print("  exit (ex)              Exit")
        print()
        print("For subcommand help: get --help, repo --help, preset --help")

    def do_exit(self, _: str) -> bool:
        print("Bye.")
        return True

    def completenames(self, text: str, *ignored) -> list[str]:
        return [c for c in self.CORE_CMDS if c.startswith(text)]


def run_repl() -> None:
    PkgeterREPL().cmdloop()
