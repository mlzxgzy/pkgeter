# Dependency Tree Visualization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `pkgeter tree` subcommand that generates a self-contained interactive HTML file visualizing the dependency tree for one or more packages.

**Architecture:** New `TreeNode` dataclass and `build_dependency_tree()` function in `pkgeter/deps/tree.py` build nested tree structures from the package DB. `pkgeter/output/tree_html.py` injects the tree JSON into an HTML template (`pkgeter/data/tree_template.html`) that embeds D3.js for interactive visualization. `pkgeter/tree.py` wires it all together as a CLI subcommand.

**Tech Stack:** Python dataclasses, D3.js v7 (vendored), HTML/CSS/JS template, existing pkgeter backend infrastructure.

**Spec:** `docs/superpowers/specs/2026-05-15-dependency-tree-visualization-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `pkgeter/deps/tree.py` | Create | `TreeNode` dataclass + `build_dependency_tree()` builder |
| `tests/test_deps/test_tree.py` | Create | Unit tests for tree builder |
| `pkgeter/output/tree_html.py` | Create | `render_tree_html()` — template injection |
| `tests/test_output/test_tree_html.py` | Create | Unit tests for HTML renderer |
| `pkgeter/data/d3.v7.min.js` | Create | Vendored D3.js v7 minified |
| `pkgeter/data/tree_template.html` | Create | HTML/D3.js template with placeholders |
| `pkgeter/tree.py` | Create | `run_tree()` subcommand entry point |
| `pkgeter/cli.py` | Modify | Register `tree` command + `t` alias |

---

### Task 1: TreeNode dataclass and basic tree builder

**Files:**
- Create: `pkgeter/deps/tree.py`
- Test: `tests/test_deps/test_tree.py`

- [ ] **Step 1: Write failing tests for TreeNode and basic tree building**

Create `tests/test_deps/test_tree.py`:

```python
"""Tests for dependency tree builder."""

import pytest

from pkgeter.deps.tree import TreeNode, build_dependency_tree
from pkgeter.models import PackageInfo, Dependency


def _make_pkg(name, version="1.0", depends=None, provides=None) -> PackageInfo:
    return PackageInfo(
        package=name,
        version=version,
        depends=depends or [],
        provides=provides or [],
        arch="amd64",
        filename=f"pool/main/{name[0]}/{name}/{name}_{version}_amd64.deb",
        sha256="x" * 64,
        size=1024,
    )


def test_single_package_no_deps():
    """A package with no dependencies produces a single leaf node."""
    db = {"nginx": _make_pkg("nginx", "1.22.1")}
    trees = build_dependency_tree(["nginx"], db)
    assert len(trees) == 1
    node = trees[0]
    assert node.name == "nginx"
    assert node.version == "1.22.1"
    assert node.children == []
    assert not node.is_circular
    assert not node.is_virtual


def test_single_package_with_deps():
    """A package with dependencies produces a tree with children."""
    db = {
        "nginx": _make_pkg("nginx", depends=[[Dependency("libc6")]]),
        "libc6": _make_pkg("libc6", "2.36"),
    }
    trees = build_dependency_tree(["nginx"], db)
    assert len(trees) == 1
    root = trees[0]
    assert root.name == "nginx"
    assert len(root.children) == 1
    assert root.children[0].name == "libc6"
    assert root.children[0].version == "2.36"
    assert root.children[0].children == []


def test_deep_dependency_chain():
    """Dependencies of dependencies are nested correctly."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("libfoo")]]),
        "libfoo": _make_pkg("libfoo", depends=[[Dependency("libc6")]]),
        "libc6": _make_pkg("libc6"),
    }
    trees = build_dependency_tree(["app"], db)
    root = trees[0]
    assert root.name == "app"
    assert len(root.children) == 1
    assert root.children[0].name == "libfoo"
    assert len(root.children[0].children) == 1
    assert root.children[0].children[0].name == "libc6"


def test_multiple_deps():
    """A package with multiple AND dependencies gets multiple children."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("liba")], [Dependency("libb")]]),
        "liba": _make_pkg("liba"),
        "libb": _make_pkg("libb"),
    }
    trees = build_dependency_tree(["app"], db)
    root = trees[0]
    assert len(root.children) == 2
    names = {c.name for c in root.children}
    assert names == {"liba", "libb"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_deps/test_tree.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pkgeter.deps.tree'`

- [ ] **Step 3: Implement TreeNode and build_dependency_tree**

Create `pkgeter/deps/tree.py`:

```python
"""Dependency tree builder - construct nested tree structures for visualization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from pkgeter.deps.virtual import find_providers
from pkgeter.models import PackageInfo


@dataclass
class TreeNode:
    """A node in the dependency tree."""

    name: str
    version: str
    children: list[TreeNode] = field(default_factory=list)
    is_circular: bool = False
    is_virtual: bool = False
    provider: str = ""
    or_alternatives: list[str] = field(default_factory=list)


def build_dependency_tree(
    pkg_names: list[str],
    all_pkgs: Dict[str, PackageInfo],
    installed: Optional[Set[str]] = None,
) -> list[TreeNode]:
    """Build dependency trees for the given package names.

    Returns one TreeNode per target package, with nested children
    representing the full dependency graph.
    """
    installed = installed or set()
    trees: list[TreeNode] = []
    for name in pkg_names:
        tree = _build_node(name, all_pkgs, installed, ancestors=set())
        trees.append(tree)
    return trees


def _build_node(
    pkg_name: str,
    all_pkgs: Dict[str, PackageInfo],
    installed: Set[str],
    ancestors: Set[str],
) -> TreeNode:
    """Recursively build a TreeNode for a single package."""
    # Cycle detection
    if pkg_name in ancestors:
        return TreeNode(name=pkg_name, version="", is_circular=True)

    # Installed packages become leaf nodes
    if pkg_name in installed:
        info = all_pkgs.get(pkg_name)
        version = info.version if info else ""
        return TreeNode(name=pkg_name, version=version)

    info = all_pkgs.get(pkg_name)
    if info is None:
        # Try virtual package resolution
        providers = find_providers(pkg_name, all_pkgs)
        if not providers:
            return TreeNode(name=pkg_name, version="(not found)")
        chosen = providers[0]
        real_node = _build_node(chosen, all_pkgs, installed, ancestors)
        return TreeNode(
            name=pkg_name,
            version="",
            children=real_node.children,
            is_virtual=True,
            provider=chosen,
        )

    new_ancestors = ancestors | {pkg_name}
    children: list[TreeNode] = []

    if info.depends:
        for dep_group in info.depends:
            child = _resolve_dep_group(dep_group, all_pkgs, installed, new_ancestors)
            if child is not None:
                children.append(child)

    return TreeNode(name=pkg_name, version=info.version, children=children)


def _resolve_dep_group(
    dep_group: list,
    all_pkgs: Dict[str, PackageInfo],
    installed: Set[str],
    ancestors: Set[str],
) -> TreeNode | None:
    """Resolve an OR-dependency group, returning a TreeNode for the chosen dep."""
    chosen_dep = None
    alternatives: list[str] = []

    for dep in dep_group:
        # Skip system-provided deps
        if dep.name.startswith("/") or ".so" in dep.name or dep.name.startswith("rpmlib(") or dep.name == "rtld(GNU_HASH)":
            return None

        if chosen_dep is None and (dep.name in all_pkgs or dep.name in installed or find_providers(dep.name, all_pkgs)):
            chosen_dep = dep
        else:
            alternatives.append(dep.name)

    if chosen_dep is None:
        # No alternative found — use the first one and let it show as "not found"
        if dep_group:
            chosen_dep = dep_group[0]
            alternatives = [d.name for d in dep_group[1:]]
        else:
            return None

    node = _build_node(chosen_dep.name, all_pkgs, installed, ancestors)
    if alternatives:
        node.or_alternatives = alternatives
    return node
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_deps/test_tree.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add pkgeter/deps/tree.py tests/test_deps/test_tree.py
git commit -m "feat(deps): add TreeNode dataclass and basic tree builder"
```

---

### Task 2: Tree builder edge cases

**Files:**
- Modify: `pkgeter/deps/tree.py` (already implemented in Task 1)
- Test: `tests/test_deps/test_tree.py`

- [ ] **Step 1: Write failing tests for edge cases**

Append to `tests/test_deps/test_tree.py`:

```python
def test_cycle_detection():
    """Circular dependency produces a node with is_circular=True."""
    db = {
        "pkg-a": _make_pkg("pkg-a", depends=[[Dependency("pkg-b")]]),
        "pkg-b": _make_pkg("pkg-b", depends=[[Dependency("pkg-a")]]),
    }
    trees = build_dependency_tree(["pkg-a"], db)
    root = trees[0]
    assert root.name == "pkg-a"
    assert len(root.children) == 1
    child_b = root.children[0]
    assert child_b.name == "pkg-b"
    assert len(child_b.children) == 1
    circular_ref = child_b.children[0]
    assert circular_ref.name == "pkg-a"
    assert circular_ref.is_circular is True
    assert circular_ref.children == []


def test_or_dependency_picks_first_available():
    """OR dependency picks the first available and records alternatives."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("pkg-x"), Dependency("pkg-y")]]),
        "pkg-y": _make_pkg("pkg-y"),
    }
    trees = build_dependency_tree(["app"], db)
    root = trees[0]
    assert len(root.children) == 1
    child = root.children[0]
    assert child.name == "pkg-y"
    assert child.or_alternatives == ["pkg-x"]


def test_or_dependency_first_present():
    """OR dependency picks the first present alternative."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("pkg-x"), Dependency("pkg-y")]]),
        "pkg-x": _make_pkg("pkg-x"),
        "pkg-y": _make_pkg("pkg-y"),
    }
    trees = build_dependency_tree(["app"], db)
    child = trees[0].children[0]
    assert child.name == "pkg-x"
    assert child.or_alternatives == ["pkg-y"]


def test_virtual_package_resolution():
    """Virtual packages are marked with is_virtual and provider."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("mail-transport-agent")]]),
        "postfix": _make_pkg("postfix", provides=["mail-transport-agent"]),
    }
    trees = build_dependency_tree(["app"], db)
    child = trees[0].children[0]
    assert child.name == "mail-transport-agent"
    assert child.is_virtual is True
    assert child.provider == "postfix"


def test_installed_packages_are_leaf_nodes():
    """Installed packages become leaf nodes without expanding children."""
    db = {
        "app": _make_pkg("app", depends=[[Dependency("libc6")]]),
        "libc6": _make_pkg("libc6", depends=[[Dependency("libgcc")]]),
        "libgcc": _make_pkg("libgcc"),
    }
    trees = build_dependency_tree(["app"], db, installed={"libc6"})
    root = trees[0]
    child = root.children[0]
    assert child.name == "libc6"
    assert child.children == []  # Not expanded because it's installed


def test_multiple_target_packages():
    """Multiple target packages produce multiple root nodes."""
    db = {
        "curl": _make_pkg("curl"),
        "wget": _make_pkg("wget"),
    }
    trees = build_dependency_tree(["curl", "wget"], db)
    assert len(trees) == 2
    assert trees[0].name == "curl"
    assert trees[1].name == "wget"


def test_package_not_found():
    """Unknown package produces a node with '(not found)' version."""
    db = {}
    trees = build_dependency_tree(["nonexistent"], db)
    assert len(trees) == 1
    assert trees[0].name == "nonexistent"
    assert trees[0].version == "(not found)"


def test_system_deps_skipped():
    """System-provided deps (absolute paths, .so) are skipped."""
    db = {
        "app": _make_pkg("app", depends=[
            [Dependency("/bin/sh")],
            [Dependency("libc.so.6()(64bit)")],
            [Dependency("rpmlib(CompressedFileNames)")],
        ]),
    }
    trees = build_dependency_tree(["app"], db)
    assert trees[0].children == []
```

- [ ] **Step 2: Run tests to verify new tests pass (implementation from Task 1 should handle these)**

Run: `pytest tests/test_deps/test_tree.py -v`
Expected: All tests PASS. If any fail, fix the implementation in `pkgeter/deps/tree.py`.

- [ ] **Step 3: Fix any failing tests**

If `test_or_dependency_picks_first_available` fails because the current `_resolve_dep_group` logic doesn't handle the case where `pkg-x` is not in `all_pkgs`, adjust the logic. The `chosen_dep` selection in `_resolve_dep_group` should skip alternatives not present in the DB when choosing, but record them as alternatives. Specifically, the issue is that when iterating, `pkg-x` is checked first but not found, so it goes to `alternatives`. Then `pkg-y` is found and becomes `chosen_dep`. The `alternatives` list would be `["pkg-x"]` which is wrong — it should be that `pkg-x` is the alternative to `pkg-y`, but `or_alternatives` records the unchosen names. Let me re-examine:

In the current implementation, when iterating `dep_group = [Dep("pkg-x"), Dep("pkg-y")]`:
- `dep = Dep("pkg-x")`: `chosen_dep is None`, `pkg-x not in all_pkgs` and no providers → goes to `else` → `alternatives = ["pkg-x"]`
- `dep = Dep("pkg-y")`: `chosen_dep is None`, `pkg-y in all_pkgs` → `chosen_dep = Dep("pkg-y")`

So `alternatives = ["pkg-x"]` and `chosen_dep = pkg-y`. The test asserts `child.or_alternatives == ["pkg-x"]` — this should already pass.

For `test_or_dependency_first_present` where both exist:
- `dep = Dep("pkg-x")`: `chosen_dep is None`, `pkg-x in all_pkgs` → `chosen_dep = Dep("pkg-x")`
- `dep = Dep("pkg-y")`: `chosen_dep is not None` → `alternatives = ["pkg-y"]`

The test asserts `child.or_alternatives == ["pkg-y"]` — this should pass.

All tests should pass with the Task 1 implementation. If any don't, make targeted fixes.

- [ ] **Step 4: Commit**

```bash
git add tests/test_deps/test_tree.py pkgeter/deps/tree.py
git commit -m "test(deps): add edge case tests for tree builder"
```

---

### Task 3: HTML renderer

**Files:**
- Create: `pkgeter/output/tree_html.py`
- Test: `tests/test_output/test_tree_html.py`

- [ ] **Step 1: Write failing tests for the HTML renderer**

Create `tests/test_output/test_tree_html.py`:

```python
"""Tests for HTML tree renderer."""

import json

from pkgeter.deps.tree import TreeNode
from pkgeter.output.tree_html import render_tree_html, tree_to_dict


def test_tree_to_dict_single_node():
    """A single leaf node serializes correctly."""
    node = TreeNode(name="nginx", version="1.22.1")
    d = tree_to_dict(node)
    assert d == {
        "name": "nginx",
        "version": "1.22.1",
        "children": [],
        "isCircular": False,
        "isVirtual": False,
        "provider": "",
        "orAlternatives": [],
    }


def test_tree_to_dict_with_children():
    """Nested children are serialized recursively."""
    child = TreeNode(name="libc6", version="2.36")
    root = TreeNode(name="nginx", version="1.22.1", children=[child])
    d = tree_to_dict(root)
    assert len(d["children"]) == 1
    assert d["children"][0]["name"] == "libc6"


def test_tree_to_dict_special_flags():
    """Special flags (circular, virtual) are serialized."""
    node = TreeNode(
        name="mail-agent", version="",
        is_virtual=True, provider="postfix",
        or_alternatives=["sendmail", "exim4"],
    )
    d = tree_to_dict(node)
    assert d["isVirtual"] is True
    assert d["provider"] == "postfix"
    assert d["orAlternatives"] == ["sendmail", "exim4"]


def test_render_tree_html_single_tree(tmp_path):
    """Single tree produces an HTML file with embedded JSON data."""
    tree = TreeNode(name="nginx", version="1.22.1", children=[
        TreeNode(name="libc6", version="2.36"),
    ])
    output = tmp_path / "tree.html"
    result = render_tree_html([tree], output)
    assert result == output
    assert output.exists()
    content = output.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert '"name": "nginx"' in content or '"name":"nginx"' in content
    assert '"name": "libc6"' in content or '"name":"libc6"' in content


def test_render_tree_html_multi_tree_wraps_in_root(tmp_path):
    """Multiple trees get wrapped in a virtual root node."""
    trees = [
        TreeNode(name="curl", version="7.88"),
        TreeNode(name="wget", version="1.21"),
    ]
    output = tmp_path / "tree.html"
    render_tree_html(trees, output)
    content = output.read_text(encoding="utf-8")
    # The virtual root should contain both trees as children
    assert "pkgeter" in content
    assert "curl" in content
    assert "wget" in content


def test_render_tree_html_contains_d3(tmp_path):
    """The output HTML contains D3.js code."""
    tree = TreeNode(name="test", version="1.0")
    output = tmp_path / "tree.html"
    render_tree_html([tree], output)
    content = output.read_text(encoding="utf-8")
    # D3 minified source contains this identifier
    assert "d3" in content.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_output/test_tree_html.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pkgeter.output.tree_html'`

- [ ] **Step 3: Implement tree_to_dict and render_tree_html**

Create `pkgeter/output/tree_html.py`:

```python
"""Render dependency trees as self-contained interactive HTML files."""

from __future__ import annotations

import json
from pathlib import Path

from pkgeter.deps.tree import TreeNode

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_TEMPLATE_PATH = _DATA_DIR / "tree_template.html"
_D3_PATH = _DATA_DIR / "d3.v7.min.js"


def tree_to_dict(node: TreeNode) -> dict:
    """Convert a TreeNode into a JSON-serializable dict."""
    return {
        "name": node.name,
        "version": node.version,
        "children": [tree_to_dict(c) for c in node.children],
        "isCircular": node.is_circular,
        "isVirtual": node.is_virtual,
        "provider": node.provider,
        "orAlternatives": node.or_alternatives,
    }


def render_tree_html(trees: list[TreeNode], output_path: Path) -> Path:
    """Render dependency trees into a self-contained HTML file.

    If multiple trees are provided, they are wrapped in a virtual
    root node named "pkgeter".
    """
    if len(trees) == 1:
        data = tree_to_dict(trees[0])
    else:
        data = {
            "name": "pkgeter",
            "version": "",
            "children": [tree_to_dict(t) for t in trees],
            "isCircular": False,
            "isVirtual": False,
            "provider": "",
            "orAlternatives": [],
        }

    json_str = json.dumps(data, ensure_ascii=False, indent=2)

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    d3_source = _D3_PATH.read_text(encoding="utf-8")

    html = template.replace("__D3_JS__", d3_source)
    html = html.replace("__TREE_DATA__", json_str)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
```

- [ ] **Step 4: Run tests — some will fail because template/D3 files don't exist yet**

Run: `pytest tests/test_output/test_tree_html.py::test_tree_to_dict_single_node tests/test_output/test_tree_html.py::test_tree_to_dict_with_children tests/test_output/test_tree_html.py::test_tree_to_dict_special_flags -v`
Expected: The 3 `tree_to_dict` tests PASS. The `render_tree_html` tests will fail until Task 4.

- [ ] **Step 5: Commit the partial implementation**

```bash
git add pkgeter/output/tree_html.py tests/test_output/test_tree_html.py
git commit -m "feat(output): add tree-to-dict serializer and HTML renderer skeleton"
```

---

### Task 4: D3.js template and vendored library

**Files:**
- Create: `pkgeter/data/d3.v7.min.js`
- Create: `pkgeter/data/tree_template.html`

- [ ] **Step 1: Download and vendor D3.js v7 minified**

```bash
curl -L "https://cdn.jsdelivr.net/npm/d3@7/dist/d3.min.js" -o pkgeter/data/d3.v7.min.js
```

Verify the file is non-empty and contains D3 code:

```bash
head -c 200 pkgeter/data/d3.v7.min.js
```

Expected: starts with `// https://d3js.org` or minified JS code.

- [ ] **Step 2: Create the HTML template**

Create `pkgeter/data/tree_template.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>pkgeter — dependency tree</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace; background: #1a1a2e; color: #e0e0e0; overflow: hidden; }
#toolbar { position: fixed; top: 0; left: 0; right: 0; z-index: 10; background: #16213e; padding: 10px 20px; display: flex; align-items: center; gap: 16px; border-bottom: 1px solid #0f3460; }
#toolbar h1 { font-size: 14px; font-weight: 600; color: #e94560; white-space: nowrap; }
#search { background: #1a1a2e; border: 1px solid #0f3460; color: #e0e0e0; padding: 6px 12px; border-radius: 4px; font-size: 13px; width: 260px; }
#search:focus { outline: none; border-color: #e94560; }
#info { font-size: 12px; color: #888; }
#tree-container { width: 100vw; height: 100vh; padding-top: 50px; }
svg { width: 100%; height: 100%; }
.link { fill: none; stroke: #0f3460; stroke-width: 1.5px; }
.node circle { r: 5; fill: #16213e; stroke: #e94560; stroke-width: 2px; cursor: pointer; }
.node text { font-size: 12px; fill: #e0e0e0; }
.node.circular circle { stroke: #ff4444; stroke-dasharray: 4,3; }
.node.circular text { fill: #ff4444; }
.node.virtual circle { stroke: #ffa500; fill: #2a1f00; }
.node.virtual text { fill: #ffa500; }
.node.highlight circle { stroke: #00ff88; stroke-width: 3px; fill: #003322; }
.node.highlight text { fill: #00ff88; font-weight: bold; }
.or-alt { font-size: 9px; fill: #666; }
.tooltip { position: fixed; background: #16213e; border: 1px solid #0f3460; border-radius: 4px; padding: 8px 12px; font-size: 12px; pointer-events: none; z-index: 20; color: #e0e0e0; display: none; }
.tooltip .pkg-name { color: #e94560; font-weight: 600; }
.tooltip .pkg-ver { color: #888; }
</style>
</head>
<body>
<div id="toolbar">
  <h1>pkgeter dependency tree</h1>
  <input id="search" type="text" placeholder="Search packages..." autocomplete="off">
  <span id="info"></span>
</div>
<div id="tree-container"></div>
<div class="tooltip" id="tooltip"></div>
<script>__D3_JS__</script>
<script>
(function() {
  const treeData = __TREE_DATA__;

  // Count total nodes
  function countNodes(node) {
    let c = 1;
    if (node.children) node.children.forEach(ch => c += countNodes(ch));
    return c;
  }
  const totalNodes = countNodes(treeData);
  document.getElementById("info").textContent =
    treeData.name + " — " + totalNodes + " packages";

  const container = document.getElementById("tree-container");
  const width = container.clientWidth;
  const height = container.clientHeight;

  const svg = d3.select("#tree-container").append("svg")
    .attr("width", width)
    .attr("height", height);

  const g = svg.append("g");

  // Zoom
  const zoom = d3.zoom()
    .scaleExtent([0.05, 4])
    .on("zoom", (event) => g.attr("transform", event.transform));
  svg.call(zoom);

  // Build hierarchy
  const root = d3.hierarchy(treeData);
  const nodeCount = root.descendants().length;

  // Dynamic sizing based on node count
  const dy = Math.max(180, 220);
  const dx = Math.max(20, Math.min(30, 600 / nodeCount));

  const treeLayout = d3.tree().nodeSize([dx, dy]);
  treeLayout(root);

  // Center the tree
  let x0 = Infinity, x1 = -Infinity;
  root.each(d => {
    if (d.x > x1) x1 = d.x;
    if (d.x < x0) x0 = d.x;
  });
  const treeHeight = x1 - x0 + dx * 2;

  // Initial transform to show root
  const initialTransform = d3.zoomIdentity
    .translate(80, height / 2 - (x0 + x1) / 2);
  svg.call(zoom.transform, initialTransform);

  // Links
  g.selectAll(".link")
    .data(root.links())
    .join("path")
    .attr("class", "link")
    .attr("d", d3.linkHorizontal()
      .x(d => d.y)
      .y(d => d.x));

  // Nodes
  const node = g.selectAll(".node")
    .data(root.descendants())
    .join("g")
    .attr("class", d => {
      let cls = "node";
      if (d.data.isCircular) cls += " circular";
      if (d.data.isVirtual) cls += " virtual";
      return cls;
    })
    .attr("transform", d => `translate(${d.y},${d.x})`);

  node.append("circle");

  node.append("text")
    .attr("dy", "0.31em")
    .attr("x", d => d.children ? -10 : 10)
    .attr("text-anchor", d => d.children ? "end" : "start")
    .text(d => {
      let label = d.data.name;
      if (d.data.isCircular) label += " ↻";
      if (d.data.isVirtual && d.data.provider) label += " → " + d.data.provider;
      if (d.data.version && d.data.version !== "(not found)") label += " " + d.data.version;
      return label;
    });

  // OR alternatives annotation
  node.each(function(d) {
    if (d.data.orAlternatives && d.data.orAlternatives.length > 0) {
      d3.select(this).append("text")
        .attr("class", "or-alt")
        .attr("dy", "1.8em")
        .attr("x", d.children ? -10 : 10)
        .attr("text-anchor", d.children ? "end" : "start")
        .text("alt: " + d.data.orAlternatives.join(", "));
    }
  });

  // Tooltip
  const tooltip = document.getElementById("tooltip");
  node.on("mouseover", (event, d) => {
    const data = d.data;
    let html = '<span class="pkg-name">' + data.name + '</span>';
    if (data.version) html += ' <span class="pkg-ver">' + data.version + '</span>';
    html += '<br>Dependencies: ' + (data.children ? data.children.length : 0);
    if (data.isCircular) html += '<br><span style="color:#ff4444">⚠ Circular dependency</span>';
    if (data.isVirtual) html += '<br>Virtual → ' + data.provider;
    if (data.orAlternatives && data.orAlternatives.length)
      html += '<br>Alternatives: ' + data.orAlternatives.join(', ');
    tooltip.innerHTML = html;
    tooltip.style.display = "block";
    tooltip.style.left = (event.clientX + 15) + "px";
    tooltip.style.top = (event.clientY - 10) + "px";
  })
  .on("mousemove", (event) => {
    tooltip.style.left = (event.clientX + 15) + "px";
    tooltip.style.top = (event.clientY - 10) + "px";
  })
  .on("mouseout", () => { tooltip.style.display = "none"; });

  // Search
  const searchInput = document.getElementById("search");
  searchInput.addEventListener("input", function() {
    const query = this.value.toLowerCase().trim();
    node.classed("highlight", false);
    if (!query) return;

    const matches = [];
    node.each(function(d) {
      if (d.data.name.toLowerCase().includes(query)) {
        d3.select(this).classed("highlight", true);
        matches.push(d);
      }
    });

    // Center on first match
    if (matches.length > 0) {
      const target = matches[0];
      const transform = d3.zoomIdentity
        .translate(width / 2 - target.y, height / 2 - target.x);
      svg.transition().duration(500).call(zoom.transform, transform);
    }
  });
})();
</script>
</body>
</html>
```

- [ ] **Step 3: Run the render tests**

Run: `pytest tests/test_output/test_tree_html.py -v`
Expected: All 6 tests PASS

- [ ] **Step 4: Commit**

```bash
git add pkgeter/data/d3.v7.min.js pkgeter/data/tree_template.html
git commit -m "feat(data): add D3.js v7 and HTML tree template"
```

---

### Task 5: Tree subcommand entry point and CLI registration

**Files:**
- Create: `pkgeter/tree.py`
- Modify: `pkgeter/cli.py`

- [ ] **Step 1: Create pkgeter/tree.py**

Create `pkgeter/tree.py`. This follows the same pattern as `pkgeter/get.py` for arg parsing, preset/config resolution, and backend instantiation:

```python
"""tree subcommand — visualize package dependency trees."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

from pkgeter.config import Config
from pkgeter.deps.tree import build_dependency_tree
from pkgeter.models import RepoConfig
from pkgeter.output.tree_html import render_tree_html


def run_tree(argv: list[str]) -> int:
    """Tree subcommand — generate dependency tree visualization."""
    parser = argparse.ArgumentParser(prog="pkgeter tree")
    parser.add_argument("packages", nargs="*", help="Target packages (positional)")
    parser.add_argument("--distro")
    parser.add_argument("--release", "-r")
    parser.add_argument("--arch", "-a")
    parser.add_argument("--mirror", "-m", help="Mirror variant (default, cn, etc.)")
    parser.add_argument("--cn", action="store_true", help="Shortcut for --mirror cn")
    parser.add_argument("--force-update", action="store_true", help="Force cache refresh")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose/debug output")
    parser.add_argument("--output", "-o", type=Path, default=Path("./tree.html"))
    parser.add_argument("--config", type=Path, default=None)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 1

    if args.verbose:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(levelname)s: %(message)s",
            force=True,
        )

    if not args.packages:
        print("Error: specify packages to visualize", file=sys.stderr)
        return 1

    config = Config(args.config)
    arch = args.arch or config.get("arch", "amd64")
    mirror_variant = args.mirror or config.get_mirror_variant()
    if args.cn:
        mirror_variant = "cn"

    # Determine repos and backend
    if args.distro:
        from pkgeter.preset import get_preset
        preset = get_preset(args.distro, mirror_variant=mirror_variant)
        if not preset:
            print(f"Error: unknown preset '{args.distro}'", file=sys.stderr)
            return 1
        repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in preset["repos"]]
        backend_name = preset["backend"]
        arch = preset.get("arch", arch)
    else:
        repos_dicts = config.get_repos()
        if not repos_dicts:
            from pkgeter.preset import get_preset
            preset = get_preset("debian-bookworm", mirror_variant=mirror_variant)
            repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in preset["repos"]]
            backend_name = preset["backend"]
        else:
            repos = [RepoConfig(**r) if isinstance(r, dict) else r for r in repos_dicts]
            backend_name = config.get_backend()

    # Instantiate backend
    if backend_name in ("apt", "debian"):
        from pkgeter.backend.debian import DebianBackend
        backend = DebianBackend()
    elif backend_name == "dnf":
        from pkgeter.backend.rpm import DnfBackend
        backend = DnfBackend()
    elif backend_name == "rpm":
        from pkgeter.backend.rpm import RpmBackend
        backend = RpmBackend()
    else:
        print(f"Error: unknown backend '{backend_name}'", file=sys.stderr)
        return 1

    # Download package DB
    print("Loading package database...")
    package_db = backend.download_package_db(repos, arch, force_update=args.force_update)
    if not package_db:
        print("Error: no packages found from any repo", file=sys.stderr)
        return 1
    logger.debug("Package DB loaded: %d packages", len(package_db))

    # Build dependency trees
    print("Building dependency tree...")
    trees = build_dependency_tree(args.packages, package_db)

    # Render HTML
    output_path = render_tree_html(trees, args.output)
    print(f"Dependency tree written to: {output_path}")
    return 0
```

- [ ] **Step 2: Register tree command in cli.py**

In `pkgeter/cli.py`, add `"tree"` to the `COMMANDS` dict and `"t"` to `_ALIASES`:

Change line 7:
```python
COMMANDS = {"get": "get", "repo": "repo", "preset": "preset", "search": "search", "tree": "tree", "help": "help", "exit": "exit"}
```

Change line 8:
```python
_ALIASES = {"quit": "exit", "bye": "exit", "h": "help", "g": "get", "r": "repo", "s": "search", "t": "tree"}
```

Add dispatch branch after the `search` branch (after line 62, before `elif resolved == "help"`):

```python
    elif resolved == "tree":
        from pkgeter.tree import run_tree
        sys.exit(run_tree(sys.argv[2:]))
```

Also update the help text (line 70) to include `tree`:
```python
        print("Commands: get, repo, preset, search, tree, help, exit")
```

- [ ] **Step 3: Smoke test the CLI registration**

Run: `python -m pkgeter help`
Expected: output includes `tree` in the command list.

Run: `python -m pkgeter tree`
Expected: `Error: specify packages to visualize`

- [ ] **Step 4: Commit**

```bash
git add pkgeter/tree.py pkgeter/cli.py
git commit -m "feat(cli): add tree subcommand for dependency tree visualization"
```

---

### Task 6: Integration test with real package DB

**Files:**
- Test: `tests/test_deps/test_tree.py` (append integration test)

- [ ] **Step 1: Add an integration test using sample_packages.gz fixture**

Append to `tests/test_deps/test_tree.py`:

```python
import gzip
from pathlib import Path
from pkgeter.backend.debian import DebianBackend

SAMPLE_PACKAGES_GZ = Path(__file__).parent.parent / "data" / "sample_packages.gz"


def test_tree_with_sample_packages_gz():
    """Integration test: build tree from sample_packages.gz fixture."""
    if not SAMPLE_PACKAGES_GZ.exists():
        pytest.skip("sample_packages.gz not found")
    raw = SAMPLE_PACKAGES_GZ.read_bytes()
    backend = DebianBackend()
    db = backend._parse_packages_gz(raw)
    if not db:
        pytest.skip("sample_packages.gz is empty")
    # Pick first package from DB
    first_pkg = next(iter(db))
    trees = build_dependency_tree([first_pkg], db)
    assert len(trees) == 1
    assert trees[0].name == first_pkg
    assert trees[0].version == db[first_pkg].version
```

- [ ] **Step 2: Add an end-to-end test for HTML rendering**

Append to `tests/test_output/test_tree_html.py`:

```python
def test_render_roundtrip_json_valid(tmp_path):
    """The JSON embedded in the HTML is valid and matches the input tree."""
    tree = TreeNode(
        name="app", version="2.0",
        children=[
            TreeNode(name="liba", version="1.0", or_alternatives=["libb"]),
            TreeNode(name="libc", version="3.0", is_circular=True),
            TreeNode(name="virt", version="", is_virtual=True, provider="real-pkg"),
        ],
    )
    output = tmp_path / "test.html"
    render_tree_html([tree], output)
    content = output.read_text(encoding="utf-8")

    # Extract JSON from HTML — it's between "const treeData = " and ";\n"
    start = content.index("const treeData = ") + len("const treeData = ")
    end = content.index(";\n", start)
    json_str = content[start:end]
    data = json.loads(json_str)

    assert data["name"] == "app"
    assert len(data["children"]) == 3
    assert data["children"][0]["orAlternatives"] == ["libb"]
    assert data["children"][1]["isCircular"] is True
    assert data["children"][2]["isVirtual"] is True
    assert data["children"][2]["provider"] == "real-pkg"
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS (both new and existing).

- [ ] **Step 4: Commit**

```bash
git add tests/test_deps/test_tree.py tests/test_output/test_tree_html.py
git commit -m "test: add integration tests for tree builder and HTML renderer"
```

---

### Task 7: Package data configuration and final verification

**Files:**
- Modify: `pyproject.toml` (ensure `*.html` and `*.js` are included in package data)

- [ ] **Step 1: Verify package data includes new files**

Check that `pyproject.toml` `[tool.setuptools.package-data]` includes `.html` and `.js` files. Current config is:

```toml
[tool.setuptools.package-data]
pkgeter = ["data/*.yaml"]
```

Update to:

```toml
[tool.setuptools.package-data]
pkgeter = ["data/*.yaml", "data/*.html", "data/*.js"]
```

- [ ] **Step 2: Run the full test suite**

Run: `pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 3: Manual smoke test with a real distro (optional, requires network)**

Run: `python -m pkgeter tree curl --distro debian-bookworm -o /tmp/curl-tree.html`
Expected: HTML file generated at `/tmp/curl-tree.html`. Open in browser to verify:
- Tree renders with curl as root
- Dependencies are visible as nested nodes
- Zoom/pan works (mouse wheel + drag)
- Search box finds packages
- Tooltips show on hover

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "build: include HTML and JS data files in package distribution"
```
