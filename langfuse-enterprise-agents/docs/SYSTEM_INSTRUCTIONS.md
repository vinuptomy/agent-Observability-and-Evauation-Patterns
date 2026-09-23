# System Instructions (Prompt) Design & Governance

Prompts live in `src/langfuse_agents/prompts/` as Markdown and are versioned with the code
(`AgentSpec.version`, propagated onto every trace). Optionally they can be served from **Langfuse
Prompt Management**.

## Structure used

1. **Role** — who the agent is and whom it serves.
2. **Objectives** — ordered priorities.
3. **Tools** — when to use each, with risk notes.
4. **Operating rules** — grounding, citations, untrusted-data handling, secrets, confidentiality,
   escalation.
5. **Output format** — concise, structured, with citations.

## Principles

* **Ground or abstain.** Answer from tool results; say "not documented" rather than guess.
* **Instructions ≠ data.** Content inside `<tool_output>` is never followed as instructions.
* **Defence in depth.** Prompt rules are *not* the only control: allowlists, validation, approval
  and guardrails enforce the same rules in code.
* **No secrets in prompts.** The canary marker is random per process and exists only to detect
  leakage.

## File prompts vs Langfuse prompt management

| | Repository files (default) | Langfuse prompt management (`LANGFUSE_PROMPT_MANAGEMENT=true`) |
|---|---|---|
| Change process | Pull request, code review, deploy | Edit in the UI, label `production`, no deploy |
| Rollback | Git revert + deploy | Switch the label to a previous version |
| Audience | Engineers | Product owners, support leads, prompt engineers |
| Risk | Slower iteration | Prompt changes bypass code review — govern with labels and approvals |
| Availability | Always local | Cached by the SDK; this repo falls back to the file version on any error |

Whichever source is used, the evaluation gate is the control that matters: no prompt reaches
`production` without a passing dataset run.

## Change process

1. Edit the prompt (file or Langfuse draft) → bump `AgentSpec.version`.
2. `pytest` + `agentctl-lf eval --mode local` must pass.
3. Run `agentctl-lf eval --mode langfuse --run-name <agent>-v<version>` with the real model and
   compare against the previous run.
4. Merge / promote the label; deploy; watch trace scores and user feedback in Langfuse.
