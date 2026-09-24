"""Human-in-the-loop approval for high-risk tool calls (e.g. write operations)."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

logger = logging.getLogger(__name__)

ApprovalHandler = Callable[[str, dict], bool]


def deny_all(tool_name: str, arguments: dict) -> bool:
    """Secure default: high-risk actions require an explicit approval workflow."""
    logger.warning("High-risk tool call denied (no approver configured)", extra={"tool": tool_name})
    return False


def approve_all(tool_name: str, arguments: dict) -> bool:
    """ONLY for sandboxes, tests and offline evaluation with in-memory tools."""
    return True


def console_approval(tool_name: str, arguments: dict) -> bool:
    print(f"\n[APPROVAL REQUIRED] Agent wants to call '{tool_name}' with:")
    print(json.dumps(arguments, indent=2))
    return input("Approve? [y/N]: ").strip().lower() in {"y", "yes"}
