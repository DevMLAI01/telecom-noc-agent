# =============================================================================
# src/tools.py
# =============================================================================
# Purpose: Defines LangChain @tool decorated functions that the agent nodes
# can invoke. Tools represent discrete, verifiable actions — like querying
# an external system — that are separate from the LLM reasoning loop.
#
# In a production NOC environment, these tools would call real APIs:
#   - Cisco NSO REST API for device configuration queries
#   - Nokia NetAct SOAP/REST for alarm enrichment
#   - Splunk API for log correlation
#   - ServiceNow API for CMDB lookups
#
# For this demo, we simulate the NMS with our mock telemetry dictionary.
# =============================================================================

import sys
import os

# ---------------------------------------------------------------------------
# Path Setup: Ensure we can import from the 'data' directory regardless of
# the working directory from which the script is executed.
# ---------------------------------------------------------------------------
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from langchain_core.tools import tool
from data.mock_telemetry import get_telemetry_for_alarm


@tool
def query_nms_for_alarm_telemetry(alarm_id: str) -> dict:
    """
    Queries the Network Management System (NMS) to retrieve live telemetry
    data for a specific network alarm.

    This tool simulates a real NMS API call and returns a structured dictionary
    of current network vitals (e.g., SNR levels, error counts, power readings,
    device type, and location) for the given alarm ID.

    Use this tool when you need to gather factual, quantitative network data
    before drafting a resolution procedure. The returned data should drive
    your technical analysis and root-cause hypothesis.

    Args:
        alarm_id: The unique alarm identifier string (e.g., 'ALARM-001',
                  'ALARM-002'). Must match a known alarm in the NMS.

    Returns:
        A dictionary containing live network metrics for the specified alarm,
        or an error dictionary if the alarm_id is not recognized.

    Example:
        >>> result = query_nms_for_alarm_telemetry.invoke({"alarm_id": "ALARM-001"})
        >>> print(result["upstream_snr_db"])
        21.4
    """
    print(f"   [Tool] Querying NMS database for alarm: {alarm_id}")
    telemetry_data = get_telemetry_for_alarm(alarm_id)

    if "error" in telemetry_data:
        print(f"   [Tool] WARNING: {telemetry_data['error']}")
    else:
        print(f"   [Tool] Telemetry retrieved for device: {telemetry_data.get('device', 'Unknown')}")
        print(f"   [Tool] Severity: {telemetry_data.get('severity', 'Unknown')} | "
              f"Error Type: {telemetry_data.get('error_type', 'Unknown')}")

    return telemetry_data
