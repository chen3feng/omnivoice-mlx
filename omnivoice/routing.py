"""Shared tool-routing safety net.

Both pipelines ask the model for a tool decision, and both need the same
fallback when an obvious live-data question comes back as NO_TOOL: retry the
decision once, then call a safe tool directly if the retry also declines.

Keeping this logic pure makes it testable without loading an MLX model.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from .prompts import build_retry_instruction
from .public_tools import fallback_tool_call, matched_tool_names
from .utils import parse_tool_call

# (first_reply, retry_instruction) -> second router reply
RetryFn = Callable[[str, str], str]


def forced_call_text(call: dict) -> str:
    """Render a directly-built call like the model's own tool-call text."""
    return "<tool_call>" + json.dumps(call, ensure_ascii=False) + "</tool_call>"


def resolve_decision(question: str | None, first: str, retry: RetryFn):
    """Turn the router's first reply into a tool call, retrying if needed.

    Returns ``(call, decision_used, retry_reply, forced)``:

    * ``call`` is a parsed tool call or None.
    * ``decision_used`` is the assistant text to put in the answer turn.
    * ``retry_reply`` is the second router reply, or None if no retry ran.
    * ``forced`` is True when neither model decision called a tool and a safe
      tool was called directly from the question text.
    """
    call = parse_tool_call(first)
    decision_used = first
    retry_reply = None
    forced = False

    # Pure chat has no keyword match: NO_TOOL is a valid answer, not a failure.
    if call or not matched_tool_names(question):
        return call, decision_used, retry_reply, forced

    retry_reply = retry(first or "NO_TOOL", build_retry_instruction(question))
    call = parse_tool_call(retry_reply)
    if call:
        return call, retry_reply, retry_reply, forced

    call = fallback_tool_call(question)
    if call:
        forced = True
        decision_used = forced_call_text(call)
    return call, decision_used, retry_reply, forced
