# =============================================================================
# data/mock_telemetry.py
# =============================================================================
# Purpose: Provides live telemetry data for network alarms by reading from
# the DynamoDB 'telecom-noc-telemetry' table.
#
# Architecture:
#   - On first call, scans the DynamoDB table and caches all records in memory.
#   - Subsequent calls (warm Lambda invocations) use the cached dict — no
#     additional DynamoDB calls are made per invocation.
#   - get_telemetry_for_alarm() is the only public interface, consumed by
#     src/tools.py via the @tool decorator.
#
# In production, replace this with a real NMS API call:
#   response = requests.get(f"https://your-nms/api/alarms/{alarm_id}", ...)
#   return response.json()
#
# To add new alarm scenarios:
#   1. Add a new item to data/mock_telemetry.json
#   2. Run scripts/seed_dynamodb.py to upload to DynamoDB
#   3. Add the corresponding ALARM_SCENARIOS entry in main.py
# =============================================================================

import os
import boto3
from botocore.exceptions import ClientError

# ---------------------------------------------------------------------------
# Configuration — read from environment variables
# ---------------------------------------------------------------------------
AWS_REGION           = os.getenv("AWS_REGION", "us-east-1")
TELEMETRY_TABLE_NAME = os.getenv("DYNAMODB_TELEMETRY_TABLE", "telecom-noc-telemetry")

# ---------------------------------------------------------------------------
# Module-level cache — loaded once per Lambda container lifecycle.
# On warm invocations, DynamoDB is NOT queried again.
# ---------------------------------------------------------------------------
_telemetry_cache: dict | None = None


def _load_telemetry_from_dynamodb() -> dict:
    """
    Scans the DynamoDB telemetry table and returns all alarm scenarios as a
    dict keyed by alarm_id.

    Returns:
        Dict mapping alarm_id (str) -> telemetry metrics (dict).
    """
    global _telemetry_cache

    if _telemetry_cache is not None:
        return _telemetry_cache

    print(f"   [Telemetry] Loading alarm data from DynamoDB table '{TELEMETRY_TABLE_NAME}'...")
    try:
        dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
        table = dynamodb.Table(TELEMETRY_TABLE_NAME)

        response = table.scan()
        items = response.get("Items", [])

        # Handle DynamoDB pagination
        while "LastEvaluatedKey" in response:
            response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
            items.extend(response.get("Items", []))

        # Build cache dict: {alarm_id: telemetry_metrics}
        _telemetry_cache = {}
        for item in items:
            alarm_id = item.get("alarm_id")
            telemetry = item.get("telemetry", {})
            if alarm_id:
                _telemetry_cache[alarm_id] = telemetry

        print(f"   [Telemetry] Loaded {len(_telemetry_cache)} alarm scenarios from DynamoDB.")
        return _telemetry_cache

    except ClientError as e:
        print(f"   [Telemetry] ERROR loading telemetry from DynamoDB: {e}")
        raise


# Kept for backward compatibility with main.py imports
MOCK_NETWORK_TELEMETRY: dict = {}


def get_telemetry_for_alarm(alarm_id: str) -> dict:
    """
    Retrieves live telemetry data for a given alarm ID from DynamoDB.

    Args:
        alarm_id: The unique identifier of the network alarm (e.g., 'ALARM-001').

    Returns:
        A dictionary of live network vitals, or an error dict if not found.
    """
    telemetry = _load_telemetry_from_dynamodb()

    if alarm_id in telemetry:
        return telemetry[alarm_id]
    else:
        return {
            "error": f"No telemetry found for alarm_id: {alarm_id}",
            "available_alarms": list(telemetry.keys()),
        }
