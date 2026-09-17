# Security Measures

## Threat model → controls (OWASP Top 10 for LLM Applications mapping)

| Risk | Threat | Control in this solution | File |
|---|---|---|---|
| LLM01 Prompt injection (direct) | User overrides instructions | Pattern-based input guardrail; blocked **before** the LLM | `security/guardrails.py` |
| LLM01 Prompt injection (indirect) | Malicious content in tool/KB output | Tool output wrapped in `<tool_output>` + closing-tag escaping; prompt states it's untrusted data | `guardrails.wrap_untrusted`, prompts |
| LLM02 Sensitive information disclosure | PII in prompts, traces, logs, answers | Regex PII redaction at input, trace export, logging and output | `security/pii.py`, `observability/tracing.py`, `logging_config.py` |
| LLM07 System prompt leakage | Model reveals instructions | Per-agent random canary token; output containing it is blocked | `guardrails.OutputGuardrail` |
| LLM06 Excessive agency | Agent performs unauthorised actions | Per-agent tool allowlist (schema filter + runtime re-check); `requires_approval` for high-risk tools; default `deny_all` | `core/agent.py`, `security/approval.py` |
| LLM05 Improper output handling | Tool args used unsafely | Strict pydantic validation (regex, enums, lengths) before execution | `core/tools.py` |
| LLM10 Unbounded consumption | Loops, huge inputs, cost blow-ups | Max steps, input length limit, token and cost tracking, retry cap | `config.py`, `core/agent.py` |
| Error leakage | Stack traces reach model/user | Tools return generic errors; details only in server logs | `core/tools.py` |
| Secrets exposure | Keys in code or logs | `SecretStr` config, `.env` git-ignored, secrets from vault in deployment | `config.py` |
| API abuse | Unauthenticated access | `X-API-Key` with constant-time comparison; gateway + Entra ID/OAuth2 in prod | `api/app.py` |
| Container compromise | Privilege escalation | Non-root user, read-only filesystem, `no-new-privileges`, multi-stage slim image | `Dockerfile`, `docker-compose.yml` |

## Production hardening checklist

- [ ] Replace regex guardrails with/add a managed classifier (e.g. Azure AI Content Safety Prompt Shields, Llama Guard) — keep regex as a cheap first pass.
- [ ] Add Microsoft Presidio or Azure AI Language for PII in multiple languages.
- [ ] Route `create_ticket` approvals through ITSM/Teams approval flows, not console prompts.
- [ ] Propagate end-user identity to tools (on-behalf-of) so tools enforce the user's own permissions.
- [ ] Rate limiting per user and per tenant at the gateway.
- [ ] Self-host Opik in the same trust boundary for confidential data; enable RBAC and retention.
- [ ] Red-team before go-live; add findings to the eval dataset.
- [ ] Map controls to EU AI Act transparency/logging obligations and ISO/IEC 42001 where applicable.
- [ ] Dependency scanning (e.g. `pip-audit`) and image scanning in CI.

## Known limitations

Pattern-based injection detection is **not** a complete defence; it's one layer. The primary
protection against harmful actions is architectural: least privilege, validated arguments and
human approval for any write operation.
