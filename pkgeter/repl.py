"""Interactive REPL for pkgeter (like a switch CLI)."""

from __future__ import annotations

import cmd
import shlex
import sys

# Enable readline-based TAB completion.
# On Windows, install 'pyreadline3' for completion support.
try:
    import readline  # noqa: F401  — Unix / macOS / pyreadline3
except ImportError:
    try:
        import pyreadline3  # noqa: F401
    except ImportError:
        pass


class PkgeterREPL(cmd.Cmd):
    intro = "\n    pkgeter — Offline package downloader\n    Type ? or help\n\n"
    prompt = "pkgeter> "

    CORE_CMDS = {"get", "repo", "preset", "help", "exit"}
    ALIASES = {"quit": "exit", "bye": "exit", "h": "help", "g": "get", "r": "repo"}

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
        elif resolved == "repo":
            from pkgeter.repo import run_repo
            try:
                run_repo(args)
            except SystemExit:
                pass
        elif resolved == "preset":
            from pkgeter.preset import run_preset
            try:
                run_preset(args)
            except SystemExit:
                pass
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
        parts = shlex.split(line)
        # completing action (2nd word)
        if len(parts) <= 2:
            return [a for a in actions if a.startswith(text)]
        return []

    # ---- TAB completion: preset ----

    def complete_preset(self, text: str, line: str, begidx: int, endidx: int) -> list[str]:
        parts = shlex.split(line)
        words = len(parts)
        # completing action (2nd word)
        if words <= 2:
            return [a for a in ["list", "apply"] if a.startswith(text)]
        # completing preset name after "apply"
        if words >= 3 and parts[1] in ("apply", "a"):
            from pkgeter.preset import list_presets
            return sorted(p for p in list_presets() if p.startswith(text))
        return []

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
    if "readline" not in sys.modules and "pyreadline3" not in sys.modules:
        print(
            "Tip: install 'pyreadline3' for TAB completion:\n"
            "  pip install pkgeter[readline]\n",
            file=sys.stderr,
        )
    PkgeterREPL().cmdloop()
