# pkgeter <small>v1.1</small>

**中文** | [English](README.md)

**离线包下载工具** — 支持 **Debian/apt** 和 **RPM/dnf**（CentOS Stream）。解析依赖树、下载 `.deb` 或 `.rpm` 文件，并生成离线安装脚本。

跨平台支持（Linux、Windows、macOS）—— 当需要在离线机器上安装包时非常有用。

## 特性

- **双后端** — 支持 Debian（`dpkg`）和 RPM（`rpm`）系发行版
- **发行版预设** — 一条命令选择：`--distro debian-bookworm`、`--distro centos-9`
- **交互式 REPL** — 直接运行 `pkgeter` 进入类交换机命令行，支持前缀匹配和 TAB 补全
- **多源合并** — 自动组合多个仓库（如 main + security，BaseOS + AppStream + EPEL）
- **依赖解析** — 递归解析目标包的所有依赖
- **SHA256 校验** — 验证每个下载的 `.deb` 或 `.rpm` 文件
- **源缓存** — 缓存仓库元数据并用 SHA256 校验（类似 APT），只下载变更部分
- **离线安装脚本** — 自动生成按依赖顺序安装的 `install.sh`（`dpkg -i` 或 `rpm -ivh`）
- **多镜像源** — 可指定多个镜像，按顺序尝试，直到成功
- **持久配置** — 配置保存在 `~/.config/pkgeter/config.yaml`
- **源管理** — 通过 `pkgeter repo` 添加、列出、删除自定义源

## 安装
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
pkgeter get -p nginx --distro debian-bullseye

# 支持前缀简写
pkgeter g -p nginx --distro centos-9

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

## 输出

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
2. **解析依赖树** — 递归解析所有需要的包
3. **下载包文件** — 下载每个包并进行 SHA256 校验
4. **生成输出** — 生成 `debs/` 或 `rpms/` 目录和 `install.sh` 安装脚本

## 发行版预设

| 预设 | 后端 | 包含仓库 |
|------|------|---------|
| `debian-bookworm` | deb | main, security, updates |
| `debian-bullseye` | deb | main, security, updates |
| `centos-9` | rpm | BaseOS, AppStream, EPEL |

## 许可证

MIT
