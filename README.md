# pkgeter <small>v1.0</small>

**English** | [中文](README_CH.md)

**Offline Debian package downloader** — resolve dependencies, download `.deb` files, and generate an offline install script.

Works on any platform (Linux, Windows, macOS) — useful when you need to install Debian packages on an air-gapped or offline machine.

## Features

- **Dependency resolution** — recursively resolves all dependencies for the target packages
- **Skip installed packages** — optionally provide a `dpkg -l` output to skip already-installed packages
- **SHA256 verification** — validates every downloaded `.deb` file
- **Offline install script** — auto-generates `install.sh` that runs `dpkg -i` in dependency order
- **Persistent config** — preferences saved to `~/.config/pkgeter/config.yaml`

## Installation
### From source

```bash
git clone https://github.com/mlzxgzy/pkgeter.git
cd pkgeter
pip install -e .
```

## Usage

```bash
# Download vim and all its dependencies
pkgeter -p vim

# Download multiple packages
pkgeter -p nginx curl git

# Specify a custom output directory
pkgeter -p python3 -o ./my-output

# Use a specific Debian release and architecture
pkgeter -p docker.io -r bookworm -a arm64

# Skip packages already installed on a target machine
pkgeter -p nginx --dpkg-list /path/to/dpkg-l-output.txt

# Use a custom config file
pkgeter -p vim --config /path/to/config.yaml
```

## Output

All `.deb` files are placed in a `debs/` subdirectory within the output directory. An `install.sh` script is generated that runs `dpkg -i` in dependency order. On the target machine:

```bash
# Copy the debs/ directory and install.sh to the target machine, then:
sudo bash install.sh
```

## Configuration

pkgeter stores persistent preferences at `~/.config/pkgeter/config.yaml`. This file is automatically created when you run the tool.

Example config:

```yaml
release: bookworm
arch: amd64
mirror: https://deb.debian.org/debian
output_dir: ./output
```

CLI flags override config file values. If no config file exists, sensible defaults are used (on Linux systems, release and arch are auto-detected).

## How It Works

1. **Download package database** — fetches `Packages.gz` from the specified Debian mirror
2. **Parse dependency tree** — recursively resolves all required packages
3. **Download `.deb` files** — downloads each package with SHA256 verification
4. **Generate output** — creates `debs/` directory with `install.sh`

## License

MIT
