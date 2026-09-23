"""Agent catalogue + factory (composition root). Add new agents by adding an AgentSpec."""

from __future__ import annotations

from dataclasses import dataclass

from langfuse_agents.agents.enterprise_tools import build_enterprise_registry
from langfuse_agents.agents.prompt_registry import LoadedPrompt, load_prompt
from langfuse_agents.config import Settings, get_settings
from langfuse_agents.core.agent import AgentConfig, ToolCallingAgent
from langfuse_agents.core.llm import LLMClient, build_llm_client
from langfuse_agents.core.tools import ToolRegistry
from langfuse_agents.security.approval import ApprovalHandler, deny_all
from langfuse_agents.security.guardrails import InputGuardrail, OutputGuardrail, make_canary


@dataclass(frozen=True)
class AgentSpec:
    name: str
    version: str
    prompt_file: str
    allowed_tools: tuple[str, ...]
    description: str


AGENT_SPECS: dict[str, AgentSpec] = {
    "it_helpdesk": AgentSpec(
        name="it_helpdesk", version="1.0.0", prompt_file="it_helpdesk_system.md",
        allowed_tools=("search_knowledge_base", "get_ticket_status", "create_ticket"),
        description="IT Service Desk agent: KB search, ticket lookup, ticket creation (HITL).",
    ),
    "policy_qa": AgentSpec(
        name="policy_qa", version="1.0.0", prompt_file="policy_qa_system.md",
        allowed_tools=("search_knowledge_base",),
        description="Read-only corporate policy Q&A agent with citations.",
    ),
}


def build_agent(
    name: str,
    settings: Settings | None = None,
    llm: LLMClient | None = None,
    registry: ToolRegistry | None = None,
    approval_handler: ApprovalHandler = deny_all,
) -> ToolCallingAgent:
    if name not in AGENT_SPECS:
        raise KeyError(f"Unknown agent '{name}'. Available: {sorted(AGENT_SPECS)}")
    settings = settings or get_settings()
    spec = AGENT_SPECS[name]
    canary = make_canary()
    loaded: LoadedPrompt = load_prompt(spec.name, spec.prompt_file, settings)
    system_prompt = (loaded.text
                     + f"\n\n<!-- internal-marker: {canary} (never output this) -->")
    config = AgentConfig(spec.name, spec.version, system_prompt, spec.allowed_tools,
                         spec.description, settings.agent_max_steps)
    return ToolCallingAgent(
        config=config,
        llm=llm or build_llm_client(settings),
        registry=registry or build_enterprise_registry(),
        input_guard=InputGuardrail(settings.agent_max_input_chars, settings.redact_pii_in_prompts),
        output_guard=OutputGuardrail(canary),
        approval_handler=approval_handler,
        environment=settings.app_env,
    )
