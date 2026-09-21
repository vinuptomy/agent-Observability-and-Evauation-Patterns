# 07 · CI/CD & deployment

## Where evaluation sits in the delivery lifecycle

```
 develop ──► PR ─────────────► main ───────────► release ─────────► production
   │          │ unit tests       │ full suite       │ gate = go/no-go   │ OnlineEvaluator (sampled)
   │          │ offline eval     │ real LLM judge   │ signed reports    │ dashboards + alerts
   │          │ (mock judge)     │ JUnit + summary  │ audit log kept    │ failures → new EvalCases
 local: make test / make demo    nightly: drift check on larger dataset
```

## Local

```bash
pip install -e ".[dev]"
make test            # pytest
make lint            # ruff
make demo            # production vs. naive comparison
make eval            # CLI run with the quality gate (exit code)
```

## GitHub Actions

`.github/workflows/agent-eval.yml` is ready to use:

* **`test` job** — Python 3.10 & 3.12 matrix, `ruff`, `pytest`.
* **`eval` job** — installs the kit, runs `agentic-eval run` with the quality gate, verifies the audit
  chain, writes the Markdown report into the **job summary**, publishes JUnit as a **check run**, uploads
  `reports/` as an artifact (30 days).
* **Judge selection** — pull requests use the `mock` judge (no secrets exposed to forks); `main`, nightly
  and manual runs use `azure_openai` with `AZURE_OPENAI_ENDPOINT` / `AZURE_OPENAI_API_KEY` repository secrets.

To adapt to your app: replace `--dataset` and `--target` with your own, and add your package prefix to
`security.allowed_target_modules`. For keyless Azure access from GitHub, use `azure/login` with OIDC
federated credentials and drop the API key (the judge falls back to `DefaultAzureCredential`).

## Azure DevOps

```yaml
trigger: [main]
pr: [main]
pool: {vmImage: ubuntu-latest}
steps:
  - task: UsePythonVersion@0
    inputs: {versionSpec: "3.12"}
  - script: pip install -e ".[azure]"
    displayName: Install
  - task: AzureCLI@2                    # service connection with workload identity federation → no secrets
    displayName: Agent evaluation
    inputs:
      azureSubscription: sc-ai-eval
      scriptType: bash
      scriptLocation: inlineScript
      inlineScript: |
        export AGENTIC_EVAL_JUDGE=azure_openai AZURE_OPENAI_ENDPOINT=$(AOAI_ENDPOINT)
        agentic-eval run --config config/eval_config.yaml \
          --dataset evals/dataset.jsonl --target my_company.agents.app:run
  - task: PublishTestResults@2
    condition: always()
    inputs: {testResultsFormat: JUnit, testResultsFiles: "reports/*.junit.xml", testRunTitle: "Agent evaluation"}
  - publish: reports
    artifact: eval-reports
    condition: always()
```

## GitLab CI

```yaml
agent-eval:
  image: python:3.12-slim
  script:
    - pip install -e ".[openai]"
    - agentic-eval run --config config/eval_config.yaml --dataset evals/dataset.jsonl --target my_company.agents.app:run
  artifacts:
    when: always
    reports: {junit: reports/*.junit.xml}
    paths: [reports/]
```

## Docker

```bash
docker build -t agentic-eval-kit .                         # EXTRAS build-arg, default "azure,otel"
docker build --build-arg EXTRAS="openai,langchain" -t agentic-eval-kit:lc .
docker run --rm -v "$PWD/reports:/app/reports" agentic-eval-kit            # runs the sample suite

docker run --rm --env-file .env -v "$PWD/reports:/app/reports" \
  -v "$PWD/evals:/app/evals:ro" agentic-eval-kit \
  run --config config/eval_config.yaml --dataset evals/dataset.jsonl --target examples.enterprise_it_service_desk.agents:run_service_desk
```

The image is `python:3.12-slim`, runs as non-root UID 10001, and contains no secrets. To evaluate your own
agents, build a derived image that installs your application package (or install the kit into your app's
image — recommended, so the target imports cleanly).

## Scheduled evaluations (drift detection)

Model providers update models, prompts drift, knowledge bases change. Run the full suite on a schedule:

* **Azure Container Apps Job** (cron trigger) or **Kubernetes CronJob** running the image, with a managed /
  workload identity for Azure OpenAI and a mounted volume or Blob Storage upload for `reports/`.
* Compare `summary()` with the previous run and alert when a metric mean drops by more than a tolerance
  (e.g. 0.05) — a simple script over the JSON reports, or push scores to OTel/Langfuse and alert there.

## Release gating policy (recommended)

| Rule | Why |
|---|---|
| Safety category is blocking | One leaked secret or privileged action is a no-go regardless of averages |
| `min_pass_rate` 1.0 on the golden set, ≥ 0.95 on larger sets | Non-determinism tolerance on big suites only |
| `metric_min_means` on tool selection and handoffs ≥ 0.9 | Routing and action regressions are the most expensive |
| Report + audit log archived per release | Evidence for change management / AI governance |
| Judge model version pinned in config | Reproducibility of the verdict |
