from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .external_tools import load_external_tools
from .llm import ChatLLM, OpenAICompatibleLLM
from .tools import AgentTool, default_tools, render_tools_for_prompt


SYSTEM_PROMPT = """You are a ReAct agent for the GIS2BEM workflow.

Your job is to solve the user's task by choosing workflow tools.
Prefer built-in GIS2BEM tools for core modelling steps. Use external HTTP tools
when the user-provided API is relevant to the task (for example open-source
weather, geospatial, knowledge, or model services).
Do not run EnergyPlus batch simulations unless the user explicitly asks for simulation.

Use exactly one of these response formats:

Thought: explain your reasoning briefly
Action: tool_name
Action Input: {{"key": "value"}}

or:

Final Answer: concise answer to the user

Rules:
- Action Input must be valid JSON.
- Use only tools listed below.
- Inspect config first when config_path is available and the task depends on project paths.
- Stop when you have enough evidence to answer.

Available tools:
{tools}
"""


@dataclass
class AgentStep:
    thought: str
    action: Optional[str] = None
    action_input: Optional[dict[str, Any]] = None
    observation: Optional[dict[str, Any]] = None
    final_answer: Optional[str] = None
    raw: str = ""


@dataclass
class AgentResult:
    success: bool
    final_answer: str
    steps: list[AgentStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "final_answer": self.final_answer,
            "steps": [
                {
                    "thought": step.thought,
                    "action": step.action,
                    "action_input": step.action_input,
                    "observation": step.observation,
                    "final_answer": step.final_answer,
                    "raw": step.raw,
                }
                for step in self.steps
            ],
        }


def parse_react_message(text: str) -> AgentStep:
    final_match = re.search(r"Final Answer:\s*(.*)", text, flags=re.S)
    if final_match:
        return AgentStep(thought="", final_answer=final_match.group(1).strip(), raw=text)

    thought_match = re.search(r"Thought:\s*(.*?)(?:\nAction:|\Z)", text, flags=re.S)
    action_match = re.search(r"Action:\s*([A-Za-z_][A-Za-z0-9_]*)", text)
    input_match = re.search(r"Action Input:\s*(\{.*\})", text, flags=re.S)

    thought = thought_match.group(1).strip() if thought_match else ""
    if not action_match:
        raise ValueError(f"Could not parse Action from LLM output: {text}")
    if not input_match:
        raise ValueError(f"Could not parse Action Input from LLM output: {text}")

    try:
        action_input = json.loads(input_match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Action Input must be valid JSON: {exc}") from exc

    if not isinstance(action_input, dict):
        raise ValueError("Action Input must decode to a JSON object.")

    return AgentStep(thought=thought, action=action_match.group(1), action_input=action_input, raw=text)


class ReActAgent:
    def __init__(
        self,
        llm: ChatLLM,
        tools: Optional[dict[str, AgentTool]] = None,
        max_steps: int = 8,
    ) -> None:
        self.llm = llm
        self.tools = tools or default_tools()
        self.max_steps = max_steps

    def run(self, task: str, *, config_path: Optional[str] = None) -> AgentResult:
        context = f"Task: {task}"
        if config_path:
            context += f"\nKnown config_path: {config_path}"

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT.format(tools=render_tools_for_prompt(self.tools))},
            {"role": "user", "content": context},
        ]
        steps: list[AgentStep] = []

        for _ in range(self.max_steps):
            raw = self.llm.complete(messages)
            step = parse_react_message(raw)
            steps.append(step)

            if step.final_answer is not None:
                return AgentResult(success=True, final_answer=step.final_answer, steps=steps)

            if step.action not in self.tools:
                observation = {"success": False, "error": f"Unknown tool: {step.action}"}
            else:
                try:
                    observation = self.tools[step.action].func(step.action_input or {})
                except Exception as exc:
                    observation = {"success": False, "error": f"{type(exc).__name__}: {exc}"}

            step.observation = observation
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": "Observation: " + json.dumps(observation, ensure_ascii=False)})

        return AgentResult(
            success=False,
            final_answer=f"Reached max_steps={self.max_steps} without a Final Answer.",
            steps=steps,
        )


def build_tools(external_tools_path: Optional[str] = None) -> dict[str, AgentTool]:
    tools = default_tools()
    tools.update(load_external_tools(external_tools_path))
    return tools


def run_agent(
    task: str,
    config_path: Optional[str] = None,
    max_steps: int = 8,
    external_tools_path: Optional[str] = None,
) -> dict[str, Any]:
    agent = ReActAgent(llm=OpenAICompatibleLLM(), tools=build_tools(external_tools_path), max_steps=max_steps)
    return agent.run(task, config_path=config_path).to_dict()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GIS2BEM ReAct agent.")
    parser.add_argument("--task", required=True, help="Natural language task for the agent.")
    parser.add_argument("--config", dest="config_path", help="Optional workflow config path.")
    parser.add_argument("--external-tools", dest="external_tools_path", help="Optional JSON/YAML external HTTP tools file.")
    parser.add_argument("--max-steps", type=int, default=8)
    args = parser.parse_args()

    result = run_agent(
        args.task,
        config_path=args.config_path,
        max_steps=args.max_steps,
        external_tools_path=args.external_tools_path,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

