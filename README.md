# Autonomous Telecom NOC Resolution Agent

An enterprise-grade, production-deployed Agentic RAG system built with **LangGraph**, **GPT-4o**, and **AWS** that autonomously investigates network alarms, retrieves vendor SOPs, drafts incident resolution tickets, and self-evaluates for safety compliance — deployed as a serverless microservice on AWS Lambda and publicly accessible via API Gateway.

---

## Live Demo

The agent is **deployed and running on AWS**. You can trigger it right now — no setup required:

```powershell
curl.exe -X POST https://yjhndtxwxh.execute-api.us-east-1.amazonaws.com/alarm -H "Content-Type: application/json" -d '{"alarm_id": "ALARM-001", "error_message": ""}'
```

Try all four alarm scenarios:

| `alarm_id` | Device | Fault Type | Severity |
|-----------|--------|------------|----------|
| `ALARM-001` | Arris E6000 CMTS | DOCSIS T3 Timeout — 347 modems affected | CRITICAL |
| `ALARM-002` | Nokia 7360 ISAM FX OLT | GPON ONU Rx Power Degradation | MAJOR |
| `ALARM-003` | Cisco ASR9001 Core Router | BGP Session Flap — 14 flaps/hour | CRITICAL |
| `ALARM-004` | Juniper MX480 Edge Router | Interface Queue Congestion — 98.7% util | MAJOR |

**Expected response** (~20–40s on cold start, ~5s warm):
```json
{
  "alarm_id": "ALARM-001",
  "is_safe_to_execute": true,
  "safety_feedback": "The proposed resolution ticket is SAFE. All steps are directly traceable to the SOPs...",
  "proposed_resolution": "INCIDENT RESOLUTION TICKET\n==========================\n...",
  "iteration_count": 3,
  "elapsed_seconds": 19.38
}
```

---

## Business Value

In modern Telecom Network Operations Centers, L3 engineers spend an average of **45–90 minutes per critical alarm** manually:
1. Correlating live telemetry from NMS dashboards
2. Searching through hundreds of pages of vendor manuals
3. Drafting step-by-step resolution procedures
4. Getting peer review for safety compliance

This agent compresses that entire workflow to **under 60 seconds**, with built-in SOP compliance enforcement — reducing Mean Time to Resolution (MTTR), minimizing human error, and freeing senior engineers for complex escalations.

---

## Cloud Architecture

```
                        ┌─────────────────────────────────┐
  curl / HTTP client    │   AWS API Gateway (HTTP API)     │
  POST /alarm  ───────► │   yjhndtxwxh.execute-api...      │
                        └────────────────┬────────────────┘
                                         │ triggers
                                         ▼
                        ┌─────────────────────────────────┐
                        │   AWS Lambda                     │
                        │   telecom-noc-agent              │
                        │   Python 3.12 · 1 GiB · 300s    │
                        │                                  │
                        │  ┌──────────────────────────┐   │
                        │  │  Docker Container (ECR)  │   │
                        │  │  public.ecr.aws/lambda/  │   │
                        │  │    python:3.12           │   │
                        │  │                          │   │
                        │  │   lambda_handler.py      │   │
                        │  │       │                  │   │
                        │  │       ▼                  │   │
                        │  │   LangGraph StateGraph   │   │
                        │  │   (4 nodes + critic loop)│   │
                        │  └──────────────────────────┘   │
                        └────┬────────────────────┬───────┘
                             │                    │
                IAM role     │                    │  OpenAI API
                (no keys)    ▼                    ▼
              ┌──────────────────────┐   ┌──────────────────┐
              │   AWS DynamoDB       │   │  GPT-4o           │
              │                      │   │  text-embedding   │
              │  telecom-noc-sops    │   │    -3-small       │
              │  (5 SOP documents)   │   │                  │
              │                      │   │  Brain: temp=0.1  │
              │  telecom-noc-        │   │  Critic: temp=0.0 │
              │    telemetry         │   │  (structured out) │
              │  (4 alarm scenarios) │   └──────────────────┘
              └──────────────────────┘
```

### How it works

1. **API Gateway** receives a `POST /alarm` request with an `alarm_id` and routes it to Lambda.
2. **Lambda** (Docker container from ECR) runs the LangGraph workflow.
3. **Node 1** queries DynamoDB for live device telemetry (CPU, SNR, error counters, etc.).
4. **Node 2** fetches all SOPs from DynamoDB, embeds them with `text-embedding-3-small`, and returns the top-3 most relevant via numpy cosine similarity — no vector database required.
5. **Node 3** (GPT-4o Brain) synthesizes telemetry + SOPs into a structured resolution ticket.
6. **Node 4** (GPT-4o Critic) audits every step for SOP compliance using structured output.
7. If the ticket fails the audit, the agent loops back to Node 2 with the critic's feedback for a more targeted SOP retrieval — up to 3 iterations.
8. The final approved ticket is returned as JSON to the API caller.

### Self-Correction Loop

```
START → check_network → get_manuals → draft_fix → safety_check
                              ▲                          │
                              │    (is_safe=False,       │
                              └─── iterations < 3)  ◄───┘
                                                         │
                                                    (is_safe=True
                                                    OR iterations ≥ 3)
                                                         │
                                                        END
```

---

## Tech Stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| **Orchestration** | LangGraph ≥0.2.0 | StateGraph with conditional routing |
| **LLM** | GPT-4o via LangChain | Brain (temp=0.1) + Critic (temp=0.0, structured output) |
| **Embeddings** | text-embedding-3-small | Cached per Lambda container lifecycle |
| **RAG / Vector Search** | DynamoDB + numpy cosine similarity | No vector DB — free tier, cloud-native |
| **Data Store** | AWS DynamoDB | PAY_PER_REQUEST billing — free tier forever |
| **Compute** | AWS Lambda | 1 GiB RAM, 300s timeout, Docker image |
| **Container Registry** | AWS ECR | linux/amd64 image, public.ecr.aws base |
| **API** | AWS API Gateway (HTTP API) | POST /alarm, auto-deploy, CORS enabled |
| **Validation** | Pydantic v2 | `SafetyAuditResult` enforces boolean `is_safe` + feedback |
| **Runtime** | Python 3.12 | uv for local dependency management |
| **Testing** | pytest + moto | DynamoDB mocked via moto; OpenAI mocked via unittest.mock |
| **Linting / Formatting** | Ruff + mypy | Enforced via pre-commit hooks and CI |
| **CI** | GitHub Actions | 3-stage pipeline: lint → test → docker build |

---

## Project Structure

```
telecom-noc-agent/
├── src/
│   ├── state.py               # NOCAgentState TypedDict — single source of truth
│   ├── tools.py               # @tool: query_nms_for_alarm_telemetry
│   ├── retriever.py           # DynamoDB SOP loader + numpy cosine similarity RAG
│   ├── nodes.py               # 4 LangGraph node functions + SafetyAuditResult model
│   └── graph.py               # StateGraph compilation + conditional routing
├── tests/
│   ├── conftest.py            # Shared fixtures: moto DynamoDB, mock OpenAI, sample data
│   ├── test_state.py          # NOCAgentState schema validation
│   ├── test_retriever.py      # RAG: DynamoDB load + cosine similarity
│   ├── test_nodes.py          # Node unit tests (check_network, draft_fix, safety_check)
│   └── test_lambda_handler.py # Lambda handler integration tests
├── data/
│   ├── sops.json              # Source of truth for 5 SOP documents (seeds DynamoDB)
│   ├── mock_telemetry.json    # Source of truth for 4 alarm scenarios (seeds DynamoDB)
│   └── mock_telemetry.py      # DynamoDB telemetry loader with module-level cache
├── scripts/
│   └── seed_dynamodb.py       # One-time script: creates DynamoDB tables + uploads data
├── .github/
│   └── workflows/ci.yml       # CI pipeline: lint → test → docker build
├── lambda_handler.py          # AWS Lambda entry point (graph built once at module load)
├── Dockerfile                 # Lambda container — public.ecr.aws/lambda/python:3.12
├── pyproject.toml             # pytest, ruff, mypy, and coverage configuration
├── .pre-commit-config.yaml    # Pre-commit: ruff, mypy, detect-secrets, JSON/YAML checks
├── main.py                    # CLI entry point (local dev)
├── requirements.txt           # Python dependencies (boto3, numpy, langgraph, openai...)
└── .env.example               # Environment variable template
```

---

## Component Overview

| Component | File | Responsibility |
|-----------|------|---------------|
| State Schema | `src/state.py` | TypedDict with all workflow fields |
| NMS Tool | `src/tools.py` | LangChain `@tool` for telemetry lookup |
| RAG Engine | `src/retriever.py` | DynamoDB scan + numpy cosine similarity |
| Node 1 | `src/nodes.py:check_network` | Fetches live device telemetry via `@tool` |
| Node 2 | `src/nodes.py:get_manuals` | Semantic SOP retrieval |
| Node 3 | `src/nodes.py:draft_fix` | GPT-4o resolution ticket drafting |
| Node 4 | `src/nodes.py:safety_check` | GPT-4o critic with structured Pydantic output |
| Graph | `src/graph.py` | LangGraph compilation + `MAX_ITERATIONS=3` routing |
| Lambda Handler | `lambda_handler.py` | AWS Lambda entry point, graph cached at module load |
| CLI Runner | `main.py` | Local development with 4 pre-built alarm scenarios |

---

## Embedded SOPs (DynamoDB Contents)

Five realistic SOP documents are stored in the `telecom-noc-sops` DynamoDB table, embedded on Lambda cold start, and retrieved by cosine similarity at query time:

| SOP ID | Title | Source |
|--------|-------|--------|
| SOP-001 | Arris E6000 CMTS — DOCSIS T3 Timeout Remediation | Arris E6000 Guide v4.2 |
| SOP-002 | Nokia 7360 ISAM FX — GPON ONU Rx Power Low | Nokia 7360 Manual Rev 3.1 |
| SOP-003 | BGP Session Flap — Core Router Runbook | Internal NOC Runbook v2.8 |
| SOP-004 | Interface Queue Congestion — QoS Runbook | Internal NOC Runbook v2.8 |
| SOP-005 | NOC Escalation and Communication Protocol | NOC Operations Policy v5.0 |

---

## Testing & Code Quality

### Running tests
```bash
pytest                   # all tests, coverage enforced at 70%
pytest -m unit           # unit tests only (no external services)
pytest --no-cov -v       # quick run without coverage
```

Tests use **moto** to mock DynamoDB and `unittest.mock` for OpenAI — no real API calls or AWS credentials needed. Test markers: `unit`, `integration`, `slow`.

### Linting & formatting (Ruff)
```bash
ruff check --fix .       # lint and auto-fix
ruff format .            # format
mypy src/                # type check
```

### Pre-commit hooks
```bash
pre-commit install        # install hooks (one-time)
pre-commit run --all-files
```

Hooks run ruff, ruff-format, mypy, and security scanners (detect-secrets, detect-private-key) on every commit.

### CI Pipeline
GitHub Actions runs three jobs in sequence on every push:
1. **Lint & Type Check** — ruff + mypy
2. **Unit & Integration Tests** — pytest with coverage report (≥70%)
3. **Docker Build Check** — verifies the Lambda container builds successfully

---

## Local Development Setup

### Prerequisites
- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)
- An OpenAI API key with access to `gpt-4o` and `text-embedding-3-small`
- AWS credentials with DynamoDB read access (`aws configure`)

### Step 1: Clone and install
```bash
git clone https://github.com/DevMLAI01/telecom-noc-agent.git
cd telecom-noc-agent
uv venv && .venv/Scripts/activate   # Windows
# or: source .venv/bin/activate     # macOS / Linux
uv pip install -r requirements.txt
```

### Step 2: Configure environment
```bash
cp .env.example .env
# Edit .env — fill in OPENAI_API_KEY and AWS credentials
```

### Step 3: Seed DynamoDB (one-time)
```bash
python scripts/seed_dynamodb.py
# Creates telecom-noc-sops and telecom-noc-telemetry tables
# and uploads all SOPs and telemetry data from the data/ JSON files
```

### Step 4: Run locally
```bash
python main.py                     # ALARM-001 (default)
python main.py --alarm ALARM-002   # Nokia GPON ONU Rx Low
python main.py --alarm ALARM-003   # Cisco ASR9001 BGP Flap
python main.py --alarm ALARM-004   # Juniper MX480 Congestion
```

---

## Docker / Lambda Deployment

```bash
# Build the Lambda container image (linux/amd64 — required for Lambda)
docker buildx build --platform linux/amd64 --provenance=false \
  -t 585707316150.dkr.ecr.us-east-1.amazonaws.com/telecom-noc-agent:latest \
  --push .

# Update Lambda to pull the new image
aws lambda update-function-code \
  --function-name telecom-noc-agent \
  --image-uri 585707316150.dkr.ecr.us-east-1.amazonaws.com/telecom-noc-agent:latest
```

> `--provenance=false` is required when building on Docker Desktop for Windows — without it, Docker
> pushes a multi-arch manifest list that AWS Lambda rejects.

---

## Extending the Agent

### Add a new alarm scenario
1. Add an entry to `data/mock_telemetry.json`
2. Run `python scripts/seed_dynamodb.py` to upload it
3. Add the scenario to `ALARM_SCENARIOS` in `main.py`

### Connect to a real NMS
Replace the DynamoDB loader in `data/mock_telemetry.py` with an API call:
```python
def get_telemetry_for_alarm(alarm_id: str) -> dict:
    response = requests.get(
        f"https://your-nms/api/alarms/{alarm_id}",
        headers={"Authorization": f"Bearer {os.getenv('NMS_API_KEY')}"}
    )
    return response.json()
```

### Load real SOP documents
1. Add entries to `data/sops.json` (or load from PDFs with `PyPDFLoader`)
2. Re-run `python scripts/seed_dynamodb.py`
3. Redeploy Lambda to clear the in-memory embedding cache

### Add memory and persistence
```python
from langgraph.checkpoint.sqlite import SqliteSaver
memory = SqliteSaver.from_conn_string("noc_agent_memory.db")
graph = build_graph().compile(checkpointer=memory)
```

---

## License

This project is provided for educational and demonstration purposes.
For production use, ensure compliance with your organization's AI governance and change management policies.
