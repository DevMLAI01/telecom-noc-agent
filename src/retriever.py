# =============================================================================
# src/retriever.py
# =============================================================================
# Purpose: Manages the ChromaDB vector store lifecycle — seeding it with
# dummy Telecom SOPs (Standard Operating Procedures) and exposing a function
# for semantic search retrieval.
#
# Architecture:
#   - Uses OpenAIEmbeddings to convert SOP text into high-dimensional vectors.
#   - Stores vectors in a local persistent ChromaDB collection on disk.
#   - On startup, checks if the collection already exists to avoid re-embedding
#     (saves OpenAI API costs on repeated runs).
#   - Exposes retrieve_sops() for Node 2 of the LangGraph workflow.
#
# In production, SOPs would be loaded from:
#   - Confluence pages via Atlassian REST API
#   - PDF manuals via PyMuPDF/PDFMiner loaders
#   - SharePoint document libraries via Microsoft Graph API
# =============================================================================

import os
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document

# ---------------------------------------------------------------------------
# ChromaDB persistence path — stored at project root to keep it out of src/
# ---------------------------------------------------------------------------
CHROMA_PERSIST_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "chroma_db"
)
COLLECTION_NAME = "telecom_sops"

# =============================================================================
# DUMMY TELECOM SOPs
# =============================================================================
# These simulate the content of real vendor manuals and internal NOC runbooks.
# Each document represents a distinct procedure chunk as it would appear after
# ingesting and chunking a real PDF manual.
# =============================================================================

DUMMY_SOPS: list[dict] = [
    # -------------------------------------------------------------------------
    # SOP-001: Arris CMTS DOCSIS T3 Timeout Remediation
    # Source: Arris E6000 CMTS Troubleshooting Guide v4.2, Chapter 7
    # -------------------------------------------------------------------------
    {
        "id": "SOP-001",
        "content": """
ARRIS E6000 CMTS — DOCSIS T3 TIMEOUT REMEDIATION PROCEDURE
Source: Arris E6000 Troubleshooting Guide v4.2 | Section 7.3

CONDITION: T3 Timeout count exceeds 500 per hour on any upstream channel.

APPROVED REMEDIATION STEPS (execute in order):
1. VERIFY: Log into the CMTS CLI via SSH. Run `show interface cable X/Y/Z upstream`
   to confirm T3/T4 timeout counts match the NMS alarm data.
2. MEASURE SNR: Run `show cable modem X/Y/Z phy` to capture current upstream SNR.
   A reading below 25 dB on ATDMA channels indicates noise ingress.
3. SPECTRUM SWEEP: Use the integrated CMTS spectrum analyzer to sweep the affected
   upstream frequency range (5–85 MHz). Document any visible impulse noise,
   ingress spikes, or narrowband interference patterns.
4. ISOLATE: Execute a node isolation procedure. Terminate cable segments one-by-one
   at the fiber node amplifier taps to identify the impaired leg. The leg whose
   removal causes T3 counts to drop >80% is the suspected impaired segment.
5. DISPATCH: If ingress source is confirmed to a specific tap or amplifier,
   create a field dispatch work order for the Outside Plant (OSP) team to:
   a. Inspect and replace any corroded or improperly sealed tap faceplate.
   b. Verify all unused ports on amplifiers and taps are properly terminated (75-ohm).
   c. Measure and document sweep results post-repair using an Acterna/JDSU meter.
6. MODULATION FALLBACK: While field repair is in progress, temporarily lower the
   upstream modulation profile from 256-QAM to 64-QAM using
   `cable upstream X modulation-profile 21` to maintain service for subscribers.
7. RESTORE: After OSP confirms physical repair, revert modulation profile and
   monitor T3 counts for 30 minutes to confirm resolution. Close ticket.

SAFETY CONSTRAINTS:
- DO NOT reboot the CMTS chassis during peak hours (7 AM – 11 PM local time).
- DO NOT modify downstream channel plans without NOC Manager approval.
- DO NOT power-cycle fiber node amplifiers without OSP team coordination.
- All CLI changes must be peer-reviewed by a second L3 engineer.
        """,
        "metadata": {"source": "Arris E6000 Guide v4.2", "category": "CMTS", "alarm_type": "T3_Timeout"}
    },

    # -------------------------------------------------------------------------
    # SOP-002: Nokia GPON ONU Low Rx Power Remediation
    # Source: Nokia 7360 ISAM FX OLT Field Operations Manual, Rev 3.1
    # -------------------------------------------------------------------------
    {
        "id": "SOP-002",
        "content": """
NOKIA 7360 ISAM FX OLT — GPON ONU RX POWER LOW REMEDIATION PROCEDURE
Source: Nokia 7360 ISAM FX Field Operations Manual Rev 3.1 | Chapter 12

CONDITION: ONU Rx power reading drops below the -28.0 dBm alarm threshold.

APPROVED REMEDIATION STEPS (execute in order):
1. CONFIRM: Access the Nokia 7360 CLI via SSH or ISAM Craft Terminal. Run:
   `show equipment ont detail port <port_id> ont <ont_id>`
   Confirm optical-rx-signal-level matches the NMS alarm value.
2. CALCULATE LOSS: Determine total path loss = OLT Tx power - ONU Rx power.
   Acceptable optical path loss budget for GPON class B+ is ≤28 dB.
   Values exceeding 28 dB indicate a physical layer fault in the ODN.
3. OTDR TEST: Request an OSP technician to perform an OTDR (Optical Time Domain
   Reflectometer) test on the affected feeder fiber from the OLT port to the ONU.
   The OTDR trace will identify:
   a. Connector reflections or high-loss events (dirty/cracked connectors).
   b. Macro-bend events (fiber bent too tightly around a corner or staple).
   c. Physical fiber breaks or splices with excessive loss (>0.3 dB for fusion).
4. CLEAN CONNECTORS: If the OTDR trace shows a high-reflection event at a
   connector point, clean the suspect connector with an appropriate fiber optic
   cleaner tool (e.g., Fujikura CT-30). Inspect with a fiber inspection scope
   (200x magnification minimum). Reconnect and re-measure.
5. REPLACE FIBER: If the OTDR identifies a fiber break or irreparable macro-bend,
   dispatch an OSP crew to replace the affected fiber segment or re-route the cable.
6. REPROVISION ONU: If physical layer checks pass but Rx power remains low,
   attempt to re-range the ONU using:
   `configure equipment ont port <port_id> ont <ont_id> admin-state disabled`
   Wait 60 seconds, then:
   `configure equipment ont port <port_id> ont <ont_id> admin-state enabled`
7. ESCALATE: If Rx power does not recover above -27.0 dBm after steps 1-6,
   escalate to Nokia TAC with OTDR trace, ONT serial number, and OLT port details.

SAFETY CONSTRAINTS:
- DO NOT disable the OLT port — this will impact ALL ONUs on the shared PON port.
- DO NOT attempt to clean fiber connectors at the OLT frame without an outage window.
- Laser safety: Ensure fiber is dark (disabled) before inspecting connectors optically.
- All fiber work requires OSP certified personnel. NOC engineers must NOT dispatch
  without confirming crew availability via the OSP dispatch system.
        """,
        "metadata": {"source": "Nokia 7360 Manual Rev 3.1", "category": "Fiber", "alarm_type": "ONU_Rx_Low"}
    },

    # -------------------------------------------------------------------------
    # SOP-003: BGP Session Flap — Core Router Remediation
    # Source: Internal NOC Runbook v2.8 — IP/MPLS Core Operations
    # -------------------------------------------------------------------------
    {
        "id": "SOP-003",
        "content": """
BGP SESSION FLAP REMEDIATION — CORE ROUTER RUNBOOK
Source: Internal NOC Runbook v2.8 | IP/MPLS Core Operations | Section 4.1

CONDITION: BGP session with external or internal peer enters IDLE/ACTIVE state
and flap count exceeds 5 events per hour.

APPROVED REMEDIATION STEPS (execute in order):
1. IDENTIFY: Log into the affected core router. Run:
   - Cisco IOS-XR: `show bgp neighbors <peer_ip> | include State`
   - Juniper JunOS:  `show bgp neighbor <peer_ip>`
   Record the last-error reason, hold-timer expired vs notification received.
2. CHECK PHYSICAL LINK: Inspect the physical interface connecting to the BGP peer:
   - Cisco: `show interfaces HundredGigE0/0/0/1`
   - Juniper: `show interfaces xe-0/0/2`
   Look for: CRC errors, input/output errors, flap events in carrier-transitions.
   High CRC errors confirm a physical layer (L1/L2) problem. Escalate to transport.
3. VERIFY MTU: MTU mismatch is a common BGP session killer. Verify:
   - Local interface MTU: `show interfaces HundredGigE0/0/0/1 | include MTU`
   - Confirm with peer NOC/ISP that their interface MTU matches (must be identical).
   - If mismatch: negotiate MTU correction or implement TCP MSS clamping.
4. CHECK ROUTE POLICY: Ensure no route policy or prefix-list change was recently
   deployed that might be rejecting the peer's routes and causing NOTIFICATION.
   Review change management tickets for the past 2 hours.
5. SOFT RESET: If configuration appears correct and physical link is clean,
   attempt a BGP soft reset (non-disruptive):
   - Cisco: `clear bgp ipv4 unicast <peer_ip> soft`
   - Juniper: `clear bgp neighbor <peer_ip>`
   Monitor for 10 minutes post-reset. Log the session state transition.
6. HOLD TIMER ADJUSTMENT: If flaps persist due to transient latency, consider
   adjusting BGP timers in coordination with the peer:
   `neighbor <peer_ip> timers 10 30` (keepalive 10s, hold 30s)
7. ESCALATE: If session does not stabilize after steps 1-6, open a P1 bridge with
   the IP/MPLS core team and peer carrier NOC. Do not hard-reset BGP sessions
   without explicit authorization from the Network Engineering team.

SAFETY CONSTRAINTS:
- DO NOT use `clear bgp * hard` — this drops ALL BGP sessions and causes mass outage.
- DO NOT modify BGP AS path, communities, or local-preference without change approval.
- DO NOT make physical interface changes during business hours without outage window.
- CPU utilization above 70% on the routing engine requires immediate escalation.
        """,
        "metadata": {"source": "Internal NOC Runbook v2.8", "category": "IP/MPLS", "alarm_type": "BGP_Flap"}
    },

    # -------------------------------------------------------------------------
    # SOP-004: Interface Congestion — QoS and Traffic Management
    # Source: Internal NOC Runbook v2.8 — Edge Traffic Engineering | Section 6.3
    # -------------------------------------------------------------------------
    {
        "id": "SOP-004",
        "content": """
INTERFACE QUEUE CONGESTION — EDGE ROUTER QoS RUNBOOK
Source: Internal NOC Runbook v2.8 | Edge Traffic Engineering | Section 6.3

CONDITION: Interface utilization exceeds 90% for >5 consecutive minutes,
or packet drop rate on a CoS queue exceeds 1% for priority traffic.

APPROVED REMEDIATION STEPS (execute in order):
1. CONFIRM: Log into the affected edge router and verify interface stats:
   - Juniper: `show interfaces xe-0/0/2 extensive | match "bps|pps|drops"`
   - Capture queue depth and drop counters per CoS class.
2. IDENTIFY TOP TALKERS: Use NetFlow/IPFIX or router sampling to identify source IPs
   or traffic flows consuming the most bandwidth.
   - Juniper: `show pfe statistics traffic | match drop`
   - Cross-reference with the NMS top-talker report.
3. RATE LIMIT (Emergency): If a single source IP is responsible for >30% of traffic
   (potential DDoS or runaway application), apply a temporary rate limiter:
   - Juniper: Apply a firewall filter with a policer targeting the source prefix.
   - Document the action in the incident ticket immediately.
4. QoS REBALANCING: If congestion is legitimate traffic growth (not abuse),
   review and rebalance CoS queue weights. Increase bandwidth allocation for
   priority (Q7) traffic if Q7 drops exceed 1%. Requires change approval.
5. CAPACITY ESCALATION: If sustained utilization >85% is confirmed as organic growth:
   a. Open a capacity planning ticket with the Network Engineering team.
   b. Request interface upgrade or LAG (Link Aggregation) provisioning.
   c. Estimated provisioning time: 2-4 weeks for fiber-based upgrades.
6. TRAFFIC ENGINEERING: As an interim measure, work with the IP team to re-route
   specific high-bandwidth flows to an alternate, less-congested path via
   MPLS TE (Traffic Engineering) tunnels or BGP local-preference adjustments.

SAFETY CONSTRAINTS:
- DO NOT apply blanket rate limits without identifying the traffic type (may impact SLAs).
- DO NOT modify QoS policies in production without peer review and change window.
- Rate limiting emergency actions must be reviewed and either formalized or removed
  within 4 hours of application.
- DO NOT shut down the interface — this causes immediate service outage.
        """,
        "metadata": {"source": "Internal NOC Runbook v2.8", "category": "QoS", "alarm_type": "Congestion"}
    },

    # -------------------------------------------------------------------------
    # SOP-005: General NOC Escalation and Communication Protocol
    # Source: NOC Operations Policy Manual v5.0 | Section 2.1
    # -------------------------------------------------------------------------
    {
        "id": "SOP-005",
        "content": """
NOC ESCALATION AND COMMUNICATION PROTOCOL
Source: NOC Operations Policy Manual v5.0 | Section 2.1

SEVERITY DEFINITIONS:
- CRITICAL (P1): Service-affecting event impacting >100 subscribers or a core
  network element. Target resolution time: 4 hours. Requires immediate bridge call.
- MAJOR (P2): Service degradation impacting 10-100 subscribers or a network element
  with redundancy. Target resolution time: 8 hours.
- MINOR (P3/P4): Single subscriber or non-service-affecting fault. Target: 24-48 hours.

ESCALATION MATRIX:
- 0-30 min:   L2 NOC Engineer owns the ticket. Triage and document findings.
- 30-60 min:  If unresolved, escalate to L3 Engineer. Loop in vendor TAC if needed.
- 60-120 min: If P1 unresolved, invoke Major Incident Management (MIM) process.
              Page the on-call Network Engineering Manager.
- >120 min:   Executive notification required for P1 events. Vendor field dispatch if applicable.

DOCUMENTATION REQUIREMENTS (ALL tickets must include):
1. Alarm ID and timestamp of first occurrence.
2. Impacted device, location, and subscriber count.
3. Root cause analysis (RCA) — even preliminary.
4. All CLI commands executed with timestamps.
5. All configuration changes made (with before/after snapshots).
6. Names of all engineers involved and actions taken.
7. Resolution steps and confirmation of service restoration.

COMMUNICATION RULES:
- All customer-impacting events (>10 subscribers) require proactive status page update.
- Bridge calls must be recorded and added to the incident ticket.
- Never estimate an ETA without consulting the responsible team first.
        """,
        "metadata": {"source": "NOC Operations Policy v5.0", "category": "Process", "alarm_type": "General"}
    },
]


def get_or_create_vectorstore() -> Chroma:
    """
    Initializes the ChromaDB vector store.

    On first run: Embeds all DUMMY_SOPS using OpenAI embeddings and persists
    them to the local chroma_db directory.

    On subsequent runs: Loads the existing persisted collection from disk,
    skipping the embedding step to avoid redundant API calls.

    Returns:
        A Chroma vector store object ready for similarity search queries.
    """
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    # Check if the collection already exists on disk to avoid re-embedding
    collection_marker = os.path.join(CHROMA_PERSIST_DIR, ".initialized")

    if os.path.exists(collection_marker):
        print("   [Retriever] Loading existing ChromaDB collection from disk...")
        vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=CHROMA_PERSIST_DIR,
        )
    else:
        print("   [Retriever] First run detected — embedding SOPs into ChromaDB...")
        print(f"   [Retriever] Ingesting {len(DUMMY_SOPS)} SOP documents...")

        # Convert our SOP dictionaries into LangChain Document objects
        documents = [
            Document(
                page_content=sop["content"],
                metadata={**sop["metadata"], "sop_id": sop["id"]},
            )
            for sop in DUMMY_SOPS
        ]

        # Create the Chroma collection and embed all documents
        vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=embeddings,
            collection_name=COLLECTION_NAME,
            persist_directory=CHROMA_PERSIST_DIR,
        )

        # Mark as initialized to prevent re-embedding on future runs
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
        with open(collection_marker, "w") as f:
            f.write("ChromaDB initialized with telecom SOPs.\n")

        print(f"   [Retriever] Successfully embedded and stored {len(DUMMY_SOPS)} SOPs.")

    return vectorstore


def retrieve_sops(query: str, k: int = 3) -> list[str]:
    """
    Performs a semantic similarity search against the ChromaDB SOP collection.

    Takes a natural-language query (derived from the alarm error message and
    telemetry data) and returns the top-k most semantically similar SOP chunks.

    Args:
        query: A natural language description of the network fault to search for.
               Example: "DOCSIS T3 timeout upstream noise ingress Arris CMTS"
        k:     Number of top documents to retrieve (default: 3).

    Returns:
        A list of SOP text strings ordered by semantic relevance to the query.
    """
    vectorstore = get_or_create_vectorstore()

    print(f"   [Retriever] Executing semantic search: '{query[:80]}...'")
    results = vectorstore.similarity_search(query=query, k=k)

    sop_texts = []
    for i, doc in enumerate(results):
        sop_id = doc.metadata.get("sop_id", f"DOC-{i+1}")
        source = doc.metadata.get("source", "Unknown")
        print(f"   [Retriever] Retrieved: {sop_id} | Source: {source}")
        sop_texts.append(doc.page_content)

    return sop_texts
