import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError(
        "OPENAI_API_KEY is not set. Configure it as a Lambda environment variable or in .env for local testing."
    )

from src.graph import build_graph
from src.state import NOCAgentState

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}


def lambda_handler(event: dict, context) -> dict:
    """
    AWS Lambda handler for the Telecom NOC Resolution Agent.

    Accepts both API Gateway events (with a JSON body string) and direct Lambda
    invocation events (flat dict with alarm_id key).

    Args:
        event:   Lambda/API Gateway event dict.
        context: Lambda context object (unused; may be None for local testing).

    Returns:
        API Gateway-compatible response dict with statusCode, headers, and JSON body.
    """
    start_time = datetime.now()

    # ── Parse request body ────────────────────────────────────────────────────
    if "body" in event:
        # API Gateway event — body is a JSON string
        try:
            body = json.loads(event.get("body") or "{}")
        except (json.JSONDecodeError, TypeError):
            return {
                "statusCode": 400,
                "headers": CORS_HEADERS,
                "body": json.dumps({"error": "Request body is not valid JSON"}),
            }
    else:
        # Direct Lambda invocation (local testing / main.py compat)
        body = event

    # ── Validate required fields ──────────────────────────────────────────────
    alarm_id = body.get("alarm_id")
    if not alarm_id:
        return {
            "statusCode": 400,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": "alarm_id is required"}),
        }

    error_message = body.get("error_message", "")
    print(f"[Lambda] Received alarm: {alarm_id}")

    # ── Build graph and invoke ────────────────────────────────────────────────
    initial_state: NOCAgentState = {
        "alarm_id": alarm_id,
        "error_message": error_message,
        "telemetry": {},
        "sops": [],
        "resolution_ticket": "",
        "is_safe": None,
        "safety_feedback": None,
        "iterations": 0,
    }

    graph = build_graph()

    try:
        final_state = graph.invoke(initial_state)
    except Exception as e:
        print(f"[Lambda] ERROR during graph execution: {e}")
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(e), "alarm_id": alarm_id}),
        }

    elapsed = (datetime.now() - start_time).total_seconds()
    print(
        f"[Lambda] Workflow completed in {elapsed:.2f}s | "
        f"safe={final_state.get('is_safe')} | "
        f"iterations={final_state.get('iterations', 0)}"
    )

    return {
        "statusCode": 200,
        "headers": CORS_HEADERS,
        "body": json.dumps(
            {
                "alarm_id": final_state.get("alarm_id"),
                "is_safe": final_state.get("is_safe"),
                "safety_feedback": final_state.get("safety_feedback"),
                "resolution_ticket": final_state.get("resolution_ticket"),
                "iterations": final_state.get("iterations", 0),
                "elapsed_seconds": round(elapsed, 2),
            }
        ),
    }


# ---------------------------------------------------------------------------
# Backward-compat alias — the original handler name used by direct Lambda tests
# ---------------------------------------------------------------------------
handler = lambda_handler
