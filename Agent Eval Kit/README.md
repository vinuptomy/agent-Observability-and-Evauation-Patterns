# agentic-eval-kit

**A framework-agnostic evaluation module for multi-agent AI systems.** Plug it into LangGraph, LangChain,
CrewAI, AutoGen, the OpenAI Agents SDK, Semantic Kernel, LlamaIndex, Google ADK, Bedrock/Strands — or your own
Python code — and evaluate *what the agents did*, not only *what they answered*.

```
Your agent app ──(adapter / decorators / OTel spans)──►  Trace  ──►  33 metrics + LLM judges  ──►  Report + Quality Gate
                                                                     (task, tool, trajectory,        (JSON · Markdown · JUnit,
                                                                      multi-agent, RAG, safety,       OTel metrics, Langfuse,
                                                                      performance, custom)            LangSmith, audit log)
```

| | |
|---|---|
| **Framework-agnostic** | One normalised `Trace` model. Adapters for LangChain/LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, plus a universal OpenTelemetry importer (GenAI semconv + OpenInference). |
| **Multi-agent native** | Handoff accuracy, agent participation, ping-pong/coordination efficiency, error propagation, role adherence, workload balance, collaboration quality — mapped to the MAST failure taxonomy. |
| **Best-of-breed methods** | G-Eval rubrics, LLM-as-judge (Likert, strict JSON), Ragas-style RAG triad, DeepEval-style tool correctness, τ-bench/AgentBench-style trajectory checks, deterministic metrics first. Native bridges to **Ragas** and **DeepEval**. |
| **Enterprise security** | PII redaction before any judge call, judge prompt-injection hardening, adversarial canary tests, forbidden-tool (least-privilege) checks, target module allow-list, hash-chained tamper-evident audit log. |
| **Observability** | Structured JSON logs, OpenTelemetry spans + metrics, exporters to Langfuse and LangSmith, online (production) sampling evaluator. |
| **CI/CD ready** | YAML config, CLI with exit codes, quality gate with blocking categories, JUnit output, GitHub Actions workflow, Docker image. |
| **Light core** | Only `pydantic` + `PyYAML` required. Every framework/provider is an optional extra with lazy imports. |

---

## 1. Install

Requirements: **Python 3.10+**.

```bash
# from the unzipped folder
cd agentic-eval-kit
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                                  # core + pytest + ruff

# add only what you use
pip install -e ".[azure]"          # Azure OpenAI judge (API key or Entra ID)
pip install -e ".[openai]"         # OpenAI / OpenAI-compatible gateways (vLLM, LiteLLM, Ollama)
pip install -e ".[anthropic]"      # Claude judge
pip install -e ".[langchain]"      # LangChain / LangGraph adapter
pip install -e ".[crewai]"         # CrewAI adapter
pip install -e ".[autogen]"        # AutoGen AgentChat adapter
pip install -e ".[openai-agents]"  # OpenAI Agents SDK adapter
pip install -e ".[otel]"           # OpenTelemetry export
pip install -e ".[ragas,deepeval]" # third-party metric bridges
pip install -e ".[langfuse]"       # Langfuse score export
pip install -e ".[all]"            # everything
```

Configure secrets via environment variables (never in YAML): `cp .env.example .env` and fill in what you need.
Everything works **offline by default** with the deterministic `mock` judge.

## 2. Run the enterprise sample (2 minutes, no API keys)

The repo ships an **Enterprise IT Service Desk** multi-agent system (supervisor → triage → knowledge → resolution)
with 4 test cases, including a prompt-injection attack — plus a deliberately *vulnerable* variant to prove the
suite catches regressions.

```bash
make test          # or: pytest -q                       → 26 tests
make demo          # or: python -m examples.enterprise_it_service_desk.run_eval
```

Expected output:

```
=== PRODUCTION === pass_rate=100% mean_score=0.982 gate=PASS
=== NAIVE ===      pass_rate=0%   mean_score=0.842 gate=FAIL
  - canary_leaked, forbidden tool 'reset_password' used, repeated search_kb x3, handoff_accuracy 0.79 ...
```

Reports land in `reports/` (`*.json`, `*.md`, `*.junit.xml`) together with the tamper-evident `audit.jsonl`.
Pre-generated examples: [production](docs/sample-reports/production-report.md) · [naive](docs/sample-reports/naive-report.md).

Via the CLI (what CI uses):

```bash
agentic-eval list-metrics
agentic-eval run --config config/eval_config.yaml \
                 --dataset examples/enterprise_it_service_desk/dataset.jsonl \
                 --target examples.enterprise_it_service_desk.agents:run_service_desk
echo $?            # 0 = gate passed, 1 = gate failed, 2 = configuration error
agentic-eval verify-audit reports/audit.jsonl
```

## 3. Plug it into your agents (3 lines)

```python
from agentic_eval import Evaluator, create_metric, create_judge, load_dataset

evaluator = Evaluator([create_metric("task_completion"), create_metric("tool_call_accuracy"),
                       create_metric("handoff_accuracy"), create_metric("prompt_injection_resilience")],
                      judge=create_judge("azure_openai", model="gpt-4o-mini"))
report = evaluator.run(my_agent_entrypoint, load_dataset("evals/dataset.jsonl"))   # fn(str) -> answer | Trace
print(report.summary())
```

How the trace is captured depends on your stack:

| Your stack | Plug-in point | Guide |
|---|---|---|
| LangGraph / LangChain | `config={"callbacks": [AgentEvalCallbackHandler()]}` | [docs/02](docs/02-integration-guide.md#langgraph--langchain) |
| CrewAI | `CrewAIAdapter().instrument(crew)` → `adapter.finish(output)` | [docs/02](docs/02-integration-guide.md#crewai) |
| AutoGen AgentChat 0.4+ | `trace_from_autogen_result(task_result)` | [docs/02](docs/02-integration-guide.md#autogen-agentchat) |
| OpenAI Agents SDK | `add_trace_processor(AgentEvalTracingProcessor())` | [docs/02](docs/02-integration-guide.md#openai-agents-sdk) |
| Semantic Kernel, LlamaIndex, ADK, Bedrock, Phoenix, *any OTel* | `trace_from_otel_spans(spans)` | [docs/02](docs/02-integration-guide.md#any-framework-via-opentelemetry) |
| Custom Python / REST services | `@trace_agent`, `@trace_tool`, `handoff()` | [docs/02](docs/02-integration-guide.md#custom-code-decorators) |
| Already have traces / logs | `evaluator.evaluate_traces([(trace, case), ...])` | [docs/02](docs/02-integration-guide.md#offline-trace-evaluation) |

Runnable snippets for each are in [`examples/integrations/`](examples/integrations).

## 4. Deploy

| Where | How |
|---|---|
| **GitHub Actions** | `.github/workflows/agent-eval.yml` — lint + tests, offline eval on PRs (mock judge, no secrets on forks), LLM-judged eval on `main` and nightly, JUnit check + Markdown job summary + report artifact. |
| **Azure DevOps / GitLab / Jenkins** | Run the same CLI; consume `reports/*.junit.xml`; fail the stage on exit code ≠ 0. |
| **Docker** | `make docker` → non-root image, `ENTRYPOINT agentic-eval`. Override `CMD` with your config/dataset/target. |
| **Scheduled (Azure Container Apps Jobs / K8s CronJob)** | Run the image on a schedule with a real judge (managed identity → Entra ID) to detect model/prompt drift. |
| **Production monitoring** | Embed `OnlineEvaluator` in your service: sampled, non-blocking, bounded queue; push scores to OTel / Langfuse / LangSmith. |

Details: [docs/07-ci-cd-and-deployment.md](docs/07-ci-cd-and-deployment.md).

## 5. Documentation

| # | Document | What you'll find |
|---|---|---|
| 01 | [Architecture](docs/01-architecture.md) | Design principles, components, data model, extension points |
| 02 | [**Integration guide**](docs/02-integration-guide.md) | Step-by-step plug-in for every framework + custom apps |
| 03 | [Metric catalogue & methodology](docs/03-metrics-catalogue.md) | All 33 metrics, what they catch, required fields, framework lineage |
| 04 | [Test cases & evaluation criteria](docs/04-test-cases-and-criteria.md) | `EvalCase` schema, the sample cases, how to author enterprise datasets |
| 05 | [Configuration & CLI](docs/05-configuration-and-cli.md) | YAML reference, env vars, quality gate, CLI commands |
| 06 | [LLM judges](docs/06-llm-judges.md) | Mock / OpenAI / Azure (Entra ID) / Anthropic / custom; judge best practices |
| 07 | [CI/CD & deployment](docs/07-ci-cd-and-deployment.md) | Pipelines, Docker, scheduled evals, release gating |
| 08 | [Observability & online evaluation](docs/08-observability-and-online-eval.md) | Logs, OTel, Langfuse/LangSmith, production sampling |
| 09 | [Security & governance](docs/09-security-and-governance.md) | Threat model, controls, audit, EU AI Act / ISO 42001 mapping |
| 10 | [System instructions](docs/10-system-instructions.md) | Agent system prompts, judge system prompt, prompt design rules |
| 11 | [Troubleshooting & FAQ](docs/11-troubleshooting-faq.md) | Common errors and answers |

## 6. Project structure

```
agentic-eval-kit/
├── src/agentic_eval/            # the installable package
│   ├── core/                    # Trace/Span/EvalCase models, BaseMetric + registry, config, exceptions
│   ├── collectors/              # Tracer (contextvars), @trace_agent / @trace_tool / handoff()
│   ├── adapters/                # LangChain·LangGraph, CrewAI, AutoGen, OpenAI Agents SDK, OpenTelemetry
│   ├── metrics/                 # task, tool, trajectory, multi_agent, rag, safety, performance, LLM-judge base
│   ├── judges/                  # BaseJudge (redaction, retries, concurrency), prompts, providers, mock
│   ├── bridges/                 # Ragas and DeepEval metric wrappers
│   ├── runners/                 # Evaluator (batch), OnlineEvaluator (prod), dataset loader, QualityGate
│   ├── security/                # PII detection/redaction, injection heuristics, audit chain, input validation
│   ├── observability/           # JSON logging, OTel telemetry, Langfuse / LangSmith exporters
│   ├── reporting/               # JSON, Markdown, JUnit reporters
│   └── cli.py                   # agentic-eval CLI
├── examples/
│   ├── enterprise_it_service_desk/   # multi-agent sample: prompts, tools, agents, dataset, runner
│   ├── integrations/                 # LangGraph, CrewAI, AutoGen, OpenAI Agents, OTel, custom metrics
│   └── sample_traces/                # OTel GenAI span fixture
├── config/eval_config.yaml      # full suite configuration + quality gate
├── tests/                       # pytest suite (metrics, security, adapters, end-to-end, examples)
├── docs/                        # the documentation set above
├── .github/workflows/           # CI pipeline
├── Dockerfile · Makefile · pyproject.toml · .env.example · LICENSE
```

## 7. Evaluation strategy in one picture

```
             ┌──────────── offline (pre-release) ────────────┐   ┌──── online (production) ────┐
 dataset ──► │ Evaluator.run(target) → metrics → QualityGate │ ► │ OnlineEvaluator (sampled)   │
 (golden +   │    deterministic first, LLM judge where needed │   │ → OTel / Langfuse dashboards │
 adversarial)│    JUnit + Markdown + audit log → CI verdict   │   │ → alerts → new test cases    │
             └────────────────────────────────────────────────┘   └──────────────┬──────────────┘
                   ▲                                                              │
                   └──────────── production failures become regression cases ─────┘
```

## License

MIT — see [LICENSE](LICENSE).
