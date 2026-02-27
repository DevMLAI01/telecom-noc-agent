# =============================================================================
# src/state.py
# =============================================================================
# Purpose: Defines the central "nervous system" of the LangGraph agent —
# the NOCAgentState TypedDict.
#
# In LangGraph, the State is the single source of truth that flows through
# every node in the graph. Each node reads from and writes to this shared
# state object. Think of it as the "incident ticket" that gets enriched
# as it passes through each stage of the NOC triage workflow.
# =============================================================================

from typing import TypedDict, Optional


class NOCAgentState(TypedDict):
    """
    Represents the complete state of a single NOC incident resolution workflow.

    This TypedDict is passed between every node in the LangGraph state machine.
    Each node is responsible for populating specific fields as the investigation
    progresses from alarm triage through to final resolution ticket generation.

    Fields:
        alarm_id (str):
            The unique identifier of the incoming network alarm.
            Example: "ALARM-001"
            Set by: Initial invocation (main.py)

        error_message (str):
            A human-readable description of the network fault.
            Example: "DOCSIS T3 Timeout flood on Arris E6000 CMTS upstream"
            Set by: Initial invocation (main.py)

        live_telemetry (dict):
            Real-time network vitals fetched from the mock NMS.
            Contains device metrics like SNR, Rx power, error rates, etc.
            Set by: Node 1 — check_network()

        retrieved_sops (list[str]):
            A list of relevant SOP (Standard Operating Procedure) text chunks
            retrieved from the ChromaDB vector store via semantic search.
            Set by: Node 2 — get_manuals()

        proposed_resolution (str):
            The full, step-by-step resolution ticket drafted by the AI brain.
            This is the primary output artifact of the workflow.
            Set by: Node 3 — draft_fix()

        is_safe_to_execute (Optional[bool]):
            Safety audit result from the AI critic.
            True  → Ticket is SOP-compliant; route to END.
            False → Ticket has unsafe steps; loop back for revision.
            None  → Audit has not yet been performed (initial state).
            Set by: Node 4 — safety_check()

        safety_feedback (Optional[str]):
            Detailed feedback from the critic node explaining WHY a ticket
            failed the safety audit. Used to guide the revision loop.
            Set by: Node 4 — safety_check()

        iteration_count (int):
            Tracks how many times the draft-and-review loop has executed.
            Used to prevent infinite loops (hard cap at MAX_ITERATIONS).
            Set by: Routing logic in graph.py
    """

    alarm_id: str
    error_message: str
    live_telemetry: dict
    retrieved_sops: list
    proposed_resolution: str
    is_safe_to_execute: Optional[bool]
    safety_feedback: Optional[str]
    iteration_count: int
