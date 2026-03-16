from typing import TypedDict, Optional
from pydantic import BaseModel, Field


class SafetyAuditResult(BaseModel):
    """Structured output schema for the NOC Safety Critic (Node 4)."""

    is_safe: bool = Field(
        description=(
            "True if EVERY step in the proposed resolution is explicitly documented "
            "in the provided SOPs and follows all stated safety constraints. "
            "False if ANY step deviates from, contradicts, or is absent from the SOPs."
        )
    )
    feedback: str = Field(
        description=(
            "Detailed explanation of the audit finding. If is_safe=True, briefly confirm "
            "SOP compliance. If is_safe=False, quote the specific non-compliant step(s) "
            "and explain which SOP rule is violated. Be precise and actionable."
        )
    )


class NOCAgentState(TypedDict):
    """
    Represents the complete state of a single NOC incident resolution workflow.

    Fields:
        alarm_id:          Unique identifier of the incoming network alarm.
        error_message:     Human-readable description of the network fault.
        telemetry:         Real-time device metrics fetched from DynamoDB (Node 1).
        sops:              Top-k SOP dicts retrieved via semantic search (Node 2).
        resolution_ticket: Full resolution ticket drafted by the AI brain (Node 3).
        is_safe:           Safety audit result from the AI critic (Node 4).
        safety_feedback:   Critic feedback explaining why a ticket failed (Node 4).
        iterations:        Loop counter — tracks self-correction attempts.
    """

    alarm_id: str
    error_message: str
    telemetry: dict
    sops: list
    resolution_ticket: str
    is_safe: Optional[bool]
    safety_feedback: Optional[str]
    iterations: int
