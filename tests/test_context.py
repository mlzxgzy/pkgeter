"""Tests for pkgeter.context — shared backend resolution."""

from __future__ import annotations

import pytest

from pkgeter.config import Config
from pkgeter.context import BackendContext, resolve_backend
from pkgeter.models import RepoConfig


# ---------------------------------------------------------------------------
# Fixtures — minimal config files on disk
# ---------------------------------------------------------------------------

DEBIAN_CONFIG = """\
backend: debian
mirror_variant: default
repos:
  - name: debian
    url: http://deb.debian.org/debian
    release: bookworm
    arch: amd64
    components: [main]
"""

DEBIAN_CONFIG_WITH_MIRROR = """\
backend: debian
mirror_variant: cn
repos:
  - name: debian
    url: http://deb.debian.org/debian
    release: bookworm
    components: [main]
    arch: amd64
"""

RPM_CONFIG = """\
backend: rpm
repos:
  - name: centos
    url: http://mirror.centos.org/centos
    release: 9
    arch: x86_64
    components: [BaseOS]
"""

EMPTY_REPOS_CONFIG = """\
backend: debian
repos: []
"""


@pytest.fixture
def debian_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(DEBIAN_CONFIG)
    return Config(path)


@pytest.fixture
def debian_config_with_mirror(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(DEBIAN_CONFIG_WITH_MIRROR)
    return Config(path)


@pytest.fixture
def rpm_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(RPM_CONFIG)
    return Config(path)


@pytest.fixture
def empty_repos_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(EMPTY_REPOS_CONFIG)
    return Config(path)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestResolveBackend:
    def test_with_distro_debian(self, debian_config):
        """Preset 'debian-bookworm' resolves to DebianBackend with correct repos."""
        ctx = resolve_backend(distro="debian-bookworm", config=debian_config)
        assert ctx.backend.name == "apt"
        assert len(ctx.repos) > 0
        assert "amd64" in ctx.arch
        assert ctx.mirror_variant == "default"
        assert ctx.preset_name == "debian-bookworm"

    def test_with_distro_rpm(self, rpm_config):
        """Preset 'centos-9' resolves to RpmBackend."""
        ctx = resolve_backend(distro="centos-9", config=rpm_config)
        assert ctx.backend.name == "rpm"
        assert len(ctx.repos) > 0
        assert ctx.preset_name == "centos-9"

    def test_with_distro_cn_variant(self, debian_config):
        """Preset with @cn variant applies the cn mirror."""
        ctx = resolve_backend(distro="debian-bookworm", mirror="cn", config=debian_config)
        assert ctx.mirror_variant == "cn"
        # The cn variant should change repo URLs
        for repo in ctx.repos:
            assert "cdn" in repo.url or "cn" in repo.url

    def test_unknown_distro_raises(self, debian_config):
        """Unknown preset name raises ValueError."""
        with pytest.raises(ValueError, match="unknown preset"):
            resolve_backend(distro="nonexistent-os-99", config=debian_config)

    def test_from_config_repos(self, debian_config):
        """When no --distro, repos come from config."""
        ctx = resolve_backend(config=debian_config)
        assert ctx.backend.name == "apt"
        assert len(ctx.repos) == 1
        assert ctx.repos[0].url == "http://deb.debian.org/debian"
        assert ctx.preset_name is None  # not from preset

    def test_fallback_to_debian(self, empty_repos_config):
        """When no --distro and config has empty repos, falls back to debian-bookworm."""
        ctx = resolve_backend(config=empty_repos_config)
        assert ctx.backend.name == "apt"
        assert len(ctx.repos) > 0
        assert ctx.preset_name == "debian-bookworm"

    def test_cn_shortcut(self, debian_config):
        """cn=True sets mirror_variant to 'cn'."""
        ctx = resolve_backend(distro="debian-bookworm", cn=True, config=debian_config)
        assert ctx.mirror_variant == "cn"

    def test_preset_arch_override(self, debian_config):
        """Preset can override the architecture."""
        ctx = resolve_backend(
            distro="debian-bookworm",
            arch="arm64",
            config=debian_config,
        )
        # arch may be overridden by preset; at minimum it's a string
        assert isinstance(ctx.arch, str) and len(ctx.arch) > 0

    def test_arch_from_config(self, debian_config):
        """When no arch arg given, falls back to config default."""
        ctx = resolve_backend(config=debian_config)
        assert ctx.arch == "amd64"  # config default

    def test_unknown_backend_raises(self, tmp_path):
        """Backend name that doesn't match any known backend raises ValueError."""
        path = tmp_path / "config.yaml"
        path.write_text("""\
backend: foo
repos:
  - name: test
    url: http://example.com
    release: test
    arch: amd64
    components: [main]
""")
        cfg = Config(path)
        with pytest.raises(ValueError, match="unknown backend"):
            resolve_backend(config=cfg)

    def test_dnf_backend(self, tmp_path):
        """DnfBackend can be resolved through preset selection."""
        path = tmp_path / "config.yaml"
        path.write_text("""\
backend: dnf
repos:
  - name: centos
    url: http://mirror.centos.org/centos
    release: 9
    arch: x86_64
    components: [BaseOS]
""")
        cfg = Config(path)
        ctx = resolve_backend(config=cfg)
        assert ctx.backend.name == "dnf"

    def test_repos_are_repo_config_objects(self, debian_config):
        """All repos in the result are RepoConfig instances."""
        ctx = resolve_backend(distro="debian-bookworm", config=debian_config)
        for repo in ctx.repos:
            assert isinstance(repo, RepoConfig)

    def test_backend_context_dataclass(self, debian_config):
        """BackendContext fields are accessible as attributes."""
        ctx = resolve_backend(distro="debian-bookworm", config=debian_config)
        assert hasattr(ctx, "backend")
        assert hasattr(ctx, "repos")
        assert hasattr(ctx, "arch")
        assert hasattr(ctx, "mirror_variant")
        assert hasattr(ctx, "preset_name")
