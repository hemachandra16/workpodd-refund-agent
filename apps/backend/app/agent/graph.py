"""LangGraph refund agent — the compiled state machine.

Graph flow:
    START → guard → classify → fetch_customer → fetch_order
         → policy_engine → draft_response → respond → END

Key security property: the policy_engine node calls the deterministic engine
and writes the verdict into state. The draft_response node can only *style*
the message around that verdict — it cannot change it.

The graph is compiled once and reused for every customer interaction.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    node_classify,
    node_draft_response,
    node_fetch_customer,
    node_fetch_order,
    node_guard,
    node_policy_engine,
    node_respond,
)
from app.agent.state import AgentState, initial_state
from app.db import SessionLocal


def build_graph() -> StateGraph:
    """Build and compile the refund agent graph.

    Returns a compiled LangGraph runnable that accepts an AgentState dict
    and returns the final state with reasoning_log populated.
    """
    workflow = StateGraph(AgentState)

    # Add nodes.
    workflow.add_node("guard", _guard_with_db)
    workflow.add_node("classify", node_classify)
    workflow.add_node("fetch_customer", _fetch_customer_with_db)
    workflow.add_node("fetch_order", _fetch_order_with_db)
    workflow.add_node("policy_engine", _policy_engine_with_db)
    workflow.add_node("draft_response", node_draft_response)
    workflow.add_node("respond", node_respond)

    # Entry point.
    workflow.set_entry_point("guard")

    # Conditional routing: if injection blocked, skip straight to respond.
    workflow.add_conditional_edges(
        "guard",
        _route_guard,
        {
            "blocked": "respond",
            "safe": "classify",
        },
    )

    # Linear flow from classify to policy_engine.
    workflow.add_edge("classify", "fetch_customer")
    workflow.add_edge("fetch_customer", "fetch_order")
    workflow.add_edge("fetch_order", "policy_engine")

    # After policy_engine: always draft (even if no verdict → ask for info).
    workflow.add_edge("policy_engine", "draft_response")

    # Draft → respond → END.
    workflow.add_edge("draft_response", "respond")
    workflow.add_edge("respond", END)

    return workflow.compile()


# --- DB-injected wrappers (LangGraph nodes can't take extra args) ---

def _guard_with_db(state: AgentState) -> AgentState:
    db = SessionLocal()
    try:
        return node_guard(state, db)
    finally:
        db.close()


def _fetch_customer_with_db(state: AgentState) -> AgentState:
    db = SessionLocal()
    try:
        return node_fetch_customer(state, db)
    finally:
        db.close()


def _fetch_order_with_db(state: AgentState) -> AgentState:
    db = SessionLocal()
    try:
        return node_fetch_order(state, db)
    finally:
        db.close()


def _policy_engine_with_db(state: AgentState) -> AgentState:
    db = SessionLocal()
    try:
        return node_policy_engine(state, db)
    finally:
        db.close()


def _route_guard(state: AgentState) -> str:
    """Route after the guard node: blocked → respond, safe → classify."""
    if state.get("injection_blocked"):
        return "blocked"
    return "safe"


# Compiled singleton.
compiled_graph = build_graph()


def run_agent(user_input: str, metadata: dict[str, Any] | None = None) -> AgentState:
    """
    Run the full agent graph for a single user message.

    Args:
        user_input: The customer's message.
        metadata: Optional dict (session_id, etc.) for audit trail.

    Returns:
        The final AgentState with reasoning_log, verdict, and response_text.
    """
    initial_state_dict: dict = initial_state(user_input=user_input, metadata=metadata)
    final_state = compiled_graph.invoke(initial_state_dict)
    return final_state
