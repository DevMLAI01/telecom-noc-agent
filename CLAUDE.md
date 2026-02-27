# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Agent

```bash
# Activate virtual environment first (Windows)
.venv\Scripts\activate

# Run with default alarm (ALARM-001)
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
cp .env.example .env            # Then add real OPENAI_API_KEY
```

The only required environment variable is `OPENAI_API_KEY` (GPT-4o + text-embedding-3-small). `main.py` validates its presence at startup and exits with a clear error if missing.

There is no test suite yet.

## Architecture

This is a **LangGraph StateGraph** where a single `NOCAgentState` TypedDict flows through four nodes. Each node receives the full state and returns only the fields it modified (LangGraph merges partial dicts back into state automatically).

### Node Execution Flow

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

### The Self-Correction Loop

The key architectural feature is the **critic loop** in [src/graph.py](src/graph.py):

- `route_after_safety_check()` is a conditional edge function that reads `is_safe_to_execute` from state.
- On failure, it routes to `increment_iteration` (a bookkeeping pass-through node) then back to `get_manuals`.
- `MAX_ITERATIONS = 3` prevents infinite loops. After 3 attempts, the agent exits with a safety warning.
- When looping back, `get_manuals` enriches its ChromaDB query with the critic's `safety_feedback` text for more targeted SOP retrieval.

### State Schema (`src/state.py`)

`NOCAgentState` is the single source of truth. Key fields and which node owns them:

| Field | Set by | Purpose |
|-------|--------|---------|
| `alarm_id`, `error_message` | `main.py` (initial) | Input alarm context |
| `live_telemetry` | Node 1 `check_network` | Device metrics from mock NMS |
| `retrieved_sops` | Node 2 `get_manuals` | Top-3 SOP chunks from ChromaDB |
| `proposed_resolution` | Node 3 `draft_fix` | Full resolution ticket text |
| `is_safe_to_execute` | Node 4 `safety_check` | Drives routing decision |
| `safety_feedback` | Node 4 `safety_check` | Fed back into revision loop query |
| `iteration_count` | `increment_iteration` node | Loop guard |

### LLM Usage

Both LLM nodes instantiate `ChatOpenAI` independently each invocation:
- **Node 3 (Brain)**: `gpt-4o`, `temperature=0.1` — drafts resolution ticket from telemetry + SOPs
- **Node 4 (Critic)**: `gpt-4o`, `temperature=0.0` — audits with `.with_structured_output(SafetyAuditResult)`, where `SafetyAuditResult` is a Pydantic model in [src/nodes.py](src/nodes.py) that forces a boolean `is_safe` + `feedback` string. This structured output is what makes routing deterministic.

### ChromaDB / RAG (`src/retriever.py`)

- 5 SOP documents are embedded with `text-embedding-3-small` and stored in `./chroma_db/` on first run.
- A `.initialized` marker file prevents re-embedding on subsequent runs (avoids redundant API cost).
- `retrieve_sops(query, k=3)` is the public interface used by Node 2.
- To replace dummy SOPs with real documents, edit `DUMMY_SOPS` in [src/retriever.py](src/retriever.py) or swap in a `PyPDFLoader`. Delete `./chroma_db/` to force re-embedding.

### Mock NMS (`data/mock_telemetry.py`)

`get_telemetry_for_alarm(alarm_id)` returns a hard-coded dict of device metrics keyed by alarm ID. This is the only place to add new alarm scenarios' telemetry data. The corresponding initial state dict must also be added to `ALARM_SCENARIOS` in [main.py](main.py).

## Key Extension Points

- **New alarm scenario**: Add entry to `ALARM_SCENARIOS` in `main.py` + matching telemetry dict in `data/mock_telemetry.py`.
- **Real NMS integration**: Replace `get_telemetry_for_alarm()` in `data/mock_telemetry.py` with an API call.
- **Real SOP documents**: Replace `DUMMY_SOPS` in `src/retriever.py` with a document loader; delete `chroma_db/` to re-seed.
- **Change iteration cap**: Modify `MAX_ITERATIONS` in `src/graph.py`.
- **LangGraph persistence/memory**: Add a `SqliteSaver` checkpointer when compiling the graph in `src/graph.py`.
