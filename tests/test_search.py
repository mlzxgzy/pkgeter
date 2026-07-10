"""Tests for search subcommand output grouping."""

from __future__ import annotations

from types import SimpleNamespace

from pkgeter.models import PackageInfo, RepoConfig
from pkgeter.search import run_search


class _FakeBackend:
    def download_package_db(self, repos, arch, force_update=False):
        repo = repos[0]
        if repo.name == "main":
            return {
                "bash": PackageInfo(
                    package="bash",
                    version="1.0",
                    arch="amd64",
                    description="shell",
                    base_url=repo.url,
                )
            }
        if repo.name == "ceph-squid":
            return {
                "ceph-common": PackageInfo(
                    package="ceph-common",
                    version="2.0",
                    arch="amd64",
                    description="ceph package",
                    base_url=repo.url,
                )
            }
        return {}


class _FakeCache:
    def search(self, query, source_ids=None, search_desc=False):
        if source_ids == ["deb:ceph.example:bookworm:amd64:no-subscription"]:
            return [
                PackageInfo(
                    package="ceph-common",
                    version="2.0",
                    arch="amd64",
                    description="ceph package",
                    base_url="https://ceph.example",
                )
            ]
        return []


def test_run_search_uses_repo_scoped_cache_results(monkeypatch, capsys):
    repos = [
        RepoConfig(
            name="main",
            type="deb",
            url="https://main.example",
            release="bookworm",
            components=["main"],
            arch="amd64",
        ),
        RepoConfig(
            name="ceph-squid",
            type="deb",
            url="https://ceph.example",
            release="bookworm",
            components=["no-subscription"],
            arch="amd64",
        ),
    ]

    ctx = SimpleNamespace(
        backend=_FakeBackend(),
        repos=repos,
        arch="amd64",
        preset_name="pve-8@cn",
    )

    monkeypatch.setattr("pkgeter.search.resolve_backend", lambda **kwargs: ctx)
    monkeypatch.setattr("pkgeter.search.Config", lambda path=None: SimpleNamespace())
    monkeypatch.setattr("pkgeter.search.get_session_cache", lambda: None)
    monkeypatch.setattr("pkgeter.search.PackageCache", _FakeCache, raising=False)

    rc = run_search(["ceph"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "[pve-8@cn / ceph-squid]" in out
    assert "ceph-common" in out
    assert "[pve-8@cn / main]" not in out


class _FakeSession:
    def __init__(self, ctx, merged_db):
        self._ctx = ctx
        self._merged_db = merged_db

    def get_or_load(self, config, force_update=False):
        return self._ctx, self._merged_db


def test_run_search_bypasses_session_cache_when_distro_overridden(monkeypatch, capsys):
    cached_ctx = SimpleNamespace(
        backend=_FakeBackend(),
        repos=[
            RepoConfig(
                name="main",
                type="deb",
                url="https://cached.example",
                release="bookworm",
                components=["main"],
                arch="amd64",
            )
        ],
        arch="amd64",
        preset_name="cached-preset",
    )
    requested_ctx = SimpleNamespace(
        backend=_FakeBackend(),
        repos=[
            RepoConfig(
                name="ceph-squid",
                type="deb",
                url="https://ceph.example",
                release="bookworm",
                components=["no-subscription"],
                arch="amd64",
            )
        ],
        arch="amd64",
        preset_name="pve-8@cn",
    )

    monkeypatch.setattr("pkgeter.search.resolve_backend", lambda **kwargs: requested_ctx)
    monkeypatch.setattr("pkgeter.search.Config", lambda path=None: SimpleNamespace())
    monkeypatch.setattr(
        "pkgeter.search.get_session_cache",
        lambda: _FakeSession(cached_ctx, {"bash": PackageInfo(package="bash", version="1.0", base_url="https://cached.example")}),
    )
    monkeypatch.setattr("pkgeter.search.PackageCache", None, raising=False)

    rc = run_search(["ceph", "--distro", "pve-8@cn"])
    assert rc == 0

    out = capsys.readouterr().out
    assert "Loading ceph-squid..." in out
    assert "cached-preset" not in out
    assert "pve-8@cn / ceph-squid" in out
