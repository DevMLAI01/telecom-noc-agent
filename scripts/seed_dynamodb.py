# =============================================================================
# scripts/seed_dynamodb.py
# =============================================================================
# Purpose: One-time script to create DynamoDB tables and seed them with
# SOP documents and mock telemetry data from the local JSON files.
#
# Run once after AWS credentials are configured:
#   python scripts/seed_dynamodb.py
#
# Prerequisites:
#   - AWS credentials configured (aws configure, or env vars, or IAM role)
#   - boto3 installed (pip install boto3)
#   - data/sops.json and data/mock_telemetry.json present
# =============================================================================

import json
import os
import sys
import time
from decimal import Decimal
import boto3
from botocore.exceptions import ClientError


def _load_json_with_decimals(path: str):
    """Load JSON file converting all floats to Decimal (required by DynamoDB)."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f, parse_float=Decimal)

# ---------------------------------------------------------------------------
# Configuration — reads from environment with sensible defaults
# ---------------------------------------------------------------------------
AWS_REGION           = os.getenv("AWS_REGION", "us-east-1")
SOPS_TABLE_NAME      = os.getenv("DYNAMODB_SOPS_TABLE", "telecom-noc-sops")
TELEMETRY_TABLE_NAME = os.getenv("DYNAMODB_TELEMETRY_TABLE", "telecom-noc-telemetry")

# Resolve paths relative to the project root (one level up from scripts/)
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
SOPS_FILE    = os.path.join(PROJECT_ROOT, "data", "sops.json")
TELEMETRY_FILE = os.path.join(PROJECT_ROOT, "data", "mock_telemetry.json")


def create_table_if_not_exists(dynamodb, table_name: str, key_name: str) -> None:
    """Creates a DynamoDB table with PAY_PER_REQUEST billing (free tier compatible)."""
    try:
        dynamodb.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": key_name, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": key_name, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",  # No provisioned capacity cost
        )
        print(f"   [DynamoDB] Creating table '{table_name}'... ", end="", flush=True)

        # Wait until table is active
        waiter = dynamodb.get_waiter("table_exists")
        waiter.wait(TableName=table_name)
        print("ACTIVE")

    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceInUseException":
            print(f"   [DynamoDB] Table '{table_name}' already exists — skipping creation.")
        else:
            raise


def seed_sops(dynamodb_resource, table_name: str) -> None:
    """Loads sops.json and writes each SOP as a DynamoDB item."""
    print(f"\n   [Seed] Loading SOPs from {SOPS_FILE}...")
    sops = _load_json_with_decimals(SOPS_FILE)

    table = dynamodb_resource.Table(table_name)

    print(f"   [Seed] Writing {len(sops)} SOP documents to '{table_name}'...")
    with table.batch_writer() as batch:
        for sop in sops:
            item = {
                "sop_id":    sop["id"],
                "content":   sop["content"],
                "source":    sop["metadata"]["source"],
                "category":  sop["metadata"]["category"],
                "alarm_type": sop["metadata"]["alarm_type"],
            }
            batch.put_item(Item=item)
            print(f"      Wrote: {sop['id']} ({sop['metadata']['source']})")

    print(f"   [Seed] SOPs seeded successfully.")


def seed_telemetry(dynamodb_resource, table_name: str) -> None:
    """Loads mock_telemetry.json and writes each alarm scenario as a DynamoDB item."""
    print(f"\n   [Seed] Loading telemetry from {TELEMETRY_FILE}...")
    telemetry = _load_json_with_decimals(TELEMETRY_FILE)

    table = dynamodb_resource.Table(table_name)

    print(f"   [Seed] Writing {len(telemetry)} alarm scenarios to '{table_name}'...")
    with table.batch_writer() as batch:
        for alarm_id, metrics in telemetry.items():
            item = {
                "alarm_id":  alarm_id,
                "telemetry": metrics,
            }
            batch.put_item(Item=item)
            print(f"      Wrote: {alarm_id} ({metrics.get('device', 'unknown')})")

    print(f"   [Seed] Telemetry seeded successfully.")


def main():
    print("\n" + "="*60)
    print("  TELECOM NOC — DynamoDB Seed Script")
    print(f"  Region : {AWS_REGION}")
    print(f"  SOPs   : {SOPS_TABLE_NAME}")
    print(f"  Telemetry: {TELEMETRY_TABLE_NAME}")
    print("="*60)

    # Validate data files exist
    for path in [SOPS_FILE, TELEMETRY_FILE]:
        if not os.path.exists(path):
            print(f"\n❌ ERROR: Data file not found: {path}")
            sys.exit(1)

    # Initialize AWS clients
    dynamodb_client   = boto3.client("dynamodb", region_name=AWS_REGION)
    dynamodb_resource = boto3.resource("dynamodb", region_name=AWS_REGION)

    # Step 1: Create tables
    print("\n[Step 1] Creating DynamoDB tables (PAY_PER_REQUEST billing)...")
    create_table_if_not_exists(dynamodb_client, SOPS_TABLE_NAME, "sop_id")
    create_table_if_not_exists(dynamodb_client, TELEMETRY_TABLE_NAME, "alarm_id")

    # Step 2: Seed data
    print("\n[Step 2] Seeding data...")
    seed_sops(dynamodb_resource, SOPS_TABLE_NAME)
    seed_telemetry(dynamodb_resource, TELEMETRY_TABLE_NAME)

    print("\n" + "="*60)
    print("  Seed complete!")
    print(f"  View tables: https://console.aws.amazon.com/dynamodb/home?region={AWS_REGION}#tables")
    print("="*60 + "\n")


if __name__ == "__main__":
    main()
