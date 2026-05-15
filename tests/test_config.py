"""Tests for configuration (mirrors migration, get/set)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from pkgeter.config import Config, parse_mirror_entry


# ---------------------------------------------------------------------------
# Mirror migration from old single-mirror format
# ---------------------------------------------------------------------------


def _write_config(path: Path, data: dict) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)


def test_migrate_old_mirror_to_mirrors(tmp_path: Path):
    """Old config with just 'mirror' should populate 'mirrors'."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {"mirror": "https://old.example.com/debian"})

    config = Config(cfg_path)
    assert config.get("mirrors") == ["https://old.example.com/debian"]
    assert config.get("mirror") == "https://old.example.com/debian"


def test_new_mirrors_list_preserved(tmp_path: Path):
    """Config with 'mirrors' list should be used as-is."""
    cfg_path = tmp_path / "config.yaml"
    mirrors = ["https://mirror1.example.com", "https://mirror2.example.com"]
    _write_config(cfg_path, {"mirrors": mirrors})

    config = Config(cfg_path)
    assert config.get("mirrors") == mirrors
    assert config.get("mirror") == mirrors[0]


def test_both_mirror_and_mirrors_sync_mirror(tmp_path: Path):
    """When both are present, 'mirror' is synced to mirrors[0]."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {
        "mirror": "https://old.example.com/debian",
        "mirrors": ["https://new.example.com/debian"],
    })

    config = Config(cfg_path)
    assert config.get("mirrors") == ["https://new.example.com/debian"]
    assert config.get("mirror") == "https://new.example.com/debian"


def test_no_mirror_fields_gets_default(tmp_path: Path):
    """No mirror/mirrors in config → default Debian mirror."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {"release": "sid"})

    config = Config(cfg_path)
    assert config.get("mirrors") == ["https://deb.debian.org/debian"]


def test_empty_file_gets_default(tmp_path: Path):
    if tmp_path is None:
        pass
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {})

    config = Config(cfg_path)
    assert config.get("mirrors") == ["https://deb.debian.org/debian"]


# ---------------------------------------------------------------------------
# get_mirrors / set_mirrors
# ---------------------------------------------------------------------------


def test_get_mirrors_default():
    """Config with no file uses default mirrors."""
    config = Config()
    assert config.get_mirrors() == ["https://deb.debian.org/debian"]


def test_get_mirrors_uses_mirrors_list(tmp_path: Path):
    mirrors = ["https://a.example.com", "https://b.example.com"]
    _write_config(tmp_path / "config.yaml", {"mirrors": mirrors})
    config = Config(tmp_path / "config.yaml")
    assert config.get_mirrors() == mirrors


def test_get_mirrors_fallback_to_mirror(tmp_path: Path):
    _write_config(tmp_path / "config.yaml", {"mirror": "https://fallback.example.com"})
    config = Config(tmp_path / "config.yaml")
    assert config.get_mirrors() == ["https://fallback.example.com"]


def test_get_mirrors_mirrors_priority(tmp_path: Path):
    """mirrors > mirror when both exist."""
    _write_config(tmp_path / "config.yaml", {
        "mirror": "https://single.example.com",
        "mirrors": ["https://multi.example.com/debian"],
    })
    config = Config(tmp_path / "config.yaml")
    assert config.get_mirrors() == ["https://multi.example.com/debian"]


def test_set_mirrors_updates_both(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {"mirror": "https://old.example.com/debian"})
    config = Config(cfg_path)

    config.set_mirrors(["https://a.example.com", "https://b.example.com"])
    assert config.get("mirrors") == ["https://a.example.com", "https://b.example.com"]
    assert config.get("mirror") == "https://a.example.com"


def test_set_mirrors_empty_noop(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {"mirrors": ["https://old.example.com/debian"]})
    config = Config(cfg_path)

    config.set_mirrors([])
    assert config.get("mirrors") == ["https://old.example.com/debian"]


# ---------------------------------------------------------------------------
# Config get/set for various settings
# ---------------------------------------------------------------------------


def test_get_default_value(tmp_path: Path):
    """Config.get returns default when key is missing."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {})
    config = Config(cfg_path)
    assert config.get("nonexistent", "fallback") == "fallback"


def test_get_default_none(tmp_path: Path):
    """Config.get returns None when key is missing and no default given."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {})
    config = Config(cfg_path)
    assert config.get("nonexistent") is None


def test_set_and_get(tmp_path: Path):
    """Config.set stores a value retrievable by Config.get."""
    cfg_path = tmp_path / "config.yaml"
    config = Config(cfg_path)
    config.set("custom_key", "custom_value")
    assert config.get("custom_key") == "custom_value"


def test_get_repos_default(tmp_path: Path):
    """Config with no repos returns empty list."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {})
    config = Config(cfg_path)
    assert config.get_repos() == []


def test_set_repos_and_get(tmp_path: Path):
    """Setting repos then getting them returns the same list."""
    cfg_path = tmp_path / "config.yaml"
    config = Config(cfg_path)
    repos = [
        {"name": "main", "type": "deb", "url": "https://deb.debian.org/debian"},
    ]
    config.set_repos(repos)
    assert config.get_repos() == repos


def test_set_repos_persists(tmp_path: Path):
    """Repos survive save/reload cycle."""
    cfg_path = tmp_path / "config.yaml"
    config = Config(cfg_path)
    config.set_repos([
        {"name": "main", "type": "deb", "url": "https://deb.debian.org/debian"},
    ])
    config.save()

    config2 = Config(cfg_path)
    assert len(config2.get_repos()) == 1
    assert config2.get_repos()[0]["name"] == "main"


def test_get_backend_default(tmp_path: Path):
    """Default backend is 'apt'."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {})
    config = Config(cfg_path)
    assert config.get_backend() == "apt"


def test_set_backend(tmp_path: Path):
    """Setting backend is reflected in get_backend."""
    cfg_path = tmp_path / "config.yaml"
    config = Config(cfg_path)
    config.set_backend("rpm")
    assert config.get_backend() == "rpm"
    config.set_backend("apt")
    assert config.get_backend() == "apt"


def test_get_mirror_variant_default(tmp_path: Path):
    """Default mirror variant is 'default'."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {})
    config = Config(cfg_path)
    assert config.get_mirror_variant() == "default"


def test_set_mirror_variant(tmp_path: Path):
    """Setting mirror variant is reflected."""
    cfg_path = tmp_path / "config.yaml"
    config = Config(cfg_path)
    config.set_mirror_variant("cn")
    assert config.get_mirror_variant() == "cn"


def test_get_preset_name_default(tmp_path: Path):
    """Default preset name is empty string."""
    cfg_path = tmp_path / "config.yaml"
    _write_config(cfg_path, {})
    config = Config(cfg_path)
    assert config.get_preset_name() == ""


def test_set_preset_name(tmp_path: Path):
    """Setting preset name is reflected."""
    cfg_path = tmp_path / "config.yaml"
    config = Config(cfg_path)
    config.set_preset_name("debian-bookworm")
    assert config.get_preset_name() == "debian-bookworm"


def test_backend_saved_and_loaded(tmp_path: Path):
    """Backend setting survives save/reload."""
    cfg_path = tmp_path / "config.yaml"
    config = Config(cfg_path)
    config.set_backend("rpm")
    config.save()

    config2 = Config(cfg_path)
    assert config2.get_backend() == "rpm"


def test_save_keeps_sync(tmp_path: Path):
    cfg_path = tmp_path / "config.yaml"
    config = Config(cfg_path)
    config.set_mirrors(["https://primary.example.com", "https://fallback.example.com"])
    config.save()

    # Re-load and verify
    config2 = Config(cfg_path)
    assert config2.get("mirrors") == ["https://primary.example.com", "https://fallback.example.com"]
    assert config2.get("mirror") == "https://primary.example.com"


# ---------------------------------------------------------------------------
# parse_mirror_entry
# ---------------------------------------------------------------------------


class TestParseMirrorEntry:
    def test_plain_mirror(self):
        url, release = parse_mirror_entry("https://deb.debian.org/debian")
        assert url == "https://deb.debian.org/debian"
        assert release is None

    def test_with_release_override(self):
        url, release = parse_mirror_entry(
            "https://security.debian.org/debian-security@bookworm-security"
        )
        assert url == "https://security.debian.org/debian-security"
        assert release == "bookworm-security"

    def test_at_sign_in_path_no_override(self):
        """@ in the URL path itself is not treated as a release override."""
        url, release = parse_mirror_entry("https://example.com/@mirror/debian")
        assert url == "https://example.com/@mirror/debian"
        assert release is None

    def test_empty_suffix_not_treated_as_override(self):
        """Trailing @ with nothing after it is not an override."""
        url, release = parse_mirror_entry("https://deb.debian.org/debian@")
        assert url == "https://deb.debian.org/debian@"
        assert release is None

    def test_release_override_preserved_in_save(self, tmp_path: Path):
        """Mirrors with @ override survive save/reload cycle."""
        cfg_path = tmp_path / "config.yaml"
        config = Config(cfg_path)
        config.set_mirrors([
            "https://deb.debian.org/debian",
            "https://security.debian.org/debian-security@bookworm-security",
        ])
        config.save()

        config2 = Config(cfg_path)
        assert config2.get("mirrors") == [
            "https://deb.debian.org/debian",
            "https://security.debian.org/debian-security@bookworm-security",
        ]
