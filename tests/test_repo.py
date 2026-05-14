"""Tests for the repo subcommand."""

from __future__ import annotations

from pkgeter.repo import build_repo_parser


def test_repo_list():
    args = build_repo_parser().parse_args(["list"])
    assert args.action == "list"


def test_repo_add():
    args = build_repo_parser().parse_args([
        "add", "--name", "test", "--type", "deb", "--url", "https://example.com",
    ])
    assert args.action == "add"
    assert args.name == "test"
    assert args.type == "deb"
    assert args.url == "https://example.com"


def test_repo_remove():
    args = build_repo_parser().parse_args(["remove", "myrepo"])
    assert args.action == "remove"
    assert args.name == "myrepo"


def test_repo_add_with_all_options():
    args = build_repo_parser().parse_args([
        "add", "--name", "foo", "--type", "rpm", "--url", "https://rpm.example.com",
        "--release", "9", "--components", "main,extras", "--arch", "x86_64",
    ])
    assert args.name == "foo"
    assert args.type == "rpm"
    assert args.url == "https://rpm.example.com"
    assert args.release == "9"
    assert args.components == "main,extras"
    assert args.arch == "x86_64"
