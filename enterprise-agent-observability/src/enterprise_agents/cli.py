"""Command-line interface: ``agentctl``."""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from enterprise_agents.agents.factory import AGENT_SPECS, build_agent
from enterprise_agents.config import get_settings
from enterprise_agents.logging_config import configure_logging
from enterprise_agents.observability import tracing
from enterprise_agents.security.approval import console_approval, deny_all


def _cmd_list(_: argparse.Namespace) -> int:
    for spec in AGENT_SPECS.values():
        print(f"{spec.name:<14} v{spec.version:<7} tools={list(spec.allowed_tools)}\n  {spec.description}")
    return 0


def _cmd_ask(args: argparse.Namespace) -> int:
    settings = get_settings()
    tracing.init_observability(settings)
    agent = build_agent(args.agent, settings, approval_handler=deny_all)
    result = agent.run(args.question, session_id=args.session or uuid.uuid4().hex)
    tracing.flush()
    print(json.dumps(result.to_dict(), indent=2) if args.json else result.answer)
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
            result = agent.run(text, session_id=session)
            print(f"\n{args.agent}> {result.answer}\n  [status={result.status} steps={result.steps} "
                  f"tools={result.tool_names} tokens={result.usage.get('total_tokens')}]")
    tracing.flush()
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from enterprise_agents.evaluation.runner import print_report, run_local, run_opik

    settings = get_settings()
    if args.mode == "opik":
        run_opik(settings, args.dataset_name, args.experiment, args.dataset)
        print("Opik experiment complete — open the Opik UI > Experiments to review.")
        return 0
    report, passed = run_local(settings, args.dataset, args.thresholds, args.report_dir)
    print_report(report)
    return 0 if passed else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentctl", description="Enterprise agents with Opik")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-agents", help="List available agents").set_defaults(func=_cmd_list)

    ask = sub.add_parser("ask", help="Single question to an agent")
    ask.add_argument("question")
    ask.add_argument("--agent", default="it_helpdesk", choices=sorted(AGENT_SPECS))
    ask.add_argument("--session")
    ask.add_argument("--json", action="store_true", help="Print full AgentResult as JSON")
    ask.set_defaults(func=_cmd_ask)

    chat = sub.add_parser("chat", help="Interactive chat with human approval prompts")
    chat.add_argument("--agent", default="it_helpdesk", choices=sorted(AGENT_SPECS))
    chat.set_defaults(func=_cmd_chat)

    ev = sub.add_parser("eval", help="Run the evaluation suite")
    ev.add_argument("--mode", choices=["local", "opik"], default="local")
    ev.add_argument("--dataset", help="Path to JSONL dataset (default: built-in)")
    ev.add_argument("--dataset-name", default="enterprise-agent-regression")
    ev.add_argument("--experiment", help="Opik experiment name")
    ev.add_argument("--thresholds", default="configs/eval_thresholds.json")
    ev.add_argument("--report-dir", default="reports")
    ev.set_defaults(func=_cmd_eval)
    return parser


def main(argv: list[str] | None = None) -> int:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
