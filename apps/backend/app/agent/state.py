"""LangGraph agent state — TypedDict defining what flows between nodes.

Every node reads from and writes to this state (a plain dict). The
`reasoning_log` list is the structured audit trail streamed via SSE to the
admin dashboard. Each entry records *which node ran*, *what tool it called*,
*what came back*, and *how long it took* — making failures, retries, and
reasoning visible in real time (the key deliverable for the Loom demo).

Design: LangGraph requires a plain dict (not a custom class). Helper
functions operate on the dict rather than methods, so they survive
LangGraph's serialization.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Callable
from typing import Any, Optional, TypedDict


class AgentPhase(str, enum.Enum):
    """Current position in the graph."""
    START = "start"
    GUARD = "guard"
    AGENT = "agent"
    TOOL = "tool"
    RESPOND = "respond"
    END = "end"


@dataclass
class ReasoningStep:
    """One node's contribution to the audit log.

    Serializable to JSON for SSE transport. No PII.
    """
    node: str
    phase: str
    summary: str
    status: str = "ok"
    tool_called: str = ""
    tool_args: dict[str, Any] = field(default_factory=dict)
    tool_result_summary: str = ""
    attempt: int = 1
    duration_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "node": self.node,
            "phase": self.phase,
            "status": self.status,
            "summary": self.summary,
            "attempt": self.attempt,
            "duration_ms": round(self.duration_ms, 1),
            "timestamp": self.timestamp,
        }
        if self.tool_called:
            d["tool_called"] = self.tool_called
            d["tool_args"] = self.tool_args
            d["tool_result_summary"] = self.tool_result_summary
        return d


# LangGraph state schema — plain TypedDict, no methods (LangGraph serializes
# to a plain dict internally, so instance methods are lost).
class AgentState(TypedDict):
    """State that flows between nodes in the refund agent graph.

    Keys:
        messages:            conversation history (list of BaseMessage)
        user_input:          raw customer message (kept separate from prompt)
        order_number:        extracted or queried order ID
        customer_email:      extracted or queried customer email
        customer_id:         resolved DB primary key
        customer:            DB Customer dict (once fetched)
        order:               DB Order dict (once fetched)
        refund_reason:       parsed RefundReason enum string
        verdict:             RefundVerdict string from the policy engine (or "")
        refund_cents:        cents the engine approved (0 if denied)
        clauses_hit:         list of clause IDs that fired
        response_text:       final LLM-drafted response to the customer
        reasoning_log:       list[dict] - serialized ReasoningSteps
        pending_tool_calls:  tool calls emitted by the latest model turn
        tool_history:        tool results from this run, used for policy gating
        tool_attempts:       per-tool+args attempt counters for retry visibility
        agent_steps:         number of model turns taken so far
        policy_checked:      True once check_refund_policy succeeds in this run
        event_sink:          optional callback invoked as each reasoning step is appended
        phase:               current AgentPhase string
        injection_blocked:   True if the guard node blocked the message
        error:               any unhandled error message
        metadata:            arbitrary extra context (e.g. session_id)
    """
    messages: list
    user_input: str
    order_number: str
    customer_email: str
    customer_id: int
    customer: Optional[dict]
    order: Optional[dict]
    refund_reason: str
    verdict: Optional[str]
    refund_cents: int
    clauses_hit: list
    response_text: str
    reasoning_log: list
    pending_tool_calls: list
    tool_history: list
    tool_attempts: dict
    agent_steps: int
    policy_checked: bool
    event_sink: Optional[Callable[[dict[str, Any]], None]]
    phase: str
    injection_blocked: bool
    error: str
    metadata: dict


def add_step(state: dict, step: ReasoningStep) -> None:
    """Append a reasoning step to the state's audit log (mutates in-place)."""
    if "reasoning_log" not in state:
        state["reasoning_log"] = []
    step_dict = step.to_dict()
    state["reasoning_log"].append(step_dict)
    sink = state.get("event_sink")
    if callable(sink):
        sink(step_dict)


def initial_state(
    user_input: str,
    metadata: dict[str, Any] | None = None,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> dict:
    """Create a fresh AgentState dict with defaults."""
    return {
        "messages": [],
        "user_input": user_input,
        "order_number": "",
        "customer_email": "",
        "customer_id": 0,
        "customer": None,
        "order": None,
        "refund_reason": "",
        "verdict": None,
        "refund_cents": 0,
        "clauses_hit": [],
        "response_text": "",
        "reasoning_log": [],
        "pending_tool_calls": [],
        "tool_history": [],
        "tool_attempts": {},
        "agent_steps": 0,
        "policy_checked": False,
        "event_sink": event_sink,
        "phase": AgentPhase.START.value,
        "injection_blocked": False,
        "error": "",
        "metadata": metadata or {},
    }
