"""
Shared pytest fixtures for Telecom NOC Agent tests.
Provides mock DynamoDB tables, sample alarm data, SOP documents,
and fake OpenAI embedding/completion responses.
"""

import json
import os
from typing import Any
from unittest.mock import MagicMock, patch

import boto3
import numpy as np
import pytest
from moto import mock_aws


# ── Environment stubs (prevents real API calls in CI) ──────────────────────
os.environ.setdefault("OPENAI_API_KEY", "sk-test-key-for-ci")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test-key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test-secret")
os.environ.setdefault("DYNAMODB_SOPS_TABLE", "noc-sops-test")
os.environ.setdefault("DYNAMODB_TELEMETRY_TABLE", "noc-telemetry-test")


# ── Sample domain data ──────────────────────────────────────────────────────

SAMPLE_ALARMS = {
    "ALARM-001": {
        "alarm_id": "ALARM-001",
        "device_id": "CMTS-NYC-01",
        "alarm_type": "DOCSIS_TIMEOUT",
        "severity": "CRITICAL",
        "description": "Cable modem termination system reporting T3/T4 timeout on downstream channels",
        "affected_channels": ["DS-1", "DS-2", "DS-3"],
        "first_seen": "2024-01-15T08:23:00Z",
    },
    "ALARM-002": {
        "alarm_id": "ALARM-002",
        "device_id": "OLT-LDN-07",
        "alarm_type": "GPON_POWER_LOSS",
        "severity": "HIGH",
        "description": "GPON optical power below threshold on PON port 3",
        "rx_power_dbm": -29.5,
        "threshold_dbm": -27.0,
        "first_seen": "2024-01-15T09:10:00Z",
    },
    "ALARM-003": {
        "alarm_id": "ALARM-003",
        "device_id": "ROUTER-CHI-03",
        "alarm_type": "BGP_FLAPPING",
        "severity": "HIGH",
        "description": "BGP session flapping with peer 10.0.0.1, 5 resets in last 10 minutes",
        "peer_ip": "10.0.0.1",
        "reset_count": 5,
        "first_seen": "2024-01-15T10:05:00Z",
    },
}

SAMPLE_SOPS = [
    {
        "sop_id": "SOP-001",
        "vendor": "Arris",
        "title": "DOCSIS T3/T4 Timeout Troubleshooting Guide",
        "content": "Step 1: Check downstream channel power levels. Step 2: Verify SNR margin. Step 3: Inspect for noise ingress. Resolution: Adjust attenuator or replace splitter.",
        "tags": ["DOCSIS", "timeout", "cable modem", "T3", "T4"],
    },
    {
        "sop_id": "SOP-002",
        "vendor": "Nokia",
        "title": "GPON Optical Power Loss Recovery",
        "content": "Step 1: Check ONU registration status. Step 2: Measure fiber span loss. Step 3: Inspect connectors for contamination. Resolution: Clean connectors or replace degraded ONUs.",
        "tags": ["GPON", "optical", "power", "PON", "ONU"],
    },
    {
        "sop_id": "SOP-003",
        "vendor": "Cisco",
        "title": "BGP Session Stability Guide",
        "content": "Step 1: Review hold-timer settings. Step 2: Check interface flapping. Step 3: Validate route policy. Resolution: Increase keepalive timers or fix physical link.",
        "tags": ["BGP", "routing", "peer", "session", "flapping"],
    },
]


# ── DynamoDB mock fixtures ─────────────────────────────────────────────────

@pytest.fixture(scope="function")
def aws_credentials():
    """Ensure moto intercepts all AWS calls."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"


@pytest.fixture(scope="function")
def dynamodb_tables(aws_credentials):
    """Create mock DynamoDB tables pre-populated with test data."""
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")

        # Create SOPs table
        sops_table = client.create_table(
            TableName="noc-sops-test",
            KeySchema=[{"AttributeName": "sop_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "sop_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        for sop in SAMPLE_SOPS:
            sops_table.put_item(Item=sop)

        # Create telemetry table
        telemetry_table = client.create_table(
            TableName="noc-telemetry-test",
            KeySchema=[{"AttributeName": "alarm_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "alarm_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        for alarm in SAMPLE_ALARMS.values():
            telemetry_table.put_item(Item=alarm)

        yield {"sops": sops_table, "telemetry": telemetry_table}


# ── OpenAI mock fixtures ────────────────────────────────────────────────────

@pytest.fixture
def mock_embedding_response():
    """Return a deterministic fake embedding vector (1536-dim)."""
    rng = np.random.default_rng(seed=42)
    vector = rng.random(1536).tolist()
    mock = MagicMock()
    mock.data = [MagicMock(embedding=vector)]
    return mock


@pytest.fixture
def mock_openai_client(mock_embedding_response):
    """Patch the OpenAI client to avoid real API calls."""
    with patch("src.retriever.openai_client") as mock_client, \
         patch("src.nodes.llm") as mock_llm:
        mock_client.embeddings.create.return_value = mock_embedding_response
        mock_llm.invoke.return_value = MagicMock(
            content="Resolution ticket: Check downstream power levels and SNR. Apply attenuator adjustment per SOP-001.",
        )
        yield mock_client, mock_llm


@pytest.fixture
def mock_safety_pass():
    """Fake safety audit that always passes."""
    return MagicMock(is_safe=True, feedback="All safety checks passed.")


@pytest.fixture
def mock_safety_fail():
    """Fake safety audit that fails (triggers self-correction loop)."""
    return MagicMock(
        is_safe=False,
        feedback="Missing rollback procedure. Revision required.",
    )
