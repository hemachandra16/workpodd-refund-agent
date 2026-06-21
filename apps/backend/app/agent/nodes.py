"""Dynamic LangGraph nodes for the refund agent.

The only fixed step is the pre-LLM guard. After that, the model controls the
loop by emitting tool calls. The tool node validates, executes, records the
result, and sends control back to the model until it returns a final response.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agent.state import AgentPhase, ReasoningStep, add_step
from app.agent.tools import (
    TOOL_FUNCTIONS,
    TOOL_SCHEMAS,
    ToolValidationError,
    normalize_reason,
    validate_tool_args,
)
from app.config import get_settings
from app.llm.groq_client import get_chat_model
from app.llm.prompts import SYSTEM_PROMPT
from app.security.injection_guard import check_injection


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
ORDER_TEXT_RE = re.compile(r"\bWP\s*-?\s*\d{4}\b", re.I)


DYNAMIC_AGENT_PROMPT = SYSTEM_PROMPT + """

You are running inside a LangGraph tool-calling loop.
- Decide the next tool call yourself based on the conversation and prior tool results.
- Use get_customer and get_order only when those facts are needed.
- Always call check_refund_policy before process_refund, deny_refund, or flag_for_escalation.
- If a tool returns a validation failure with suggested_args, retry the same tool once with
  the corrected arguments and make the retry visible.
- Never override check_refund_policy. Its verdict is final.
- Return a final customer-facing response only after the policy result and any matching
  action tool have completed, or when required information is missing.
"""


def node_guard(state: dict) -> dict:
    """Check raw user input for prompt injection before it reaches the model."""
    t0 = time.monotonic()
    user_input = state.get("user_input", "")

    blocked, pattern = check_injection(user_input)
    if blocked:
        state["injection_blocked"] = True
        state["error"] = "Message blocked by security filter."
        state["response_text"] = (
            "I'm sorry, I couldn't process that message. Please rephrase your request."
        )
        state["phase"] = AgentPhase.GUARD.value
        step = ReasoningStep(
            node="guard",
            phase=AgentPhase.GUARD.value,
            status="failed",
            summary="Injection blocked before model execution.",
            tool_result_summary=pattern,
        )
        step.duration_ms = (time.monotonic() - t0) * 1000
        add_step(state, step)
        return state

    state["phase"] = AgentPhase.GUARD.value
    step = ReasoningStep(
        node="guard",
        phase=AgentPhase.GUARD.value,
        summary="Input passed security check.",
    )
    step.duration_ms = (time.monotonic() - t0) * 1000
    add_step(state, step)
    return state


def node_agent(state: dict, model: Any | None = None, *, force_fallback: bool = False) -> dict:
    """Model node: produce either tool calls or a final response."""
    t0 = time.monotonic()
    settings = get_settings()
    state["phase"] = AgentPhase.AGENT.value
    state["agent_steps"] = int(state.get("agent_steps", 0)) + 1

    if state["agent_steps"] > settings.max_agent_steps:
        state["pending_tool_calls"] = []
        state["error"] = "Agent reached the maximum step count."
        state["response_text"] = (
            "I need to pause this refund request for review because the automated "
            "workflow reached its safety limit."
        )
        step = ReasoningStep(
            node="agent",
            phase=AgentPhase.AGENT.value,
            status="failed",
            summary="Max agent step count reached.",
        )
        step.duration_ms = (time.monotonic() - t0) * 1000
        add_step(state, step)
        return state

    _ensure_initial_messages(state)
    llm_error = ""
    response: AIMessage

    if force_fallback:
        llm_error = "forced_fallback"
        response = _fallback_agent_response(state)
    else:
        try:
            response = _invoke_bound_model(state, model)
        except Exception as exc:  # pragma: no cover - exact provider errors vary
            llm_error = exc.__class__.__name__
            response = _fallback_agent_response(state)

    state["messages"].append(response)
    tool_calls = _extract_tool_calls(response)
    state["pending_tool_calls"] = tool_calls

    if not tool_calls:
        state["response_text"] = str(response.content or "").strip()

    status = "fallback" if llm_error else "ok"
    summary = (
        f"Fallback planner used because Groq was unavailable/error: {llm_error}."
        if llm_error
        else (
            f"Model requested {len(tool_calls)} tool call(s)."
            if tool_calls
            else "Model returned final response."
        )
    )
    step = ReasoningStep(
        node="agent",
        phase=AgentPhase.AGENT.value,
        status=status,
        summary=summary,
        tool_called="llm.bind_tools",
        tool_args={"available_tools": [t["function"]["name"] for t in TOOL_SCHEMAS]},
        tool_result_summary=", ".join(call["name"] for call in tool_calls) or "final_response",
    )
    step.duration_ms = (time.monotonic() - t0) * 1000
    add_step(state, step)
    return state


def node_tools(state: dict, db) -> dict:
    """Execute the model-requested tools after validation and policy gating."""
    state["phase"] = AgentPhase.TOOL.value
    calls = list(state.get("pending_tool_calls") or [])
    state["pending_tool_calls"] = []

    for call in calls:
        _execute_one_tool_call(state, db, call)

    return state


def route_after_guard(state: dict) -> str:
    return "end" if state.get("injection_blocked") else "agent"


def route_after_agent(state: dict) -> str:
    return "tools" if state.get("pending_tool_calls") else "end"


def _ensure_initial_messages(state: dict) -> None:
    if state.get("messages"):
        return
    state["messages"] = [
        SystemMessage(content=DYNAMIC_AGENT_PROMPT),
        HumanMessage(content=state.get("user_input", "")),
    ]


def _invoke_bound_model(state: dict, model: Any | None) -> AIMessage:
    chat_model = model or get_chat_model(temperature=0.1)
    if chat_model is None:
        raise RuntimeError("groq_unavailable")
    bound_model = chat_model.bind_tools(TOOL_SCHEMAS) if hasattr(chat_model, "bind_tools") else chat_model
    response = bound_model.invoke(state["messages"])
    if isinstance(response, AIMessage):
        return response
    return AIMessage(content=str(getattr(response, "content", response)))


def _extract_tool_calls(response: AIMessage) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    for index, call in enumerate(getattr(response, "tool_calls", []) or []):
        calls.append({
            "id": call.get("id") or f"call_{index}",
            "name": call.get("name", ""),
            "args": call.get("args") or call.get("arguments") or {},
        })

    raw_calls = (getattr(response, "additional_kwargs", {}) or {}).get("tool_calls", [])
    for index, call in enumerate(raw_calls):
        fn = call.get("function", {})
        raw_args = fn.get("arguments", "{}")
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
        except json.JSONDecodeError:
            args = {}
        calls.append({
            "id": call.get("id") or f"raw_call_{index}",
            "name": fn.get("name", ""),
            "args": args,
        })

    return [call for call in calls if call["name"]]


def _execute_one_tool_call(state: dict, db, call: dict[str, Any]) -> None:
    t0 = time.monotonic()
    name = call.get("name", "")
    raw_args = call.get("args") or {}
    attempts = state.setdefault("tool_attempts", {})
    attempt = int(attempts.get(name, 0)) + 1
    attempts[name] = attempt

    status = "ok"
    prepared_args: dict[str, Any] = {}
    result: dict[str, Any]

    try:
        prepared_args = validate_tool_args(name, raw_args)
        _enforce_policy_gate(state, name, prepared_args)
        result = _call_tool(db, name, prepared_args)
        status = _tool_status(name, result, attempt)
        _update_state_from_tool(state, name, prepared_args, result)
    except ToolValidationError as exc:
        status = "failed"
        result = {
            "error": exc.code,
            "message": exc.message,
            "suggested_args": exc.suggested_args,
        }

    state.setdefault("tool_history", []).append({
        "name": name,
        "args": prepared_args or _redact_args_on_failure(raw_args, result),
        "result": result,
        "status": status,
        "attempt": attempt,
    })

    state.setdefault("messages", []).append(ToolMessage(
        content=json.dumps(result, default=str),
        tool_call_id=call.get("id") or f"{name}_{attempt}",
        name=name,
    ))

    step = ReasoningStep(
        node="tools",
        phase=AgentPhase.TOOL.value,
        status=status,
        summary=_tool_summary(name, status, result),
        tool_called=name,
        tool_args=prepared_args or _redact_args_on_failure(raw_args, result),
        tool_result_summary=_summarize_tool_result(result),
        attempt=attempt,
    )
    step.duration_ms = (time.monotonic() - t0) * 1000
    add_step(state, step)


def _call_tool(db, name: str, args: dict[str, Any]) -> dict[str, Any]:
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        raise ToolValidationError("unknown_tool", f"Unknown tool: {name}")
    return fn(db, **args)


def _enforce_policy_gate(state: dict, name: str, args: dict[str, Any]) -> None:
    if name not in {"process_refund", "deny_refund", "flag_for_escalation"}:
        return

    policy = (state.get("metadata") or {}).get("policy_result") or {}
    if not state.get("policy_checked") or not policy:
        raise ToolValidationError(
            "policy_required",
            f"{name} is blocked until check_refund_policy runs in this trace.",
        )

    if args.get("order_number") != policy.get("order_number"):
        raise ToolValidationError(
            "policy_order_mismatch",
            f"{name} order number must match the checked policy order.",
        )

    verdict = policy.get("verdict")
    if name == "process_refund" and verdict not in {
        "approved",
        "approved_partial",
        "approved_store_credit",
    }:
        raise ToolValidationError("policy_not_approved", "Policy verdict does not approve a refund.")
    if name == "deny_refund" and verdict != "denied":
        raise ToolValidationError("policy_not_denied", "Policy verdict does not deny this refund.")
    if name == "flag_for_escalation" and verdict != "manual_review":
        raise ToolValidationError(
            "policy_not_manual_review",
            "Policy verdict does not require manual review.",
        )


def _tool_status(name: str, result: dict[str, Any], attempt: int) -> str:
    if result.get("error") or result.get("found") is False:
        return "failed"
    if result.get("processed") is False or result.get("denied") is False or result.get("flagged") is False:
        return "failed"
    if attempt > 1:
        return "retry"
    return "ok"


def _update_state_from_tool(state: dict, name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
    meta = state.setdefault("metadata", {})

    if name == "get_customer" and result.get("found"):
        state["customer_id"] = result["id"]
        state["customer_email"] = result["email"]
        state["customer"] = result
        meta["refund_count_90d"] = result.get("refund_count_90d", 0)

    if name == "get_order" and result.get("found"):
        state["order_number"] = result["order_number"]
        state["order"] = result

    if name == "check_refund_policy" and result.get("verdict"):
        state["policy_checked"] = True
        state["verdict"] = result.get("verdict")
        state["refund_cents"] = result.get("refund_cents", 0)
        state["clauses_hit"] = result.get("clauses_hit", [])
        state["refund_reason"] = args.get("reason", "unwanted")
        meta["policy_result"] = result
        meta["policy_rationale"] = result.get("rationale", "")
        meta["policy_breakdown"] = result.get("breakdown", {})

    if name in {"process_refund", "deny_refund", "flag_for_escalation"} and not result.get("error"):
        meta["action_result"] = result
        meta["action_taken"] = name


def _tool_summary(name: str, status: str, result: dict[str, Any]) -> str:
    if status == "failed":
        return f"{name} failed: {result.get('message') or result.get('error') or 'not found'}"
    if status == "retry":
        return f"{name} retry succeeded."
    return f"{name} succeeded."


def _summarize_tool_result(result: dict[str, Any]) -> str:
    if result.get("error"):
        suggestion = result.get("suggested_args") or {}
        suffix = f"; suggested={suggestion}" if suggestion else ""
        return f"error={result.get('error')}{suffix}"
    if result.get("verdict"):
        return (
            f"verdict={result.get('verdict')}, "
            f"amount=${result.get('refund_dollars', 0)}, "
            f"clauses={result.get('clauses_hit', [])}"
        )
    if "found" in result:
        return "found" if result.get("found") else "not found"
    if result.get("action"):
        return result["action"]
    return json.dumps(result, default=str)[:160]


def _redact_args_on_failure(args: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if result.get("error") == "prompt_injection_tool_arg":
        return {"rejected": True}
    safe: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if isinstance(value, str):
            safe[key] = value[:80]
        else:
            safe[key] = value
    return safe


def _fallback_agent_response(state: dict) -> AIMessage:
    """A small local planner used only when Groq is unavailable or forced in tests."""
    meta = state.setdefault("metadata", {})
    user_input = state.get("user_input", "")
    last_tool = state.get("tool_history", [])[-1] if state.get("tool_history") else {}
    suggested = ((last_tool.get("result") or {}).get("suggested_args") or {})

    if not state.get("customer"):
        email = _extract_email(user_input)
        if not email:
            return AIMessage(content="Please provide the email address on the order.")
        return _tool_ai_message("get_customer", {"email": email})

    if not state.get("order"):
        if suggested.get("order_number"):
            return _tool_ai_message("get_order", {"order_number": suggested["order_number"]})
        order_text = _extract_order_text(user_input)
        if not order_text:
            return AIMessage(content="Please provide the order number, for example WP-1001.")
        if not meta.get("fallback_tried_raw_order") and not re.fullmatch(r"WP-\d{4}", order_text, re.I):
            meta["fallback_tried_raw_order"] = True
            return _tool_ai_message("get_order", {"order_number": order_text})
        return _tool_ai_message("get_order", {"order_number": order_text.upper()})

    if not state.get("policy_checked"):
        return _tool_ai_message("check_refund_policy", {
            "order_number": state["order"]["order_number"],
            "reason": _infer_reason(user_input),
        })

    if not meta.get("action_taken"):
        verdict = state.get("verdict")
        order_number = state.get("order_number") or state["order"]["order_number"]
        if verdict in {"approved", "approved_partial", "approved_store_credit"}:
            return _tool_ai_message("process_refund", {
                "order_number": order_number,
                "refund_cents": state.get("refund_cents", 0),
                "reason": normalize_reason(state.get("refund_reason")),
            })
        if verdict == "denied":
            return _tool_ai_message("deny_refund", {
                "order_number": order_number,
                "reason": normalize_reason(state.get("refund_reason")),
            })
        return _tool_ai_message("flag_for_escalation", {
            "order_number": order_number,
            "reason": normalize_reason(state.get("refund_reason")),
            "message": "Policy engine requires manual review.",
        })

    return AIMessage(content=_final_response_from_state(state))


def _tool_ai_message(name: str, args: dict[str, Any]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": args, "id": f"fallback_{name}"}],
    )


def _extract_email(text: str) -> str:
    match = EMAIL_RE.search(text)
    return match.group(0).rstrip(".,;:!?").lower() if match else ""


def _extract_order_text(text: str) -> str:
    match = ORDER_TEXT_RE.search(text)
    return match.group(0).upper() if match else ""


def _infer_reason(text: str) -> str:
    lower = text.lower()
    for reason in [
        "price_adjustment",
        "not_as_described",
        "damaged_shipping",
        "late_delivery",
        "wrong_item",
        "defective",
    ]:
        if reason.replace("_", " ") in lower or reason in lower:
            return reason
    return "unwanted"


def _final_response_from_state(state: dict) -> str:
    verdict = state.get("verdict")
    clauses = ", ".join(state.get("clauses_hit") or [])
    rationale = (state.get("metadata") or {}).get("policy_rationale", "")
    refund = state.get("refund_cents", 0) / 100

    if not verdict:
        return "I need the order number and account email before I can evaluate this refund."
    if verdict == "denied":
        return f"Your refund request is denied under policy clause(s) {clauses}. {rationale}"
    if verdict == "manual_review":
        return "Your refund request is being held for manual review. You will receive an update within 1-2 business days."
    if verdict == "approved_store_credit":
        return f"Your refund of ${refund:.2f} is approved as store credit under policy clause(s) {clauses}."
    return f"Your refund of ${refund:.2f} is approved under policy clause(s) {clauses}."
