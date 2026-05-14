"""Tests for RepoConfig dataclass and preset management."""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from pkgeter.models import RepoConfig
from pkgeter.preset import (
    PRESETS,
    get_preset,
    list_presets,
    run_preset,
)


# ---------------------------------------------------------------------------
# RepoConfig dataclass
# ---------------------------------------------------------------------------


class TestRepoConfig:
    def test_defaults(self):
        """Minimal instantiation uses default values."""
        rc = RepoConfig(name="main")
        assert rc.name == "main"
        assert rc.type == "deb"
        assert rc.url == ""
        assert rc.release == ""
        assert rc.components == []
        assert rc.arch == ""

    def test_full_init(self):
        """All fields can be set via constructor."""
        rc = RepoConfig(
            name="updates",
            type="deb",
            url="https://deb.debian.org/debian",
            release="bookworm-updates",
            components=["main", "contrib"],
            arch="amd64",
        )
        assert rc.name == "updates"
        assert rc.type == "deb"
        assert rc.url == "https://deb.debian.org/debian"
        assert rc.release == "bookworm-updates"
        assert rc.components == ["main", "contrib"]
        assert rc.arch == "amd64"

    def test_to_dict(self):
        """Serialization produces expected dict."""
        rc = RepoConfig(
            name="security",
            type="deb",
            url="https://security.debian.org/debian-security",
            release="bookworm-security",
            components=["main"],
            arch="amd64",
        )
        d = rc.to_dict()
        assert d == {
            "name": "security",
            "type": "deb",
            "url": "https://security.debian.org/debian-security",
            "release": "bookworm-security",
            "components": ["main"],
            "arch": "amd64",
        }

    def test_to_dict_rpm(self):
        """RPM repos have type 'rpm' and no components/release."""
        rc = RepoConfig(
            name="baseos",
            type="rpm",
            url="https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os",
        )
        d = rc.to_dict()
        assert d["name"] == "baseos"
        assert d["type"] == "rpm"
        assert d["components"] == []

    def test_from_dict_full(self):
        """Round-trip: dict -> RepoConfig -> dict."""
        original = {
            "name": "main",
            "type": "deb",
            "url": "https://deb.debian.org/debian",
            "release": "bookworm",
            "components": ["main"],
            "arch": "amd64",
        }
        rc = RepoConfig.from_dict(original)
        assert rc.to_dict() == original

    def test_from_dict_minimal(self):
        """Empty dict uses defaults for optional fields."""
        rc = RepoConfig.from_dict({"name": "test"})
        assert rc.name == "test"
        assert rc.type == "deb"
        assert rc.url == ""
        assert rc.release == ""
        assert rc.components == []
        assert rc.arch == ""

    def test_from_dict_missing_keys(self):
        """Partially populated dict uses defaults for missing keys."""
        rc = RepoConfig.from_dict({"name": "foo", "url": "https://example.com"})
        assert rc.name == "foo"
        assert rc.url == "https://example.com"
        assert rc.type == "deb"
        assert rc.release == ""

    def test_components_not_shared(self):
        """Each RepoConfig gets its own component list (no aliasing)."""
        rc1 = RepoConfig(name="a", components=["main"])
        rc2 = RepoConfig(name="b")
        rc1.components.append("contrib")
        assert rc2.components == []


# ---------------------------------------------------------------------------
# PRESETS
# ---------------------------------------------------------------------------


class TestPresetsDict:
    def test_expected_keys(self):
        """PRESETS contains the three required presets."""
        assert "debian-bookworm" in PRESETS
        assert "debian-bullseye" in PRESETS
        assert "centos-9" in PRESETS

    def test_expected_presets_exist(self):
        """The three required presets are defined."""
        assert "debian-bookworm" in PRESETS
        assert "debian-bullseye" in PRESETS
        assert "centos-9" in PRESETS

    def test_debian_bookworm_structure(self):
        """debian-bookworm preset has correct structure."""
        preset = PRESETS["debian-bookworm"]
        assert preset["backend"] == "debian"
        assert preset["arch"] == "amd64"
        repos = preset["repos"]
        assert len(repos) == 3

        # Check individual repos
        main, sec, upd = repos
        assert main.name == "main"
        assert main.type == "deb"
        assert "deb.debian.org/debian" in main.url
        assert main.release == "bookworm"
        assert main.components == ["main"]

        assert sec.name == "security"
        assert sec.type == "deb"
        assert "security.debian.org" in sec.url
        assert sec.release == "bookworm-security"

        assert upd.name == "updates"
        assert upd.type == "deb"
        assert "deb.debian.org/debian" in upd.url
        assert upd.release == "bookworm-updates"

    def test_debian_bullseye_structure(self):
        """debian-bullseye preset mirrors bookworm with bullseye releases."""
        preset = PRESETS["debian-bullseye"]
        assert preset["backend"] == "debian"
        assert preset["arch"] == "amd64"
        repos = preset["repos"]
        assert len(repos) == 3

        main, sec, upd = repos
        assert main.release == "bullseye"
        assert sec.release == "bullseye-security"
        assert upd.release == "bullseye-updates"

    def test_centos_9_structure(self):
        """centos-9 preset has three rpm repos."""
        preset = PRESETS["centos-9"]
        assert preset["backend"] == "rpm"
        assert preset["arch"] == "x86_64"
        repos = preset["repos"]
        assert len(repos) == 3

        baseos, appstream, epel = repos
        assert baseos.name == "baseos"
        assert baseos.type == "rpm"
        assert "BaseOS" in baseos.url
        assert baseos.components == []

        assert appstream.name == "appstream"
        assert appstream.type == "rpm"
        assert "AppStream" in appstream.url

        assert epel.name == "epel"
        assert epel.type == "rpm"
        assert "fedoraproject" in epel.url


# ---------------------------------------------------------------------------
# list_presets
# ---------------------------------------------------------------------------


class TestListPresets:
    def test_returns_sorted(self):
        """list_presets returns preset names in alphabetical order."""
        names = list_presets()
        assert names == sorted(names)

    def test_includes_all(self):
        """All three presets appear in the listing."""
        names = list_presets()
        assert "centos-9" in names
        assert "debian-bookworm" in names
        assert "debian-bullseye" in names


# ---------------------------------------------------------------------------
# get_preset
# ---------------------------------------------------------------------------


class TestGetPreset:
    def test_known_preset(self):
        """get_preset returns the correct dict for a known name."""
        preset = get_preset("debian-bookworm")
        assert preset["backend"] == "debian"

    def test_unknown_preset_returns_none(self):
        """get_preset returns None for unknown preset names."""
        assert get_preset("foobar") is None


# ---------------------------------------------------------------------------
# run_preset
# ---------------------------------------------------------------------------


class TestRunPreset:
    def test_list_action(self, capsys: pytest.CaptureFixture[str]):
        """run_preset(['list']) prints available presets."""
        run_preset(["list"])
        captured = capsys.readouterr()
        assert "Available presets:" in captured.out
        assert "debian-bookworm" in captured.out
        assert "centos-9" in captured.out

    def test_apply_known_preset(self, capsys: pytest.CaptureFixture[str]):
        """run_preset(['apply', 'debian-bookworm']) calls Config methods."""
        with patch("pkgeter.preset.Config") as MockConfig:
            instance = MockConfig.return_value

            run_preset(["apply", "debian-bookworm"])

            instance.set_backend.assert_called_once_with("debian")
            assert instance.set_repos.call_count == 1
            repos_arg = instance.set_repos.call_args[0][0]
            assert len(repos_arg) == 3
            assert repos_arg[0]["name"] == "main"
            assert repos_arg[0]["type"] == "deb"

            instance.save.assert_called_once()

            captured = capsys.readouterr()
            assert "Applied preset" in captured.out
            assert "debian-bookworm" in captured.out

    def test_apply_centos_preset(self, capsys: pytest.CaptureFixture[str]):
        """run_preset(['apply', 'centos-9']) applies rpm backend."""
        with patch("pkgeter.preset.Config") as MockConfig:
            instance = MockConfig.return_value

            run_preset(["apply", "centos-9"])

            instance.set_backend.assert_called_once_with("rpm")
            repos_arg = instance.set_repos.call_args[0][0]
            assert repos_arg[0]["type"] == "rpm"
            instance.save.assert_called_once()

    def test_apply_unknown_preset(self):
        """run_preset with unknown name prints to stderr and exits."""
        with patch.object(sys, "exit") as mock_exit:
            run_preset(["apply", "nonexistent"])
            mock_exit.assert_called_once_with(1)

    def test_apply_unknown_preset_stderr(self, capsys: pytest.CaptureFixture[str]):
        """run_preset with unknown name prints error message to stderr."""
        with patch.object(sys, "exit"):
            run_preset(["apply", "foobar"])
            captured = capsys.readouterr()
            assert "Error:" in captured.err
            assert "foobar" in captured.err
