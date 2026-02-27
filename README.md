# Autonomous Telecom NOC Resolution Agent

An enterprise-grade, production-ready Agentic RAG system built with **LangGraph**, **GPT-4o**, and **ChromaDB** that autonomously investigates network alarms, retrieves vendor SOPs, drafts incident resolution tickets, and self-evaluates for safety compliance — mimicking the workflow of a Level 3 NOC Engineer.

---

## Business Value

In modern Telecom Network Operations Centers, L3 engineers spend an average of **45–90 minutes per critical alarm** manually:
1. Correlating live telemetry from NMS dashboards
2. Searching through hundreds of pages of vendor manuals
3. Drafting step-by-step resolution procedures
4. Getting peer review for safety compliance

This agent compresses that entire cycle to **under 60 seconds**, with built-in SOP compliance enforcement — reducing Mean Time to Resolution (MTTR), minimizing human error, and freeing senior engineers for complex escalations.

---

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │        NOCAgentState (TypedDict)     │
                    │  alarm_id, error_message,            │
                    │  live_telemetry, retrieved_sops,     │
                    │  proposed_resolution,                │
                    │  is_safe_to_execute, safety_feedback │
                    └─────────────────────────────────────┘
                                    │
         ┌──────────────────────────▼──────────────────────────┐
         │                                                       │
    [START]                                                      │
         │                                                       │
         ▼                                                       │
  ┌─────────────┐                                               │
  │  Node 1     │  check_network()                             │
  │  Telemetry  │  → Invokes @tool to query mock NMS           │
  │  Checker    │  → Populates live_telemetry                  │
  └──────┬──────┘                                               │
         │                                                       │
         ▼                                                       │
  ┌─────────────┐                                               │
  │  Node 2     │  get_manuals()                               │
  │  Document   │  → Semantic search in ChromaDB               │
  │  Retriever  │  → Populates retrieved_sops                  │
  └──────┬──────┘         ▲                                     │
         │                │  (retry loop on failure)            │
         ▼                │                                     │
  ┌─────────────┐         │                                     │
  │  Node 3     │  draft_fix()                                 │
  │  The Brain  │  → GPT-4o synthesizes telemetry + SOPs       │
  │  (GPT-4o)   │  → Populates proposed_resolution             │
  └──────┬──────┘                                               │
         │                                                       │
         ▼                                                       │
  ┌─────────────┐   is_safe=True    ┌──────┐                   │
  │  Node 4     │ ─────────────────►│ END  │                   │
  │  The Critic │                   └──────┘                   │
  │  (GPT-4o)   │   is_safe=False                              │
  └─────────────┘ ──────────────────► increment_iteration       │
                                     → back to get_manuals      │
                                                                │
         └──────────────────────────────────────────────────────┘
```

### Component Overview

| Component | File | Responsibility |
|-----------|------|---------------|
| State Schema | `src/state.py` | Single source of truth — TypedDict with all workflow fields |
| NMS Tool | `src/tools.py` | LangChain `@tool` for live telemetry lookup |
| Vector Store | `src/retriever.py` | ChromaDB setup, SOP ingestion, semantic search |
| Node 1 | `src/nodes.py:check_network` | Telemetry fetching via @tool |
| Node 2 | `src/nodes.py:get_manuals` | RAG retrieval from ChromaDB |
| Node 3 | `src/nodes.py:draft_fix` | GPT-4o resolution ticket drafting |
| Node 4 | `src/nodes.py:safety_check` | GPT-4o critic with structured output |
| Graph | `src/graph.py` | LangGraph compilation and conditional routing |
| Entry Point | `main.py` | CLI runner with 4 alarm scenarios |
| Mock NMS | `data/mock_telemetry.py` | Simulated live network vitals dictionary |

---

## Tech Stack

| Technology | Version | Purpose |
|------------|---------|---------|
| Python | 3.10+ | Runtime |
| LangGraph | ≥0.2.0 | Agentic state machine framework |
| LangChain | ≥0.3.0 | Tool, prompt, and LLM abstractions |
| langchain-openai | ≥0.2.0 | GPT-4o and embedding integrations |
| ChromaDB | ≥0.5.0 | Local vector database for SOP storage |
| Pydantic | ≥2.0.0 | Structured output validation for critic node |
| python-dotenv | ≥1.0.0 | Secure API key management |
| OpenAI API | GPT-4o | LLM brain + critic, text-embedding-3-small |

---

## Project Structure

```
telecom-noc-agent/
├── data/
│   └── mock_telemetry.py      # Mock NMS with 4 realistic alarm scenarios
├── src/
│   ├── __init__.py            # Package marker
│   ├── state.py               # NOCAgentState TypedDict definition
│   ├── tools.py               # @tool: query_nms_for_alarm_telemetry
│   ├── retriever.py           # ChromaDB setup + 5 SOP documents + retrieve_sops()
│   ├── nodes.py               # 4 LangGraph node functions + SafetyAuditResult model
│   └── graph.py               # StateGraph compilation + conditional routing
├── .env.example               # API key template
├── .gitignore                 # Excludes .env, chroma_db, __pycache__
├── requirements.txt           # All Python dependencies with versions
├── main.py                    # CLI entry point with 4 pre-built alarm scenarios
└── README.md                  # This file
```

---

## Setup & Installation

### Prerequisites
- Python 3.10 or higher
- [uv](https://docs.astral.sh/uv/) installed (`pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- An OpenAI API key with access to `gpt-4o` and `text-embedding-3-small`

### Step 1: Clone / Navigate to the project
```bash
cd telecom-noc-agent
```

### Step 2: Create and activate a virtual environment
```bash
uv venv
source .venv/bin/activate   # macOS / Linux
.venv\Scripts\activate      # Windows
```

### Step 3: Install dependencies
```bash
uv pip install -r requirements.txt
```

### Step 4: Configure your API key
```bash
# Copy the template
cp .env.example .env

# Edit .env and add your real OpenAI API key
# OPENAI_API_KEY=sk-your-real-key-here
```

### Step 5: Run the agent
```bash
# Default: Investigates ALARM-001 (Arris CMTS T3 Timeout)
python main.py

# Investigate specific alarms:
python main.py --alarm ALARM-001   # DOCSIS T3 Timeout (Arris E6000 CMTS)
python main.py --alarm ALARM-002   # GPON ONU Rx Low (Nokia 7360 OLT)
python main.py --alarm ALARM-003   # BGP Session Flap (Cisco ASR9001)
python main.py --alarm ALARM-004   # Interface Congestion (Juniper MX480)
```

---

## Available Alarm Scenarios

| Alarm ID | Device | Fault Type | Severity |
|----------|--------|------------|----------|
| ALARM-001 | Arris E6000 CMTS | DOCSIS T3 Timeout — 347 modems affected | CRITICAL |
| ALARM-002 | Nokia 7360 ISAM FX OLT | GPON ONU Rx Power Degradation | MAJOR |
| ALARM-003 | Cisco ASR9001 Core Router | BGP Session Flap — 14 flaps/hour | CRITICAL |
| ALARM-004 | Juniper MX480 Edge Router | Interface Queue Congestion — 98.7% util | MAJOR |

---

## Embedded SOPs (Vector Database Contents)

The ChromaDB vector store is seeded with 5 realistic SOP documents on first run:

| SOP ID | Title | Source |
|--------|-------|--------|
| SOP-001 | Arris E6000 CMTS — DOCSIS T3 Timeout Remediation | Arris E6000 Guide v4.2 |
| SOP-002 | Nokia 7360 ISAM FX — GPON ONU Rx Power Low | Nokia 7360 Manual Rev 3.1 |
| SOP-003 | BGP Session Flap — Core Router Runbook | Internal NOC Runbook v2.8 |
| SOP-004 | Interface Queue Congestion — QoS Runbook | Internal NOC Runbook v2.8 |
| SOP-005 | NOC Escalation and Communication Protocol | NOC Operations Policy v5.0 |

ChromaDB persists to `./chroma_db/` after the first run. Subsequent runs load from disk (no re-embedding cost).

---

## Agentic Self-Correction Loop

The agent implements a cyclical review mechanism:

1. **Draft** — Node 3 (GPT-4o Brain) generates a resolution ticket grounded in SOPs.
2. **Audit** — Node 4 (GPT-4o Critic) evaluates every step against SOP constraints.
3. **Route** — If the ticket is SOP-compliant → output final result. If not → loop back to retrieve additional context and re-draft (max 3 iterations).

This mirrors the human peer-review process in enterprise NOC operations, where no resolution procedure is implemented without a second engineer's sign-off.

---

## Sample Output

```
╔══════════════════════════════════════════════════════════════════╗
║       AUTONOMOUS TELECOM NOC RESOLUTION AGENT v1.0              ║
╚══════════════════════════════════════════════════════════════════╝

🔍  NODE 1: TELEMETRY CHECKER — Querying Live Network Data
   Alarm ID    : ALARM-001
   [Tool] Telemetry retrieved for device: Arris E6000 CMTS

📚  NODE 2: DOCUMENT RETRIEVER — Querying Vector Database
   [Retriever] Retrieved: SOP-001 | Source: Arris E6000 Guide v4.2

🧠  NODE 3: THE BRAIN — Drafting Resolution Ticket (GPT-4o)
   Invoking GPT-4o for ticket generation...

🛡️   NODE 4: THE CRITIC — Running Safety & SOP Compliance Audit
   🔍 AUDIT RESULT: ✅ SAFE

✅  ROUTING DECISION: Ticket is SAFE — Routing to END

INCIDENT RESOLUTION TICKET
==========================
Alarm ID       : ALARM-001
Device         : Arris E6000 CMTS — Headend-Chicago-01
Severity       : CRITICAL
...
```

---

## Extending the Agent

### Add a Real NMS Connection
Replace `data/mock_telemetry.py` with an API call to your NMS:
```python
import requests

def get_telemetry_for_alarm(alarm_id: str) -> dict:
    response = requests.get(f"https://your-nms/api/alarms/{alarm_id}",
                            headers={"Authorization": f"Bearer {os.getenv('NMS_API_KEY')}"})
    return response.json()
```

### Add Real SOP Documents
In `src/retriever.py`, replace `DUMMY_SOPS` with a document loader:
```python
from langchain_community.document_loaders import PyPDFLoader

loader = PyPDFLoader("path/to/arris_manual.pdf")
documents = loader.load_and_split()
```

### Add Memory / Persistence
Use LangGraph's built-in checkpointing to persist state across sessions:
```python
from langgraph.checkpoint.sqlite import SqliteSaver
memory = SqliteSaver.from_conn_string("noc_agent_memory.db")
graph = build_graph().compile(checkpointer=memory)
```

---

## License

This project is provided for educational and demonstration purposes.
For production use, ensure compliance with your organization's AI governance and change management policies.
