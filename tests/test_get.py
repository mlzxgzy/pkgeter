"""Tests for the get subcommand."""

from __future__ import annotations

import argparse

from pkgeter.get import run_get


def test_get_parser_packages():
    """Verify that -p accepts multiple package names."""
    parser = argparse.ArgumentParser(prog="pkgeter get")
    parser.add_argument("--packages", "-p", nargs="+", required=True)
    args = parser.parse_args(["-p", "nginx", "openssl"])
    assert args.packages == ["nginx", "openssl"]


def test_run_get_missing_packages():
    """run_get returns 1 when --packages is missing."""
    rc = run_get(["--distro", "debian-bookworm"])
    assert rc == 1


def test_run_get_unknown_distro():
    """run_get returns 1 for an unknown distro."""
    rc = run_get(["-p", "nginx", "--distro", "nonexistent"])
    assert rc == 1
