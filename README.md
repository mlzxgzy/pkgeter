# pkgeter <small>v1.1</small>

**English** | [中文](README_CH.md)

**Offline package downloader** — supports **Debian/apt** and **RPM/dnf** (CentOS Stream). Resolve dependency trees, download `.deb` or `.rpm` files, and generate an offline install script.

Works on any platform (Linux, Windows, macOS) — useful when you need to install packages on an air-gapped or offline machine.

## Features

- **Dual backend** — supports Debian (`dpkg`) and RPM (`rpm`) based distributions
- **Distribution presets** — one-command selection: `--distro debian-bookworm`, `--distro centos-9`
- **Interactive REPL** — run `pkgeter` with no arguments to enter a switch-style CLI with prefix matching and TAB completion
- **Multi-repo merge** — automatically combines repositories (e.g., main + security, BaseOS + AppStream + EPEL)
- **Dependency resolution** — recursively resolves all dependencies for the target packages
- **Skip installed packages** — optionally provide a `dpkg -l` output to skip already-installed packages
- **SHA256 verification** — validates every downloaded `.deb` or `.rpm` file
- **Source caching** — caches repository metadata with SHA256 validation (like APT), only re-downloads when changed
- **Offline install script** — auto-generates `install.sh` that runs `dpkg -i` or `rpm -ivh` in dependency order
- **Multiple mirrors** — specify fallback mirrors, tried in order until one succeeds
- **Persistent config** — preferences saved to `~/.config/pkgeter/config.yaml`
- **Repo management** — add, list, and remove custom repositories via `pkgeter repo`

## Installation
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
pkgeter get -p nginx --distro debian-bullseye

# Short prefix forms work too
pkgeter g -p nginx --distro centos-9

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

## Output

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

## How It Works

1. **Download package database** — fetches metadata from configured repositories (Packages.gz for Debian, repomd.xml + primary.xml.gz for RPM)
2. **Parse dependency tree** — recursively resolves all required packages
3. **Download package files** — downloads each package with SHA256 verification
4. **Generate output** — creates `debs/` or `rpms/` directory with `install.sh`

## Distribution Presets

| Preset | Backend | Included Repositories |
|--------|---------|----------------------|
| `debian-bookworm` | deb | main, security, updates |
| `debian-bullseye` | deb | main, security, updates |
| `centos-9` | rpm | BaseOS, AppStream, EPEL |

## License

MIT
