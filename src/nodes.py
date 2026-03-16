# =============================================================================
# src/nodes.py
# =============================================================================
# Purpose: Defines the four core agent nodes of the LangGraph state machine.
# Each node is a pure Python function that:
#   1. Receives the current NOCAgentState as input.
#   2. Performs a specific, well-defined action (tool call, LLM inference, etc.)
#   3. Returns a PARTIAL state dictionary with ONLY the fields it updated.
#      LangGraph merges these partial updates back into the full state.
#
# Node execution order in the happy path:
#   check_network → get_manuals → draft_fix → safety_check → [END or loop]
# =============================================================================

import json
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.state import NOCAgentState
from src.tools import query_nms_for_alarm_telemetry
from src.retriever import retrieve_sops

# =============================================================================
# PYDANTIC MODEL: Safety Audit Output Schema
# =============================================================================
# Used with .with_structured_output() to force the critic LLM to return
# a structured JSON response that maps cleanly to our state fields.
# =============================================================================


class SafetyAuditResult(BaseModel):
    """
    Structured output schema for the NOC Safety Critic (Node 4).

    The LLM is constrained to return ONLY these fields, ensuring deterministic
    downstream routing logic without fragile regex-based parsing.
    """

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


# =============================================================================
# NODE 1: Telemetry Checker
# =============================================================================


def check_network(state: NOCAgentState) -> dict:
    """
    Node 1 — Telemetry Checker: Retrieves live network vitals for the alarm.

    This node invokes the `query_nms_for_alarm_telemetry` LangChain tool to
    fetch real-time device metrics from the mock NMS database. The tool
    result is stored in the `live_telemetry` state field for downstream nodes.

    In production, this node might also:
    - Correlate the alarm with recent change management tickets.
    - Check if a similar alarm fired in the last 24 hours (duplicate detection).
    - Query the CMDB for device ownership and maintenance contracts.

    Args:
        state: The current NOCAgentState containing alarm_id and error_message.

    Returns:
        Partial state dict with `live_telemetry` populated.
    """
    print("\n" + "=" * 65)
    print("🔍  NODE 1: TELEMETRY CHECKER — Querying Live Network Data")
    print("=" * 65)
    print(f"   Alarm ID    : {state['alarm_id']}")
    print(f"   Error Desc  : {state['error_message']}")

    # Invoke the LangChain tool directly (not via an LLM agent)
    # This is a deterministic tool call, not an LLM inference
    telemetry = query_nms_for_alarm_telemetry.invoke({"alarm_id": state["alarm_id"]})

    print(f"\n   ✅ Telemetry retrieved successfully. Keys: {list(telemetry.keys())}")

    # Return only the fields this node is responsible for updating
    return {"live_telemetry": telemetry}


# =============================================================================
# NODE 2: Document Retriever
# =============================================================================


def get_manuals(state: NOCAgentState) -> dict:
    """
    Node 2 — Document Retriever: Performs semantic search against the SOP vector DB.

    This node constructs a rich search query from the alarm context and uses
    ChromaDB to retrieve the most semantically relevant SOP chunks. The retrieved
    SOPs provide the factual grounding that the AI Brain (Node 3) uses to draft
    its resolution ticket.

    This node is also the re-entry point for the revision loop. When the safety
    check (Node 4) fails, the graph routes back here to fetch additional or
    alternative SOP context before attempting a new draft.

    Args:
        state: NOCAgentState with alarm_id, error_message, and live_telemetry.

    Returns:
        Partial state dict with `retrieved_sops` populated.
    """
    print("\n" + "=" * 65)
    print("📚  NODE 2: DOCUMENT RETRIEVER — Querying Vector Database")
    print("=" * 65)

    # Build a rich semantic query combining alarm metadata with telemetry details
    telemetry = state.get("live_telemetry", {})
    error_type = telemetry.get("error_type", state["error_message"])
    device = telemetry.get("device", "unknown device")
    location = telemetry.get("location", "unknown location")
    severity = telemetry.get("severity", "UNKNOWN")

    # Construct a natural language query optimized for semantic similarity search
    search_query = (
        f"{severity} alarm: {error_type} on {device} at {location}. "
        f"Original error: {state['error_message']}. "
        f"Need SOP for diagnosis, isolation, and remediation procedure."
    )

    print(f"   Search Query: {search_query[:100]}...")

    # If this is a retry (safety check failed), log additional context
    iteration = state.get("iteration_count", 0)
    if iteration > 0:
        safety_feedback = state.get("safety_feedback", "")
        print(f"\n   🔄 REVISION LOOP — Iteration #{iteration}")
        print(f"   Previous audit failure: {safety_feedback[:120]}...")
        # Enrich the query with failure feedback to retrieve more targeted SOPs
        search_query += f" Safety constraint violation: {safety_feedback[:200]}"

    # Execute semantic similarity search against ChromaDB
    sop_texts = retrieve_sops(query=search_query, k=3)

    print(f"\n   ✅ Retrieved {len(sop_texts)} relevant SOP document(s).")

    return {"retrieved_sops": sop_texts}


# =============================================================================
# NODE 3: The Brain — Resolution Drafter
# =============================================================================


def draft_fix(state: NOCAgentState) -> dict:
    """
    Node 3 — The Brain: Synthesizes telemetry + SOPs into a resolution ticket.

    This is the core LLM inference node. It uses ChatOpenAI (GPT-4o) with a
    strict system prompt to reason over the live telemetry data and retrieved
    SOPs and produce a structured, step-by-step incident resolution ticket.

    The system prompt is carefully engineered to:
    - Constrain the LLM to ONLY use steps present in the provided SOPs.
    - Enforce a specific output format for downstream processing.
    - Prevent hallucination of commands or procedures not in the SOPs.

    If this is a revision attempt (iteration_count > 0), the previous draft and
    critic feedback are included in the prompt for targeted improvement.

    Args:
        state: NOCAgentState with all fields populated through Node 2.

    Returns:
        Partial state dict with `proposed_resolution` populated.
    """
    print("\n" + "=" * 65)
    print("🧠  NODE 3: THE BRAIN — Drafting Resolution Ticket (GPT-4o)")
    print("=" * 65)

    iteration = state.get("iteration_count", 0)
    if iteration > 0:
        print(f"   🔄 REVISION MODE — Applying critic feedback (Iteration #{iteration})")

    # Initialize the LLM with low temperature for deterministic, factual output
    llm = ChatOpenAI(model="gpt-4o", temperature=0.1)

    # Format telemetry and SOPs into structured strings for the prompt
    telemetry_str = json.dumps(state.get("live_telemetry", {}), indent=2)
    sops_str = "\n\n---\n\n".join(state.get("retrieved_sops", []))

    # Build the strict system prompt for the L3 NOC engineer persona
    system_prompt = """You are an elite Level 3 Telecom Network Operations Center (NOC) Engineer
with 15+ years of experience in HFC cable networks, GPON fiber optics, and IP/MPLS core routing.

Your task is to analyze a live network alarm and produce a formal, step-by-step Incident Resolution Ticket.

CRITICAL RULES — YOU MUST FOLLOW THESE WITHOUT EXCEPTION:
1. BASE EVERY STEP EXCLUSIVELY on the provided Standard Operating Procedures (SOPs) below.
2. DO NOT invent, add, or suggest any step, command, or action not explicitly described in the SOPs.
3. DO NOT recommend rebooting, power-cycling, or hard-resetting any device unless the SOP explicitly permits it.
4. DO NOT make configuration changes that the SOPs mark as requiring change approval or specific authorization.
5. If the SOPs do not cover a required action, state that escalation is required and cite the SOP's escalation matrix.

OUTPUT FORMAT — USE THIS EXACT STRUCTURE:
```
INCIDENT RESOLUTION TICKET
==========================
Alarm ID       : [alarm_id]
Device         : [device name and location]
Severity       : [severity level]
Error Type     : [error type]
Affected Count : [number of affected modems/subscribers]

ROOT CAUSE ANALYSIS:
[2-3 sentences describing the probable root cause based on telemetry data and SOP guidance]

STEP-BY-STEP RESOLUTION PROCEDURE:
[Numbered steps, each referencing which SOP authorized it]

SAFETY CONSTRAINTS ACKNOWLEDGED:
[Bullet list of all safety constraints from the SOP that apply to this incident]

ESCALATION TRIGGERS:
[Conditions under which this ticket must be escalated, per the SOP]

ENGINEER NOTES:
[Any additional observations from the telemetry data]
```"""

    # Build the human message with all context
    human_content = f"""
LIVE NETWORK TELEMETRY DATA:
{telemetry_str}

RETRIEVED STANDARD OPERATING PROCEDURES:
{sops_str}

ORIGINAL ALARM:
Alarm ID: {state["alarm_id"]}
Error: {state["error_message"]}
"""

    # If in revision mode, append the previous draft and critic's feedback
    if iteration > 0 and state.get("proposed_resolution") and state.get("safety_feedback"):
        human_content += f"""

PREVIOUS DRAFT (FAILED SAFETY AUDIT — DO NOT REUSE):
{state["proposed_resolution"]}

CRITIC'S AUDIT FEEDBACK (MUST ADDRESS IN THIS REVISION):
{state["safety_feedback"]}

INSTRUCTION: Revise the ticket to strictly comply with the SOPs.
Remove any step flagged by the critic. Add missing safety constraints.
"""

    human_content += "\nDraft the Incident Resolution Ticket now:"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_content),
    ]

    print("   Invoking GPT-4o for ticket generation...")
    response = llm.invoke(messages)
    proposed_resolution = response.content

    print(f"\n   ✅ Resolution ticket drafted ({len(proposed_resolution)} characters).")
    print(f"\n   --- DRAFT PREVIEW (first 300 chars) ---")
    print(f"   {proposed_resolution[:300]}...")

    return {"proposed_resolution": proposed_resolution}


# =============================================================================
# NODE 4: The Critic — Safety Checker
# =============================================================================


def safety_check(state: NOCAgentState) -> dict:
    """
    Node 4 — The Critic: Audits the resolution ticket for SOP compliance and safety.

    This node uses a second, independent LLM instance with `.with_structured_output()`
    bound to the `SafetyAuditResult` Pydantic model. This forces the critic to return
    a boolean verdict and detailed textual feedback — enabling deterministic routing.

    The critic's role is adversarial: it actively looks for:
    - Steps that are NOT in the provided SOPs.
    - Violations of the safety constraints listed in the SOPs.
    - Missing required documentation or escalation triggers.
    - Commands or actions that could cause additional service impact.

    The audit result drives the conditional routing in graph.py:
    - is_safe=True  → Route to END (output final ticket)
    - is_safe=False → Route back to get_manuals (revision loop)

    Args:
        state: NOCAgentState with proposed_resolution and retrieved_sops populated.

    Returns:
        Partial state dict with `is_safe_to_execute` and `safety_feedback` populated.
    """
    print("\n" + "=" * 65)
    print("🛡️   NODE 4: THE CRITIC — Running Safety & SOP Compliance Audit")
    print("=" * 65)

    # Initialize a separate LLM instance for the critic
    # Using gpt-4o with structured output for deterministic JSON response
    critic_llm = ChatOpenAI(model="gpt-4o", temperature=0.0)
    structured_critic = critic_llm.with_structured_output(SafetyAuditResult)

    sops_str = "\n\n---\n\n".join(state.get("retrieved_sops", []))
    proposed_resolution = state.get("proposed_resolution", "")

    critic_system_prompt = """You are a strict NOC Safety Compliance Auditor.
Your ONLY job is to verify that a proposed network resolution ticket is 100% compliant
with the provided Standard Operating Procedures (SOPs).

AUDIT CRITERIA — Flag as UNSAFE (is_safe=False) if ANY of the following are true:
1. The ticket includes a command, action, or step NOT explicitly described in the SOPs.
2. The ticket violates any "SAFETY CONSTRAINTS" section of any SOP.
3. The ticket recommends a hard reset, reboot, or power-cycle not authorized by the SOP.
4. The ticket recommends a configuration change that the SOP marks as requiring approval.
5. The ticket is missing required safety constraint acknowledgements from the SOP.

Mark as SAFE (is_safe=True) ONLY if every single step is directly traceable to the SOPs
and all safety constraints are explicitly acknowledged.

Be precise. If unsafe, quote the exact non-compliant step and the violated SOP rule."""

    critic_human_content = f"""
STANDARD OPERATING PROCEDURES (Ground Truth):
{sops_str}

PROPOSED RESOLUTION TICKET TO AUDIT:
{proposed_resolution}

Perform your compliance audit and return your structured verdict:"""

    messages = [
        SystemMessage(content=critic_system_prompt),
        HumanMessage(content=critic_human_content),
    ]

    print("   Invoking GPT-4o critic with structured output...")
    audit_result: SafetyAuditResult = structured_critic.invoke(messages)  # type: ignore[assignment]

    print(f"\n   🔍 AUDIT RESULT: {'✅ SAFE' if audit_result.is_safe else '❌ UNSAFE'}")
    print(f"   Feedback: {audit_result.feedback[:200]}...")

    return {
        "is_safe_to_execute": audit_result.is_safe,
        "safety_feedback": audit_result.feedback,
    }
