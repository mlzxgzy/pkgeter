"""Tests for dpkg -l parser."""

from pathlib import Path

from pkgeter.db.dpkg_list import parse_dpkg_list


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
