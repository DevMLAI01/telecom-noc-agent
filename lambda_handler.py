# =============================================================================
# lambda_handler.py
# =============================================================================
# Purpose: AWS Lambda entry point for the Telecom NOC Resolution Agent.
#
# This handler replaces the CLI main.py for cloud invocations. It accepts
# an alarm event, runs the full LangGraph workflow, and returns a structured
# JSON response suitable for API Gateway or direct Lambda invocation.
#
# The graph is built ONCE at module load time (outside the handler function).
# On warm Lambda invocations, graph compilation is skipped — only the
# graph.invoke() call is made, which is the desired fast-path behavior.
#
# Invocation format (API Gateway / direct Lambda test):
#   {
#     "alarm_id": "ALARM-001",
#     "error_message": ""          <- optional: uses DynamoDB alarm message if empty
#   }
#
# Response format:
#   {
#     "statusCode": 200,
#     "body": "{...json string...}"
#   }
#
# Local testing (after setting env vars in .env):
#   python -c "
#   from lambda_handler import handler
#   import json
#   result = handler({'alarm_id': 'ALARM-001', 'error_message': ''}, None)
#   print(json.loads(result['body'])['is_safe_to_execute'])
#   "
# =============================================================================

import json
import os
from datetime import datetime
from dotenv import load_dotenv

# load_dotenv() is a no-op when running inside Lambda (env vars are set on the
# Lambda function configuration). It enables the same file to work locally.
load_dotenv()

# Validate API key presence before graph import triggers model instantiation
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Configure it as a Lambda environment variable or in .env for local testing."
    )

from src.graph import build_graph
from src.state import NOCAgentState

# ---------------------------------------------------------------------------
# Build the LangGraph state machine ONCE at module load time.
# Lambda reuses this compiled graph across all warm invocations in the same
# container instance — avoiding repeated compilation overhead.
# ---------------------------------------------------------------------------
print("[Lambda] Building LangGraph state machine at module load...")
graph = build_graph()
print("[Lambda] Graph ready.")


def handler(event: dict, context) -> dict:
    """
    AWS Lambda handler for the Telecom NOC Resolution Agent.

    Args:
        event:   Lambda event dict. Expected keys:
                   - alarm_id (str, required): e.g. "ALARM-001"
                   - error_message (str, optional): override alarm description
        context: Lambda context object (unused, can be None for local testing).

    Returns:
        API Gateway-compatible response dict with statusCode and JSON body.
    """
    start_time = datetime.now()

    alarm_id = event.get("alarm_id", "ALARM-001")
    error_message = event.get("error_message", "")

    print(f"[Lambda] Received alarm: {alarm_id}")

    initial_state: NOCAgentState = {
        "alarm_id": alarm_id,
        "error_message": error_message,
        "live_telemetry": {},
        "retrieved_sops": [],
        "proposed_resolution": "",
        "is_safe_to_execute": None,
        "safety_feedback": None,
        "iteration_count": 0,
    }

    try:
        final_state = graph.invoke(initial_state)
    except Exception as e:
        print(f"[Lambda] ERROR during graph execution: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "error": str(e),
                    "alarm_id": alarm_id,
                }
            ),
        }

    elapsed = (datetime.now() - start_time).total_seconds()
    print(
        f"[Lambda] Workflow completed in {elapsed:.2f}s | "
        f"safe={final_state.get('is_safe_to_execute')} | "
        f"iterations={final_state.get('iteration_count', 0) + 1}"
    )

    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "alarm_id": final_state.get("alarm_id"),
                "is_safe_to_execute": final_state.get("is_safe_to_execute"),
                "safety_feedback": final_state.get("safety_feedback"),
                "proposed_resolution": final_state.get("proposed_resolution"),
                "iteration_count": final_state.get("iteration_count", 0) + 1,
                "elapsed_seconds": round(elapsed, 2),
            }
        ),
    }
