"""Tests for RepoConfig dataclass and preset management."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pkgeter.models import RepoConfig
from pkgeter.preset import (
    _apply_mirror_variant,
    _expand_system,
    _substitute_version,
    get_preset,
    list_presets,
    reload_presets,
    run_preset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_PRESETS_YAML = """\
debian-bookworm:
  backend: debian
  arch: amd64
  repos:
    - name: main
      type: deb
      url: https://deb.debian.org/debian
      release: bookworm
      components: [main]
    - name: security
      type: deb
      url: https://security.debian.org/debian-security
      release: bookworm-security
      components: [main]
    - name: updates
      type: deb
      url: https://deb.debian.org/debian
      release: bookworm-updates
      components: [main]
debian-bullseye:
  backend: debian
  arch: amd64
  repos:
    - name: main
      type: deb
      url: https://deb.debian.org/debian
      release: bullseye
      components: [main]
    - name: security
      type: deb
      url: https://security.debian.org/debian-security
      release: bullseye-security
      components: [main]
    - name: updates
      type: deb
      url: https://deb.debian.org/debian
      release: bullseye-updates
      components: [main]
centos-9:
  backend: rpm
  arch: x86_64
  repos:
    - name: baseos
      type: rpm
      url: https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os
    - name: appstream
      type: rpm
      url: https://mirror.stream.centos.org/9-stream/AppStream/x86_64/os
    - name: epel
      type: rpm
      url: https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64
"""


@pytest.fixture
def preset_file(tmp_path: Path):
    """Fixture: write sample presets to a temp file and mock the path."""
    f = tmp_path / "presets.yaml"
    f.write_text(SAMPLE_PRESETS_YAML, encoding="utf-8")

    with patch("pkgeter.preset._USER_PRESETS", f):
        reload_presets()  # clear cache so next load reads from temp file
        yield


# ---------------------------------------------------------------------------
# RepoConfig dataclass
# ---------------------------------------------------------------------------


class TestRepoConfig:
    def test_defaults(self):
        rc = RepoConfig(name="main")
        assert rc.type == "deb"
        assert rc.url == ""
        assert rc.components == []

    def test_full_init(self):
        rc = RepoConfig(
            name="updates", type="deb",
            url="https://deb.debian.org/debian", release="bookworm-updates",
            components=["main", "contrib"], arch="amd64",
        )
        assert rc.release == "bookworm-updates"
        assert rc.components == ["main", "contrib"]

    def test_to_dict(self):
        rc = RepoConfig(name="security", type="deb",
                        url="https://security.debian.org/debian-security",
                        release="bookworm-security", components=["main"])
        d = rc.to_dict()
        assert d["name"] == "security"
        assert d["release"] == "bookworm-security"

    def test_to_dict_rpm(self):
        rc = RepoConfig(name="baseos", type="rpm",
                        url="https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os")
        d = rc.to_dict()
        assert d["type"] == "rpm"
        assert d["components"] == []

    def test_from_dict_full(self):
        original = {"name": "main", "type": "deb", "url": "https://deb.debian.org/debian",
                    "release": "bookworm", "components": ["main"], "arch": "amd64"}
        assert RepoConfig.from_dict(original).to_dict() == original

    def test_from_dict_minimal(self):
        rc = RepoConfig.from_dict({"name": "test"})
        assert rc.name == "test"
        assert rc.type == "deb"
        assert rc.url == ""

    def test_from_dict_missing_keys(self):
        rc = RepoConfig.from_dict({"name": "foo", "url": "https://example.com"})
        assert rc.release == ""

    def test_components_not_shared(self):
        rc1 = RepoConfig(name="a", components=["main"])
        rc2 = RepoConfig(name="b")
        rc1.components.append("contrib")
        assert rc2.components == []


# ---------------------------------------------------------------------------
# Presets loaded from YAML
# ---------------------------------------------------------------------------


class TestPresetsContent:
    def test_expected_presets_exist(self, preset_file):
        """The three required presets are defined."""
        names = list_presets()
        assert "debian-bookworm" in names
        assert "debian-bullseye" in names
        assert "centos-9" in names

    def test_debian_bookworm_structure(self, preset_file):
        preset = get_preset("debian-bookworm")
        assert preset is not None
        assert preset["backend"] == "debian"
        assert preset["arch"] == "amd64"
        repos = preset["repos"]
        assert len(repos) == 3
        main, sec, upd = repos
        assert main.name == "main"
        assert main.type == "deb"
        assert "deb.debian.org" in main.url
        assert main.release == "bookworm"
        assert sec.release == "bookworm-security"
        assert upd.release == "bookworm-updates"

    def test_debian_bullseye_structure(self, preset_file):
        preset = get_preset("debian-bullseye")
        assert preset is not None
        repos = preset["repos"]
        assert repos[0].release == "bullseye"
        assert repos[1].release == "bullseye-security"

    def test_centos_9_structure(self, preset_file):
        preset = get_preset("centos-9")
        assert preset is not None
        assert preset["backend"] == "rpm"
        assert preset["arch"] == "x86_64"
        repos = preset["repos"]
        assert len(repos) == 3
        assert repos[0].name == "baseos"
        assert repos[0].type == "rpm"


# ---------------------------------------------------------------------------
# list_presets
# ---------------------------------------------------------------------------


class TestListPresets:
    def test_returns_sorted(self, preset_file):
        names = list_presets()
        assert names == sorted(names)

    def test_includes_all(self, preset_file):
        names = list_presets()
        assert "centos-9" in names
        assert "debian-bookworm" in names
        assert "debian-bullseye" in names


# ---------------------------------------------------------------------------
# get_preset
# ---------------------------------------------------------------------------


class TestGetPreset:
    def test_known_preset(self, preset_file):
        assert get_preset("debian-bookworm")["backend"] == "debian"

    def test_unknown_preset_returns_none(self, preset_file):
        assert get_preset("foobar") is None


# ---------------------------------------------------------------------------
# run_preset
# ---------------------------------------------------------------------------


class TestRunPreset:
    def test_list_action(self, preset_file, capsys: pytest.CaptureFixture[str]):
        run_preset(["list"])
        captured = capsys.readouterr()
        assert "Available presets" in captured.out
        assert "debian-bookworm" in captured.out
        assert "centos-9" in captured.out

    def test_apply_known_preset(self, preset_file, capsys: pytest.CaptureFixture[str]):
        with patch("pkgeter.preset.Config") as MockConfig:
            instance = MockConfig.return_value
            run_preset(["apply", "debian-bookworm"])
            instance.set_backend.assert_called_once_with("debian")
            repos_arg = instance.set_repos.call_args[0][0]
            assert len(repos_arg) == 3
            assert repos_arg[0]["name"] == "main"
            instance.save.assert_called_once()
            captured = capsys.readouterr()
            assert "Applied preset" in captured.out

    def test_apply_centos_preset(self, preset_file, capsys: pytest.CaptureFixture[str]):
        with patch("pkgeter.preset.Config") as MockConfig:
            instance = MockConfig.return_value
            run_preset(["apply", "centos-9"])
            instance.set_backend.assert_called_once_with("rpm")
            repos_arg = instance.set_repos.call_args[0][0]
            assert repos_arg[0]["type"] == "rpm"

    def test_apply_unknown_preset(self, preset_file):
        with patch.object(sys, "exit") as mock_exit:
            run_preset(["apply", "nonexistent"])
            mock_exit.assert_called_once_with(1)

    def test_apply_unknown_preset_stderr(self, preset_file, capsys: pytest.CaptureFixture[str]):
        with patch.object(sys, "exit"):
            run_preset(["apply", "foobar"])
            captured = capsys.readouterr()
            assert "Error:" in captured.err
            assert "foobar" in captured.err


# ---------------------------------------------------------------------------
# _substitute_version
# ---------------------------------------------------------------------------


class TestSubstituteVersion:
    def test_replaces_version_in_url(self):
        repos = [{"name": "main", "url": "https://example.com/{version}/repo", "release": "{version}"}]
        result = _substitute_version(repos, "bookworm")
        assert result[0]["url"] == "https://example.com/bookworm/repo"
        assert result[0]["release"] == "bookworm"

    def test_preserves_non_string_values(self):
        repos = [{"name": "main", "components": ["main", "contrib"], "url": "https://x/{version}"}]
        result = _substitute_version(repos, "trixie")
        assert result[0]["components"] == ["main", "contrib"]
        assert result[0]["url"] == "https://x/trixie"

    def test_does_not_mutate_input(self):
        repos = [{"name": "main", "url": "https://x/{version}"}]
        _substitute_version(repos, "bookworm")
        assert repos[0]["url"] == "https://x/{version}"


# ---------------------------------------------------------------------------
# _expand_system
# ---------------------------------------------------------------------------


class TestExpandSystem:
    def test_template_mode_expands_versions(self):
        data = {
            "backend": "apt",
            "arch": "amd64",
            "versions": ["bookworm", "bullseye"],
            "repos": [
                {"name": "main", "type": "deb", "url": "https://deb.debian.org/debian",
                 "release": "{version}", "components": ["main"]},
            ],
            "mirrors": {
                "cn": {"main": "https://mirrors.ustc.edu.cn/debian"},
            },
        }
        result = _expand_system("debian", data)
        assert "debian-bookworm" in result
        assert "debian-bullseye" in result
        bw = result["debian-bookworm"]
        assert bw["backend"] == "apt"
        assert bw["repos"][0].release == "bookworm"
        assert bw["repos"][0].url == "https://deb.debian.org/debian"
        assert bw["mirrors"] == {"cn": {"main": "https://mirrors.ustc.edu.cn/debian"}}

    def test_template_mode_substitutes_mirror_urls(self):
        data = {
            "backend": "rpm",
            "arch": "x86_64",
            "versions": ["9"],
            "repos": [
                {"name": "baseos", "type": "rpm",
                 "url": "https://mirror.centos.org/{version}-stream/BaseOS/x86_64/os"},
            ],
            "mirrors": {
                "cn": {"baseos": "https://mirrors.ustc.edu.cn/centos/{version}-stream/BaseOS/x86_64/os"},
            },
        }
        result = _expand_system("centos", data)
        assert result["centos-9"]["mirrors"]["cn"]["baseos"] == \
            "https://mirrors.ustc.edu.cn/centos/9-stream/BaseOS/x86_64/os"

    def test_explicit_mode_reads_version_repos(self):
        data = {
            "backend": "apt",
            "arch": "amd64",
            "versions": {
                "8": {
                    "repos": [
                        {"name": "main", "type": "deb", "url": "https://deb.debian.org/debian",
                         "release": "bookworm", "components": ["main"]},
                        {"name": "pve", "type": "deb", "url": "https://download.proxmox.com/debian/pve",
                         "release": "bookworm", "components": ["pve-no-subscription"]},
                    ],
                    "mirrors": {
                        "cn": {
                            "main": "https://mirrors.ustc.edu.cn/debian",
                            "pve": "https://mirrors.ustc.edu.cn/proxmox/debian/pve",
                        },
                    },
                },
            },
        }
        result = _expand_system("pve", data)
        assert "pve-8" in result
        p = result["pve-8"]
        assert len(p["repos"]) == 2
        assert p["repos"][1].name == "pve"
        assert p["mirrors"]["cn"]["pve"] == "https://mirrors.ustc.edu.cn/proxmox/debian/pve"

    def test_explicit_mode_inherits_system_mirrors(self):
        data = {
            "backend": "apt",
            "arch": "amd64",
            "mirrors": {"cn": {"main": "https://cn.example.com"}},
            "versions": {
                "1": {
                    "repos": [{"name": "main", "type": "deb", "url": "https://example.com",
                               "release": "v1", "components": ["main"]}],
                },
            },
        }
        result = _expand_system("test", data)
        assert result["test-1"]["mirrors"] == {"cn": {"main": "https://cn.example.com"}}

    def test_explicit_mode_no_mirrors(self):
        data = {
            "backend": "rpm",
            "arch": "x86_64",
            "versions": {
                "V10": {
                    "repos": [{"name": "base", "type": "rpm",
                               "url": "https://update.cs2c.com.cn/base/x86_64"}],
                },
            },
        }
        result = _expand_system("kylin", data)
        assert result["kylin-V10"]["mirrors"] == {}


# ---------------------------------------------------------------------------
# _apply_mirror_variant
# ---------------------------------------------------------------------------


class TestApplyMirrorVariant:
    def test_replaces_matching_urls(self):
        repos = [
            RepoConfig(name="main", type="deb", url="https://deb.debian.org/debian",
                       release="bookworm", components=["main"]),
            RepoConfig(name="security", type="deb", url="https://security.debian.org/debian-security",
                       release="bookworm-security", components=["main"]),
        ]
        url_map = {
            "main": "https://mirrors.ustc.edu.cn/debian",
            "security": "https://mirrors.ustc.edu.cn/debian-security",
        }
        result = _apply_mirror_variant(repos, url_map)
        assert result[0].url == "https://mirrors.ustc.edu.cn/debian"
        assert result[1].url == "https://mirrors.ustc.edu.cn/debian-security"

    def test_preserves_other_fields(self):
        repos = [
            RepoConfig(name="main", type="deb", url="https://deb.debian.org/debian",
                       release="bookworm", components=["main"], arch="amd64"),
        ]
        url_map = {"main": "https://mirrors.ustc.edu.cn/debian"}
        result = _apply_mirror_variant(repos, url_map)
        assert result[0].release == "bookworm"
        assert result[0].type == "deb"
        assert result[0].components == ["main"]
        assert result[0].arch == "amd64"

    def test_skips_repos_not_in_map(self):
        repos = [
            RepoConfig(name="main", url="https://example.com"),
            RepoConfig(name="extra", url="https://extra.example.com"),
        ]
        url_map = {"main": "https://mirror.example.com"}
        result = _apply_mirror_variant(repos, url_map)
        assert result[0].url == "https://mirror.example.com"
        assert result[1].url == "https://extra.example.com"

    def test_does_not_mutate_input(self):
        repos = [RepoConfig(name="main", url="https://example.com")]
        url_map = {"main": "https://mirror.example.com"}
        _apply_mirror_variant(repos, url_map)
        assert repos[0].url == "https://example.com"
