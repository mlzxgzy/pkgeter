"""Tests for CLI argument parsing and mirror fallback logic."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from pkgeter.cli import _resolve, resolve_subcmd
from pkgeter.get import _promote_mirror, _try_load_package_db, build_parser
from pkgeter.config import parse_mirror_entry


# ---------------------------------------------------------------------------
# _resolve — top-level command prefix matching
# ---------------------------------------------------------------------------


def test_resolve_get():
    assert _resolve("get") == "get"
    assert _resolve("g") == "get"
    assert _resolve("ge") == "get"


def test_resolve_repo():
    assert _resolve("repo") == "repo"
    assert _resolve("r") == "repo"


def test_resolve_preset():
    assert _resolve("preset") == "preset"
    assert _resolve("p") == "preset"


def test_resolve_help():
    assert _resolve("help") == "help"
    assert _resolve("h") == "help"


def test_resolve_exit():
    assert _resolve("exit") == "exit"
    assert _resolve("quit") == "exit"
    assert _resolve("bye") == "exit"


def test_resolve_unknown():
    assert _resolve("xyz") is None


def test_resolve_re_prefix():
    """'re' prefix uniquely matches 'repo'."""
    assert _resolve("re") == "repo"


# ---------------------------------------------------------------------------
# resolve_subcmd — subcommand prefix matching
# ---------------------------------------------------------------------------


def test_subcmd_resolve_list():
    assert resolve_subcmd("l", ["list", "add", "remove"]) == "list"


def test_subcmd_resolve_add():
    assert resolve_subcmd("a", ["list", "add", "remove"]) == "add"


def test_subcmd_resolve_remove():
    assert resolve_subcmd("r", ["list", "add", "remove"]) == "remove"


def test_subcmd_resolve_unknown():
    assert resolve_subcmd("x", ["list", "add", "remove"]) is None


def test_subcmd_resolve_ambiguous():
    """'r' matches both 'remove' and 'refresh'."""
    assert resolve_subcmd("r", ["list", "remove", "refresh"]) is None


# ---------------------------------------------------------------------------
# build_parser — --mirror flag
# ---------------------------------------------------------------------------


def test_parser_mirror_default():
    args = build_parser().parse_args(["-p", "foo"])
    assert args.mirrors is None


def test_parser_single_mirror():
    args = build_parser().parse_args(["-p", "foo", "-m", "https://deb.debian.org/debian"])
    assert args.mirrors == ["https://deb.debian.org/debian"]


def test_parser_multiple_mirrors():
    args = build_parser().parse_args([
        "-p", "foo",
        "-m", "https://mirror1.example.com",
        "-m", "https://mirror2.example.com",
    ])
    assert args.mirrors == [
        "https://mirror1.example.com",
        "https://mirror2.example.com",
    ]


def test_parser_mirror_with_release():
    args = build_parser().parse_args([
        "-p", "nginx",
        "-m", "https://deb.debian.org/debian",
        "-r", "sid",
    ])
    assert args.mirrors == ["https://deb.debian.org/debian"]
    assert args.release == "sid"


def test_parser_mirror_at_syntax():
    """--mirror passes @syntax through to args.mirrors."""
    args = build_parser().parse_args([
        "-p", "nginx",
        "-m", "https://deb.debian.org/debian",
        "-m", "https://security.debian.org/debian-security@bookworm-security",
    ])
    assert args.mirrors == [
        "https://deb.debian.org/debian",
        "https://security.debian.org/debian-security@bookworm-security",
    ]


# ---------------------------------------------------------------------------
# _promote_mirror
# ---------------------------------------------------------------------------


def test_promote_first():
    assert _promote_mirror(
        ["https://a.com", "https://b.com", "https://c.com"],
        "https://a.com",
    ) == ["https://a.com", "https://b.com", "https://c.com"]


def test_promote_middle():
    assert _promote_mirror(
        ["https://a.com", "https://b.com", "https://c.com"],
        "https://b.com",
    ) == ["https://b.com", "https://a.com", "https://c.com"]


def test_promote_last():
    assert _promote_mirror(
        ["https://a.com", "https://b.com", "https://c.com"],
        "https://c.com",
    ) == ["https://c.com", "https://a.com", "https://b.com"]


def test_promote_not_in_list():
    assert _promote_mirror(
        ["https://a.com", "https://b.com"],
        "https://x.com",
    ) == ["https://x.com", "https://a.com", "https://b.com"]


def test_promote_single():
    assert _promote_mirror(["https://a.com"], "https://a.com") == ["https://a.com"]


def test_promote_empty():
    assert _promote_mirror([], "https://a.com") == ["https://a.com"]


# ---------------------------------------------------------------------------
# _try_load_package_db
# ---------------------------------------------------------------------------


def test_first_mirror_succeeds():
    """First mirror returns data → used immediately."""
    mirrors = ["https://primary.example.com", "https://fallback.example.com"]

    def _fake_download(mirror, release, arch, **kw):
        if mirror == "https://primary.example.com":
            return {"pkg1": "ok"}

    with patch("pkgeter.get.download_package_db", _fake_download):
        db, used = _try_load_package_db(mirrors, "bookworm", "amd64")
        assert db == {"pkg1": "ok"}
        assert used == "https://primary.example.com"


def test_first_fails_fallback_succeeds():
    """First mirror fails → try next."""
    mirrors = ["https://bad.example.com", "https://good.example.com"]
    attempts = []

    def _fake_download(mirror, release, arch, **kw):
        attempts.append(mirror)
        if mirror == "https://bad.example.com":
            raise httpx.HTTPError("timeout")
        return {"pkg": "ok"}

    with patch("pkgeter.get.download_package_db", _fake_download):
        db, used = _try_load_package_db(mirrors, "bookworm", "amd64")
        assert db == {"pkg": "ok"}
        assert used == "https://good.example.com"
        assert attempts == ["https://bad.example.com", "https://good.example.com"]


def test_all_mirrors_fail():
    """All mirrors fail → returns (None, None)."""
    mirrors = ["https://bad1.example.com", "https://bad2.example.com"]

    def _fake_download(mirror, release, arch, **kw):
        raise httpx.HTTPError("timeout")

    with patch("pkgeter.get.download_package_db", _fake_download):
        db, used = _try_load_package_db(mirrors, "bookworm", "amd64")
        assert db is None
        assert used is None


def test_empty_mirrors_list():
    """No mirrors to try → returns (None, None)."""
    db, used = _try_load_package_db([], "bookworm", "amd64")
    assert db is None
    assert used is None


@pytest.mark.parametrize("exception", [
    httpx.HTTPError("connection refused"),
    httpx.TimeoutException("timed out"),
])
def test_different_http_errors(exception):
    """Various HTTP errors are caught gracefully."""
    def _fake_download(mirror, release, arch, **kw):
        raise exception

    with patch("pkgeter.get.download_package_db", _fake_download):
        db, used = _try_load_package_db(
            ["https://bad.example.com", "https://also-bad.example.com"],
            "bookworm", "amd64",
        )
        assert db is None
        assert used is None


# ---------------------------------------------------------------------------
# @release override in mirror entries
# ---------------------------------------------------------------------------


def test_mirror_at_override_used():
    """Mirror with @release passes effective_release to download_package_db."""
    def _fake_download(mirror, release, arch, **kw):
        if mirror == "https://security.debian.org/debian-security" and release == "bookworm-security":
            return {"pkg": "ok"}
        return None

    with patch("pkgeter.get.download_package_db", _fake_download):
        db, used = _try_load_package_db(
            ["https://security.debian.org/debian-security@bookworm-security"],
            "bookworm",  # global release, should be overridden
            "amd64",
        )
        assert db == {"pkg": "ok"}
        assert used == "https://security.debian.org/debian-security@bookworm-security"


def test_mirror_at_override_fallback():
    """Mirror with @release fails → falls through to next mirror."""
    attempts = []

    def _fake_download(mirror, release, arch, **kw):
        attempts.append((mirror, release))
        if mirror == "https://bad.example.com":
            raise httpx.HTTPError("fail")
        if mirror == "https://security.debian.org/debian-security" and release == "bookworm-security":
            return {"pkg": "ok"}
        return None

    with patch("pkgeter.get.download_package_db", _fake_download):
        db, used = _try_load_package_db([
            "https://bad.example.com",
            "https://security.debian.org/debian-security@bookworm-security",
        ], "bookworm", "amd64")
        assert db == {"pkg": "ok"}
        assert used == "https://security.debian.org/debian-security@bookworm-security"
        assert attempts == [
            ("https://bad.example.com", "bookworm"),
            ("https://security.debian.org/debian-security", "bookworm-security"),
        ]


def test_mirror_at_override_clean_url():
    """parse_mirror_entry extracts the clean URL from @syntax."""
    url, release = parse_mirror_entry(
        "https://security.debian.org/debian-security@bookworm-security"
    )
    assert url == "https://security.debian.org/debian-security"
    assert release == "bookworm-security"
