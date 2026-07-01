from task_orchestrator.traversal import get_work_units


def _tree():
    return {
        "id": "root",
        "status": "pending",
        "children": [
            {
                "id": "a",
                "status": "pending",
                "children": [
                    {"id": "a1", "status": "pending", "children": []},
                    {"id": "a2", "status": "completed", "children": []},
                ],
            },
            {"id": "b", "status": "pending", "children": []},
        ],
    }


def test_depth_first_skips_completed():
    units = get_work_units(_tree(), "depth_first", ["completed", "cancelled"])
    assert units == ["a", "a1", "b"]


def test_direct_children_only():
    units = get_work_units(_tree(), "direct_children")
    assert units == ["a", "b"]


def test_leaf_root_runs_itself():
    leaf = {"id": "solo", "status": "pending", "children": []}
    assert get_work_units(leaf) == ["solo"]


def test_leaf_root_skips_completed():
    leaf = {"id": "solo", "status": "completed", "children": []}
    assert get_work_units(leaf) == []


def test_flatten_preorder():
    units = get_work_units(_tree(), "flatten", ["completed", "cancelled"])
    assert units == ["a", "a1", "b"]
