import json
from pathlib import Path
from types import SimpleNamespace as NS

from agentic_eval.adapters.autogen_adapter import trace_from_autogen_result
from agentic_eval.adapters.otel_adapter import trace_from_otel_spans

ROOT = Path(__file__).resolve().parents[1]


def test_otel_genai_semconv_import():
    spans = json.loads((ROOT / "examples" / "sample_traces" / "otel_genai_spans.json").read_text())
    trace = trace_from_otel_spans(spans, final_output="Ticket INC-1 created")
    assert trace.tool_names == ["search_kb", "create_ticket"]
    assert ("supervisor", "resolution_agent") in trace.handoffs
    assert trace.total_tokens == 450


def test_autogen_task_result_conversion():
    call = NS(id="c1", name="create_ticket", arguments='{"priority": "high"}')
    msgs = [
        NS(type="TextMessage", source="user", content="VPN down"),
        NS(type="ToolCallRequestEvent", source="triage", content=[call], models_usage=NS(prompt_tokens=50, completion_tokens=10)),
        NS(type="ToolCallExecutionEvent", source="triage", content=[NS(call_id="c1", content="INC-9", is_error=False)]),
        NS(type="HandoffMessage", source="triage", target="network_ops", content="escalating"),
        NS(type="TextMessage", source="network_ops", content="Incident INC-9 escalated", models_usage=None),
    ]
    trace = trace_from_autogen_result(NS(messages=msgs, stop_reason="done"))
    assert trace.tool_calls[0].arguments == {"priority": "high"} and trace.tool_calls[0].output == "INC-9"
    assert trace.handoffs == [("triage", "network_ops")]
    assert trace.final_output == "Incident INC-9 escalated" and trace.input == "VPN down"
