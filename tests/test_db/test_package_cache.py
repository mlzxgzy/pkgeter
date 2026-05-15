"""Tests for the SQLite package cache."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pkgeter.models import Dependency, PackageInfo


@pytest.fixture
def cache(tmp_path):
    from pkgeter.db.package_cache import PackageCache
    return PackageCache(db_path=tmp_path / "test_cache.db")


@pytest.fixture
def sample_packages() -> dict[str, PackageInfo]:
    return {
        "nginx": PackageInfo(
            package="nginx",
            version="1.22.1-9",
            arch="amd64",
            filename="pool/main/n/nginx/nginx_1.22.1-9_amd64.deb",
            sha256="abc123",
            size=123456,
            description="Small, powerful, scalable web/proxy server",
            depends=[
                [Dependency(name="libc6", version_operator=">=", version="2.34")],
                [Dependency(name="libpcre2-8-0"), Dependency(name="libpcre3")],
            ],
            provides=["httpd", "httpd-cgi"],
            base_url="https://deb.debian.org/debian",
        ),
        "curl": PackageInfo(
            package="curl",
            version="7.88.1-10",
            arch="amd64",
            filename="pool/main/c/curl/curl_7.88.1-10_amd64.deb",
            sha256="def456",
            size=456789,
            description="command line tool for transferring data with URL syntax",
            depends=[
                [Dependency(name="libcurl4", version_operator="=", version="7.88.1-10")],
            ],
            provides=[],
            base_url="https://deb.debian.org/debian",
        ),
    }


SOURCE_ID = "deb:deb.debian.org/debian:bookworm:amd64:main"
SOURCE_SHA = "aabbccdd" * 8


class TestStoreAndFresh:
    def test_is_fresh_returns_false_when_empty(self, cache):
        assert cache.is_fresh(SOURCE_ID, SOURCE_SHA) is False

    def test_store_then_is_fresh(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        assert cache.is_fresh(SOURCE_ID, SOURCE_SHA) is True

    def test_is_fresh_returns_false_for_different_sha(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        assert cache.is_fresh(SOURCE_ID, "different_sha") is False

    def test_store_replaces_old_data(self, cache, sample_packages):
        cache.store(SOURCE_ID, "old_sha", sample_packages)
        new_pkgs = {"only-one": sample_packages["nginx"]}
        cache.store(SOURCE_ID, "new_sha", new_pkgs)
        assert cache.is_fresh(SOURCE_ID, "new_sha") is True
        assert cache.is_fresh(SOURCE_ID, "old_sha") is False
