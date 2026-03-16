# =============================================================================
# src/graph.py
# =============================================================================
# Purpose: Compiles the LangGraph StateGraph — wiring all nodes, edges, and
# conditional routing logic into a single executable graph object.
#
# Graph Topology:
#
#   [START]
#      │
#      ▼
#   check_network  (Node 1: Fetch live telemetry from mock NMS)
#      │
#      ▼
#   get_manuals    (Node 2: Semantic search in ChromaDB vector store)
#      │
#      ▼
#   draft_fix      (Node 3: GPT-4o generates resolution ticket)
#      │
#      ▼
#   safety_check   (Node 4: GPT-4o critic audits SOP compliance)
#      │
#      ├── is_safe=True  ──────────────────────────────────► [END]
#      │
#      └── is_safe=False (& iterations < MAX) ──► get_manuals (loop)
#      │
#      └── is_safe=False (& iterations >= MAX) ──────────► [END]
#                                                  (with safety warning)
#
# The conditional edge implements the "self-healing" agentic behavior:
# the agent can revise its own output before committing to a final answer.
# =============================================================================

from typing import Any

from langgraph.graph import StateGraph, START, END

from src.state import NOCAgentState
from src.nodes import check_network, get_manuals, draft_fix, safety_check

# ---------------------------------------------------------------------------
# Configuration: Maximum number of draft-review iterations to prevent
# infinite loops in edge cases where the LLM cannot satisfy the critic.
# ---------------------------------------------------------------------------
MAX_ITERATIONS = 3


def route_after_safety_check(state: NOCAgentState) -> str:
    """
    Conditional routing function evaluated after Node 4 (safety_check).

    This function implements the core self-correction loop of the agent.
    It reads the `is_safe_to_execute` field from the state and decides:
    - Route to "END" if the ticket passed the safety audit.
    - Route back to "get_manuals" if it failed AND we haven't hit the iteration cap.
    - Route to "END" with a warning if we've exhausted all retry attempts.

    Args:
        state: The current NOCAgentState after safety_check has run.

    Returns:
        A string matching one of the node names defined in the graph,
        or the END sentinel value from LangGraph.
    """
    is_safe = state.get("is_safe_to_execute", False)
    iteration_count = state.get("iteration_count", 0)

    if is_safe:
        print("\n" + "=" * 65)
        print("✅  ROUTING DECISION: Ticket is SAFE — Routing to END")
        print(f"    Completed in {iteration_count + 1} iteration(s).")
        print("=" * 65)
        return END

    elif iteration_count >= MAX_ITERATIONS:
        # Safety guard: stop infinite loops, output best-effort ticket with warning
        print("\n" + "=" * 65)
        print(f"⚠️   ROUTING DECISION: Max iterations ({MAX_ITERATIONS}) reached.")
        print("    Routing to END with unresolved safety concerns flagged.")
        print("=" * 65)
        return END

    else:
        # Increment the iteration counter and loop back to re-fetch SOPs + re-draft
        print("\n" + "=" * 65)
        print(f"🔄  ROUTING DECISION: Ticket FAILED safety audit.")
        print(f"    Looping back to get_manuals (Iteration {iteration_count + 1}/{MAX_ITERATIONS})")
        print("=" * 65)
        return "get_manuals"


def increment_iteration(state: NOCAgentState) -> dict:
    """
    Helper pass-through node that increments the iteration counter.

    This is used as a lightweight "bookkeeping" node inserted in the retry
    path before re-entering `get_manuals`. It ensures the loop counter is
    accurate for both routing decisions and diagnostic logging.

    In LangGraph, returning a partial dict merges into the full state.

    Args:
        state: Current NOCAgentState.

    Returns:
        Partial state dict incrementing `iteration_count` by 1.
    """
    current_count = state.get("iteration_count", 0)
    return {"iteration_count": current_count + 1}


def build_graph() -> Any:
    """
    Constructs and compiles the full LangGraph StateGraph for the NOC agent.

    This function:
    1. Creates a new StateGraph bound to the NOCAgentState schema.
    2. Registers all node functions.
    3. Defines edges (fixed transitions) and conditional edges (routing logic).
    4. Compiles the graph into an executable runnable.

    Returns:
        A compiled LangGraph CompiledGraph object ready for invocation.
    """
    print("   [Graph] Building LangGraph state machine...")

    # Initialize the graph with our state schema
    graph = StateGraph(NOCAgentState)

    # -------------------------------------------------------------------------
    # Register Nodes
    # Each node is a Python callable that takes and returns state fields.
    # -------------------------------------------------------------------------
    graph.add_node("check_network", check_network)  # Node 1: Telemetry
    graph.add_node("get_manuals", get_manuals)  # Node 2: RAG Retrieval
    graph.add_node("draft_fix", draft_fix)  # Node 3: LLM Drafting
    graph.add_node("safety_check", safety_check)  # Node 4: LLM Critic
    graph.add_node("increment_iteration", increment_iteration)  # Counter

    # -------------------------------------------------------------------------
    # Define Fixed Edges (Linear Pipeline)
    # These transitions always happen regardless of state values.
    # -------------------------------------------------------------------------
    graph.add_edge(START, "check_network")  # Entry point
    graph.add_edge("check_network", "get_manuals")  # 1 → 2
    graph.add_edge("get_manuals", "draft_fix")  # 2 → 3
    graph.add_edge("draft_fix", "safety_check")  # 3 → 4

    # -------------------------------------------------------------------------
    # Define Conditional Edge (The Self-Correction Loop)
    # After safety_check, route_after_safety_check() decides the next step.
    # The `path_map` maps return strings to node names (or END sentinel).
    # -------------------------------------------------------------------------
    graph.add_conditional_edges(
        source="safety_check",  # Evaluate after this node runs
        path=route_after_safety_check,  # This function decides where to go
        path_map={
            END: END,  # Safe → terminate
            "get_manuals": "increment_iteration",  # Unsafe → increment first
        },
    )

    # After incrementing the counter, loop back to re-fetch SOPs
    graph.add_edge("increment_iteration", "get_manuals")

    # -------------------------------------------------------------------------
    # Compile the Graph
    # This validates the graph structure and returns an executable runnable.
    # -------------------------------------------------------------------------
    compiled_graph = graph.compile()

    print("   [Graph] State machine compiled successfully.")
    print(f"   [Graph] Max revision iterations: {MAX_ITERATIONS}")

    return compiled_graph
