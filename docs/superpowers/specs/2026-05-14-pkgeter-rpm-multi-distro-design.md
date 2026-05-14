# pkgeter — RPM 多发行版支持 + REPL 解释器

## 概述

在现有 Debian/apt 离线下载能力的基础上，为 pkgeter 增加：

1. **RPM 后端** — 支持 CentOS Stream 等 RPM 系发行版的 `.rpm` 包下载
2. **后端抽象层** — `PmBackend` 接口统一不同包管理器
3. **发行版预设系统** — 一条命令选择 Debian / CentOS / Ubuntu / PVE
4. **多源合并** — 自动组合多个仓库（如 main + security，BaseOS + AppStream + EPEL）
5. **`--repo` 管理** — 增删查自定义仓库
6. **REPL 解释器** — 类交换机命令行，前缀匹配 + TAB 补全

---

## 1. CLI 子命令结构

入口行为：

```
$ pkgeter                    → 进入 REPL 解释器
$ pkgeter get -p nginx ...  → 直接执行 get 子命令
$ pkgeter g -p nginx ...    → 前缀匹配，等价于 get
$ pkgeter repo list          → 直接执行 repo 子命令
$ pkgeter r list             → 等价于 repo
```

子命令树：

```
pkgeter
├── get (g)      下载包及其依赖
├── repo (r)     仓库管理
│   ├── list             列出已配置仓库
│   ├── add <options>    添加自定义仓库
│   └── remove <name>    删除仓库
├── preset       发行版预设管理
│   ├── list             列出可用预设
│   └── apply <name>     应用预设到配置
├── help (h)     帮助
└── exit (ex)    退出
```

### 前缀匹配规则

所有子命令和子子命令均支持唯一前缀匹配：

| 输入 | 匹配 | 说明 |
|------|------|------|
| `g` | `get` | 唯一匹配 |
| `ge` | `get` | 唯一匹配 |
| `r` | `repo` | 唯一匹配 |
| `re` | `repo` | 唯一匹配 |
| `pr` | `preset` | 唯一匹配 |
| `h` | `help` | 唯一匹配 |
| `ex` | `exit` | 唯一匹配（`exit`/`quit`/`bye`） |

有歧义时提示用户。

---

## 2. REPL 解释器

基于 Python 标准库 `cmd.Cmd`（零额外依赖），内置 readline 支持。

```
pkgeter>

    ╔══════════════════════════════════════╗
    ║  pkgeter — Offline package downloader ║
    ║  Type ? or help for available commands ║
    ╚══════════════════════════════════════╝

pkgeter> help
Commands:
  get (g)    <options>   Download packages and dependencies
  repo (r)   <command>   Manage repositories (list/add/remove)
  preset                List/apply distribution presets
  help (h)              Show this help
  exit (ex)             Exit the REPL
```

- TAB 补全命令名和参数
- REPL 内部共享 Config 实例，`get` 执行后回到 REPL
- 历史记录通过 readline 自动支持（上下键）

### 实现

```python
class PkgeterREPL(cmd.Cmd):
    intro = "pkgeter — Offline package downloader. Type help."
    prompt = "pkgeter> "

    COMMANDS = {
        "get": "get", "repo": "repo", "preset": "preset",
        "help": "help", "exit": "exit", "quit": "exit", "bye": "exit",
    }

    def default(self, line):
        cmd, *args = line.split(maxsplit=1)
        resolved = self._resolve(cmd)
        if resolved == "get":    return self.do_get(args[0] if args else "")
        elif resolved == "repo": return self.do_repo(args[0] if args else "")
        ...

    def _resolve(self, cmd):
        candidates = [k for k in self.COMMANDS if k.startswith(cmd)]
        if len(candidates) == 1: return self.COMMANDS[candidates[0]]
        ...
```

---

## 3. Repo 管理系统

### 子系统 `repo.py`

```
repo list          → 打印当前配置的所有仓库
repo add ...       → 添加仓库（key-value 参数）
repo remove <name> → 按 name 删除
```

`repo add` 参数：

```
pkgeter repo add --name debian-main
                  --type deb|rpm
                  --url https://deb.debian.org/debian       # deb 类型必填
                  --baseurl https://mirror.example.com/...  # rpm 类型必填
                  --release bookworm                        # deb 必填
                  --components main,contrib                  # deb 可选
                  --arch amd64                               # 可选
```

### 配置存储

```yaml
# ~/.config/pkgeter/config.yaml
backend: debian
arch: amd64

repos:
  - name: debian-main
    type: deb
    url: https://deb.debian.org/debian
    release: bookworm
    components: [main]
  - name: debian-security
    type: deb
    url: https://security.debian.org/debian-security
    release: bookworm-security
    components: [main]
```

---

## 4. 发行版预设系统

### 预设数据

内置在 `preset.py` 中：

```python
PRESETS: dict[str, Preset] = {
    "debian-bookworm": Preset(
        backend="debian",
        arch="amd64",
        repos=[
            RepoConfig("debian-main",     "deb", "https://deb.debian.org/debian",                release="bookworm"),
            RepoConfig("debian-security", "deb", "https://security.debian.org/debian-security", release="bookworm-security"),
            RepoConfig("debian-updates",  "deb", "https://deb.debian.org/debian",                release="bookworm-updates"),
        ],
    ),
    "centos-9": Preset(
        backend="rpm",
        arch="x86_64",
        repos=[
            RepoConfig("centos-baseos",    "rpm", "https://mirror.stream.centos.org/9-stream/BaseOS/x86_64/os"),
            RepoConfig("centos-appstream", "rpm", "https://mirror.stream.centos.org/9-stream/AppStream/x86_64/os"),
            RepoConfig("epel",             "rpm", "https://dl.fedoraproject.org/pub/epel/9/Everything/x86_64"),
        ],
    ),
}
```

预设通过 `pkgeter preset apply debian-bookworm` 导入到配置中（复制到 `repos` 列表）。

### get 的仓库选择逻辑

```
1. --distro <name>  → 加载预设，忽略配置中的 repos
2. 配置中有 repos   → 使用配置的 repos
3. 都没有            → 默认加载 debian-bookworm 预设
```

---

## 5. 后端抽象层 `PmBackend`

### 接口定义

```python
class PmBackend(ABC):
    name: str  # "debian" | "rpm"

    @abstractmethod
    def download_package_db(self, repos: list[RepoConfig], arch: str) -> dict[str, PackageInfo]:
        """下载所有 repo 的元数据并合并为一个包数据库。"""

    @abstractmethod
    def build_download_url(self, repo_url: str, pkg: PackageInfo) -> str:
        """构造包的远程下载 URL。"""

    @abstractmethod
    def generate_install_script(self, files: list[str], targets: list[str]) -> str:
        """生成安装脚本内容。"""

    @abstractmethod
    def list_installed_packages(self) -> set[str]:
        """返回本机已安装的包名集合（默认空）。"""
```

### 数据流

```
CLI (子命令分发)
  │
  └─ get 子命令
       │
       ├─ repo 列表（来自预设 / 配置）
       │
       └─ PmBackend.download_package_db(repos, arch)
            │  逐个 repo:
            │    Debian: 下载 Release → Packages.gz
            │    RPM:    下载 repomd.xml → primary.xml.gz
            │  合并为 Dict[str, PackageInfo]
            ▼
          Resolver.resolve(packages)  ← 通用，不变
            ▼
          Downloader.download_all()   ← 通用，不变
            ▼
          OutputFormat.execute()      ← 根据后端生成不同脚本
```

### 多源合并策略

当同一个包名出现在多个 repo 时：

```
repo A: openssl 3.0.15
repo B: openssl 3.0.16 (security)
→ 取 version 更高的那个
```

简单版本比较（逐段比较数字）。合并顺序：repo 列表顺序，后面的 repo 中的包覆盖前面的同名包。

---

## 6. Debian 后端

从现有 `db/packages.py` + `deps/virtual.py` 迁移逻辑到 `backend/debian.py`。

```
DebianBackend.download_package_db(repos, arch):
  for each repo:
    url = f"{repo.url}/dists/{repo.release}/main/binary-{arch}/Packages.gz"
    缓存 → download → parse_stanza → PackageInfo dict
    合并到全局 dict
  return global_dict

DebianBackend.build_download_url(repo_url, pkg):
  return f"{repo_url}/{pkg.filename}"

DebianBackend.generate_install_script(files, targets):
  → dpkg -i 逐条安装
```

### 兼容层

`db/packages.py` 和 `deps/virtual.py` 保留为 import 重定向：

```python
# db/packages.py
from pkgeter.backend.debian import download_package_db, parse_packages_file, ...
```

避免破坏现有测试。

---

## 7. RPM 后端

### 元数据下载流程

```
RpmBackend.download_package_db(repos, arch):
  for each repo:
    1. 下载 {repo.baseurl}/repodata/repomd.xml
    2. 解析 XML，提取 primary.xml.gz 的路径 {hash}-primary.xml.gz
    3. 下载 {repo.baseurl}/repodata/{hash}-primary.xml.gz
    4. 解压并解析 XML → PackageInfo dict
    合并到全局 dict
  return global_dict
```

### repomd.xml → primary.xml.gz

```xml
<repomd>
  <data type="primary">
    <location href="repodata/{sha}-primary.xml.gz"/>
    <checksum type="sha256">{sha256}</checksum>
  </data>
</repomd>
```

### primary.xml.gz → PackageInfo 映射

```xml
<package type="rpm">
  <name>openssl</name>
  <arch>x86_64</arch>
  <version epoch="0" ver="1.1.1k" rel="7.el8_9"/>
  <format>
    <rpm:requires>
      <rpm:entry name="libc.so.6()(64bit)"/>
    </rpm:requires>
    <rpm:provides>
      <rpm:entry name="openssl" flags="EQ" epoch="0" ver="1.1.1k"/>
    </rpm:provides>
  </format>
  <location href="Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm"/>
  <checksum type="sha256">abc123...</checksum>
</package>
```

映射为：

```python
PackageInfo(
    package="openssl",
    version="1:1.1.1k-7.el8_9",    # epoch:ver-rel
    depends=[[Dep("libc.so.6()(64bit)")]],
    provides=["openssl"],
    arch="x86_64",
    filename="Packages/openssl-1.1.1k-7.el8_9.x86_64.rpm",
    sha256="abc123...",
)
```

### RPM 缓存

复用 `source_cache.py` 的 SHA256 缓存机制，独立缓存路径：

```
~/.config/pkgeter/sources/
  mirror.stream.centos.org_.../
    9-stream/
      x86_64/
        repomd.xml
        primary.xml.gz
```

### RPM 安装脚本

```bash
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
sudo rpm -ivh "openssl-1.1.1k-7.el8_9.x86_64.rpm"
sudo rpm -ivh "nginx-1.20.1-1.el8_9.x86_64.rpm"
```

---

## 8. 文件结构

```
pkgeter/
├── __main__.py        # run_cli()
├── cli.py             # 入口分发: REPL / 子命令路由
├── repl.py            # PkgeterREPL (cmd.Cmd)
├── get.py             # get 子命令
├── repo.py            # repo 子命令 (list/add/remove)
├── preset.py          # preset 子命令 + PRESETS 数据
├── config.py          # + repos 配置管理
├── models.py          # PackageInfo（不变）
├── downloader.py      # 不变
├── backend/
│   ├── __init__.py    # PmBackend 抽象基类
│   ├── debian.py      # Debian 实现
│   └── rpm.py         # RPM 实现
├── deps/
│   ├── resolver.py    # 不变
├── db/
│   ├── dpkg_list.py   # 不变
│   └── source_cache.py# 不变（可被 RPM 复用）
└── output/
    ├── base.py        # 不变
    ├── deb_directory.py
    └── rpm_directory.py
```

---

## 9. 不变的部分

- `models.py` — `PackageInfo`, `Dependency`, `parse_depends_line` 完全通用
- `deps/resolver.py` — Resolver 不变，按 `PackageInfo.depends` 解析
- `downloader.py` — Downloader 不变，按 URL + SHA256 下载
- `db/source_cache.py` — 缓存机制不变，RPM 复用
- `output/base.py` — OutputFormat 抽象类不变
- `output/deb_directory.py` — 不变

### 兼容层（后迁移）

```python
# db/packages.py → import redirect
from pkgeter.backend.debian import *  # noqa
```

---

## 10. 错误处理

| 场景 | 行为 |
|------|------|
| repomd.xml 下载失败 | 跳过该 repo，有缓存用缓存 |
| primary.xml.gz SHA256 不匹配 | 跳过，不保存 |
| primary.xml.gz 解析错误 | 跳过，打印错误 |
| 多 repo 都失败 | get 命令报错退出 |
| REPL 中输入未知命令 | 提示 "Unknown command: xxx" |
| REPL 中输入歧义前缀 | 提示 "Ambiguous command: x (candidates)" |
| repo add 缺少必填参数 | 提示缺少的参数并退出 |

---

## 11. 测试计划

| 模块 | 测试内容 |
|------|----------|
| `backend/rpm.py` | repomd.xml 解析、primary.xml.gz 解析、PackageInfo 映射、缓存 |
| `backend/debian.py` | 现有 packages.py 测试迁移 |
| `get.py` | 参数解析、预设选择、多 repo 合并 |
| `repo.py` | list/add/remove、配置读写 |
| `preset.py` | preset 列表、apply 写入配置 |
| `repl.py` | 前缀匹配、TAB 补全、命令路由 |
| `cli.py` | 入口分发、子命令路由 |

---

## 12. 依赖

无新增运行时依赖。用到的都是标准库：

- `xml.etree.ElementTree` — primary.xml.gz 解析
- `cmd` — REPL 框架
- `readline` — TAB 补全（Unix，Windows 上 `pyreadline` 可选）

dev 依赖不变：`pytest`。

---

## 13. 不做（未来再做）

- **版本约束解析** — 目前仅按名字匹配，不比较版本号选择满足约束的包
- **TUI** — 原设计文档中的 Textual 界面，时机到了再做
- **ISO 输出** — apt repo + ISO 打包
- **断点续传** — 下载中断需重头来
- **Ubuntu/PVE/OpenSUSE 预设** — 加预设就是加点数据，架构不变
- **`rpm -qa` 输入** — 跳过已安装包检测第一版不做
