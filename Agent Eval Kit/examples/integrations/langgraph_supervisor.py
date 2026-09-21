"""LangGraph / LangChain integration — supervisor multi-agent graph.

    pip install "agentic-eval-kit[langchain,azure]" langgraph langchain-openai
    python -m examples.integrations.langgraph_supervisor

Plug-in point: ONE callback handler passed via ``config={"callbacks": [...]}``. Every graph node becomes an
AGENT span, node transitions become HANDOFF spans, tool/LLM/retriever calls are captured automatically.
"""
from __future__ import annotations

from typing import Annotated, TypedDict

from agentic_eval import EvalCase, Evaluator, create_judge, create_metric
from agentic_eval.adapters.langchain_adapter import AgentEvalCallbackHandler


def build_graph():  # your existing application code — unchanged
    from langchain_core.messages import AIMessage
    from langchain_core.tools import tool
    from langgraph.graph import END, START, StateGraph
    from langgraph.graph.message import add_messages

    @tool
    def search_kb(query: str) -> str:
        """Search the IT knowledge base."""
        return "KB-310: open a high priority incident and escalate to network operations."

    @tool
    def create_ticket(summary: str, priority: str) -> str:
        """Create an ITSM ticket."""
        return "INC-42"

    class State(TypedDict):
        messages: Annotated[list, add_messages]

    def triage_agent(state: State):
        return {"messages": [AIMessage("category=network priority=high")]}

    def knowledge_agent(state: State):
        return {"messages": [AIMessage(search_kb.invoke({"query": "VPN outage"}))]}

    def resolution_agent(state: State):
        tid = create_ticket.invoke({"summary": "VPN outage", "priority": "high"})
        return {"messages": [AIMessage(f"High priority incident {tid} opened and escalated to network operations.")]}

    g = StateGraph(State)
    for name, fn in [("triage_agent", triage_agent), ("knowledge_agent", knowledge_agent),
                     ("resolution_agent", resolution_agent)]:
        g.add_node(name, fn)
    g.add_edge(START, "triage_agent")
    g.add_edge("triage_agent", "knowledge_agent")
    g.add_edge("knowledge_agent", "resolution_agent")
    g.add_edge("resolution_agent", END)
    return g.compile()


GRAPH = None


def target(user_input: str) -> str:
    """The Evaluator calls this per case. The handler attaches to the Tracer the Evaluator opened."""
    global GRAPH
    GRAPH = GRAPH or build_graph()
    handler = AgentEvalCallbackHandler()  # picks up Tracer.current()
    result = GRAPH.invoke({"messages": [("user", user_input)]}, config={"callbacks": [handler]})
    return result["messages"][-1].content


if __name__ == "__main__":
    case = EvalCase(
        case_id="vpn-outage", input="VPN is down for the whole Vienna office",
        expected_output="High priority incident opened and escalated to network operations",
        expected_tools=["search_kb", "create_ticket"],
        expected_agents=["triage_agent", "knowledge_agent", "resolution_agent"],
        expected_handoffs=[["triage_agent", "knowledge_agent"], ["knowledge_agent", "resolution_agent"]],
    )
    ev = Evaluator([create_metric("tool_call_accuracy"), create_metric("handoff_accuracy"),
                    create_metric("agent_participation"), create_metric("answer_correctness")],
                   judge=create_judge("mock"))
    print(ev.run(target, [case]).summary())
