# Security Measures

## Threat model → controls (OWASP Top 10 for LLM Applications mapping)

| Risk | Threat | Control in this solution | File |
|---|---|---|---|
| LLM01 Prompt injection (direct) | User overrides instructions | Pattern-based input guardrail; blocked **before** the LLM; scored on the trace | `security/guardrails.py` |
| LLM01 Prompt injection (indirect) | Malicious content in tool/KB output | Tool output wrapped in `<tool_output>` with closing-tag escaping; prompts state it is untrusted data | `guardrails.wrap_untrusted`, `prompts/` |
| LLM02 Sensitive information disclosure | PII in prompts, traces, logs, answers | Redaction at input, at payload serialisation, in logs, on output — plus the Langfuse `mask` callback as a final export filter | `security/pii.py`, `observability/tracing.py`, `logging_config.py` |
| LLM07 System prompt leakage | Model reveals instructions | Per-agent random canary token; any output containing it is blocked | `guardrails.OutputGuardrail` |
| LLM06 Excessive agency | Agent performs unauthorised actions | Per-agent tool allowlist (schema filter + runtime re-check); `requires_approval` for high-risk tools; default `deny_all` | `core/agent.py`, `security/approval.py` |
| LLM05 Improper output handling | Tool arguments used unsafely | Strict pydantic validation (regex, enums, lengths) before execution | `core/tools.py` |
| LLM10 Unbounded consumption | Loops, huge inputs, cost blow-ups | Step budget, input length limit, token/cost tracking, retry cap, trace sampling | `config.py`, `core/agent.py` |
| Error leakage | Stack traces reach the model or user | Tools return generic errors; details only in server logs | `core/tools.py` |
| Secrets exposure | Keys in code or logs | `SecretStr` config, `.env` git-ignored, secrets from a vault in deployment | `config.py` |
| API abuse | Unauthenticated access | `X-API-Key` with constant-time comparison; gateway + Entra ID/OAuth2 in production | `api/app.py` |
| Observability data exposure | Traces contain business content | Self-hostable Langfuse (EU residency), project RBAC, retention settings, masking on by default | `docs/OBSERVABILITY.md` |
| Container compromise | Privilege escalation | Non-root user, read-only filesystem, `no-new-privileges`, multi-stage slim image | `Dockerfile`, `docker-compose.yml` |

## Production hardening checklist

- [ ] Add a managed classifier (Azure AI Content Safety Prompt Shields, Llama Guard) alongside the
      regex guardrails — keep regex as a cheap first pass.
- [ ] Add Microsoft Presidio or Azure AI Language for multilingual PII detection.
- [ ] Route `create_ticket`-style approvals through ITSM/Teams workflows, not console prompts.
- [ ] Propagate end-user identity into tools (on-behalf-of) so tools enforce the user's permissions.
- [ ] Rate-limit per user and per tenant at the gateway.
- [ ] Self-host Langfuse inside the same trust boundary for confidential data; configure RBAC and
      retention; restrict who can read traces.
- [ ] Red-team before go-live; add every finding to the evaluation dataset.
- [ ] Map controls to EU AI Act transparency and record-keeping obligations and ISO/IEC 42001.
- [ ] Dependency and image scanning in CI (`pip-audit`, Trivy).

## Known limitations

Pattern-based injection detection is **not** a complete defence; it is one layer. The primary
protection against harmful actions is architectural: least privilege, validated arguments, and
human approval for every write operation.
