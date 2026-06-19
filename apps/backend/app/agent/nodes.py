"""LangGraph agent nodes — each function is one step in the refund flow.

Every node:
1. Takes the current state dict (LangGraph convention).
2. Performs one operation (guard, classify, fetch, evaluate, respond).
3. Appends a ``ReasoningStep`` to ``reasoning_log`` (for SSE streaming).
4. Returns the mutated state dict.

Security: the ``guard`` node runs first and blocks known injection patterns
*before* the user message ever reaches the LLM context.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from app.agent.state import AgentPhase, ReasoningStep, add_step
from app.agent.tools import check_refund_policy, get_customer, get_order
from app.llm.groq_client import call_with_tools
from app.llm.prompts import CLASSIFY_PROMPT, DRAFT_PROMPT, SYSTEM_PROMPT
from app.security.injection_guard import check_injection

# Patterns the classify node falls back to when the LLM is unavailable.
INTENT_PATTERNS: dict[str, re.Pattern] = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),
    "order_number": re.compile(r"\bWP-\d{4}\b", re.IGNORECASE),
}


def node_guard(state: dict, db) -> dict:
    """Guard node: check for prompt injection before LLM sees the message."""
    t0 = time.monotonic()
    user_input = state.get("user_input", "")

    blocked, patterns = check_injection(user_input)
    if blocked:
        step = ReasoningStep(
            node="guard",
            phase=AgentPhase.GUARD.value,
            summary=f"Injection blocked: {patterns}",
        )
        step.duration_ms = (time.monotonic() - t0) * 1000
        state["injection_blocked"] = True
        state["error"] = "Message blocked by security filter."
        state["phase"] = AgentPhase.GUARD.value
        state["response_text"] = "I'm sorry, I couldn't process that message. Please rephrase your request."
        add_step(state, step)
        return state

    step = ReasoningStep(
        node="guard",
        phase=AgentPhase.GUARD.value,
        summary="Input passed security check.",
    )
    step.duration_ms = (time.monotonic() - t0) * 1000
    state["phase"] = AgentPhase.GUARD.value
    add_step(state, step)
    return state


def node_classify(state: dict) -> dict:
    """Classify node: extract structured intent from the user's message.

    Uses the LLM with the CLASSIFY_PROMPT to pull out email, order_number,
    reason, and flags. Falls back to regex if the LLM is unavailable.
    """
    t0 = time.monotonic()
    user_input = state.get("user_input", "")

    # Try LLM classification first.
    llm_result = call_with_tools(
        [{"role": "system", "content": CLASSIFY_PROMPT},
         {"role": "user", "content": user_input}],
        temperature=0.0,
    )

    parsed: dict[str, Any] = {
        "email": None,
        "order_number": None,
        "reason": "unwanted",
        "wants_payment_method_change": False,
        "is_bundle_partial": False,
    }

    if llm_result.get("error") == "groq_unavailable":
        # Fallback: regex extraction.
        email_match = INTENT_PATTERNS["email"].search(user_input)
        order_match = INTENT_PATTERNS["order_number"].search(user_input)
        if email_match:
            parsed["email"] = email_match.group(0)
        if order_match:
            parsed["order_number"] = order_match.group(0).upper()
        summary = "Classified via regex (LLM unavailable)."
    else:
        content = llm_result.get("content", "")
        # Try to parse JSON from the LLM response.
        try:
            # Strip markdown fences if present.
            clean = content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0]
            parsed.update(json.loads(clean))
        except (json.JSONDecodeError, IndexError, TypeError):
            summary = f"Classification attempted (LLM response parseable: {bool(content)})"
        else:
            summary = f"Classified: email={parsed.get('email')}, order={parsed.get('order_number')}, reason={parsed.get('reason')}"

    # Write extracted fields into state.
    if parsed.get("email"):
        state["customer_email"] = parsed["email"]
    if parsed.get("order_number"):
        state["order_number"] = parsed["order_number"].upper()
    state["refund_reason"] = parsed.get("reason", "unwanted")
    meta = state.get("metadata", {})
    meta["wants_payment_method_change"] = parsed.get("wants_payment_method_change", False)
    meta["is_bundle_partial"] = parsed.get("is_bundle_partial", False)
    state["metadata"] = meta

    step = ReasoningStep(
        node="classify",
        phase=AgentPhase.CLASSIFY.value,
        summary=summary,
        tool_called="llm_classify",
        tool_args={"input_preview": user_input[:80]},
        tool_result_summary=f"extracted: email={parsed.get('email')}, order={parsed.get('order_number')}",
    )
    step.duration_ms = (time.monotonic() - t0) * 1000
    state["phase"] = AgentPhase.CLASSIFY.value
    add_step(state, step)
    return state


def node_fetch_customer(state: dict, db) -> dict:
    """Fetch customer from DB by email (extracted by classify)."""
    t0 = time.monotonic()
    email = state.get("customer_email", "")

    if not email:
        step = ReasoningStep(
            node="fetch_customer",
            phase=AgentPhase.FETCH_CUSTOMER.value,
            summary="Skipped: no email provided yet.",
        )
        step.duration_ms = (time.monotonic() - t0) * 1000
        state["phase"] = AgentPhase.FETCH_CUSTOMER.value
        add_step(state, step)
        return state

    result = get_customer(db, email)

    step = ReasoningStep(
        node="fetch_customer",
        phase=AgentPhase.FETCH_CUSTOMER.value,
        summary=f"{'Found' if result.get('found') else 'Not found'}: {email}",
        tool_called="get_customer",
        tool_args={"email": email},
        tool_result_summary=f"id={result.get('id')}, refunds_90d={result.get('refund_count_90d', 0)}" if result.get("found") else "not found",
    )
    step.duration_ms = (time.monotonic() - t0) * 1000

    if result.get("found"):
        state["customer_id"] = result["id"]
        state["customer"] = result
        meta = state.get("metadata", {})
        meta["refund_count_90d"] = result.get("refund_count_90d", 0)
        state["metadata"] = meta

    state["phase"] = AgentPhase.FETCH_CUSTOMER.value
    add_step(state, step)
    return state


def node_fetch_order(state: dict, db) -> dict:
    """Fetch order from DB by order number (extracted by classify)."""
    t0 = time.monotonic()
    order_number = state.get("order_number", "")

    if not order_number:
        step = ReasoningStep(
            node="fetch_order",
            phase=AgentPhase.FETCH_ORDER.value,
            summary="Skipped: no order number provided yet.",
        )
        step.duration_ms = (time.monotonic() - t0) * 1000
        state["phase"] = AgentPhase.FETCH_ORDER.value
        add_step(state, step)
        return state

    result = get_order(db, order_number)

    step = ReasoningStep(
        node="fetch_order",
        phase=AgentPhase.FETCH_ORDER.value,
        summary=f"{'Found' if result.get('found') else 'Not found'}: {order_number}",
        tool_called="get_order",
        tool_args={"order_number": order_number},
        tool_result_summary=f"total={result.get('total')}, status={result.get('status')}" if result.get("found") else "not found",
    )
    step.duration_ms = (time.monotonic() - t0) * 1000

    if result.get("found"):
        state["order"] = result

    state["phase"] = AgentPhase.FETCH_ORDER.value
    add_step(state, step)
    return state


def node_policy_engine(state: dict, db) -> dict:
    """
    Run the deterministic policy engine. This is the critical security node:
    its output is FINAL and cannot be changed by the LLM.
    """
    t0 = time.monotonic()
    order_number = state.get("order_number", "")
    reason = state.get("refund_reason", "unwanted")
    meta = state.get("metadata", {})
    wants_diff = meta.get("wants_payment_method_change", False)
    bundle_partial = meta.get("is_bundle_partial", False)

    if not order_number:
        step = ReasoningStep(
            node="policy_engine",
            phase=AgentPhase.POLICY_ENGINE.value,
            summary="Skipped: no order number to evaluate.",
        )
        step.duration_ms = (time.monotonic() - t0) * 1000
        state["phase"] = AgentPhase.POLICY_ENGINE.value
        add_step(state, step)
        return state

    result = check_refund_policy(
        db, order_number,
        reason=reason,
        wants_payment_method_change=wants_diff,
        is_bundle_partial=bundle_partial,
    )

    step = ReasoningStep(
        node="policy_engine",
        phase=AgentPhase.POLICY_ENGINE.value,
        summary=f"Verdict: {result.get('verdict', 'error')}",
        tool_called="check_refund_policy",
        tool_args={"order_number": order_number, "reason": reason},
        tool_result_summary=f"verdict={result.get('verdict')}, amount=${result.get('refund_dollars', 0)}, clauses={result.get('clauses_hit', [])}",
    )
    step.duration_ms = (time.monotonic() - t0) * 1000

    state["verdict"] = result.get("verdict")
    state["refund_cents"] = result.get("refund_cents", 0)
    state["clauses_hit"] = result.get("clauses_hit", [])
    meta["policy_rationale"] = result.get("rationale", "")
    meta["policy_breakdown"] = result.get("breakdown", {})
    state["metadata"] = meta
    state["phase"] = AgentPhase.POLICY_ENGINE.value
    add_step(state, step)
    return state


def node_draft_response(state: dict) -> dict:
    """
    Draft a customer-facing response using the LLM, based on the policy
    engine's verdict. The LLM styles the message but CANNOT change the verdict.
    """
    t0 = time.monotonic()
    verdict = state.get("verdict")
    clauses = state.get("clauses_hit", [])
    meta = state.get("metadata", {})
    rationale = meta.get("policy_rationale", "")
    refund_dollars = state.get("refund_cents", 0) / 100
    user_input = state.get("user_input", "")

    if not verdict:
        # No verdict yet — ask for more info.
        response = (
            "I'd like to help with your refund request. "
            "Could you please provide your email address and order number?"
        )
        step = ReasoningStep(
            node="draft_response",
            phase=AgentPhase.DRAFT_RESPONSE.value,
            summary="No verdict yet: asking for customer/order info.",
        )
        step.duration_ms = (time.monotonic() - t0) * 1000
        state["response_text"] = response
        state["phase"] = AgentPhase.DRAFT_RESPONSE.value
        add_step(state, step)
        return state

    # Build the context for the LLM to draft around.
    context = (
        f"Policy engine verdict: {verdict}\n"
        f"Clauses fired: {', '.join(clauses)}\n"
        f"Rationale: {rationale}\n"
        f"Refund amount: ${refund_dollars:.2f}\n"
        f"Customer message: {user_input[:200]}"
    )

    llm_result = call_with_tools(
        [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + DRAFT_PROMPT},
            {"role": "user", "content": context},
        ],
        temperature=0.2,
    )

    if llm_result.get("error") == "groq_unavailable" or not llm_result.get("content"):
        # Deterministic fallback: present the verdict directly.
        if verdict == "denied":
            response = f"Your refund request has been denied per policy clause(s): {', '.join(clauses)}. {rationale}"
        elif verdict == "manual_review":
            response = "Your refund request is being held for manual review. You will receive an update within 1-2 business days."
        elif verdict == "approved_store_credit":
            response = f"Your refund of ${refund_dollars:.2f} has been approved as store credit per clause {', '.join(clauses)}."
        else:
            response = f"Your refund of ${refund_dollars:.2f} has been approved per clause {', '.join(clauses)}."
    else:
        response = llm_result["content"]

    step = ReasoningStep(
        node="draft_response",
        phase=AgentPhase.DRAFT_RESPONSE.value,
        summary=f"Drafted response for verdict={verdict}",
        tool_called="llm_draft",
        tool_args={"verdict": verdict, "clauses": clauses},
        tool_result_summary=response[:120],
    )
    step.duration_ms = (time.monotonic() - t0) * 1000
    state["response_text"] = response
    state["phase"] = AgentPhase.DRAFT_RESPONSE.value
    add_step(state, step)
    return state


def node_respond(state: dict) -> dict:
    """Final node: set the response text and mark phase as END."""
    step = ReasoningStep(
        node="respond",
        phase=AgentPhase.RESPOND.value,
        summary=f"Returning response ({len(state.get('response_text', ''))} chars).",
    )
    state["phase"] = AgentPhase.END.value
    add_step(state, step)
    return state
