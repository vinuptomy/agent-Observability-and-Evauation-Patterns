# System Instructions (Prompt) Design & Governance

Prompts live in `src/phoenix_agents/prompts/` as Markdown and are versioned with the code
(`AgentSpec.version`), which is recorded in span metadata so behaviour changes stay attributable.

## Structure used

1. **Role** — who the agent is and whom it serves.
2. **Objectives** — ordered priorities.
3. **Tools** — when to use each, with risk notes.
4. **Operating rules** — grounding, citations, untrusted-data handling, secrets, confidentiality,
   escalation.
5. **Output format** — concise, structured, with citations.

## Principles

* **Ground or abstain.** Answer from retrieved articles; say "not documented" rather than guess.
  The `retrieval_hit_rate` and `citation_presence` metrics keep this honest.
* **Instructions ≠ data.** Content inside `<tool_output>` is never followed as instructions.
* **Defence in depth.** Prompt rules are not the only control: allowlists, argument validation,
  approval and guardrails enforce the same rules in code.
* **No secrets in prompts.** The canary marker is random per process and exists only to detect
  leakage.

## Change process

1. Edit the prompt → bump `AgentSpec.version`.
2. `pytest` + `agentctl-px eval --mode local` must pass.
3. Run `agentctl-px eval --mode phoenix --experiment-name <agent>-v<version>` with the real model
   and compare against the previous experiment; check retrieval metrics separately from generation
   metrics before blaming the prompt.
4. Merge with reviewer approval; deploy; watch span annotations and user feedback in Phoenix.

## Prompt experiments

Phoenix stores prompts and lets you compare versions; this folder keeps prompts in the repository so
they stay under code review. If you adopt Phoenix prompt management, keep the evaluation gate as the
promotion control — no prompt version reaches production without a passing dataset run.
