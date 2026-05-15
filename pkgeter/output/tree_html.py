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
        "isDuplicate": node.is_duplicate,
        "provider": node.provider,
        "orAlternatives": node.or_alternatives,
        "reverseDeps": node.reverse_deps,
        "installLayer": node.install_layer,
    }


def _tree_to_data(trees: list[TreeNode]) -> dict:
    """Convert a tree list into a single root dict suitable for JSON embedding."""
    if len(trees) == 1:
        return tree_to_dict(trees[0])
    return {
        "name": "pkgeter",
        "version": "",
        "children": [tree_to_dict(t) for t in trees],
        "isCircular": False,
        "isVirtual": False,
        "isDuplicate": False,
        "provider": "",
        "orAlternatives": [],
        "reverseDeps": [],
        "installLayer": 0,
    }


def render_tree_html(
    trees: list[TreeNode],
    output_path: Path,
    install_trees: list[TreeNode] | None = None,
) -> Path:
    """Render dependency trees into a self-contained HTML file.

    If *install_trees* is provided, a second dataset is embedded for
    the Install Order tab in the HTML.
    """
    full_data = _tree_to_data(trees)
    install_data = _tree_to_data(install_trees) if install_trees else full_data

    full_json = json.dumps(full_data, ensure_ascii=False, indent=2)
    install_json = json.dumps(install_data, ensure_ascii=False, indent=2)

    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    d3_source = _D3_PATH.read_text(encoding="utf-8")

    html = template.replace("__D3_JS__", d3_source)
    html = html.replace("__FULL_TREE_DATA__", full_json)
    html = html.replace("__INSTALL_ORDER_DATA__", install_json)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
