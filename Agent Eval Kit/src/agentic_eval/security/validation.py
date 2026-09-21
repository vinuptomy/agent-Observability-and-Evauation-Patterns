"""Input hygiene and safe dynamic loading of the system-under-test."""
from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Sequence
from typing import Any

from agentic_eval.core.exceptions import SecurityError

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitize_text(text: str, max_chars: int = 20_000) -> str:
    """Strip control characters and enforce a length limit (protects judge context & cost)."""
    if len(text) > max_chars:
        raise SecurityError(f"input exceeds max_chars={max_chars} (got {len(text)})")
    return _CONTROL.sub("", text)


def load_target(spec: str, allowed_prefixes: Sequence[str]) -> Callable[..., Any]:
    """Load ``package.module:function`` only if the module is on the allow-list."""
    if ":" not in spec:
        raise SecurityError("target must be in 'module.path:callable' form")
    module_name, attr = spec.split(":", 1)
    if not any(module_name == p.rstrip(".") or module_name.startswith(p) for p in allowed_prefixes):
        raise SecurityError(
            f"module '{module_name}' is not allow-listed (security.allowed_target_modules={list(allowed_prefixes)})")
    if not re.fullmatch(r"[A-Za-z_][\w.]*", module_name) or not re.fullmatch(r"[A-Za-z_]\w*", attr):
        raise SecurityError("invalid target spec")
    fn = getattr(importlib.import_module(module_name), attr, None)
    if not callable(fn):
        raise SecurityError(f"{spec} is not callable")
    return fn
