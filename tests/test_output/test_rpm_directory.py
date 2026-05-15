"""Tests for .rpm directory output."""

import sys
from pathlib import Path

from pkgeter.output.rpm_directory import RpmDirectoryOutput


def test_rpm_directory_output(tmp_path: Path):
    """Basic output creates rpms/ subdirectory with copied files."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    fake_rpm = src_dir / "openssl-1.1.1k-7.el8_9.x86_64.rpm"
    fake_rpm.write_text("rpm-content")

    rpm_files = {"openssl": fake_rpm}
    output = RpmDirectoryOutput()
    result = output.execute(
        deb_files=rpm_files,
        install_script="",
        release="9",
        arch="x86_64",
        output_dir=tmp_path / "output",
    )

    assert result.exists()
    assert result.is_dir()
    assert result.name == "rpms"
    assert list(result.rglob("*.rpm"))


def test_rpm_directory_with_install_script(tmp_path: Path):
    """Install script is written when provided."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    fake_rpm = src_dir / "openssl-1.1.1k-7.el8_9.x86_64.rpm"
    fake_rpm.write_text("rpm-content")

    rpm_files = {"openssl": fake_rpm}
    output = RpmDirectoryOutput()
    result = output.execute(
        deb_files=rpm_files,
        install_script="sudo rpm -ivh openssl-1.1.1k-7.el8_9.x86_64.rpm\n",
        release="9",
        arch="x86_64",
        output_dir=tmp_path / "output",
    )

    script = result / "install.sh"
    assert script.exists()
    if sys.platform != "win32":
        assert script.stat().st_mode & 0o111  # executable
    assert "sudo rpm -ivh" in script.read_text()


def test_rpm_directory_multiple_files(tmp_path: Path):
    """Multiple .rpm files are all copied to output."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    for name in ["openssl-1.1.1k.x86_64.rpm", "krb5-libs-1.17.x86_64.rpm"]:
        (src_dir / name).write_text("content")

    rpm_files = {
        "openssl": src_dir / "openssl-1.1.1k.x86_64.rpm",
        "krb5-libs": src_dir / "krb5-libs-1.17.x86_64.rpm",
    }
    output = RpmDirectoryOutput()
    result = output.execute(
        deb_files=rpm_files,
        install_script="",
        release="9",
        arch="x86_64",
        output_dir=tmp_path / "output",
    )

    rpm_files_found = list(result.rglob("*.rpm"))
    assert len(rpm_files_found) == 2


def test_rpm_directory_no_install_script(tmp_path: Path):
    """No install.sh when install_script is empty."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "pkg.rpm").write_text("content")

    output = RpmDirectoryOutput()
    result = output.execute(
        deb_files={"pkg": src_dir / "pkg.rpm"},
        install_script="",
        release="9",
        arch="x86_64",
        output_dir=tmp_path / "output",
    )
    assert not (result / "install.sh").exists()
