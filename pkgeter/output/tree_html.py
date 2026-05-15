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
