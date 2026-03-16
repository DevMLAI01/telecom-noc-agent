import json
import os
import boto3
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage

from src.state import NOCAgentState, SafetyAuditResult
from src.retriever import retrieve_relevant_sops

# ---------------------------------------------------------------------------
# Module-level resources — patchable in tests
# ---------------------------------------------------------------------------
boto3_resource = boto3.resource

llm = ChatOpenAI(model="gpt-4o", temperature=0.1)

TELEMETRY_TABLE = os.getenv("DYNAMODB_TELEMETRY_TABLE", "telecom-noc-telemetry")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


# =============================================================================
# NODE 1: Telemetry Checker
# =============================================================================


def check_network(state: NOCAgentState) -> dict:
    """Fetch live device telemetry from DynamoDB for the given alarm."""
    print("\n" + "=" * 65)
    print("NODE 1: TELEMETRY CHECKER — Querying Live Network Data")
    print("=" * 65)
    print(f"   Alarm ID: {state['alarm_id']}")

    alarm_id = state["alarm_id"]
    dynamodb = boto3_resource("dynamodb", region_name=AWS_REGION)
    table = dynamodb.Table(TELEMETRY_TABLE)
    response = table.get_item(Key={"alarm_id": alarm_id})
    item = response.get("Item", {})

    print(f"   Telemetry keys: {list(item.keys()) if item else 'none'}")
    return {"telemetry": item if item else {}}


# =============================================================================
# NODE 2: Document Retriever
# =============================================================================


def get_manuals(state: NOCAgentState) -> dict:
    """Retrieve the most relevant SOPs via semantic similarity search."""
    print("\n" + "=" * 65)
    print("NODE 2: DOCUMENT RETRIEVER — Querying SOP Vector Store")
    print("=" * 65)

    telemetry = state.get("telemetry", {})
    error_type = telemetry.get("error_type", state.get("error_message", ""))
    device = telemetry.get("device", "unknown device")
    location = telemetry.get("location", "unknown location")
    severity = telemetry.get("severity", "UNKNOWN")

    search_query = (
        f"{severity} alarm: {error_type} on {device} at {location}. "
        f"Original error: {state.get('error_message', '')}. "
        f"Need SOP for diagnosis, isolation, and remediation procedure."
    )

    iteration = state.get("iterations", 0)
    if iteration > 0:
        safety_feedback = state.get("safety_feedback", "")
        print(f"   REVISION LOOP — Iteration #{iteration}")
        search_query += f" Safety constraint violation: {safety_feedback[:200]}"

    print(f"   Search Query: {search_query[:100]}...")
    sop_results = retrieve_relevant_sops(search_query, top_k=3)
    print(f"   Retrieved {len(sop_results)} relevant SOP document(s).")

    return {"sops": sop_results}


# =============================================================================
# NODE 3: The Brain — Resolution Drafter
# =============================================================================


def draft_fix(state: NOCAgentState) -> dict:
    """Synthesize telemetry + SOPs into a structured resolution ticket (GPT-4o)."""
    print("\n" + "=" * 65)
    print("NODE 3: THE BRAIN — Drafting Resolution Ticket (GPT-4o)")
    print("=" * 65)

    iteration = state.get("iterations", 0)

    telemetry_str = json.dumps(state.get("telemetry", {}), indent=2)

    sops = state.get("sops", [])
    sops_str = "\n\n---\n\n".join(s.get("content", str(s)) if isinstance(s, dict) else s for s in sops)

    system_prompt = """You are an elite Level 3 Telecom Network Operations Center (NOC) Engineer
with 15+ years of experience in HFC cable networks, GPON fiber optics, and IP/MPLS core routing.

Your task is to analyze a live network alarm and produce a formal, step-by-step Incident Resolution Ticket.

CRITICAL RULES:
1. BASE EVERY STEP EXCLUSIVELY on the provided Standard Operating Procedures (SOPs) below.
2. DO NOT invent, add, or suggest any step not explicitly described in the SOPs.
3. DO NOT recommend rebooting or power-cycling unless the SOP explicitly permits it.
4. If the SOPs do not cover a required action, state that escalation is required."""

    human_content = f"""
LIVE NETWORK TELEMETRY DATA:
{telemetry_str}

RETRIEVED STANDARD OPERATING PROCEDURES:
{sops_str}

ORIGINAL ALARM:
Alarm ID: {state["alarm_id"]}
Error: {state.get("error_message", "")}
"""

    if iteration > 0 and state.get("resolution_ticket") and state.get("safety_feedback"):
        human_content += f"""

PREVIOUS DRAFT (FAILED SAFETY AUDIT — DO NOT REUSE):
{state["resolution_ticket"]}

CRITIC'S AUDIT FEEDBACK (MUST ADDRESS IN THIS REVISION):
{state["safety_feedback"]}

INSTRUCTION: Revise the ticket to strictly comply with the SOPs.
"""

    human_content += "\nDraft the Incident Resolution Ticket now:"

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_content),
    ]

    print("   Invoking GPT-4o for ticket generation...")
    response = llm.invoke(messages)
    resolution_ticket = response.content

    print(f"   Resolution ticket drafted ({len(resolution_ticket)} characters).")
    return {"resolution_ticket": resolution_ticket}


# =============================================================================
# NODE 4: The Critic — Safety Checker
# =============================================================================


def safety_check(state: NOCAgentState) -> dict:
    """Audit the resolution ticket for SOP compliance (GPT-4o structured output)."""
    print("\n" + "=" * 65)
    print("NODE 4: THE CRITIC — Running Safety & SOP Compliance Audit")
    print("=" * 65)

    structured_critic = llm.with_structured_output(SafetyAuditResult)

    sops = state.get("sops", [])
    sops_str = "\n\n---\n\n".join(s.get("content", str(s)) if isinstance(s, dict) else s for s in sops)
    proposed_resolution = state.get("resolution_ticket", "")

    critic_system_prompt = """You are a strict NOC Safety Compliance Auditor.
Your ONLY job is to verify that a proposed network resolution ticket is 100% compliant
with the provided Standard Operating Procedures (SOPs).

Mark as SAFE (is_safe=True) ONLY if every single step is directly traceable to the SOPs.
Mark as UNSAFE (is_safe=False) if ANY step deviates from the SOPs."""

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

    print(f"   AUDIT RESULT: {'SAFE' if audit_result.is_safe else 'UNSAFE'}")
    print(f"   Feedback: {audit_result.feedback[:200]}...")

    current_iterations = state.get("iterations", 0)
    result: dict = {
        "is_safe": audit_result.is_safe,
        "safety_feedback": audit_result.feedback,
    }
    if not audit_result.is_safe:
        result["iterations"] = current_iterations + 1

    return result
