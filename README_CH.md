# pkgeter <small>v1.3.2</small>

**中文** | [English](README.md)

**离线包下载工具** — 支持 **Debian/apt** 和 **RPM/dnf**（CentOS、Kylin、RockyLinux 等）。解析依赖树、下载 `.deb` 或 `.rpm` 文件、生成离线安装脚本，或构建本地 apt/yum 源。

跨平台支持（Linux、Windows、macOS）—— 当需要在离线机器上安装包时非常有用。

## 特性

- **双后端** — 支持 Debian（`dpkg`）和 RPM（`rpm`/`dnf`/`yum`）系发行版
- **发行版预设** — 14+ 个开箱即用预设：`--distro debian-bookworm`、`--distro centos-7`、`--distro ubuntu-noble`
- **交互式 REPL** — 直接运行 `pkgeter` 进入类交换机命令行，支持前缀匹配和 TAB 补全
- **多源合并** — 自动组合多个仓库（如 main + security，BaseOS + AppStream + EPEL）
- **依赖解析** — 递归解析目标包的所有依赖（支持 AND/OR 依赖、虚拟包、循环检测）
- **虚拟包解析** — 追踪 `Provides` 字段处理虚拟依赖，交互式选择提供者
- **SHA256 校验** — 验证每个下载的 `.deb` 或 `.rpm` 文件
- **源缓存** — SQLite 后端缓存仓库元数据并用 SHA256 校验，只下载变更部分
- **本地源输出** — `--repo` 参数生成完整的 apt 源（`Packages.gz` + `Release`）或 yum 源（`repomd.xml` + 元数据）
- **依赖树可视化** — `--tree` 参数生成交互式 HTML 依赖树报告
- **离线安装脚本** — 自动生成按依赖顺序安装的 `install.sh`（`dpkg -i` 或 `rpm -ivh`，自动检测 sudo）
- **多镜像源** — 可指定多个镜像，按顺序尝试，直到成功
- **持久配置** — 配置保存在 `~/.config/pkgeter/config.yaml`
- **源管理** — 通过 `pkgeter repo` 添加、列出、删除自定义源

## 安装

### 从 PyPI 安装（推荐）

```bash
pip install pkgeter
```

### 从源码安装

```bash
git clone https://github.com/mlzxgzy/pkgeter.git
cd pkgeter
pip install -e .
```

## 使用方法

```bash
# 交互式 REPL（无参数）
pkgeter

# 使用发行版预设下载包
pkgeter get -p nginx --distro debian-bookworm
pkgeter get -p nginx --distro centos-9
pkgeter get -p nginx --distro ubuntu-noble

# 支持前缀简写
pkgeter g -p nginx --distro centos-9

# 生成本地 apt/yum 源（而非扁平目录）
pkgeter get -p nginx --distro debian-bookworm --repo

# 生成依赖树 HTML 报告
pkgeter get -p nginx --distro debian-bookworm --tree

# 兼容旧用法
pkgeter get -p vim
pkgeter get -p nginx -r bookworm -a amd64

# 指定多个镜像（按顺序尝试）
pkgeter get -p nginx -m https://deb.debian.org/debian -m https://ftp.debian.org/debian

# 管理仓库源
pkgeter repo list
pkgeter repo add --name myrepo --type deb --url https://example.com/debian --release bookworm
pkgeter repo remove myrepo

# 查看和应用发行版预设
pkgeter preset list
pkgeter preset apply centos-9

# 指定输出目录
pkgeter get -p python3 -o ./my-output
```

## 输出格式

`--repo` 参数控制两种输出模式：

| 模式 | 参数 | 结构 | 用途 |
|------|------|------|------|
| **扁平**（默认） | *(无)* | `debs/*.deb` + `install.sh` 或 `rpms/*.rpm` + `install.sh` | 快速复制 + 安装 |
| **源** | `--repo` | `pool/`、`dists/`、`Packages.gz`、`Release`（deb）或 `Packages/`、`repomd.xml`（rpm） | 作为永久 apt/yum 源 |

Debian 模式下所有 `.deb` 文件输出到 `debs/` 子目录，RPM 模式下所有 `.rpm` 文件输出到 `rpms/` 子目录。并生成 `install.sh`，按依赖顺序执行 `dpkg -i` 或 `rpm -ivh` 安装。

```bash
# 将 debs/ 或 rpms/ 目录和 install.sh 复制到目标机器，然后：
sudo bash install.sh
```

## 配置

pkgeter 将持久配置保存在 `~/.config/pkgeter/config.yaml`。运行工具时会自动创建此文件。

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

命令行参数优先级高于配置文件。可用预设快速填充配置：

```bash
pkgeter preset apply centos-9
```

## 工作原理

1. **下载包数据库** — 从配置的源获取元数据（Debian 用 Packages.gz，RPM 用 repomd.xml + primary.xml.gz）
2. **解析依赖树** — 递归解析所有需要的包（支持 AND/OR 依赖、虚拟包、循环检测）
3. **下载包文件** — 下载每个包并进行 SHA256 校验
4. **生成输出** — 生成 `debs/` 或 `rpms/` 目录和 `install.sh` 安装脚本，或 `--repo` 时生成本地源结构

## 发行版预设

| 预设 | 后端 | 包含仓库 |
|------|------|---------|
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

## 许可证

MIT
