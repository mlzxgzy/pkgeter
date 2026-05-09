# pkgeter <small>v0.1</small>

**离线 Debian 包下载工具** — 解析依赖、下载 `.deb` 文件，并生成离线安装脚本。

跨平台支持（Linux、Windows、macOS）—— 当需要在离线或气隙机器上安装 Debian 包时非常有用。

## 特性

- **依赖解析** — 递归解析目标包的所有依赖
- **跳过已安装包** — 可提供 `dpkg -l` 输出，跳过已安装的包
- **SHA256 校验** — 验证每个下载的 `.deb` 文件
- **离线安装脚本** — 自动生成按依赖顺序安装的 `install.sh`
- **持久配置** — 配置保存在 `~/.config/pkgeter/config.yaml`
