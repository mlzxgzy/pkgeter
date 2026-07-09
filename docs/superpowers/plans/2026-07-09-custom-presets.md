# Custom Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split built-in presets from user custom presets by moving user overrides to `~/.config/pkgeter/custom-presets.yaml` and loading merged results without reading legacy `presets.yaml`.

**Architecture:** Keep all preset loading in `pkgeter/preset.py`. Load built-in presets first, then optionally load `custom-presets.yaml`, merge custom entries into built-ins by preset key, then expose merged data to preset listing, completion, lookup, and `preset apply`.

**Tech Stack:** Python 3.10+, PyYAML, pytest, existing `RepoConfig` dataclass and preset CLI flow.

## Global Constraints

- Built-in presets must load from `pkgeter/data/presets.yaml`.
- User custom presets must load only from `~/.config/pkgeter/custom-presets.yaml`.
- Legacy `~/.config/pkgeter/presets.yaml` must not be read.
- Missing `custom-presets.yaml` must be treated as normal.
- `preset apply <name>` must keep writing merged concrete repos into `config.yaml`.
- No automatic seeding or copying of built-in presets into user config directory.
- Follow TDD: every production behavior change starts with failing tests.

---

### Task 1: Switch preset loader to custom-presets path

**Files:**
- Modify: `pkgeter/preset.py`
- Test: `tests/test_preset.py`

**Interfaces:**
- Consumes: existing `_load_presets() -> dict[str, Any]`, `reload_presets() -> None`
- Produces: `_CUSTOM_PRESETS: Path`, `_load_presets() -> dict[str, Any]` that reads built-in presets plus optional custom preset file

- [ ] **Step 1: Write failing test for missing custom file fallback**

```python
def test_missing_custom_preset_file_uses_builtin_only(self, preset_file):
    builtin, user = preset_file
    builtin.write_text(SAMPLE_PRESETS_YAML, encoding="utf-8")
    if user.exists():
        user.unlink()
    reload_presets()

    preset = get_preset("debian-bookworm")

    assert preset is not None
    assert preset["backend"] == "apt"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_preset.py::TestGetPreset::test_missing_custom_preset_file_uses_builtin_only -v`
Expected: FAIL because fixture or loader still depends on legacy user preset path behavior.

- [ ] **Step 3: Write minimal implementation**

```python
_BUILTIN_PRESETS = _PACKAGE_DIR / "data" / "presets.yaml"
_CUSTOM_PRESETS = CONFIG_PATH.parent / "custom-presets.yaml"

if not _CUSTOM_PRESETS.exists():
    user_raw = {}
else:
    custom_text = _CUSTOM_PRESETS.read_text(encoding="utf-8")
    user_candidate = yaml.safe_load(custom_text) or {}
    user_raw = {k: v for k, v in user_candidate.items() if isinstance(v, dict)}
```

Also remove seed/reset logic tied to `presets.yaml`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest pytest tests/test_preset.py::TestGetPreset::test_missing_custom_preset_file_uses_builtin_only -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pkgeter/preset.py tests/test_preset.py
git commit -m "refactor: load custom presets from dedicated file"
```

### Task 2: Lock merge behavior for custom repo and mirror overrides

**Files:**
- Modify: `tests/test_preset.py`
- Modify: `pkgeter/preset.py`
- Test: `tests/test_preset.py`

**Interfaces:**
- Consumes: `_merge_preset_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]`
- Produces: merged preset behavior where repos merge by `name` and mirror URLs merge by repo-name key

- [ ] **Step 1: Write failing tests for custom repo and mirror merge**

```python
def test_user_override_merges_missing_fields_from_builtin(self, preset_file):
    builtin, user = preset_file
    builtin.write_text(
        SAMPLE_PRESETS_YAML
        + """

pve-8:
  system: pve
  backend: apt
  arch: amd64
  repos:
    - name: main
      type: deb
      url: https://deb.debian.org/debian
      release: bookworm
      components: [main]
    - name: pve-no-subscription
      type: deb
      url: https://download.proxmox.com/debian/pve
      release: bookworm
      components: [pve-no-subscription]
  mirrors:
    - name: cn
      provider: ustc
      urls:
        main: https://mirrors.ustc.edu.cn/debian
        pve-no-subscription: https://mirrors.ustc.edu.cn/proxmox/debian/pve
""",
        encoding="utf-8",
    )
    user.write_text(CUSTOM_PRESETS_YAML, encoding="utf-8")
    reload_presets()

    preset = get_preset("pve-8@cn")

    assert preset is not None
    repos = {repo.name: repo for repo in preset["repos"]}
    assert set(repos) == {"main", "pve-no-subscription", "ceph-squid"}
    assert repos["ceph-squid"].url == "https://mirrors.ustc.edu.cn/proxmox/debian/ceph-squid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_preset.py::TestGetPreset::test_user_override_merges_missing_fields_from_builtin -v`
Expected: FAIL with missing merged data or missing scalar keys.

- [ ] **Step 3: Write minimal implementation**

```python
def _merge_preset_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)

    for key in ("system", "backend", "arch"):
        if key in override:
            merged[key] = override[key]

    if "repos" in override:
        base_repos = {
            item.get("name", ""): item
            for item in base.get("repos", [])
            if isinstance(item, dict) and item.get("name")
        }
        for item in override.get("repos", []):
            if isinstance(item, dict) and item.get("name"):
                base_repos[item["name"]] = item
        merged["repos"] = list(base_repos.values())

    if "mirrors" in override:
        base_mirrors = {
            item.get("name", ""): item
            for item in base.get("mirrors", [])
            if isinstance(item, dict) and item.get("name")
        }
        for item in override.get("mirrors", []):
            if not isinstance(item, dict) or not item.get("name"):
                continue
            name = item["name"]
            existing = base_mirrors.get(name, {})
            merged_mirror = dict(existing)
            merged_mirror.update({k: v for k, v in item.items() if k != "urls"})
            urls = dict(existing.get("urls", {})) if isinstance(existing.get("urls"), dict) else {}
            urls.update(item.get("urls", {}))
            merged_mirror["urls"] = urls
            base_mirrors[name] = merged_mirror
        merged["mirrors"] = list(base_mirrors.values())

    return merged
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest pytest tests/test_preset.py::TestGetPreset::test_user_override_merges_missing_fields_from_builtin -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pkgeter/preset.py tests/test_preset.py
git commit -m "feat: merge custom preset overrides by entry name"
```

### Task 3: Prove legacy presets.yaml is ignored

**Files:**
- Modify: `tests/test_preset.py`
- Test: `tests/test_preset.py`

**Interfaces:**
- Consumes: `_CUSTOM_PRESETS` path behavior from Task 1
- Produces: test coverage proving only `custom-presets.yaml` is read from config directory

- [ ] **Step 1: Write failing test for ignored legacy file**

```python
def test_legacy_presets_yaml_is_ignored(self, tmp_path: Path):
    builtin = tmp_path / "builtin-presets.yaml"
    builtin.write_text(SAMPLE_PRESETS_YAML, encoding="utf-8")
    custom = tmp_path / "custom-presets.yaml"
    legacy = tmp_path / "presets.yaml"
    legacy.write_text(
        """
pve-8:
  repos:
    - name: ceph-squid
      type: deb
      url: https://legacy.example.invalid/debian/ceph-squid
      release: bookworm
      components: [no-subscription]
""",
        encoding="utf-8",
    )

    with patch("pkgeter.preset._BUILTIN_PRESETS", builtin), patch("pkgeter.preset._CUSTOM_PRESETS", custom):
        reload_presets()
        preset = get_preset("pve-8")

    assert preset is None
```
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_preset.py::TestGetPreset::test_legacy_presets_yaml_is_ignored -v`
Expected: FAIL if loader still reads legacy path or fixture assumptions need update.

- [ ] **Step 3: Write minimal implementation**

```python
# No production code expected if Task 1 already removed legacy reads.
# If failure shows remaining legacy path references, delete them.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest pytest tests/test_preset.py::TestGetPreset::test_legacy_presets_yaml_is_ignored -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_preset.py pkgeter/preset.py
git commit -m "test: lock legacy preset file deprecation"
```

### Task 4: Keep preset apply behavior on merged data

**Files:**
- Modify: `tests/test_preset.py`
- Test: `tests/test_preset.py`

**Interfaces:**
- Consumes: `run_preset(argv: list[str] | None = None) -> None`
- Produces: coverage that `preset apply` writes merged repo list and chosen variant to config

- [ ] **Step 1: Write failing test for merged apply output**

```python
def test_apply_merged_custom_preset(self, preset_file, capsys):
    builtin, user = preset_file
    builtin.write_text(
        SAMPLE_PRESETS_YAML
        + """

pve-8:
  system: pve
  backend: apt
  arch: amd64
  repos:
    - name: main
      type: deb
      url: https://deb.debian.org/debian
      release: bookworm
      components: [main]
  mirrors:
    - name: cn
      provider: ustc
      urls:
        main: https://mirrors.ustc.edu.cn/debian
""",
        encoding="utf-8",
    )
    user.write_text(CUSTOM_PRESETS_YAML, encoding="utf-8")
    reload_presets()

    with patch("pkgeter.preset.Config") as MockConfig:
        instance = MockConfig.return_value
        run_preset(["apply", "pve-8@cn"])

        repos_arg = instance.set_repos.call_args[0][0]
        names = {repo["name"] for repo in repos_arg}
        assert names == {"main", "ceph-squid"}
        instance.set_mirror_variant.assert_called_once_with("cn")
        instance.set_preset_name.assert_called_once_with("pve-8@cn")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_preset.py::TestRunPreset::test_apply_merged_custom_preset -v`
Expected: FAIL because merged repos or variant persistence is wrong.

- [ ] **Step 3: Write minimal implementation**

```python
# No new API needed if merged loading already works.
# Fix any failing assertion by ensuring run_preset() uses get_preset(args.name)
# and writes merged repo dicts unchanged to Config.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --with pytest pytest tests/test_preset.py::TestRunPreset::test_apply_merged_custom_preset -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_preset.py pkgeter/preset.py
git commit -m "test: preserve preset apply behavior with custom presets"
```

### Task 5: Update built-in pve-8 ceph source and docs

**Files:**
- Modify: `pkgeter/data/presets.yaml`
- Modify: `README.md`
- Modify: `README_CH.md`
- Test: `tests/test_preset.py`

**Interfaces:**
- Consumes: merged preset loader from prior tasks
- Produces: corrected built-in `pve-8` ceph source URL and user-facing docs that point custom overrides to `custom-presets.yaml`

- [ ] **Step 1: Write failing test for pve-8 ceph source URL**

```python
def test_pve_8_ceph_uses_download_domain(self, preset_file):
    builtin, user = preset_file
    builtin.write_text(
        SAMPLE_PRESETS_YAML
        + """

pve-8:
  system: pve
  backend: apt
  arch: amd64
  repos:
    - name: ceph-squid
      type: deb
      url: https://download.proxmox.com/debian/ceph-squid
      release: bookworm
      components: [no-subscription]
""",
        encoding="utf-8",
    )
    reload_presets()

    preset = get_preset("pve-8")

    assert preset["repos"][0].url == "https://download.proxmox.com/debian/ceph-squid"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --with pytest pytest tests/test_preset.py::TestGetPreset::test_pve_8_ceph_uses_download_domain -v`
Expected: FAIL if fixture or built-in sample still uses old enterprise domain.

- [ ] **Step 3: Write minimal implementation**

```yaml
pve-8:
  repos:
    - name: ceph-squid
      type: deb
      url: https://download.proxmox.com/debian/ceph-squid
      release: bookworm
      components: [no-subscription]
```

And document user custom overrides in README sections that describe presets.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with pytest pytest tests/test_preset.py tests/test_context.py tests/test_repl.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add pkgeter/data/presets.yaml README.md README_CH.md tests/test_preset.py
git commit -m "docs: document custom preset overrides"
```

### Task 6: Final verification and cleanup

**Files:**
- Modify: `tests/test_preset.py`
- Modify: `pkgeter/preset.py`
- Modify: `README.md`
- Modify: `README_CH.md`
- Modify: `pkgeter/data/presets.yaml`

**Interfaces:**
- Consumes: all previous task outputs
- Produces: final verified branch with no placeholder behavior and no accidental legacy path usage

- [ ] **Step 1: Run targeted grep for legacy path references**

Run: `rg "\.config.*/pkgeter.*/presets\.yaml|_USER_PRESETS|seed" pkgeter tests README.md README_CH.md`
Expected: no matches for active legacy user preset path behavior

- [ ] **Step 2: Run full relevant test suite**

Run: `uv run --with pytest pytest tests/test_preset.py tests/test_context.py tests/test_repl.py tests/test_get.py -q`
Expected: all PASS

- [ ] **Step 3: Inspect git diff for scope**

Run: `git diff -- pkgeter/preset.py pkgeter/data/presets.yaml tests/test_preset.py README.md README_CH.md`
Expected: only custom preset separation, merge behavior, pve ceph URL, and docs updates

- [ ] **Step 4: Remove accidental tool artifacts if present**

Run: `git status --short`
Expected: no unrelated files like `uv.lock` staged unless intentionally kept

- [ ] **Step 5: Commit final cleanup**

```bash
git add pkgeter/preset.py pkgeter/data/presets.yaml tests/test_preset.py README.md README_CH.md
git commit -m "refactor: separate built-in and custom presets"
```
