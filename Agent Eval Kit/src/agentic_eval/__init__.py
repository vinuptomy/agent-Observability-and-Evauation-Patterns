"""agentic_eval — a pluggable, framework-agnostic evaluation toolkit for (multi-)agent AI systems.

Typical usage::

    from agentic_eval import Evaluator, load_dataset, create_metric, create_judge

    evaluator = Evaluator(
        metrics=[create_metric("task_completion"), create_metric("handoff_accuracy")],
        judge=create_judge("azure_openai", model="gpt-4o-mini"),
    )
    report = evaluator.run(my_agent_callable, load_dataset("cases.jsonl"))
"""
import agentic_eval.metrics  # noqa: F401,E402  (registers built-in metrics)
from agentic_eval.collectors.decorators import handoff, trace_agent, trace_tool
from agentic_eval.collectors.tracer import Tracer
from agentic_eval.core.metric import (
    BaseMetric,
    MetricCategory,
    create_metric,
    function_metric,
    list_metrics,
    register_metric,
)
from agentic_eval.core.models import (
    CaseResult,
    EvalCase,
    EvalReport,
    MetricResult,
    Span,
    SpanKind,
    ToolCall,
    Trace,
)
from agentic_eval.judges import BaseJudge, MockJudge, create_judge
from agentic_eval.runners.dataset import load_dataset
from agentic_eval.runners.evaluator import Evaluator
from agentic_eval.runners.gate import GateResult, QualityGate
from agentic_eval.runners.online import OnlineEvaluator

__version__ = "1.0.0"

__all__ = [
    "BaseJudge", "BaseMetric", "CaseResult", "EvalCase", "EvalReport", "Evaluator", "GateResult",
    "MetricCategory", "MetricResult", "MockJudge", "OnlineEvaluator", "QualityGate", "Span", "SpanKind",
    "ToolCall", "Trace", "Tracer", "create_judge", "create_metric", "function_metric", "handoff",
    "list_metrics", "load_dataset", "register_metric", "trace_agent", "trace_tool", "__version__",
]
