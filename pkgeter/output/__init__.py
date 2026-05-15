"""Output formats for pkgeter."""

from pkgeter.output.deb_directory import DebDirectoryOutput
from pkgeter.output.rpm_directory import RpmDirectoryOutput
from pkgeter.output.deb_mirror import DebMirrorOutput
from pkgeter.output.rpm_mirror import RpmMirrorOutput, DnfMirrorOutput

__all__ = [
    "DebDirectoryOutput",
    "RpmDirectoryOutput",
    "DebMirrorOutput",
    "RpmMirrorOutput",
    "DnfMirrorOutput",
]
