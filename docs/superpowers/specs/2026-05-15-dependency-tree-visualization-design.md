# Dependency Tree Visualization Design

**Date:** 2026-05-15
**Status:** Approved

## Overview

Add a `pkgeter tree` subcommand that visualizes the dependency tree for one or more packages as a self-contained interactive HTML file. The HTML embeds D3.js for a zoomable, pannable, searchable tree layout. No packages are downloaded — this is a read-only inspection tool.

## Architecture

```
pkgeter tree <packages> [--distro ...] [--output tree.html]
  │
  ├─ Reuse existing flow: load preset/config → download Packages.gz → build package DB
  │
  ├─ pkgeter/deps/tree.py: traverse dependencies, build nested tree structure
  │     Input: target package names + package DB
  │     Output: list[TreeNode] (nested dataclass tree)
  │
  ├─ pkgeter/output/tree_html.py: render tree data into self-contained HTML
  │     Reads template from pkgeter/data/tree_template.html
  │     Injects tree JSON data + D3.js source into template
  │
  └─ pkgeter/tree.py: tree subcommand entry point
        Parse args, load package DB, build tree, render HTML, write file
```

### New Files

| File | Purpose |
|------|---------|
| `pkgeter/deps/tree.py` | Tree data model (`TreeNode`) and tree builder |
| `pkgeter/output/tree_html.py` | HTML renderer (template injection) |
| `pkgeter/data/tree_template.html` | HTML/D3.js template with `__TREE_DATA__` and `__D3_JS__` placeholders |
| `pkgeter/data/d3.v7.min.js` | D3.js v7 minified source (vendored) |
| `pkgeter/tree.py` | `tree` subcommand entry point |

### Modified Files

| File | Change |
|------|--------|
| `pkgeter/cli.py` | Register `tree` in `COMMANDS` dict and dispatch in `run_cli()` |

## Tree Data Model (`pkgeter/deps/tree.py`)

```python
@dataclass
class TreeNode:
    name: str
    version: str
    children: list[TreeNode]
    is_circular: bool = False       # cycle detected — leaf node, no further recursion
    is_virtual: bool = False        # virtual package resolved to a provider
    provider: str = ""              # actual provider package name (when is_virtual=True)
    or_alternatives: list[str] = field(default_factory=list)  # unchosen OR-dep alternatives
```

### Builder Function

```python
def build_dependency_tree(
    pkg_names: list[str],
    all_pkgs: dict[str, PackageInfo],
    installed: set[str] | None = None,
) -> list[TreeNode]:
```

**Behavior:**

- For each target package, recursively traverse `depends` field to build a nested `TreeNode` tree.
- **OR dependencies:** Pick the first alternative present in the package DB. Record unchosen alternatives in `or_alternatives`.
- **Cycle detection:** Track an `ancestors` set (packages on the current recursion path). When a package is already in `ancestors`, create a leaf `TreeNode` with `is_circular=True`.
- **Installed packages:** If `installed` set is provided, installed packages become leaf nodes (no child expansion).
- **Virtual packages:** Use existing `find_providers()` to resolve. Pick the first provider, mark node with `is_virtual=True` and `provider=<chosen>`.
- **Multiple targets:** Returns a list of root `TreeNode`s, one per target package.

## HTML Visualization (`pkgeter/output/tree_html.py` + template)

### Template Structure (`pkgeter/data/tree_template.html`)

```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>pkgeter dependency tree</title>
  <style>/* embedded styles */</style>
</head>
<body>
  <div id="toolbar"><!-- search box + package summary --></div>
  <div id="tree-container"></div>
  <script>__D3_JS__</script>
  <script>
    const treeData = __TREE_DATA__;
    // D3 tree rendering logic
  </script>
</body>
</html>
```

### Renderer

```python
def render_tree_html(trees: list[TreeNode], output_path: Path) -> Path:
    # 1. Serialize TreeNode list to JSON
    # 2. If multiple trees, wrap in virtual root {"name": "pkgeter", "children": [...]}
    # 3. Read template file from pkgeter/data/tree_template.html
    # 4. Read D3 source from pkgeter/data/d3.v7.min.js
    # 5. Replace __D3_JS__ with D3 source
    # 6. Replace __TREE_DATA__ with JSON
    # 7. Write final HTML to output_path
    # 8. Return output_path
```

### D3.js Visualization Features

- **Layout:** Horizontal tree (`d3.tree()`), root on left, leaves on right. Bezier curve links between nodes. Horizontal layout reads naturally for package name labels.
- **Zoom/Pan:** `d3-zoom` for mouse wheel zoom and drag-to-pan.
- **Search:** Top toolbar with a text input. Typing a package name highlights matching nodes and auto-centers the view on the first match.
- **Tooltips:** Hover over a node to see package name, version, and direct dependency count.
- **Special node styles:**
  - Circular dependency: dashed border + red label
  - Virtual package: orange color, shows provider name
  - OR alternatives: gray small text annotated near the link
- **Full display:** No depth limit or collapsing. The entire tree is rendered; user zooms/scrolls to navigate.

### D3.js Embedding

D3 v7 minified (`d3.v7.min.js`) is vendored in `pkgeter/data/`. The template uses `__D3_JS__` as a placeholder. At render time, the Python code reads the JS file and injects it inline. This keeps the template readable during development while producing a fully self-contained HTML output.

## CLI Interface (`pkgeter/tree.py`)

### Command Format

```
pkgeter tree <packages...> [options]
```

### Arguments

| Argument | Short | Description | Default |
|----------|-------|-------------|---------|
| `packages` | (positional) | One or more target package names | Required |
| `--distro` | | Distribution preset (e.g. debian-bookworm, centos-9) | From config |
| `--release` | `-r` | Release name | From preset/config |
| `--arch` | `-a` | Architecture | amd64 |
| `--mirror` | `-m` | Mirror variant (default, cn, etc.) | From config |
| `--cn` | | Shortcut for `--mirror cn` | |
| `--output` | `-o` | Output file path | `./tree.html` |
| `--force-update` | | Force refresh package DB cache | false |
| `--verbose` | `-v` | Debug output | false |

### Parameter Reuse

The arguments `--distro`, `--release`, `--arch`, `--mirror`, `--cn`, `--force-update`, `--verbose` are identical to those in the `get` subcommand. The package DB loading logic (preset resolution, backend selection, DB download) will be extracted from `get.py` into shared helpers to avoid duplication.

### `cli.py` Changes

- Add `"tree": "tree"` to `COMMANDS` dict and `"t": "tree"` to `_ALIASES`.
- Add dispatch branch in `run_cli()`:
  ```python
  elif resolved == "tree":
      from pkgeter.tree import run_tree
      sys.exit(run_tree(sys.argv[2:]))
  ```

### Usage Examples

```bash
# View nginx dependency tree
pkgeter tree nginx --distro debian-bookworm

# Multiple packages with CN mirror
pkgeter tree curl wget --distro debian-bookworm --cn

# Custom output path
pkgeter tree nginx --distro debian-bookworm -o deps.html
```

### Output Behavior

Prints the output file path after generation. Does not auto-open a browser (user may be on a headless server).

## Testing

- `tests/test_deps/test_tree.py` — Unit tests for `build_dependency_tree()`: basic tree, OR deps, cycle detection, virtual packages, multiple targets, installed package skipping.
- `tests/test_output/test_tree_html.py` — Unit tests for `render_tree_html()`: template injection produces valid HTML, JSON data is embedded correctly, multi-tree virtual root wrapping.
