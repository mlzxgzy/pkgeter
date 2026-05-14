"""Interactive REPL for pkgeter (like a switch CLI)."""

from __future__ import annotations

import cmd
import shlex
import sys

# Enable readline-based TAB completion.
# pyreadline3 is required on Windows; readline is built-in on Unix/macOS.
try:
    import readline  # noqa: F401
except ImportError:
    import pyreadline3  # noqa: F401  # Windows

from pkgeter.config import Config


class PkgeterREPL(cmd.Cmd):
    prompt = "pkgeter> "

    CORE_CMDS = {"get", "repo", "preset", "help", "exit"}
    ALIASES = {"quit": "exit", "bye": "exit", "h": "help", "g": "get", "r": "repo"}

    def __init__(self):
        super().__init__()
        self.intro = self._build_intro()

    # ---- Status display ----

    def _status_lines(self) -> list[str]:
        cfg = Config()
        lines = []
        backend = cfg.get_backend()
        arch = cfg.get("arch", "amd64")
        release = cfg.get("release", "")
        mirror = cfg.get("mirror", "")
        mirrors = cfg.get_mirrors()
        repos = cfg.get_repos()

        lines.append(f"  Backend:   {backend}")
        if release:
            lines.append(f"  Release:   {release}")
        lines.append(f"  Arch:      {arch}")
        if mirror:
            lines.append(f"  Mirror:    {mirror}")
        if len(mirrors) > 1:
            lines.append(f"  Fallbacks: {', '.join(mirrors[1:])}")
        if repos:
            lines.append(f"  Repos:     {len(repos)} configured")
        else:
            lines.append("  Repos:     (none — will use default debian-bookworm preset)")
        lines.append(f"  Output:    {cfg.get('output_dir', './output')}")
        return lines

    def _build_intro(self) -> str:
        lines = ["", "  pkgeter — Offline package downloader", ""]
        lines.extend(self._status_lines())
        lines.append("")
        lines.append("  Type ? or help")
        lines.append("")
        return "\n".join(lines)

    def emptyline(self) -> bool:
        print()
        for line in self._status_lines():
            print(line)
        print()
        return False

    # ---- Prefix resolution ----

    def _resolve(self, cmd: str) -> str | None:
        candidates = [c for c in self.CORE_CMDS if c.startswith(cmd)]
        if cmd in self.ALIASES:
            return self.ALIASES[cmd]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            print(f"Ambiguous command '{cmd}': {', '.join(sorted(candidates))}")
        return None

    # ---- Command dispatch ----

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
            try:
                run_get(args)
            except SystemExit:
                pass
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
        elif resolved == "repo":
            from pkgeter.repo import run_repo
            try:
                run_repo(args)
            except SystemExit:
                pass
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
        elif resolved == "preset":
            from pkgeter.preset import run_preset
            try:
                run_preset(args)
            except SystemExit:
                pass
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
        return False

    # ---- TAB completion: commands ----

    def completenames(self, text: str, *ignored) -> list[str]:
        return sorted(c for c in self.CORE_CMDS if c.startswith(text))

    # ---- TAB completion: get ----

    def complete_get(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        flags = [
            "--packages", "-p", "--distro", "--release", "-r",
            "--arch", "-a", "--mirror", "-m", "--output", "-o", "--config",
        ]
        return [f for f in flags if f.startswith(text)]

    # ---- TAB completion: repo ----

    def complete_repo(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        actions = ["list", "add", "remove"]
        parsed = shlex.split(line)
        # If we only have 1 word, or 2 words without a trailing space,
        # we're completing the action.
        if len(parsed) <= 1 or (len(parsed) == 2 and not line.rstrip().endswith(parsed[1] + " ")):
            # Actually simpler: check if we're past the 2nd word
            pass
        # Use word count: past the end means past action
        words = len(parsed)
        trailing = line.endswith(" ")
        if words == 1 or (words == 2 and not trailing):
            return [a for a in actions if a.startswith(text)]
        return []

    # ---- TAB completion: preset ----

    def complete_preset(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        parsed = shlex.split(line)
        words = len(parsed)
        trailing = line.endswith(" ")

        # Completing action — 1 word, or 2 words with active word being typed
        if words == 1 or (words == 2 and not trailing):
            return [a for a in ["list", "apply"] if a.startswith(text)]

        # Completing preset name after "apply"
        if words >= 2:
            # Resolve action with prefix matching
            action = self._resolve_action(parsed[1], ["apply"])
            if action == "apply":
                from pkgeter.preset import list_presets
                return sorted(p for p in list_presets() if p.startswith(text))

        return []

    # ---- TAB completion: repo arg completer (for remove) ----

    @staticmethod
    def _resolve_action(cmd: str, actions: list[str]) -> str | None:
        candidates = [a for a in actions if a.startswith(cmd)]
        if len(candidates) == 1:
            return candidates[0]
        return None

    # ---- help ----

    def do_help(self, _: str) -> None:
        print("Commands (prefix matching: g=get, r=repo, pr=preset):")
        print("  get (g)    <options>   Download packages with dependencies")
        print("  repo (r)   <command>   Manage repositories (list/add/remove)")
        print("  preset     <command>   List/apply distribution presets")
        print("  help (h)               Show this help")
        print("  exit (ex)              Exit")
        print()
        print("Subcommands can also be prefix-matched (l=list, a=add).")
        print("Press TAB twice to see all options.")
        print()
        print("Examples:")
        print('  g -p nginx --distro centos-9')
        print('  r l')
        print('  r a --name myrepo --type deb --url https://example.com')
        print('  p a debian-bookworm')

    def do_exit(self, _: str) -> bool:
        print("Bye.")
        return True


def run_repl() -> None:
    PkgeterREPL().cmdloop()
