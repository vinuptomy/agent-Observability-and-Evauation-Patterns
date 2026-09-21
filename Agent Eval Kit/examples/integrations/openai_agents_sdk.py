"""OpenAI Agents SDK integration.

    pip install "agentic-eval-kit[openai-agents]"
    python -m examples.integrations.openai_agents_sdk

Plug-in point: register ``AgentEvalTracingProcessor`` once at startup. It implements the SDK's
TracingProcessor protocol, so agent / generation / function / handoff / guardrail spans are captured natively.
"""
from __future__ import annotations

import asyncio

from agentic_eval import EvalCase, Evaluator, create_metric
from agentic_eval.adapters.openai_agents_adapter import AgentEvalTracingProcessor

PROCESSOR = AgentEvalTracingProcessor()


def setup():
    from agents import add_trace_processor
    add_trace_processor(PROCESSOR)  # keeps the default OpenAI exporter as well


def build_agents():  # your existing agents — unchanged
    from agents import Agent, function_tool

    @function_tool
    def check_license(product: str) -> str:
        return f"{product}: 3 seats available"

    resolver = Agent(name="resolution_agent", instructions="Check licenses and answer.", tools=[check_license])
    return Agent(name="triage_agent", instructions="Route license requests to resolution_agent.",
                 handoffs=[resolver])


async def target(user_input: str):
    from agents import Runner
    result = await Runner.run(build_agents(), user_input)
    return PROCESSOR.pop_latest(final_output=result.final_output)


if __name__ == "__main__":
    setup()
    case = EvalCase(case_id="license", input="Do we have Adobe Acrobat Pro seats?",
                    expected_tools=["check_license"], expected_handoffs=[["triage_agent", "resolution_agent"]],
                    expected_tool_args={"check_license": {"product": "Adobe Acrobat Pro"}})
    ev = Evaluator([create_metric(n) for n in ("tool_call_accuracy", "tool_argument_accuracy", "handoff_accuracy")])
    print(asyncio.run(ev.arun(target, [case])).summary())
