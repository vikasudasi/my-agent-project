"""Depth-first and other traversal strategies over task trees."""

from __future__ import annotations

from typing import Iterable


def get_work_units(
    tree_root: dict,
    traversal: str = "depth_first",
    skip_statuses: Iterable[str] | None = None,
) -> list[str]:
    """
    Return ordered task IDs to execute under tree_root.

    - Leaf root (no children): run the root itself if not skipped.
    - Otherwise: descendants only (root is the container).
    """
    skip = set(skip_statuses or ["completed", "cancelled"])
    children = tree_root.get("children") or []

    if not children:
        if tree_root.get("status") not in skip:
            return [tree_root["id"]]
        return []

    if traversal == "direct_children":
        return [c["id"] for c in children if c.get("status") not in skip]
    if traversal == "flatten":
        return _flatten_preorder(tree_root, skip)
    return _depth_first_children(tree_root, skip)


def _depth_first_children(node: dict, skip: set[str]) -> list[str]:
    units: list[str] = []
    for child in node.get("children") or []:
        if child.get("status") not in skip:
            units.append(child["id"])
        units.extend(_depth_first_children(child, skip))
    return units


def _flatten_preorder(node: dict, skip: set[str]) -> list[str]:
    units: list[str] = []

    def walk(n: dict) -> None:
        for child in n.get("children") or []:
            if child.get("status") not in skip:
                units.append(child["id"])
            walk(child)

    walk(node)
    return units
