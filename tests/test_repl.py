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
    """If 'r' was ambiguous, it'd return None. But 'r' uniquely maps to 'repo'."""
    repl = PkgeterREPL()
    assert repl._resolve("r") == "repo"


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
