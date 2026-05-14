"""Core data models for Debian package metadata."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Dependency:
    """A single dependency with optional version constraint."""

    name: str
    version_operator: str | None = None
    version: str | None = None

    def __str__(self) -> str:
        if self.version_operator and self.version:
            return f"{self.name} ({self.version_operator} {self.version})"
        return self.name


@dataclass
class PackageInfo:
    """Parsed metadata for a single Debian package."""

    package: str
    version: str
    depends: list[list[Dependency]] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    arch: str = ""
    filename: str = ""
    sha256: str = ""
    size: int = 0
    description: str = ""


@dataclass
class RepoConfig:
    """Configuration for a single package repository (deb or rpm)."""

    name: str
    type: str = "deb"  # "deb" | "rpm"
    url: str = ""
    release: str = ""
    components: list[str] = field(default_factory=list)
    arch: str = ""

    def to_dict(self) -> dict[str, object]:
        """Serialize to a JSON/YAML-compatible dict."""
        return {
            "name": self.name,
            "type": self.type,
            "url": self.url,
            "release": self.release,
            "components": list(self.components),
            "arch": self.arch,
        }

    @classmethod
    def from_dict(cls, d: dict) -> RepoConfig:
        """Deserialize from a dict (backwards-compatible with missing keys)."""
        return cls(
            name=d.get("name", ""),
            type=d.get("type", "deb"),
            url=d.get("url", ""),
            release=d.get("release", ""),
            components=list(d.get("components", [])),
            arch=d.get("arch", ""),
        )


def parse_depends_line(line: str) -> list[list[Dependency]]:
    """Parse a Debian Depends line into AND-of-OR groups.

    Input: "libc6 (>= 2.34), pkg-a | pkg-b"
    Output: [[Dep("libc6", ">=", "2.34")],
             [Dep("pkg-a"), Dep("pkg-b")]]
    """
    if not line or line.strip() == "":
        return []

    groups: list[list[Dependency]] = []
    groups_inner = line.split(",")
    for group in groups_inner:
        group = group.strip()
        if not group:
            continue
        alternatives = group.split("|")
        deps: list[Dependency] = []
        for alt in alternatives:
            alt = alt.strip()
            dep = _parse_single_dep(alt)
            if dep:
                deps.append(dep)
        if deps:
            groups.append(deps)
    return groups


def _parse_single_dep(text: str) -> Dependency | None:
    """Parse a single dependency string like 'libc6 (>= 2.34)'."""
    text = text.strip()
    if not text:
        return None
    open_paren = text.find("(")
    if open_paren != -1:
        close_paren = text.find(")", open_paren)
        if close_paren == -1:
            return Dependency(name=text)
        name = text[:open_paren].strip()
        rest = text[open_paren + 1 : close_paren]
        parts = rest.split()
        op = parts[0] if parts else None
        ver = parts[1] if len(parts) > 1 else None
        return Dependency(name=name, version_operator=op, version=ver)
    return Dependency(name=text)


def format_package_info(info: PackageInfo) -> str:
    """Format PackageInfo back into Debian control stanza format."""
    lines = [
        f"Package: {info.package}",
        f"Version: {info.version}",
        f"Architecture: {info.arch}",
        f"Filename: {info.filename}",
        f"SHA256: {info.sha256}",
        f"Size: {info.size}",
    ]
    if info.description:
        lines.append(f"Description: {info.description}")
    if info.depends:
        dep_strs = []
        for group in info.depends:
            dep_strs.append(" | ".join(str(d) for d in group))
        lines.append(f"Depends: {', '.join(dep_strs)}")
    if info.provides:
        lines.append(f"Provides: {', '.join(info.provides)}")
    return "\n".join(lines) + "\n\n"
