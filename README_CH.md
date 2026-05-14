# pkgeter <small>v1.0</small>

**中文** | [English](README.md)

**离线 Debian 包下载工具** — 解析依赖、下载 `.deb` 文件，并生成离线安装脚本。

跨平台支持（Linux、Windows、macOS）—— 当需要在离线机器上安装 Debian 包时非常有用。

## 特性

- **依赖解析** — 递归解析目标包的所有依赖
- **跳过已安装包** — 可提供 `dpkg -l` 输出，跳过已安装的包
- **SHA256 校验** — 验证每个下载的 `.deb` 文件
- **离线安装脚本** — 自动生成按依赖顺序安装的 `install.sh`
- **持久配置** — 配置保存在 `~/.config/pkgeter/config.yaml`

## 安装
### 从源码安装

```bash
git clone https://github.com/mlzxgzy/pkgeter.git
cd pkgeter
pip install -e .
```

## 使用方法

```bash
# 下载 vim 及其所有依赖
pkgeter -p vim

# 下载多个包
pkgeter -p nginx curl git

# 指定自定义输出目录
pkgeter -p python3 -o ./my-output

# 指定 Debian 版本和架构
pkgeter -p docker.io -r bookworm -a arm64

# 跳过目标机器上已安装的包
pkgeter -p nginx --dpkg-list /path/to/dpkg-l-output.txt

# 使用自定义配置文件
pkgeter -p vim --config /path/to/config.yaml
```

## 输出

所有 `.deb` 文件将输出到指定目录下的 `debs/` 子目录中，并生成 `install.sh`，按依赖顺序执行 `dpkg -i` 安装。在目标机器上：

```bash
# 将 debs/ 目录和 install.sh 复制到目标机器，然后：
sudo bash install.sh
```

## 配置

pkgeter 将持久配置保存在 `~/.config/pkgeter/config.yaml`。运行工具时会自动创建此文件。

配置示例：

```yaml
release: bookworm
arch: amd64
mirror: https://deb.debian.org/debian
output_dir: ./output
```

命令行参数优先级高于配置文件。如果配置文件不存在，将使用合理的默认值（Linux 系统会尝试自动检测本机的 release 和 arch）。

## 工作原理

1. **下载包数据库** — 从指定的 Debian 镜像源获取 `Packages.gz`
2. **解析依赖树** — 递归解析所有需要的包
3. **下载 `.deb` 文件** — 下载每个包并进行 SHA256 校验
4. **生成输出** — 生成 `debs/` 目录和 `install.sh` 安装脚本

## 许可证

MIT
