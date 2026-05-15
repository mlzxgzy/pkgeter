# Preset 层级化重构设计

## 概述

将 `presets.yaml` 从扁平的 `系统-版本` 单级 key 结构，改为 **系统 → 版本** 两级层级结构。同时简化 mirrors 配置（从完整 repos 列表改为 URL-only 覆盖），改进 `preset list` 输出格式和 REPL 补全体验。

## 目标

1. **YAML 去重**：多版本系统（debian、centos）用 `{version}` 模板，repos 和 mirrors 只写一次
2. **mirrors 简化**：mirrors 只写 `repo名: 镜像URL`，其余字段从默认 repos 继承
3. **preset list 分组**：按系统分组展示版本，不再是扁平列表
4. **REPL 层级补全**：`deb<TAB>` → `debian-`，`debian-<TAB>` → 显示版本列表
5. **CLI 兼容**：`--distro debian-bookworm` 用法不变，新增 `@cn` 后缀支持镜像选择

## 新 presets.yaml 结构

### 两种版本模式

**模板模式**（`versions` 为 list）—— 适用于多版本、repos 结构一致的系统：

```yaml
debian:
  backend: apt
  arch: amd64
  versions: [bookworm, bullseye, trixie]
  repos:
    - name: main
      type: deb
      url: https://deb.debian.org/debian
      release: "{version}"
      components: [main]
    - name: security
      type: deb
      url: https://security.debian.org/debian-security
      release: "{version}-security"
      components: [main]
    - name: updates
      type: deb
      url: https://deb.debian.org/debian
      release: "{version}-updates"
      components: [main]
  mirrors:
    cn:
      main: https://mirrors.ustc.edu.cn/debian
      security: https://mirrors.ustc.edu.cn/debian-security
      updates: https://mirrors.ustc.edu.cn/debian
```

**显式模式**（`versions` 为 dict）—— 适用于单版本或 repos 结构特殊的系统：

```yaml
pve:
  backend: apt
  arch: amd64
  versions:
    "8":
      repos:
        - name: main
          type: deb
          url: https://deb.debian.org/debian
          release: bookworm
          components: [main]
        - name: security
          type: deb
          url: https://security.debian.org/debian-security
          release: bookworm-security
          components: [main]
        - name: updates
          type: deb
          url: https://deb.debian.org/debian
          release: bookworm-updates
          components: [main]
        - name: pve-no-subscription
          type: deb
          url: https://download.proxmox.com/debian/pve
          release: bookworm
          components: [pve-no-subscription]
      mirrors:
        cn:
          main: https://mirrors.ustc.edu.cn/debian
          security: https://mirrors.ustc.edu.cn/debian-security
          updates: https://mirrors.ustc.edu.cn/debian
          pve-no-subscription: https://mirrors.ustc.edu.cn/proxmox/debian/pve
```

### mirrors URL-only 覆盖规则

mirrors 节点只声明 `repo名: 镜像URL` 映射。当用户选择 `debian-bookworm@cn` 时，加载逻辑：

1. 先按模板/显式模式生成基础 repos（含 type、release、components 等完整字段）
2. 遍历基础 repos，如果 repo name 在 mirrors.cn 映射中存在，用映射的 URL 替换原 URL
3. 其余字段（type、release、components）不变

### 完整 YAML 示例

```yaml
debian:
  backend: apt
  arch: amd64
  versions: [bookworm, bullseye, trixie]
  repos:
    - name: main
      type: deb
      url: https://deb.debian.org/debian
      release: "{version}"
      components: [main]
    - name: security
      type: deb
      url: https://security.debian.org/debian-security
      release: "{version}-security"
      components: [main]
    - name: updates
      type: deb
      url: https://deb.debian.org/debian
      release: "{version}-updates"
      components: [main]
  mirrors:
    cn:
      main: https://mirrors.ustc.edu.cn/debian
      security: https://mirrors.ustc.edu.cn/debian-security
      updates: https://mirrors.ustc.edu.cn/debian

centos:
  backend: rpm
  arch: x86_64
  versions: ["9"]
  repos:
    - name: baseos
      type: rpm
      url: https://mirror.stream.centos.org/{version}-stream/BaseOS/x86_64/os
    - name: appstream
      type: rpm
      url: https://mirror.stream.centos.org/{version}-stream/AppStream/x86_64/os
    - name: epel
      type: rpm
      url: https://dl.fedoraproject.org/pub/epel/{version}/Everything/x86_64
  mirrors:
    cn:
      baseos: https://mirrors.ustc.edu.cn/centos-stream/{version}-stream/BaseOS/x86_64/os
      appstream: https://mirrors.ustc.edu.cn/centos-stream/{version}-stream/AppStream/x86_64/os
      epel: https://mirrors.ustc.edu.cn/epel/{version}/Everything/x86_64

pve:
  backend: apt
  arch: amd64
  versions:
    "8":
      repos:
        - name: main
          type: deb
          url: https://deb.debian.org/debian
          release: bookworm
          components: [main]
        - name: security
          type: deb
          url: https://security.debian.org/debian-security
          release: bookworm-security
          components: [main]
        - name: updates
          type: deb
          url: https://deb.debian.org/debian
          release: bookworm-updates
          components: [main]
        - name: pve-no-subscription
          type: deb
          url: https://download.proxmox.com/debian/pve
          release: bookworm
          components: [pve-no-subscription]
      mirrors:
        cn:
          main: https://mirrors.ustc.edu.cn/debian
          security: https://mirrors.ustc.edu.cn/debian-security
          updates: https://mirrors.ustc.edu.cn/debian
          pve-no-subscription: https://mirrors.ustc.edu.cn/proxmox/debian/pve

kylin:
  backend: rpm
  arch: x86_64
  versions:
    V10:
      repos:
        - name: base
          type: rpm
          url: https://update.cs2c.com.cn/NS/V10/V10SP3-2403/os/adv/lic/base/x86_64
        - name: updates
          type: rpm
          url: https://update.cs2c.com.cn/NS/V10/V10SP3-2403/os/adv/lic/updates/x86_64
```

## preset.py 代码变更

### 加载逻辑

`_load_presets()` 改为读取新的层级 YAML，展开为内部扁平映射 `Dict[str, preset_dict]`。

展开伪代码：

```python
def _expand_system(system_name, data):
    versions = data["versions"]
    base_repos = data.get("repos", [])
    mirrors = data.get("mirrors", {})

    if isinstance(versions, list):
        # 模板模式：替换 {version}
        for ver in versions:
            key = f"{system_name}-{ver}"
            repos = _substitute_version(base_repos, ver)
            yield key, {
                "backend": data["backend"],
                "arch": data.get("arch", ""),
                "repos": repos,
                "mirrors": _substitute_mirrors(mirrors, ver),
            }
    else:
        # 显式模式：每个 version 有自己的 repos
        for ver, ver_data in versions.items():
            key = f"{system_name}-{ver}"
            repos = ver_data["repos"]
            ver_mirrors = ver_data.get("mirrors", mirrors)
            yield key, {
                "backend": data["backend"],
                "arch": data.get("arch", ""),
                "repos": repos,
                "mirrors": ver_mirrors,
            }
```

### `{version}` 替换

对 repos 列表中每个 repo dict 的所有 string 值做 `str.replace("{version}", ver)` 替换。mirrors URL 值同理。

### `@variant` 解析

`get_preset(name)` 接收 `debian-bookworm@cn` 格式：

1. 用 `@` 分割出 variant（默认为 `"default"`）
2. 用 `系统-版本` 查找基础 preset
3. 如果 variant 不是 `"default"`，从 preset 的 mirrors 映射中取对应 variant 的 URL 覆盖
4. 复制基础 repos，按 repo name 替换 URL
5. 返回替换后的 preset dict

### 公共 API 变更

| 函数 | 旧签名/返回值 | 新签名/返回值 |
|------|--------------|--------------|
| `list_presets()` | `list[str]`（扁平名称列表） | `dict[str, dict]`，格式为 `{"debian": {"versions": ["bookworm", "bullseye", "trixie"], "variants": ["cn"]}, ...}`。`variants` 为该系统可用的 mirror variant 名列表（不含 "default"），无 mirror 时为空列表 |
| `get_preset(name, mirror_variant)` | 两个参数 | `get_preset(name)` 单参数，variant 从 `@` 后缀解析；保留 `mirror_variant` 参数作为 fallback 兼容。**优先级**：name 中的 `@variant` > `mirror_variant` 参数 > config 中的默认值 |
| 新增 `list_systems()` | — | `list[str]` 系统名列表 |

### 调用方适配

- `get.py` / `search.py`：`--distro` 值现在可以含 `@variant` 后缀，传给 `get_preset()` 即可。当 `--cn` flag 存在且 `--distro` 不含 `@`，自动拼接 `@cn`。
- `repl.py`：`emptyline()` 中展示分组 preset 列表；快速切换（直接输入 preset 名）支持 `@variant`。
- `config.py`：`mirror_variant` 配置项保留，作为默认 variant。当 preset 名不含 `@` 时从 config 读取默认 variant。

## preset list 输出格式

```
Available presets:
  debian:       bookworm, bullseye, trixie  (@cn)
  centos:       9  (@cn)
  pve:          8  (@cn)
  kylin:        V10

Usage: preset apply debian-bookworm
       preset apply debian-bookworm@cn
```

系统名左对齐，版本列表逗号分隔，末尾括号内列出可用 mirror variants。无 mirror 的系统不显示括号。

## REPL 补全改进

TAB 补全分层：

1. `deb<TAB>` → `debian-`
2. `debian-<TAB>` → `bookworm  bullseye  trixie`
3. `debian-bookworm<TAB>` → `debian-bookworm  debian-bookworm@cn`

在 `completenames()` 和 `complete_preset()` 中实现。逻辑：

- 如果输入不含 `-`，匹配系统名前缀，补全到 `系统名-`
- 如果输入含 `-`，拆分出系统名和版本前缀，匹配该系统下的版本
- 如果输入已是完整的 `系统-版本`，追加可用的 `@variant` 选项

## 测试变更

- `test_preset.py` 的 `SAMPLE_PRESETS_YAML` fixture 改成新层级格式
- `list_presets()` 返回值从 `list[str]` 变成 `dict`，断言更新
- 新增测试用例：
  - 模板展开（`{version}` 替换）
  - `@cn` mirror variant 解析和 URL 替换
  - 显式版本模式（PVE 风格）
  - 未知 variant fallback 到 default
  - `list_systems()` 返回值
  - REPL 补全层级行为

## 不做的事

- 不引入 `base` 继承机制（PVE 不从 debian 继承）
- 不拆分 `--distro` 为两个 CLI 参数
- 不改变 config.yaml 的结构
- 不改变 RepoConfig 数据类
