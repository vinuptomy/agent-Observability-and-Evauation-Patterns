# System Instructions (Prompt) Design & Governance

Prompts live in `src/enterprise_agents/prompts/` as Markdown and are versioned with the code
(`AgentSpec.version`). Every trace records the agent version, so behaviour changes are attributable.

## Structure used

1. **Role** — who the agent is and whom it serves.
2. **Objectives** — ordered priorities.
3. **Tools** — when to use each, and risk notes.
4. **Operating rules** — grounding, citations, untrusted-data handling, secrets, confidentiality, escalation.
5. **Output format** — concise, structured, with citations.

## Principles

* **Ground or abstain.** Answer from tool results; say "not documented" rather than guess.
* **Instructions ≠ data.** Content in `<tool_output>` is never followed as instructions.
* **Defence in depth.** Prompt rules are *not* the only control; allowlists, validation, approval and guardrails enforce the same rules in code.
* **No secrets in prompts.** The canary marker is random per process and exists only to detect leakage.

## Change process

1. Edit prompt → bump `AgentSpec.version`.
2. `pytest` + `agentctl eval --mode local` must pass.
3. Run `agentctl eval --mode opik --experiment <agent>-v<version>` with the real model; compare against the previous experiment in Opik.
4. Merge with reviewer approval; deploy; monitor feedback scores and online evaluation in Opik.
