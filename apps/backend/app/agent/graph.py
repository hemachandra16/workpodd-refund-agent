"""Dynamic LangGraph refund agent.

Graph flow:
    guard -> agent -> tools -> agent -> ... -> END

The model decides which tool to call next by using Groq/LangChain tool calling.
The graph only loops, validates tool calls, enforces policy-gating, and stops
when the model returns a final response without tool calls.
"""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    node_agent,
    node_guard,
    node_tools,
    route_after_agent,
    route_after_guard,
)
from app.agent.state import AgentState, initial_state
from app.db import SessionLocal


SessionFactory = Callable[[], Any]


def build_graph(
    *,
    model: Any | None = None,
    session_factory: SessionFactory | None = None,
    force_fallback: bool = False,
):
    """Build and compile the dynamic refund agent graph."""
    workflow = StateGraph(AgentState)
    factory = session_factory or SessionLocal

    def _agent_node(state: AgentState) -> AgentState:
        return node_agent(state, model=model, force_fallback=force_fallback)

    def _tools_node(state: AgentState) -> AgentState:
        db = factory()
        try:
            return node_tools(state, db)
        finally:
            db.close()

    workflow.add_node("guard", node_guard)
    workflow.add_node("agent", _agent_node)
    workflow.add_node("tools", _tools_node)

    workflow.set_entry_point("guard")
    workflow.add_conditional_edges(
        "guard",
        route_after_guard,
        {
            "agent": "agent",
            "end": END,
        },
    )
    workflow.add_conditional_edges(
        "agent",
        route_after_agent,
        {
            "tools": "tools",
            "end": END,
        },
    )
    workflow.add_edge("tools", "agent")

    return workflow.compile()


compiled_graph = build_graph()


def run_agent(
    user_input: str,
    metadata: dict[str, Any] | None = None,
    *,
    model: Any | None = None,
    session_factory: SessionFactory | None = None,
    force_fallback: bool = False,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> AgentState:
    """Run the dynamic refund agent for one customer message."""
    graph = (
        compiled_graph
        if model is None and session_factory is None and not force_fallback
        else build_graph(model=model, session_factory=session_factory, force_fallback=force_fallback)
    )
    initial_state_dict: dict = initial_state(
        user_input=user_input,
        metadata=metadata,
        event_sink=event_sink,
    )
    return graph.invoke(initial_state_dict)
