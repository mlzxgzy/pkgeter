"""Tests for .deb directory output."""

import tarfile
import io
from pathlib import Path

from pkgeter.output.deb_directory import DebDirectoryOutput


def _create_fake_deb(path: Path, pkg_name: str, version: str, deps: str = "") -> None:
    """Create a minimal valid .deb file."""
    control = (
        f"Package: {pkg_name}\n"
        f"Version: {version}\n"
        f"Architecture: amd64\n"
        f"Depends: {deps}\n"
        f"Description: test package\n"
    )

    buf = io.BytesIO()
    tf = tarfile.open(fileobj=buf, mode="w:gz")
    control_bytes = control.encode()
    ti = tarfile.TarInfo(name="control")
    ti.size = len(control_bytes)
    tf.addfile(ti, io.BytesIO(control_bytes))
    tf.close()
    control_tar = buf.getvalue()

    with open(path, "wb") as f:
        f.write(b"!<arch>\n")
        db_content = b"2.0\n"
        f.write(b"debian-binary       ")
        f.write(b"0    0    0    100644  ")
        f.write(f"{len(db_content):<10}".encode())
        f.write(b"\x60\x0a")
        f.write(db_content)
        f.write(b"control.tar.gz      ")
        f.write(b"0    0    0    100644  ")
        f.write(f"{len(control_tar):<10}".encode())
        f.write(b"\x60\x0a")
        f.write(control_tar)


def test_deb_directory_output(tmp_path):
    debs_dir = tmp_path / "debs"
    debs_dir.mkdir()
    _create_fake_deb(debs_dir / "libc6_2.36_amd64.deb", "libc6", "2.36")

    deb_files = {"libc6": debs_dir / "libc6_2.36_amd64.deb"}
    output = DebDirectoryOutput()
    result = output.execute(
        deb_files=deb_files,
        install_script="",
        release="bookworm",
        arch="amd64",
        output_dir=tmp_path / "output",
    )

    assert result.exists()
    assert result.is_dir()
    assert list(result.rglob("*.deb"))
