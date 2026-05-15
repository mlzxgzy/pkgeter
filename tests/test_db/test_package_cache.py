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


class TestLoad:
    def test_load_returns_none_when_empty(self, cache):
        assert cache.load(SOURCE_ID) is None

    def test_load_round_trip(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        loaded = cache.load(SOURCE_ID)
        assert loaded is not None
        assert set(loaded.keys()) == {"nginx", "curl"}

        nginx = loaded["nginx"]
        assert nginx.package == "nginx"
        assert nginx.version == "1.22.1-9"
        assert nginx.arch == "amd64"
        assert nginx.filename == "pool/main/n/nginx/nginx_1.22.1-9_amd64.deb"
        assert nginx.sha256 == "abc123"
        assert nginx.size == 123456
        assert nginx.description == "Small, powerful, scalable web/proxy server"
        assert nginx.base_url == "https://deb.debian.org/debian"

        # Verify depends round-trip
        assert len(nginx.depends) == 2
        assert nginx.depends[0][0].name == "libc6"
        assert nginx.depends[0][0].version_operator == ">="
        assert nginx.depends[0][0].version == "2.34"
        assert len(nginx.depends[1]) == 2  # OR group
        assert nginx.depends[1][0].name == "libpcre2-8-0"
        assert nginx.depends[1][1].name == "libpcre3"

        # Verify provides round-trip
        assert nginx.provides == ["httpd", "httpd-cgi"]

    def test_load_empty_depends_and_provides(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        loaded = cache.load(SOURCE_ID)
        curl = loaded["curl"]
        assert curl.provides == []
        assert len(curl.depends) == 1


class TestClear:
    def test_clear_specific_source(self, cache, sample_packages):
        other_id = "deb:other:bookworm:amd64:main"
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        cache.store(other_id, "other_sha", {"curl": sample_packages["curl"]})

        cache.clear(SOURCE_ID)
        assert cache.load(SOURCE_ID) is None
        assert cache.load(other_id) is not None

    def test_clear_all(self, cache, sample_packages):
        other_id = "deb:other:bookworm:amd64:main"
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        cache.store(other_id, "other_sha", {"curl": sample_packages["curl"]})

        cache.clear()
        assert cache.load(SOURCE_ID) is None
        assert cache.load(other_id) is None


class TestSearch:
    def test_search_by_name_substring(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("ngi")
        assert len(results) == 1
        assert results[0].package == "nginx"

    def test_search_by_name_case_insensitive(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("CURL")
        assert len(results) == 1
        assert results[0].package == "curl"

    def test_search_wildcard_star(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("ng*")
        names = [r.package for r in results]
        assert "nginx" in names

    def test_search_wildcard_question(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("cur?")
        assert len(results) == 1
        assert results[0].package == "curl"

    def test_search_description(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("proxy", search_desc=True)
        assert len(results) >= 1
        assert any(r.package == "nginx" for r in results)

    def test_search_with_source_filter(self, cache, sample_packages):
        other_id = "deb:other:bookworm:amd64:main"
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        cache.store(other_id, "other_sha", {"curl": sample_packages["curl"]})

        results = cache.search("curl", source_ids=[other_id])
        assert len(results) == 1

        results_all = cache.search("curl")
        assert len(results_all) >= 1

    def test_search_no_results(self, cache, sample_packages):
        cache.store(SOURCE_ID, SOURCE_SHA, sample_packages)
        results = cache.search("nonexistent_xyz")
        assert results == []
