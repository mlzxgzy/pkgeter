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
    assert "pkgeter" in content
    assert "curl" in content
    assert "wget" in content


def test_render_tree_html_contains_d3(tmp_path):
    """The output HTML contains D3.js code."""
    tree = TreeNode(name="test", version="1.0")
    output = tmp_path / "tree.html"
    render_tree_html([tree], output)
    content = output.read_text(encoding="utf-8")
    assert "d3" in content.lower()
