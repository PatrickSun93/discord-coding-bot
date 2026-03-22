"""Verify router and tools_schema import cleanly after refactor."""

from devbot.llm.router import LLMRouter
from devbot.llm.tools_schema import ANTHROPIC_TOOLS, ROUTER_SYSTEM_PROMPT, TOOLS

# Anthropic tools format check
assert len(ANTHROPIC_TOOLS) == 9
for t in ANTHROPIC_TOOLS:
    assert "name" in t
    assert "input_schema" in t, f"Missing input_schema in {t['name']}"
print(f"ANTHROPIC_TOOLS OK: {[t['name'] for t in ANTHROPIC_TOOLS]}")

# OpenAI tools format check
assert len(TOOLS) == 9
for t in TOOLS:
    assert t.get("type") == "function"
    assert "function" in t
    assert "parameters" in t["function"], f"Missing parameters in {t['function']['name']}"
print(f"TOOLS (OpenAI) OK: {[t['function']['name'] for t in TOOLS]}")

# Parse Anthropic response mock
class FakeBlock:
    def __init__(self, btype, name=None, input_=None, text=None):
        self.type = btype
        self.name = name
        self.input = input_
        self.text = text


class FakeResponse:
    content = [
        FakeBlock(
            "tool_use",
            name="analyze_project",
            input_={"project": "backend", "goal": "evaluate current workflow"},
        )
    ]


decision = LLMRouter._parse_anthropic(FakeResponse())
assert decision.tool == "analyze_project"
assert decision.args["project"] == "backend"
print(f"_parse_anthropic OK: tool={decision.tool}, args={decision.args}")

assert "TEAM ROLES" in ROUTER_SYSTEM_PROMPT
assert "run_pipeline" in ROUTER_SYSTEM_PROMPT
print("\nAll router checks passed.")
