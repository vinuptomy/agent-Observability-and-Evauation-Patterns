"""Framework adapters: translate native framework events into a framework-agnostic ``Trace``.

Each adapter imports its framework lazily, so installing agentic_eval never pulls heavy dependencies.

| Framework                         | Adapter                                   |
|-----------------------------------|-------------------------------------------|
| LangChain / LangGraph             | ``langchain_adapter.AgentEvalCallbackHandler`` |
| CrewAI                            | ``crewai_adapter.CrewAIAdapter``          |
| Microsoft AutoGen (AgentChat 0.4+) | ``autogen_adapter.trace_from_autogen_result`` |
| OpenAI Agents SDK                 | ``openai_agents_adapter.AgentEvalTracingProcessor`` |
| Any OTel-instrumented framework (Semantic Kernel, LlamaIndex, Google ADK, Bedrock, Strands) | ``otel_adapter.trace_from_otel_spans`` |
| Custom code                       | ``@trace_agent`` / ``@trace_tool`` / ``Tracer`` |
"""
