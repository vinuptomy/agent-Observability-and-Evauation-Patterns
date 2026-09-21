"""Universal path: evaluate ANY framework that emits OpenTelemetry spans (runs offline).

Works with OTel GenAI semantic conventions (``gen_ai.*``) and OpenInference (Arize Phoenix, LlamaIndex,
Semantic Kernel, Google ADK, AWS Bedrock/Strands, DSPy, smolagents, Pydantic AI, ...).

    python -m examples.integrations.otel_any_framework

In production, export spans via OTLP/JSON (file exporter, collector, or ``InMemorySpanExporter`` in tests)
and feed them to ``trace_from_otel_spans`` — no change to the agent code at all.
"""
from __future__ import annotations

import json
from pathlib import Path

from agentic_eval import EvalCase, Evaluator, create_metric
from agentic_eval.adapters.otel_adapter import trace_from_otel_spans

SPANS = Path(__file__).resolve().parents[1] / "sample_traces" / "otel_genai_spans.json"


def main() -> None:
    trace = trace_from_otel_spans(json.loads(SPANS.read_text()),
                                  final_output="High priority incident INC-1 opened for the VPN outage.")
    case = EvalCase(case_id="otel-vpn", input="My VPN is down and I cannot work",
                    expected_tools=["search_kb", "create_ticket"],
                    expected_agents=["supervisor", "knowledge_agent", "resolution_agent"],
                    expected_handoffs=[["supervisor", "knowledge_agent"], ["supervisor", "resolution_agent"]],
                    constraints={"max_tokens": 1000, "max_latency_ms": 5000})
    ev = Evaluator([create_metric(n) for n in ("tool_call_accuracy", "handoff_accuracy", "agent_participation",
                                               "token_budget", "latency_budget", "loop_detection")])
    result = ev.evaluate_trace(trace, case)
    for m in result.results:
        print(f"{m.metric:<24} score={m.score if m.score is None else round(m.score, 3)} passed={m.passed}")


if __name__ == "__main__":
    main()
