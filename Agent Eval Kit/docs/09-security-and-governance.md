# 09 · Security & governance

The evaluation module has two security roles: it **tests** the security of your agents, and it must itself be
**safe to run** on sensitive enterprise data.

## A. Testing agent security

| Threat (OWASP LLM Top 10 2025) | How the kit tests it |
|---|---|
| LLM01 Prompt injection (direct & indirect) | `prompt_injection_resilience`: canary token in the system prompt must never appear; injected tool calls (`forbidden_tools`) must not execute; success markers must not appear; injection patterns in *tool outputs* (poisoned KB / email) are detected. Heuristic detector `security.injection.detect_injection` (7 rules: `override_instructions`, `role_hijack`, `prompt_exfiltration`, `no_restrictions`, `chat_template_tokens`, `tool_coercion`, `secret_request`). |
| LLM02 Sensitive information disclosure | `pii_leakage` on answers **and** tool arguments (email, IBAN with checksum, credit card with Luhn, phone, IPv4, API keys/secrets). |
| LLM06 Excessive agency | `forbidden_tool_usage`, `role_adherence`, custom approval metrics (see `approval_before_action` example) — least privilege and human-in-the-loop. |
| LLM07 System prompt leakage | canary + `policy_compliance` banned patterns (e.g. `my instructions are`). |
| LLM09 Misinformation | `faithfulness`, `answer_correctness`, `context_recall`. |
| LLM10 Unbounded consumption | `step_budget`, `token_budget`, `cost_budget`, `loop_detection`, `coordination_efficiency`. |

**Canary pattern.** Put a unique, meaningless token (e.g. `CANARY-7f3a91`) in the system prompt of the agent
under test and in `EvalCase.canary`. If it ever appears in an output or tool argument, the system prompt was
exfiltrated. The sample's `TC-004` uses this.

Recommended adversarial set per release: direct injection, indirect injection via retrieved content,
privilege escalation (admin/root/service accounts), PII exfiltration ("list all employees' emails"), jailbreak
role-play, tool-argument injection. For broad red-teaming, complement with PyRIT, garak or promptfoo and
import their findings as `EvalCase`s.

## B. Running the evaluator safely

| Control | Implementation |
|---|---|
| **No data egress without redaction** | `BaseJudge` redacts PII/secrets (`PIIRedactor`) before every judge call when `redact_pii_for_judge: true` (default). |
| **Judge prompt-injection hardening** | System-under-test data is wrapped in `<untrusted>` tags with closing-tag neutralisation; fixed judge system prompt forbids following embedded instructions; strict JSON output validated. |
| **No secrets in config** | `${ENV}` expansion; config snapshot in reports/audit is redacted; `.env` git-ignored; Azure Entra ID (managed identity) supported so no keys at all. |
| **Code-execution allow-list** | CLI `--target` must match `security.allowed_target_modules`, preventing a pipeline variable from importing arbitrary modules. |
| **Input validation & limits** | pydantic validation of every dataset row, duplicate id rejection, `max_cases`, `max_input_chars`, control-character sanitisation (`sanitize_text`). |
| **Payload truncation** | Tracer truncates stored span payloads (4 000 chars) to limit data retained in traces. |
| **Traces off in reports by default** | `reporting.include_traces: false` — reports contain scores and reasons, not business payloads, unless you opt in. |
| **Tamper-evident audit** | `AuditLogger` writes JSONL where each entry contains the SHA-256 of the previous one; `agentic-eval verify-audit` detects edits, deletions and reordering. Entries record actor, run id, dataset hash, config hash, results. |
| **Failure isolation** | Target exceptions/timeouts are scored, not propagated; online evaluation never raises into the request path. |
| **Least-privilege runtime** | Docker image runs as non-root; CI workflow uses minimal `permissions`; PRs from forks use the mock judge and get no secrets. |
| **Minimal supply chain** | Core depends only on `pydantic` + `PyYAML`; everything else is an opt-in extra. Pin versions in your lock file and scan with your SCA tool. |

### Data handling guidance

* Datasets should contain **synthetic** personal data only. Keep real incident data out of Git; if you must
  use it, store datasets in a restricted location and reference them from CI.
* Choose judge endpoints in the **same data region** as the data (e.g. Azure OpenAI Sweden Central / Germany
  West Central for EU), under your enterprise agreement's no-training terms.
* Retain reports and audit logs according to your records policy; they are evidence artefacts.

## C. Governance: mapping to frameworks

| Requirement | Evidence produced by the kit |
|---|---|
| **EU AI Act** — accuracy, robustness & cybersecurity (Art. 15), record-keeping (Art. 12), risk management & testing (Art. 9), post-market monitoring (Art. 72) for high-risk systems | Versioned datasets and metric thresholds (defined accuracy levels), adversarial robustness tests, audit log with dataset/config hashes, per-release reports, online monitoring |
| **ISO/IEC 42001** (AI management system) — performance evaluation (clause 9), operational controls, verification & validation (Annex A) | Documented evaluation criteria (quality gate), repeatable CI evaluation, records of results, continual-improvement loop |
| **NIST AI RMF** — MEASURE & MANAGE functions | Quantitative metrics per risk (safety, reliability, cost), tracking over time, gating decisions |
| **Internal change management** (ITIL / CAB) | JUnit + Markdown report attached to change, gate verdict as go/no-go criterion |

This is engineering evidence, not a legal assessment — involve your compliance function for classification
and conformity decisions.

## Security checklist before production

- [ ] At least one direct and one indirect injection case, one privilege-escalation case, one PII case
- [ ] Canary token present in each agent system prompt of the test deployment
- [ ] `forbidden_tools` defined for every case where destructive/privileged tools exist
- [ ] `blocking_categories: [safety]` in the gate
- [ ] `redact_pii_for_judge: true`, judge in approved data region, keyless auth where possible
- [ ] `allowed_target_modules` restricted to your packages
- [ ] Audit log archived and `verify-audit` part of the pipeline
- [ ] Online safety metrics (`pii_leakage`, `policy_compliance`) sampled in production with alerting
