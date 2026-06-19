"""Groq LLM client — thin wrapper around ChatGroq.

Manages one shared client instance (lru_cached by settings) and exposes
a call that returns structured tool-call results. When GROQ_API_KEY is
absent/placeholder the client degrades gracefully so the rest of the stack
still runs (agent falls back to deterministic-only mode).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from langchain_groq import ChatGroq

from app.config import get_settings
from app.agent.tools import TOOL_SCHEMAS

log = logging.getLogger(__name__)


def get_chat_model(temperature: float = 0.1) -> Optional[ChatGroq]:
    """
    Create a ChatGroq model bound to the configured API key and model.

    Returns ``None`` if the key is not set (deterministic-only mode).
    Temperature is low (0.1) because the agent should be factual and consistent,
    not creative.
    """
    settings = get_settings()
    if not settings.groq_available:
        log.warning("groq_unavailable: agent will operate in deterministic-only mode")
        return None
    return ChatGroq(
        model=settings.groq_llm_model,
        temperature=temperature,
        max_tokens=1024,
        api_key=settings.groq_api_key,
    )


def call_with_tools(
    messages: list[dict[str, str]],
    tools: Optional[list[dict[str, Any]]] = None,
    temperature: float = 0.1,
) -> dict[str, Any]:
    """
    Call the Groq model with optional tool schemas.

    Returns a dict with either:
      - ``content``: the model's text response
      - ``tool_calls``: a list of parsed tool call dicts

    Tool calls are structured as:
      ``{"name": str, "arguments": dict}``
    """
    model = get_chat_model(temperature=temperature)
    if model is None:
        return {"content": "", "tool_calls": [], "error": "groq_unavailable"}

    from langchain_core.messages import HumanMessage, SystemMessage

    lc_messages = []
    for m in messages:
        if m["role"] == "system":
            lc_messages.append(SystemMessage(content=m["content"]))
        else:
            lc_messages.append(HumanMessage(content=m["content"]))

    if tools:
        model_with_tools = model.bind_tools(tools)
    else:
        model_with_tools = model

    response = model_with_tools.invoke(lc_messages)

    result: dict[str, Any] = {"content": "", "tool_calls": [], "error": ""}
    if response.content:
        result["content"] = response.content
    if hasattr(response, "tool_call_chunks") and response.tool_call_chunks:
        # Parse raw tool calls from the response.
        for tc in response.tool_call_chunks:
            if tc.get("name"):
                args = {}
                if tc.get("args"):
                    try:
                        args = json.loads(tc["args"]) if isinstance(tc["args"], str) else tc["args"]
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                result["tool_calls"].append({"name": tc["name"], "arguments": args})
    # Also check response.additional_kwargs for OpenAI-style tool_calls.
    raw_calls = (response.additional_kwargs or {}).get("tool_calls", [])
    for tc in raw_calls:
        fn = tc.get("function", {})
        name = fn.get("name", "")
        args_str = fn.get("arguments", "{}")
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else args_str
        except json.JSONDecodeError:
            args = {}
        if name:
            result["tool_calls"].append({"name": name, "arguments": args})

    return result
