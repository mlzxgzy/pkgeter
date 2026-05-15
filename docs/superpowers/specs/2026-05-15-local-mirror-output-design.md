# Local Mirror Output — Design Spec

Date: 2026-05-15

## Overview

Add an output mode to `pkgeter get` that generates a complete **local filesystem mirror** for both RPM and Debian packages, alongside the existing flat-directory output. The output includes:

1. Downloaded package files (`.rpm` / `.deb`)
2. Self-generated repository metadata (no external tools like `createrepo_c` or `dpkg-scanpackages`)
3. A **temporary** package-manager configuration file (non-invasive, does not write to `/etc/`)
4. An `install.sh` script that uses the temporary configuration with `sudo`

## Motivation

The current output (`DebDirectoryOutput` / `RpmDirectoryOutput`) copies packages flat into a directory and generates `rpm -ivh` / `dpkg -i` install scripts. This works but bypasses the native package manager's dependency resolution. A local mirror lets users run `yum install` / `dnf install` / `apt-get install` against the downloaded packages, allowing the package manager to handle any runtime dependencies present on the target system.

## Output Directory Structure

### RPM (shared by RpmBackend and DnfBackend)

```
output/
├── rpms/
│   ├── openssl-1.1.1k-7.el8_9.x86_64.rpm
│   └── curl-7.76.1-8.el8_9.x86_64.rpm
├── repodata/
│   ├── repomd.xml
│   └── primary.xml.gz
├── local.repo
├── yum.conf              (only for yum3 compatibility)
└── install.sh
```

### Debian (shared by DebianBackend)

```
output/
├── debs/
│   ├── vsftpd_3.0.5-3_amd64.deb
│   └── libssl1.1_1.1.1k-1_amd64.deb
├── dists/
│   └── <release>/
│       └── main/
│           └── binary-<arch>/
│               ├── Packages.gz
│               └── Release
├── local.sources
└── install.sh
```

## Architecture

### New Output Classes

Instead of modifying the existing `DebDirectoryOutput` / `RpmDirectoryOutput`, create new output format classes that produce the local mirror structure **including** metadata generation.

```
OutputFormat (ABC)
├── DebDirectoryOutput       (existing — flat .deb + install.sh)
├── RpmDirectoryOutput       (existing — flat .rpm + install.sh)
├── DebMirrorOutput          (new — local apt mirror)
└── RpmMirrorOutput          (new — local yum/dnf mirror)
```

### Selection in `get.py`

The `get` subcommand currently picks the output format based on `backend.name`:

```python
if backend.name in ("apt", "debian"):
    fmt = DebDirectoryOutput()
else:
    fmt = RpmDirectoryOutput()
```

This is replaced with mirror-output versions. The flat-directory output remains accessible (e.g. via a CLI flag), but the default becomes the mirror output.

## Metadata Generation (Pure Python)

### RPM repodata

Generate two files in `repodata/`:

**`repomd.xml`** — Top-level metadata pointing to primary (no filelists — not needed for install and avoids empty/placeholder data):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<repomd xmlns="http://linux.duke.edu/metadata/repo">
  <data type="primary">
    <location href="repodata/primary.xml.gz"/>
    <checksum type="sha256">abc123...</checksum>
    <timestamp>1715000000</timestamp>
    <open-size>12345</open-size>
    <size>2345</size>
  </data>
</repomd>
```

**`primary.xml.gz`** — Package metadata (gzip-compressed):
```xml
<?xml version="1.0"?>
<metadata xmlns="http://linux.duke.edu/metadata/common"
          xmlns:rpm="http://linux.duke.edu/metadata/rpm"
          packages="2">
  <package type="rpm">
    <name>openssl</name>
    <arch>x86_64</arch>
    <version epoch="0" ver="1.1.1k" rel="7.el8_9"/>
    <checksum type="sha256" pkgid="YES">abc123...</checksum>
    <location href="rpms/openssl-1.1.1k-7.el8_9.x86_64.rpm"/>
    <time file="1715000000" build="1610000000"/>
    <size package="1234567" installed="3456789" archive="2345678"/>
    <format>
      <rpm:requires>
        <rpm:entry name="libc.so.6"/>
      </rpm:requires>
      <rpm:provides>
        <rpm:entry name="openssl"/>
      </rpm:provides>
    </format>
  </package>
</metadata>
```

**Data sources**: All required fields already exist in `PackageInfo`:
- `pkg.depends` → requires entries
- `pkg.provides` → provides entries
- `pkg.size` → package size
- `pkg.arch` → arch field
- `pkg.filename` → location href (used to derive file on disk)
- Real `.rpm` file stats → installed size, archive size (estimate or read from file)
- File timestamps → use current time
- `pkg.sha256` → checksum (re-computed from actual file content)

### Debian Packages.gz + Release

**`Packages.gz`** — Debian package metadata (gzip-compressed):

Same format as what `DebianBackend._parse_deb_stanza` reads — write it back as stanzas.

```
Package: vsftpd
Version: 3.0.5-3
Architecture: amd64
Filename: debs/vsftpd_3.0.5-3_amd64.deb
SHA256: abc123...
Size: 123456
Depends: libc6 (>= 2.28), libssl1.1 (>= 1.1.0)
Description: FTP server

Package: libssl1.1
Version: 1.1.1k-1
Architecture: amd64
Filename: debs/libssl1.1_1.1.1k-1_amd64.deb
SHA256: def456...
Size: 234567
Depends: libc6 (>= 2.28)
Description: SSL library

```

**Data sources**: Same `PackageInfo` fields, which are populated from the original `Packages.gz` parsing.

**`Release`** — Suite-level metadata:

```
Codename: bookworm
Architectures: amd64
Components: main
Date: Thu, 15 May 2026 12:00:00 UTC
SHA256:
 abc123... 1234 main/binary-amd64/Packages.gz
```

### Generation Modules

Place metadata generation logic in new modules under `pkgeter/output/`:
- `pkgeter/output/repomd_gen.py` — generate repomd.xml and primary.xml.gz
- `pkgeter/output/apt_repo_gen.py` — generate Packages.gz and Release

This keeps the output format classes clean and the metadata logic testable in isolation.

## Temporary Configuration

### RPM — DnfBackend (`dnf`)

Minimal approach — no config file needed:

**local.repo** (placed in output dir):
```ini
[local]
name=Local Repository
baseurl=file:///path/to/rpms
enabled=1
gpgcheck=0
```

**install.sh**:
```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
sudo dnf --repofrompath=local,file://"$SCRIPT_DIR"/rpms --nogpgcheck install <pkg1> <pkg2> ...
```

`--repofrompath` dynamically adds a repo without any config files. This is the cleanest approach for dnf.

### RPM — RpmBackend (older yum3)

yum3 does not support `--repofrompath`, so generate a minimal configuration:

**yum.conf**:
```ini
[main]
gpgcheck=0
reposdir=$SCRIPT_DIR
```

**local.repo**:
```ini
[local]
name=Local Repository
baseurl=file:///path/to/rpms
enabled=1
gpgcheck=0
```

**install.sh**:
```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
sudo yum --config="$SCRIPT_DIR/yum.conf" --nogpgcheck install <pkg1> <pkg2> ...
```

### Debian

No sources.list config file needed — use `-o` options inline:

**install.sh**:
```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
sudo apt-get \
  -o Dir::Etc::sourcelist="$SCRIPT_DIR/local.sources" \
  -o Dir::Etc::sourceparts=/dev/null \
  -o Acquire::AllowInsecureRepositories=yes \
  -o APT::Get::List-Cleanup="0" \
  update
sudo apt-get \
  -o Dir::Etc::sourcelist="$SCRIPT_DIR/local.sources" \
  -o Dir::Etc::sourceparts=/dev/null \
  -o APT::Get::List-Cleanup="0" \
  install <pkg1> <pkg2> ...
```

**local.sources**:
```
deb [trusted=yes] file:/SCRIPT_DIR <release> main
```

The `file:` URL points to the output root (parent of `dists/`). apt uses `<URL>/dists/<release>/main/binary-<arch>/Packages.gz` to find metadata, and the `Filename` fields in `Packages.gz` (e.g. `debs/vsftpd_3.0.5-3_amd64.deb`) are resolved relative to the URL root.

Note: The `Acquire::AllowInsecureRepositories=yes` option may not be needed when `[trusted=yes]` is in the sources entry, but both are specified for safety across different apt versions.

## Changes to `get.py`

The `get` subcommand selects mirror output formats by default:

```python
if backend.name in ("apt", "debian"):
    from pkgeter.output.deb_mirror import DebMirrorOutput
    fmt = DebMirrorOutput()
elif backend.name == "dnf":
    from pkgeter.output.rpm_mirror import DnfMirrorOutput
    fmt = DnfMirrorOutput()
else:
    from pkgeter.output.rpm_mirror import RpmMirrorOutput
    fmt = RpmMirrorOutput()
```

The `run_get` function also needs to pass through additional fields to `fmt.execute()`:
- `mirror_variant` (already available via `BackendContext`)
- `repo_configs` (already available via `BackendContext.repos`)
- `packages` (target package names, already available)

## Files to Create/Modify

| File | Action |
|------|--------|
| `pkgeter/output/rpm_mirror.py` | New — `RpmMirrorOutput` and `DnfMirrorOutput` classes |
| `pkgeter/output/deb_mirror.py` | New — `DebMirrorOutput` class |
| `pkgeter/output/repomd_gen.py` | New — pure-Python repodata generation |
| `pkgeter/output/apt_repo_gen.py` | New — pure-Python Packages.gz + Release generation |
| `pkgeter/get.py` | Modify — use mirror output formats by default, pass required fields to execute() |

No modifications to existing output formats or backend modules.

## Error Handling

- If a `.rpm` / `.deb` file is missing (e.g., download failed), the output format skips it and generates metadata for the files that exist
- SHA256 checksums in metadata are derived from actual file content with `hashlib.sha256`
- If `createrepo` or `dpkg-scanpackages` exist on the system, ignore them — always use self-generated metadata
- Generated XML content uses proper XML escaping (`xml.sax.saxutils.escape`)
- Gzip compression uses Python's `gzip` module with `mtime=0` for deterministic output

## Testing

- `tests/output/test_repomd_gen.py` — Golden file tests: generate repodata for a small set of `PackageInfo` objects, compare against known-good XML/GZ outputs
- `tests/output/test_apt_repo_gen.py` — Golden file tests: generate Packages.gz + Release, compare stanzas
- `tests/output/test_rpm_mirror.py` — Integration: `RpmMirrorOutput.execute()` produces expected directory tree with correct files
- `tests/output/test_deb_mirror.py` — Integration: `DebMirrorOutput.execute()` produces expected directory tree
- Edge cases: empty package set (no packages downloaded), single package, packages with missing optional fields (no depends, no provides, no sha256)

## Summary

| Aspect | Decision |
|--------|----------|
| External tool dependency | Zero — all metadata generated in pure Python |
| System config modification | Zero — all configs temporary, in output dir |
| RPM metadata format | repomd.xml + primary.xml.gz |
| Debian metadata format | Packages.gz + Release in dists/ layout |
| DNF install method | `dnf --repofrompath=... --nogpgcheck install` |
| yum3 install method | `yum --config=yum.conf --nogpgcheck install` |
| APT install method | `apt-get -o Dir::Etc::sourcelist=... install` |
| Default output | Mirror output replaces flat directory as default |
| Old output preserved | Existing DebDirectoryOutput / RpmDirectoryOutput unchanged |
