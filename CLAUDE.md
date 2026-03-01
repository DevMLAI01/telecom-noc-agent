# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Agent

```bash
# Activate virtual environment first (Windows)
.venv\Scripts\activate

# Run with default alarm (ALARM-001) — reads from DynamoDB
python main.py

# Run a specific alarm scenario
python main.py --alarm ALARM-002   # GPON ONU Rx Low (Nokia 7360 OLT)
python main.py --alarm ALARM-003   # BGP Session Flap (Cisco ASR9001)
python main.py --alarm ALARM-004   # Interface Congestion (Juniper MX480)
```

## Environment Setup

```bash
uv venv
.venv\Scripts\activate          # Windows
uv pip install -r requirements.txt
cp .env.example .env            # Then fill in real values
```

Required environment variables (see `.env.example`):

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | GPT-4o (brain + critic) and text-embedding-3-small |
| `AWS_REGION` | DynamoDB region (default: `us-east-1`) |
| `DYNAMODB_SOPS_TABLE` | SOPs table name (default: `telecom-noc-sops`) |
| `DYNAMODB_TELEMETRY_TABLE` | Telemetry table name (default: `telecom-noc-telemetry`) |

AWS credentials for local development: run `aws configure` or set `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`. Inside Lambda, the execution role provides credentials automatically.

There is no test suite yet.

## Seeding DynamoDB (one-time setup)

```bash
python scripts/seed_dynamodb.py
```

This creates two DynamoDB tables (`PAY_PER_REQUEST` billing = free tier) and populates them from the local JSON files:
- `data/sops.json` → `telecom-noc-sops` table (5 SOP documents)
- `data/mock_telemetry.json` → `telecom-noc-telemetry` table (4 alarm scenarios)

To add new SOPs or alarm scenarios: edit the JSON files and re-run the seed script.

## Cloud-Native Architecture

```
API Gateway (POST /alarm)
      │   https://yjhndtxwxh.execute-api.us-east-1.amazonaws.com/alarm
      ▼
AWS Lambda  ←── lambda_handler.py (telecom-noc-agent, us-east-1)
   1 GiB RAM | 300s timeout | ECR image (linux/amd64)
      │
      ├── DynamoDB: telecom-noc-sops       ← SOPs (replaces local DUMMY_SOPS)
      ├── DynamoDB: telecom-noc-telemetry  ← Alarm data (replaces mock dict)
      ├── OpenAI text-embedding-3-small    ← Query embedding (cached per container)
      └── LangGraph StateGraph             ← Unchanged core workflow
```

**Live endpoint:**
```bash
curl -X POST https://yjhndtxwxh.execute-api.us-east-1.amazonaws.com/alarm \
  -H "Content-Type: application/json" \
  -d '{"alarm_id": "ALARM-001", "error_message": ""}'
```

**Cost:** DynamoDB free tier is permanent (25 GB, 25M reads/month). Lambda free tier covers all dev/testing.

### Deploying a new version
```bash
# 1. Rebuild and push to ECR (linux/amd64, single-arch — required for Lambda)
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin 585707316150.dkr.ecr.us-east-1.amazonaws.com

docker buildx build --platform linux/amd64 --provenance=false \
  -t 585707316150.dkr.ecr.us-east-1.amazonaws.com/telecom-noc-agent:latest \
  --push .

# 2. Update Lambda to pull the new image
aws lambda update-function-code \
  --function-name telecom-noc-agent \
  --image-uri 585707316150.dkr.ecr.us-east-1.amazonaws.com/telecom-noc-agent:latest
```

> **Important:** Always use `--provenance=false` when building for Lambda. Docker Desktop on Windows
> creates multi-arch manifest lists by default, which Lambda rejects.

## LangGraph Node Execution Flow

```
START → check_network → get_manuals → draft_fix → safety_check
                              ▲                          │
                              │    (is_safe=False,       │
                              └─── iterations < 3)  ◄───┘
                                                         │
                                                    (is_safe=True
                                                    OR iterations >= 3)
                                                         │
                                                        END
```

## The Self-Correction Loop

The key architectural feature is the **critic loop** in [src/graph.py](src/graph.py):

- `route_after_safety_check()` is a conditional edge function that reads `is_safe_to_execute` from state.
- On failure, it routes to `increment_iteration` (a bookkeeping pass-through node) then back to `get_manuals`.
- `MAX_ITERATIONS = 3` prevents infinite loops. After 3 attempts, the agent exits with a safety warning.
- When looping back, `get_manuals` enriches its query with the critic's `safety_feedback` text for more targeted SOP retrieval.

## State Schema (`src/state.py`)

`NOCAgentState` is the single source of truth. Key fields and which node owns them:

| Field | Set by | Purpose |
|-------|--------|---------|
| `alarm_id`, `error_message` | `main.py` / `lambda_handler.py` (initial) | Input alarm context |
| `live_telemetry` | Node 1 `check_network` | Device metrics from DynamoDB |
| `retrieved_sops` | Node 2 `get_manuals` | Top-3 SOP chunks via numpy cosine similarity |
| `proposed_resolution` | Node 3 `draft_fix` | Full resolution ticket text |
| `is_safe_to_execute` | Node 4 `safety_check` | Drives routing decision |
| `safety_feedback` | Node 4 `safety_check` | Fed back into revision loop query |
| `iteration_count` | `increment_iteration` node | Loop guard |

## LLM Usage

Both LLM nodes instantiate `ChatOpenAI` independently each invocation:
- **Node 3 (Brain)**: `gpt-4o`, `temperature=0.1` — drafts resolution ticket from telemetry + SOPs
- **Node 4 (Critic)**: `gpt-4o`, `temperature=0.0` — audits with `.with_structured_output(SafetyAuditResult)`, where `SafetyAuditResult` is a Pydantic model in [src/nodes.py](src/nodes.py) that forces a boolean `is_safe` + `feedback` string. This structured output is what makes routing deterministic.

## RAG — DynamoDB + Numpy (`src/retriever.py`)

- SOPs are stored in DynamoDB (`telecom-noc-sops` table). No local vector database.
- On Lambda cold start: all SOPs are loaded from DynamoDB and embedded with `text-embedding-3-small`.
- Embeddings are cached in a module-level variable — warm invocations skip re-embedding.
- `retrieve_sops(query, k=3)` computes cosine similarity in numpy and returns the top-k SOP strings.
- Same public interface as the previous ChromaDB implementation — `src/nodes.py` is unchanged.
- To add new SOPs: insert items into `data/sops.json` and re-run `scripts/seed_dynamodb.py`.

## Mock NMS — DynamoDB (`data/mock_telemetry.py`)

- Telemetry is stored in DynamoDB (`telecom-noc-telemetry` table).
- Module-level cache ensures DynamoDB is only scanned once per container lifecycle.
- `get_telemetry_for_alarm(alarm_id)` is the public interface used by [src/tools.py](src/tools.py).
- To add new alarm scenarios: add to `data/mock_telemetry.json`, re-run seed script, and add to `ALARM_SCENARIOS` in [main.py](main.py).

## Docker / Lambda

```bash
# Build the Lambda container image
docker build -t telecom-noc-agent .

# Test locally (requires Docker Desktop)
docker run -p 9000:8080 \
  -e OPENAI_API_KEY=sk-... \
  -e AWS_REGION=us-east-1 \
  -e DYNAMODB_SOPS_TABLE=telecom-noc-sops \
  -e DYNAMODB_TELEMETRY_TABLE=telecom-noc-telemetry \
  -e AWS_ACCESS_KEY_ID=... \
  -e AWS_SECRET_ACCESS_KEY=... \
  telecom-noc-agent

# Invoke the local container
curl -X POST http://localhost:9000/2015-03-31/functions/function/invocations \
  -d '{"alarm_id": "ALARM-001", "error_message": ""}'
```

Lambda invocation event format:
```json
{ "alarm_id": "ALARM-001", "error_message": "" }
```

Lambda response format:
```json
{
  "statusCode": 200,
  "body": "{\"alarm_id\": \"ALARM-001\", \"is_safe_to_execute\": true, \"proposed_resolution\": \"...\", ...}"
}
```

## Key Extension Points

- **New alarm scenario**: Add entry to `data/mock_telemetry.json` + `ALARM_SCENARIOS` in `main.py`, then re-run seed script.
- **Real NMS integration**: Replace `_load_telemetry_from_dynamodb()` in `data/mock_telemetry.py` with an NMS API call.
- **New SOP documents**: Add entries to `data/sops.json`, re-run `scripts/seed_dynamodb.py`. Delete `_sop_embeddings` cache by redeploying Lambda.
- **Change iteration cap**: Modify `MAX_ITERATIONS` in [src/graph.py](src/graph.py).
- **LangGraph persistence/memory**: Add a `SqliteSaver` checkpointer when compiling the graph in `src/graph.py`.
- **Push to ECR / deploy Lambda**: See the push commands in the Dockerfile header comments.
