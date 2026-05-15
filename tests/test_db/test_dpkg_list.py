"""Tests for dpkg -l parser."""

from pathlib import Path

from pkgeter.db.dpkg_list import parse_dpkg_list, parse_dpkg_list_file


DATA_DIR = Path(__file__).parent.parent / "data"


def test_parse_dpkg_list_sample():
    fixture = DATA_DIR / "sample_dpkg_list.txt"
    pkgs = parse_dpkg_list(fixture.read_text())
    assert "adduser" in pkgs
    assert "apt" in pkgs
    assert "libc6" in pkgs
    assert "libssl3" in pkgs
    assert "zlib1g" in pkgs
    assert len(pkgs) >= 5


def test_parse_dpkg_list_hi_status():
    """Packages with 'hi' (hold) status should also be captured."""
    text = "hi  held-pkg 1.0 amd64 a held package"
    pkgs = parse_dpkg_list(text)
    assert "held-pkg" in pkgs


def test_parse_dpkg_list_iU_status():
    """Packages with 'iU' (unpacked) status should be captured."""
    text = "iU  unpacked-pkg 1.0 amd64 an unpacked package"
    pkgs = parse_dpkg_list(text)
    assert "unpacked-pkg" in pkgs


def test_parse_dpkg_list_rc_excluded():
    """Packages with 'rc' (removed-but-config) status should NOT be included."""
    text = "rc  removed-pkg 1.0 amd64 a removed package"
    pkgs = parse_dpkg_list(text)
    assert "removed-pkg" not in pkgs


def test_parse_dpkg_list_empty():
    assert parse_dpkg_list("") == set()


def test_parse_dpkg_list_headers_only():
    text = """\
Desired=Unknown/Install/Remove/Purge/Hold
| Status=Not/Inst/Conf-files/Unpacked/halF-conf/Half-inst/trig-aWait/Trig-pend
|/ Err?=(none)/Reinst-required (Status,Err: uppercase=bad)
||/ Name                              Version                   Architecture Description
+++-=================================-=========================-============-==========================================
"""
    assert parse_dpkg_list(text) == set()


def test_parse_dpkg_list_line_with_few_parts():
    """Short status lines (status + name only) should not crash."""
    text = "ii  short-pkg"
    pkgs = parse_dpkg_list(text)
    assert "short-pkg" in pkgs


def test_parse_dpkg_list_mixed_newlines():
    """Empty lines mixed with status lines are handled."""
    text = "\n\nii  pkg-a 1.0 amd64 desc\n\nii  pkg-b 2.0 amd64 desc\n"
    pkgs = parse_dpkg_list(text)
    assert "pkg-a" in pkgs
    assert "pkg-b" in pkgs
    assert len(pkgs) == 2


def test_parse_dpkg_list_file(tmp_path: Path):
    """parse_dpkg_list_file reads and parses a file on disk."""
    content = (
        "Desired=Unknown/Install/Remove/Purge/Hold\n"
        "||/ Name\n"
        "+++-============\n"
        "ii  file-pkg 1.0 amd64 a file based package\n"
    )
    path = tmp_path / "dpkg-list.txt"
    path.write_text(content, encoding="utf-8")

    pkgs = parse_dpkg_list_file(path)
    assert "file-pkg" in pkgs
    assert len(pkgs) == 1
