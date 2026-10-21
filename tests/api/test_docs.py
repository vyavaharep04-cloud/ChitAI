"""The documentation must describe what the code really does."""

from __future__ import annotations

from pathlib import Path

from chitai.api.rooms import AI_AGENTS

ROOT = Path(__file__).parents[2]


def test_readme_documents_the_real_start_command_agents_and_limits():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "python -m chitai.api" in readme and "http://127.0.0.1:8000" in readme
    assert "Human vs AI" in readme and "RuleBot" in readme and "MindBot" in readme
    assert "No claim is made that MindBot plays better" in readme
    assert "Current limitations" in readme and "No reconnection" in readme
    for kind, (label, spec) in AI_AGENTS.items():  # the documented presets are the real ones
        assert label in readme and spec.agent_config["non_target_order"] in readme


def test_project_context_has_an_additive_m10_entry_and_keeps_history():
    text = (ROOT / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
    assert "### 2026-10-21 — Milestone 10 implemented" in text
    assert "### 2026-10-19 — Milestone 8 implemented" in text  # history untouched
    assert text.index("Milestone 8 implemented") < text.index("Milestone 10 implemented")
    assert "has not been inspected in a real browser" in text
