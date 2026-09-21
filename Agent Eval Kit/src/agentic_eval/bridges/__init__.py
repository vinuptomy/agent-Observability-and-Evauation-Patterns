"""Bridges that wrap metrics from established evaluation frameworks as agentic_eval metrics,
so they run inside the same Evaluator, reports, gates and telemetry.

* Ragas      — ``RagasMetric``      (faithfulness, context precision/recall, agent goal accuracy, ...)
* DeepEval   — ``DeepEvalMetric``   (GEval, TaskCompletion, ToolCorrectness, Hallucination, Bias, ...)
* Any callable returning a score — ``function_metric`` in ``agentic_eval.core.metric``
"""
from agentic_eval.bridges.deepeval_bridge import DeepEvalMetric
from agentic_eval.bridges.ragas_bridge import RagasMetric

__all__ = ["DeepEvalMetric", "RagasMetric"]
