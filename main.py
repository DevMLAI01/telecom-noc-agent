# =============================================================================
# main.py
# =============================================================================
# Purpose: Entry point for the Autonomous Telecom NOC Resolution Agent.
#
# This script:
#   1. Loads environment variables (OPENAI_API_KEY) from the .env file.
#   2. Defines the initial state for the LangGraph workflow.
#   3. Compiles and invokes the graph.
#   4. Pretty-prints the final resolution ticket and safety status.
#
# Usage:
#   python main.py
#   python main.py --alarm ALARM-002
#   python main.py --alarm ALARM-003
# =============================================================================

import argparse
import json
import sys
import os
from datetime import datetime
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment variables from .env file BEFORE importing any LangChain
# modules, as they need OPENAI_API_KEY to be set at import time.
# ---------------------------------------------------------------------------
load_dotenv()

# Verify API key is present before proceeding
if not os.getenv("OPENAI_API_KEY"):
    print("\n❌ ERROR: OPENAI_API_KEY not found.")
    print("   Please create a .env file with: OPENAI_API_KEY=sk-...")
    print("   See .env.example for reference.")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Local imports (after dotenv load ensures env vars are available)
# ---------------------------------------------------------------------------
from src.graph import build_graph
from src.state import NOCAgentState
from data.mock_telemetry import MOCK_NETWORK_TELEMETRY


# =============================================================================
# ALARM TEST SCENARIOS
# =============================================================================
# Pre-defined initial states for different alarm scenarios.
# Each represents a distinct incident type that exercises different SOPs.
# =============================================================================

ALARM_SCENARIOS: dict[str, dict] = {
    "ALARM-001": {
        "alarm_id": "ALARM-001",
        "error_message": (
            "CRITICAL: DOCSIS T3 Timeout flood detected on Arris E6000 CMTS. "
            "Upstream SNR degraded to 21.4 dB (threshold: 25 dB). "
            "1,482 T3 timeouts in the last hour affecting 347 cable modems. "
            "Upstream channel US-CH-6 showing 18.7% corrected error rate."
        ),
        "live_telemetry": {},
        "retrieved_sops": [],
        "proposed_resolution": "",
        "is_safe_to_execute": None,
        "safety_feedback": None,
        "iteration_count": 0,
    },
    "ALARM-002": {
        "alarm_id": "ALARM-002",
        "error_message": (
            "MAJOR: GPON ONU Rx Power Low on Nokia 7360 ISAM FX OLT. "
            "ONU serial NOKIA-A3F2C1D9 on port GPON-1/1/4 reporting Rx power "
            "of -28.9 dBm (alarm threshold: -28.0 dBm). "
            "Optical path loss of 31.0 dB exceeds B+ budget of 28 dB. "
            "Residential 1Gbps subscriber experiencing service degradation."
        ),
        "live_telemetry": {},
        "retrieved_sops": [],
        "proposed_resolution": "",
        "is_safe_to_execute": None,
        "safety_feedback": None,
        "iteration_count": 0,
    },
    "ALARM-003": {
        "alarm_id": "ALARM-003",
        "error_message": (
            "CRITICAL: BGP session flapping on Cisco ASR9001 core router "
            "at POP-NewYork-Hub-01. Peer 203.0.113.1 (AS64512) in IDLE state. "
            "14 flaps in last hour. MTU mismatch detected: local 9000, peer 1500. "
            "2,847 interface errors and 1,923 CRC errors on HundredGigE0/0/0/1. "
            "892,341 BGP routes impacted."
        ),
        "live_telemetry": {},
        "retrieved_sops": [],
        "proposed_resolution": "",
        "is_safe_to_execute": None,
        "safety_feedback": None,
        "iteration_count": 0,
    },
    "ALARM-004": {
        "alarm_id": "ALARM-004",
        "error_message": (
            "MAJOR: Interface queue congestion on Juniper MX480 edge router at Edge-LA-02. "
            "Interface xe-0/0/2 at 98.7% utilization (9.87 Gbps on 10G link). "
            "45,230 packets/sec drop rate. High-priority CoS queue (Q7) showing 34.1% drops. "
            "Top talker 192.0.2.45 consuming 3.2 Gbps. Tail drops: 89,452."
        ),
        "live_telemetry": {},
        "retrieved_sops": [],
        "proposed_resolution": "",
        "is_safe_to_execute": None,
        "safety_feedback": None,
        "iteration_count": 0,
    },
}


def print_banner():
    """Prints the NOC Agent startup banner."""
    banner = """
╔══════════════════════════════════════════════════════════════════╗
║       AUTONOMOUS TELECOM NOC RESOLUTION AGENT v1.0              ║
║       Powered by LangGraph + GPT-4o + ChromaDB RAG              ║
║       © 2026 — Agentic AI NOC Operations Platform               ║
╚══════════════════════════════════════════════════════════════════╝
    """
    print(banner)


def print_final_report(final_state: NOCAgentState, elapsed_seconds: float):
    """
    Renders the final resolution ticket and agent summary to the console.

    Args:
        final_state:     The complete NOCAgentState after graph execution.
        elapsed_seconds: Total wall-clock time for the workflow run.
    """
    print("\n\n" + "█" * 65)
    print("█" + " " * 20 + "FINAL AGENT OUTPUT" + " " * 25 + "█")
    print("█" * 65)

    is_safe = final_state.get("is_safe_to_execute", False)
    iteration_count = final_state.get("iteration_count", 0)

    print(f"\n📋 Alarm ID         : {final_state.get('alarm_id', 'N/A')}")
    print(f"🔒 Safety Status    : {'✅ APPROVED — SOP Compliant' if is_safe else '⚠️  WARNING — Review Required'}")
    print(f"🔄 Total Iterations : {iteration_count + 1}")
    print(f"⏱️  Execution Time   : {elapsed_seconds:.2f} seconds")

    # Print safety feedback
    if not is_safe:
        print(f"\n⚠️  SAFETY AUDIT FEEDBACK:")
        print(f"   {final_state.get('safety_feedback', 'No feedback available.')}")

    # Print the final resolution ticket
    print("\n" + "─" * 65)
    print("📄 RESOLUTION TICKET:")
    print("─" * 65)
    print(final_state.get("proposed_resolution", "No resolution generated."))

    # Print telemetry summary
    print("\n" + "─" * 65)
    print("📊 TELEMETRY SUMMARY:")
    print("─" * 65)
    telemetry = final_state.get("live_telemetry", {})
    key_fields = [
        "device",
        "location",
        "severity",
        "error_type",
        "upstream_snr_db",
        "t3_timeout_count_last_hour",
        "rx_power_dbm",
        "flap_count_last_hour",
        "current_traffic_gbps",
        "affected_modems_count",
        "affected_subscribers",
    ]
    for key in key_fields:
        if key in telemetry:
            print(f"   {key:35s}: {telemetry[key]}")

    print("\n" + "─" * 65)
    print(f"✅ Agent workflow completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("─" * 65 + "\n")


def main():
    """Main execution function for the NOC Agent."""

    # -------------------------------------------------------------------------
    # Parse command-line arguments
    # -------------------------------------------------------------------------
    parser = argparse.ArgumentParser(
        description="Autonomous Telecom NOC Resolution Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"Available alarm IDs: {', '.join(ALARM_SCENARIOS.keys())}",
    )
    parser.add_argument(
        "--alarm",
        type=str,
        default="ALARM-001",
        choices=list(ALARM_SCENARIOS.keys()),
        help="The alarm ID to investigate (default: ALARM-001)",
    )
    args = parser.parse_args()

    # -------------------------------------------------------------------------
    # Display startup information
    # -------------------------------------------------------------------------
    print_banner()
    print(f"🚀 Starting NOC Agent for: {args.alarm}")
    print(f"📅 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🤖 Model: GPT-4o (Brain + Critic) | Embeddings: text-embedding-3-small")
    print(f"🗄️  Vector DB: ChromaDB (local persistent)")

    # -------------------------------------------------------------------------
    # Select initial state based on the chosen alarm
    # -------------------------------------------------------------------------
    initial_state: NOCAgentState = ALARM_SCENARIOS[args.alarm]

    print(f"\n📟 INCOMING ALARM:")
    print(f"   {initial_state['error_message'][:120]}...")

    # -------------------------------------------------------------------------
    # Build and compile the LangGraph state machine
    # -------------------------------------------------------------------------
    print(f"\n🔧 Compiling LangGraph state machine...")
    graph = build_graph()

    # -------------------------------------------------------------------------
    # Execute the agentic workflow
    # -------------------------------------------------------------------------
    print(f"\n{'=' * 65}")
    print("🔄 STARTING AGENTIC WORKFLOW — ENTERING LANGGRAPH STATE MACHINE")
    print(f"{'=' * 65}")

    start_time = datetime.now()

    try:
        # Invoke the compiled graph with the initial state
        # LangGraph handles state propagation between all nodes automatically
        final_state = graph.invoke(initial_state)

    except Exception as e:
        print(f"\n❌ FATAL ERROR during graph execution: {e}")
        print("   Check your OPENAI_API_KEY and network connectivity.")
        raise

    end_time = datetime.now()
    elapsed = (end_time - start_time).total_seconds()

    # -------------------------------------------------------------------------
    # Render the final output report
    # -------------------------------------------------------------------------
    print_final_report(final_state, elapsed)


if __name__ == "__main__":
    main()
