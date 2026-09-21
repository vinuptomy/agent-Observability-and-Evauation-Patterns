"""CrewAI integration.

    pip install "agentic-eval-kit[crewai]"
    python -m examples.integrations.crewai_crew        # needs an LLM configured for CrewAI

Plug-in point: ``CrewAIAdapter().instrument(crew)`` wires CrewAI's ``step_callback`` / ``task_callback``;
``adapter.finish(crew_output)`` returns the Trace. Task ownership changes between agents become HANDOFF spans.
"""
from __future__ import annotations

from agentic_eval import EvalCase, Evaluator, create_metric
from agentic_eval.adapters.crewai_adapter import CrewAIAdapter


def build_crew():  # your existing crew — unchanged
    from crewai import Agent, Crew, Process, Task

    analyst = Agent(role="triage_agent", goal="Classify IT requests and set priority",
                    backstory="Senior service-desk analyst. Never executes changes.")
    resolver = Agent(role="resolution_agent", goal="Resolve the request with approved procedures",
                     backstory="ITIL-certified engineer. Always documents a ticket.")
    t1 = Task(description="Classify: {request}", expected_output="category + priority", agent=analyst)
    t2 = Task(description="Resolve the classified request", expected_output="resolution summary", agent=resolver)
    return Crew(agents=[analyst, resolver], tasks=[t1, t2], process=Process.sequential)


def target(user_input: str):
    adapter = CrewAIAdapter()                  # attaches to the Evaluator's active Tracer
    crew = adapter.instrument(build_crew())
    output = crew.kickoff(inputs={"request": user_input})
    return adapter.finish(output)              # returning a Trace is allowed


if __name__ == "__main__":
    cases = [EvalCase(case_id="license", input="I need an Adobe Acrobat Pro license",
                      expected_agents=["triage_agent", "resolution_agent"],
                      expected_handoffs=[["triage_agent", "resolution_agent"]],
                      constraints={"max_steps": 12, "max_latency_ms": 60000})]
    ev = Evaluator([create_metric(n) for n in ("agent_participation", "handoff_accuracy",
                                               "coordination_efficiency", "step_budget", "latency_budget")])
    print(ev.run(target, cases).summary())
