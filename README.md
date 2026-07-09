# pkgeter <small>v1.3.2</small>

**English** | [中文](README_CH.md)

**Offline package downloader** — supports **Debian/apt** and **RPM/dnf** (CentOS, Kylin, RockyLinux, etc.). Resolve dependency trees, download `.deb` or `.rpm` files, generate offline install script, or produce a local apt/yum mirror.

Works on any platform (Linux, Windows, macOS) — useful when you need to install packages on an air-gapped or offline machine.

## Features

- **Dual backend** — supports Debian (`dpkg`) and RPM (`rpm`/`dnf`/`yum`) based distributions
- **Distribution presets** — 14+ ready-to-use presets: `--distro debian-bookworm`, `--distro centos-7`, `--distro ubuntu-noble`
- **Interactive REPL** — run `pkgeter` with no arguments to enter a switch-style CLI with prefix matching and TAB completion
- **Multi-repo merge** — automatically combines repositories (e.g., main + security, BaseOS + AppStream + EPEL)
- **Dependency resolution** — recursively resolves all dependencies for the target packages
- **Virtual package resolution** — follows `Provides` fields for virtual dependencies with interactive provider selection
- **Skip installed packages** — optionally provide a `dpkg -l` / `rpm -qa` output to skip already-installed packages
- **SHA256 verification** — validates every downloaded `.deb` or `.rpm` file
- **Source caching** — caches repository metadata with SHA256 validation (SQLite-backed), only re-downloads when changed
- **Local mirror output** — `--repo` flag generates a fully structured apt repo (`Packages.gz` + `Release`) or yum repo (`repomd.xml` + metadata)
- **Dependency tree visualization** — `--tree` flag generates an interactive HTML dependency tree
- **Offline install script** — auto-generates `install.sh` that runs `dpkg -i` or `rpm -ivh` in dependency order (auto-detects sudo)
- **Multiple mirrors** — specify fallback mirrors, tried in order until one succeeds
- **Persistent config** — preferences saved to `~/.config/pkgeter/config.yaml`
- **Repo management** — add, list, and remove custom repositories via `pkgeter repo`

## Installation

### From PyPI (recommended)

```bash
pip install pkgeter
```

### From source

```bash
git clone https://github.com/mlzxgzy/pkgeter.git
cd pkgeter
pip install -e .
```

## Usage

```bash
# Interactive REPL (no arguments)
pkgeter

# Download packages using a distribution preset
pkgeter get -p nginx --distro debian-bookworm
pkgeter get -p nginx --distro centos-9
pkgeter get -p nginx --distro ubuntu-noble

# Short prefix forms work too
pkgeter g -p nginx --distro centos-9

# Generate local apt/yum mirror metadata (instead of flat output)
pkgeter get -p nginx --distro debian-bookworm --repo

# Generate dependency tree HTML report
pkgeter get -p nginx --distro debian-bookworm --tree

# Legacy usage (backward compatible)
pkgeter get -p vim
pkgeter get -p nginx -r bookworm -a amd64

# Specify multiple mirrors (tried in order)
pkgeter get -p nginx -m https://deb.debian.org/debian -m https://ftp.debian.org/debian

# Manage repositories
pkgeter repo list
pkgeter repo add --name myrepo --type deb --url https://example.com/debian --release bookworm
pkgeter repo remove myrepo

# List and apply distribution presets
pkgeter preset list
pkgeter preset apply centos-9

# Specify a custom output directory
pkgeter get -p python3 -o ./my-output
```

## Output Formats

Two output modes, controlled by the `--repo` flag:

| Mode | Flag | Structure | Use Case |
|------|------|-----------|----------|
| **Flat** (default) | *(none)* | `debs/*.deb` + `install.sh` or `rpms/*.rpm` + `install.sh` | Quick copy + install |
| **Mirror** | `--repo` | `pool/`, `dists/`, `Packages.gz`, `Release` (deb) or `Packages/`, `repomd.xml` (rpm) | Add as permanent apt/yum source |

For Debian mode, all `.deb` files are placed in a `debs/` subdirectory. For RPM mode, all `.rpm` files are placed in a `rpms/` subdirectory. An `install.sh` script is generated that runs `dpkg -i` or `rpm -ivh` in dependency order.

```bash
# Debian: copy the debs/ directory and install.sh to the target machine, then:
sudo bash install.sh

# RPM: copy the rpms/ directory and install.sh to the target machine, then:
sudo bash install.sh
```

## Configuration

pkgeter stores persistent preferences at `~/.config/pkgeter/config.yaml`. This file is automatically created when you run the tool.

```yaml
backend: debian
arch: amd64
repos:
  - name: debian-main
    type: deb
    url: https://deb.debian.org/debian
    release: bookworm
  - name: debian-security
    type: deb
    url: https://security.debian.org/debian-security
    release: bookworm-security
```

CLI flags override config file values. Apply a preset to quickly populate the config:

```bash
pkgeter preset apply centos-9
```

To add or override repositories in a built-in preset, create `~/.config/pkgeter/custom-presets.yaml`. This file is optional and merged onto built-in presets by preset name, repo name, and mirror name.

```yaml
pve-8:
  repos:
    - name: ceph-squid
      type: deb
      url: https://download.proxmox.com/debian/ceph-squid
      release: bookworm
      components: [no-subscription]
  mirrors:
    - name: cn
      provider: ustc
      urls:
        ceph-squid: https://mirrors.ustc.edu.cn/proxmox/debian/ceph-squid
```

After editing `custom-presets.yaml`, re-run `pkgeter preset apply <preset>` to persist the merged repo list into `config.yaml`.

## How It Works

1. **Download package database** — fetches metadata from configured repositories (Packages.gz for Debian, repomd.xml + primary.xml.gz for RPM)
2. **Parse dependency tree** — recursively resolves all required packages (handles AND/OR deps, virtual packages, cycle detection)
3. **Download package files** — downloads each package with SHA256 verification
4. **Generate output** — creates `debs/` or `rpms/` directory with `install.sh`, or full mirror structure when `--repo` is used

## Distribution Presets

| Preset | Backend | Included Repositories |
|--------|---------|----------------------|
| `debian-bookworm` | apt (deb) | main, security, updates |
| `debian-bullseye` | apt (deb) | main, security, updates |
| `debian-trixie`  | apt (deb) | main, security, updates |
| `debian-buster` | apt (deb) | main, security, updates |
| `debian-stretch` | apt (deb) | main, security, updates |
| `ubuntu-noble` (24.04) | apt (deb) | main, universe, security, updates |
| `ubuntu-jammy` (22.04) | apt (deb) | main, universe, security, updates |
| `ubuntu-focal` (20.04) | apt (deb) | main, universe, security, updates |
| `ubuntu-bionic` (18.04) | apt (deb) | main, universe, security, updates |
| `centos-9` | rpm | BaseOS, AppStream, EPEL |
| `centos-7` | rpm | base, extras, updates, EPEL |
| `pve-8` | apt (deb) | bookworm main, security, updates + pve-no-subscription |
| `kylin-V10` | rpm | base, updates |

## License

MIT
