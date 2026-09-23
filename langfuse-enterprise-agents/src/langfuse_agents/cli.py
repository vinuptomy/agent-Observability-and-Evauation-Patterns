"""Command-line interface: ``agentctl-lf``."""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from langfuse_agents.agents.factory import AGENT_SPECS, build_agent
from langfuse_agents.config import get_settings
from langfuse_agents.logging_config import configure_logging
from langfuse_agents.observability import tracing
from langfuse_agents.security.approval import console_approval, deny_all


def _cmd_list(_: argparse.Namespace) -> int:
    for spec in AGENT_SPECS.values():
        print(f"{spec.name:<14} v{spec.version:<7} tools={list(spec.allowed_tools)}\n  {spec.description}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    settings = get_settings()
    tracing.init_observability(settings)
    agent = build_agent(args.agent, settings, approval_handler=deny_all)
    result = agent.run(args.question, session_id=args.session or uuid.uuid4().hex,
                       user_id=args.user)
    tracing.flush()
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.answer)
        if result.trace_url:
            print(f"\nTrace: {result.trace_url}")
    return 0 if result.status in {"completed", "blocked"} else 1


def _cmd_chat(args: argparse.Namespace) -> int:
    settings = get_settings()
    tracing.init_observability(settings)
    agent = build_agent(args.agent, settings, approval_handler=console_approval)
    session = uuid.uuid4().hex
    print(f"Chatting with '{args.agent}' (session {session[:8]}). Type 'exit' to quit.")
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text.lower() in {"exit", "quit"}:
            break
        if text:
            result = agent.run(text, session_id=session, user_id=args.user)
            print(f"\n{args.agent}> {result.answer}\n  [status={result.status} steps={result.steps} "
                  f"tools={result.tool_names} tokens={result.usage.get('total_tokens')}]")
    tracing.flush()
    tracing.shutdown()
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from langfuse_agents.evaluation.runner import print_report, run_langfuse, run_local

    settings = get_settings()
    if args.mode == "langfuse":
        result = run_langfuse(settings, args.dataset_name, args.run_name, args.dataset)
        print(result.format(include_item_results=args.verbose))
        return 0
    report, passed = run_local(settings, args.dataset, args.thresholds, args.report_dir)
    print_report(report)
    return 0 if passed else 2


def _cmd_push_dataset(args: argparse.Namespace) -> int:
    from langfuse_agents.evaluation.dataset import load_cases, push_to_langfuse

    settings = get_settings()
    if not tracing.init_observability(settings):
        print("Langfuse is not configured; cannot push the dataset.", file=sys.stderr)
        return 1
    push_to_langfuse(tracing.get_client(), args.dataset_name or settings.eval_dataset_name,
                     load_cases(args.dataset))
    tracing.flush()
    print("Dataset pushed to Langfuse.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentctl-lf",
                                     description="Enterprise agents instrumented with Langfuse")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-agents", help="List available agents").set_defaults(func=_cmd_list)

    ask = sub.add_parser("ask", help="Single question to an agent")
    ask.add_argument("question")
    ask.add_argument("--agent", default="it_helpdesk", choices=sorted(AGENT_SPECS))
    ask.add_argument("--session", help="Session id (groups a conversation in Langfuse)")
    ask.add_argument("--user", help="End-user id attached to the trace")
    ask.add_argument("--json", action="store_true", help="Print the full AgentResult as JSON")
    ask.set_defaults(func=_cmd_ask)

    chat = sub.add_parser("chat", help="Interactive chat with human approval prompts")
    chat.add_argument("--agent", default="it_helpdesk", choices=sorted(AGENT_SPECS))
    chat.add_argument("--user")
    chat.set_defaults(func=_cmd_chat)

    ev = sub.add_parser("eval", help="Run the evaluation suite")
    ev.add_argument("--mode", choices=["local", "langfuse"], default="local")
    ev.add_argument("--dataset", help="Path to a JSONL dataset (default: built-in)")
    ev.add_argument("--dataset-name")
    ev.add_argument("--run-name", help="Langfuse experiment run name")
    ev.add_argument("--thresholds", default="configs/eval_thresholds.json")
    ev.add_argument("--report-dir", default="reports")
    ev.add_argument("--verbose", action="store_true", help="Show per-item results")
    ev.set_defaults(func=_cmd_eval)

    push = sub.add_parser("push-dataset", help="Publish the regression suite as a Langfuse dataset")
    push.add_argument("--dataset", help="Path to a JSONL dataset (default: built-in)")
    push.add_argument("--dataset-name")
    push.set_defaults(func=_cmd_push_dataset)
    return parser


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
