from task_orchestrator.prompt import build_prompt


def test_build_prompt_includes_task_id():
    prompt = build_prompt("task-abc", "Do one thing only.")
    assert "task-abc" in prompt
    assert "Do one thing only." in prompt
    assert "task_get(task-abc)" in prompt
    assert "fetch full context" in prompt.lower()


def test_build_prompt_without_repeat_instructions():
    prompt = build_prompt("task-xyz", "")
    assert "task-xyz" in prompt
    assert "task_get(task-xyz)" in prompt
