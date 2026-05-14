"""Tests for REPL."""

from pkgeter.repl import PkgeterREPL


def test_resolve_get():
    repl = PkgeterREPL()
    assert repl._resolve("get") == "get"
    assert repl._resolve("g") == "get"
    assert repl._resolve("ge") == "get"


def test_resolve_repo():
    repl = PkgeterREPL()
    assert repl._resolve("repo") == "repo"
    assert repl._resolve("r") == "repo"
    assert repl._resolve("re") == "repo"


def test_resolve_preset():
    repl = PkgeterREPL()
    assert repl._resolve("preset") == "preset"
    assert repl._resolve("pr") == "preset"


def test_resolve_help():
    repl = PkgeterREPL()
    assert repl._resolve("help") == "help"
    assert repl._resolve("h") == "help"


def test_resolve_exit():
    repl = PkgeterREPL()
    assert repl._resolve("exit") == "exit"
    assert repl._resolve("quit") == "exit"
    assert repl._resolve("bye") == "exit"


def test_resolve_unknown():
    repl = PkgeterREPL()
    assert repl._resolve("xyz") is None


def test_resolve_ambiguous():
    repl = PkgeterREPL()
    assert repl._resolve("r") == "repo"


# ---------------------------------------------------------------------------
# completenames — command-level TAB completion
# ---------------------------------------------------------------------------


def test_completenames():
    repl = PkgeterREPL()
    matches = repl.completenames("g")
    assert "get" in matches
    assert "repo" not in matches


def test_completenames_prefix():
    repl = PkgeterREPL()
    matches = repl.completenames("ex")
    assert "exit" in matches
    assert len(matches) == 1


def test_completenames_all():
    repl = PkgeterREPL()
    matches = repl.completenames("")
    assert "get" in matches
    assert "repo" in matches
    assert "preset" in matches
    assert "help" in matches
    assert "exit" in matches


# ---------------------------------------------------------------------------
# complete_get — get subcommand TAB completion
# ---------------------------------------------------------------------------


def test_complete_get_flags():
    repl = PkgeterREPL()
    matches = repl.complete_get("--p", "get --p", 5, 8)
    assert "--packages" in matches
    assert "-p" not in matches  # doesn't start with --


def test_complete_get_short_flag():
    repl = PkgeterREPL()
    matches = repl.complete_get("-", "get -", 5, 6)
    assert "-p" in matches
    assert "-r" in matches


# ---------------------------------------------------------------------------
# complete_repo — repo subcommand TAB completion
# ---------------------------------------------------------------------------


def test_complete_repo_actions():
    repl = PkgeterREPL()
    matches = repl.complete_repo("l", "repo l", 5, 6)
    assert "list" in matches
    assert "add" not in matches


def test_complete_repo_all():
    repl = PkgeterREPL()
    matches = repl.complete_repo("", "repo ", 5, 5)
    assert "list" in matches
    assert "add" in matches
    assert "remove" in matches


def test_complete_repo_no_match():
    repl = PkgeterREPL()
    matches = repl.complete_repo("x", "repo x", 5, 6)
    assert matches == []


# ---------------------------------------------------------------------------
# complete_preset — preset subcommand TAB completion
# ---------------------------------------------------------------------------


def test_complete_preset_actions():
    repl = PkgeterREPL()
    matches = repl.complete_preset("l", "preset l", 7, 8)
    assert "list" in matches
    assert "apply" not in matches


def test_complete_preset_apply_names():
    repl = PkgeterREPL()
    matches = repl.complete_preset("deb", 'preset apply deb', 12, 15)
    assert "debian-bookworm" in matches
    assert "debian-bullseye" in matches
