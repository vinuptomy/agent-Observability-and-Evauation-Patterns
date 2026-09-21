"""AutoGen AgentChat (0.4+) integration.

    pip install "agentic-eval-kit[autogen]" "autogen-ext[openai]"
    python -m examples.integrations.autogen_team

Plug-in point: convert the ``TaskResult`` returned by ``team.run(...)``. Tool requests/executions,
``HandoffMessage`` (Swarm) and speaker changes are mapped to TOOL / HANDOFF / AGENT spans with token usage.
"""
from __future__ import annotations

import asyncio

from agentic_eval import EvalCase, Evaluator, create_metric
from agentic_eval.adapters.autogen_adapter import trace_from_autogen_result


def build_team():  # your existing team — unchanged
    from autogen_agentchat.agents import AssistantAgent
    from autogen_agentchat.conditions import MaxMessageTermination
    from autogen_agentchat.teams import Swarm
    from autogen_ext.models.openai import OpenAIChatCompletionClient

    model = OpenAIChatCompletionClient(model="gpt-4o-mini")

    def create_ticket(summary: str, priority: str) -> str:
        return "INC-9"

    triage = AssistantAgent("triage", model_client=model, handoffs=["network_ops"],
                            system_message="Classify the request, then hand off to network_ops for outages.")
    network_ops = AssistantAgent("network_ops", model_client=model, tools=[create_ticket],
                                 system_message="Open a high priority incident. Reply with the ticket id.")
    return Swarm([triage, network_ops], termination_condition=MaxMessageTermination(8))


async def target(user_input: str):
    result = await build_team().run(task=user_input)
    return trace_from_autogen_result(result, task=user_input)


if __name__ == "__main__":
    case = EvalCase(case_id="vpn", input="VPN down for all Vienna users", expected_tools=["create_ticket"],
                    expected_handoffs=[["triage", "network_ops"]], constraints={"max_tokens": 6000})
    ev = Evaluator([create_metric(n) for n in ("tool_call_accuracy", "handoff_accuracy", "token_budget")])
    print(asyncio.run(ev.arun(target, [case])).summary())
