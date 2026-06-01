"""Tests for RepoConfig dataclass and preset management."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from pkgeter.models import RepoConfig
from pkgeter.preset import (
    _apply_mirror_variant,
    _load_presets,
    all_preset_names,
    complete_preset_name,
    get_preset,
    list_presets,
    list_systems,
    reload_presets,
    run_preset,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_PRESETS_YAML = """\
debian-bookworm:
  system: debian
  backend: apt
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
  mirrors:
    - name: cn
      provider: ustc
      urls:
        main: https://mirrors.ustc.edu.cn/debian
        security: https://mirrors.ustc.edu.cn/debian-security
        updates: https://mirrors.ustc.edu.cn/debian

debian-bullseye:
  system: debian
  backend: apt
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
  mirrors:
    - name: cn
      provider: ustc
      urls:
        main: https://mirrors.ustc.edu.cn/debian
        security: https://mirrors.ustc.edu.cn/debian-security
        updates: https://mirrors.ustc.edu.cn/debian

centos-9:
  system: centos
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
        presets = _load_presets()
        assert "debian-bookworm" in presets
        assert "debian-bullseye" in presets
        assert "centos-9" in presets

    def test_debian_bookworm_structure(self, preset_file):
        preset = get_preset("debian-bookworm")
        assert preset is not None
        assert preset["backend"] == "apt"
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
        assert "9-stream" in repos[0].url

    def test_mirror_variant(self, preset_file):
        preset = get_preset("debian-bookworm@cn")
        assert preset is not None
        assert "mirrors.ustc.edu.cn" in preset["repos"][0].url
        assert preset["repos"][0].release == "bookworm"

    def test_mirror_variant_via_parameter(self, preset_file):
        preset = get_preset("debian-bookworm", mirror_variant="cn")
        assert preset is not None
        assert "mirrors.ustc.edu.cn" in preset["repos"][0].url

    def test_at_variant_overrides_parameter(self, preset_file):
        preset = get_preset("debian-bookworm@cn", mirror_variant="default")
        assert "mirrors.ustc.edu.cn" in preset["repos"][0].url

    def test_unknown_variant_falls_back(self, preset_file, capsys):
        preset = get_preset("debian-bookworm@jp")
        assert preset is not None
        assert "deb.debian.org" in preset["repos"][0].url
        assert "Warning" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# list_presets
# ---------------------------------------------------------------------------


class TestListPresets:
    def test_returns_system_info(self, preset_file):
        result = list_presets()
        assert "debian" in result
        assert "centos" in result

    def test_debian_versions(self, preset_file):
        info = list_presets()["debian"]
        assert "bookworm" in info["versions"]
        assert "bullseye" in info["versions"]

    def test_debian_variants(self, preset_file):
        info = list_presets()["debian"]
        assert "cn" in info["variants"]

    def test_system_without_mirrors_has_empty_variants(self, preset_file):
        info = list_presets()["centos"]
        assert info["variants"] == []


class TestListSystems:
    def test_returns_sorted(self, preset_file):
        systems = list_systems()
        assert systems == sorted(systems)

    def test_includes_all(self, preset_file):
        systems = list_systems()
        assert "debian" in systems
        assert "centos" in systems


class TestAllPresetNames:
    def test_includes_base_names(self, preset_file):
        names = all_preset_names()
        assert "debian-bookworm" in names
        assert "debian-bullseye" in names
        assert "centos-9" in names

    def test_includes_variant_names(self, preset_file):
        names = all_preset_names()
        assert "debian-bookworm@cn" in names
        assert "debian-bullseye@cn" in names

    def test_sorted(self, preset_file):
        names = all_preset_names()
        assert names == sorted(names)


class TestCompletePresetName:
    def test_system_prefix(self, preset_file):
        result = complete_preset_name("deb")
        assert "debian-" in result

    def test_version_completion(self, preset_file):
        result = complete_preset_name("debian-")
        assert "debian-bookworm" in result
        assert "debian-bullseye" in result

    def test_variant_completion(self, preset_file):
        result = complete_preset_name("debian-bookworm")
        assert "debian-bookworm" in result
        assert "debian-bookworm@cn" in result

    def test_no_match(self, preset_file):
        result = complete_preset_name("nonexistent")
        assert result == []


# ---------------------------------------------------------------------------
# get_preset
# ---------------------------------------------------------------------------


class TestGetPreset:
    def test_known_preset(self, preset_file):
        assert get_preset("debian-bookworm")["backend"] == "apt"

    def test_unknown_preset_returns_none(self, preset_file):
        assert get_preset("foobar") is None

    def test_default_variant_returns_base_repos(self, preset_file):
        preset = get_preset("debian-bookworm")
        assert "deb.debian.org" in preset["repos"][0].url


# ---------------------------------------------------------------------------
# run_preset
# ---------------------------------------------------------------------------


class TestRunPreset:
    def test_list_action(self, preset_file, capsys: pytest.CaptureFixture[str]):
        run_preset(["list"])
        captured = capsys.readouterr()
        assert "Available presets" in captured.out
        assert "debian:" in captured.out
        assert "bookworm" in captured.out
        assert "centos:" in captured.out
        assert "@cn" in captured.out

    def test_apply_known_preset(self, preset_file, capsys: pytest.CaptureFixture[str]):
        with patch("pkgeter.preset.Config") as MockConfig:
            instance = MockConfig.return_value
            run_preset(["apply", "debian-bookworm"])
            instance.set_backend.assert_called_once_with("apt")
            repos_arg = instance.set_repos.call_args[0][0]
            assert len(repos_arg) == 3
            assert repos_arg[0]["name"] == "main"
            instance.set_mirror_variant.assert_called_once_with("default")
            instance.save.assert_called_once()
            captured = capsys.readouterr()
            assert "Applied preset" in captured.out

    def test_apply_with_variant(self, preset_file, capsys: pytest.CaptureFixture[str]):
        with patch("pkgeter.preset.Config") as MockConfig:
            instance = MockConfig.return_value
            run_preset(["apply", "debian-bookworm@cn"])
            instance.set_mirror_variant.assert_called_once_with("cn")
            repos_arg = instance.set_repos.call_args[0][0]
            assert "mirrors.ustc.edu.cn" in repos_arg[0]["url"]

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
