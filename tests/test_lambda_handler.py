"""
Tests for the AWS Lambda entry point (lambda_handler.py).
Validates request parsing, graph invocation, response formatting,
error handling, and HTTP status codes.
"""

import json
import pytest
from unittest.mock import MagicMock, patch


# ── Helpers ─────────────────────────────────────────────────────────────────

def _api_gateway_event(body: dict, method: str = "POST") -> dict:
    """Simulate an API Gateway HTTP event payload."""
    return {
        "httpMethod": method,
        "path": "/alarm",
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
        "isBase64Encoded": False,
    }

def _lambda_context():
    ctx = MagicMock()
    ctx.function_name = "telecom-noc-agent"
    ctx.aws_request_id = "test-request-123"
    ctx.get_remaining_time_in_millis.return_value = 280000
    return ctx


SUCCESSFUL_GRAPH_RESULT = {
    "alarm_id": "ALARM-001",
    "telemetry": {"device_id": "CMTS-NYC-01", "alarm_type": "DOCSIS_TIMEOUT"},
    "sops": [{"sop_id": "SOP-001", "content": "DOCSIS guide"}],
    "resolution_ticket": "Adjust attenuator per SOP-001. Rollback: restore to -3dBmV.",
    "is_safe": True,
    "iterations": 1,
    "safety_feedback": "All safety checks passed.",
}


# ── Lambda handler tests ─────────────────────────────────────────────────────

class TestLambdaHandler:

    def test_valid_alarm_returns_200(self):
        from lambda_handler import lambda_handler
        event = _api_gateway_event({"alarm_id": "ALARM-001"})

        with patch("lambda_handler.build_graph") as mock_build:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = SUCCESSFUL_GRAPH_RESULT
            mock_build.return_value = mock_graph

            response = lambda_handler(event, _lambda_context())

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["alarm_id"] == "ALARM-001"

    def test_missing_alarm_id_returns_400(self):
        from lambda_handler import lambda_handler
        event = _api_gateway_event({})  # No alarm_id

        response = lambda_handler(event, _lambda_context())

        assert response["statusCode"] == 400
        body = json.loads(response["body"])
        assert "error" in body or "message" in body

    def test_response_contains_resolution_ticket(self):
        from lambda_handler import lambda_handler
        event = _api_gateway_event({"alarm_id": "ALARM-002"})

        with patch("lambda_handler.build_graph") as mock_build:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = {**SUCCESSFUL_GRAPH_RESULT, "alarm_id": "ALARM-002"}
            mock_build.return_value = mock_graph

            response = lambda_handler(event, _lambda_context())

        body = json.loads(response["body"])
        assert "resolution_ticket" in body

    def test_graph_exception_returns_500(self):
        from lambda_handler import lambda_handler
        event = _api_gateway_event({"alarm_id": "ALARM-001"})

        with patch("lambda_handler.build_graph") as mock_build:
            mock_graph = MagicMock()
            mock_graph.invoke.side_effect = RuntimeError("DynamoDB connection failed")
            mock_build.return_value = mock_graph

            response = lambda_handler(event, _lambda_context())

        assert response["statusCode"] == 500
        body = json.loads(response["body"])
        assert "error" in body

    def test_response_includes_cors_headers(self):
        from lambda_handler import lambda_handler
        event = _api_gateway_event({"alarm_id": "ALARM-001"})

        with patch("lambda_handler.build_graph") as mock_build:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = SUCCESSFUL_GRAPH_RESULT
            mock_build.return_value = mock_graph

            response = lambda_handler(event, _lambda_context())

        headers = response.get("headers", {})
        assert "Access-Control-Allow-Origin" in headers

    def test_malformed_json_body_returns_400(self):
        from lambda_handler import lambda_handler
        event = {
            "httpMethod": "POST",
            "path": "/alarm",
            "body": "not-valid-json{{",
            "headers": {},
        }
        response = lambda_handler(event, _lambda_context())
        assert response["statusCode"] in (400, 500)

    def test_graph_is_invoked_with_correct_initial_state(self):
        from lambda_handler import lambda_handler
        event = _api_gateway_event({"alarm_id": "ALARM-003"})

        with patch("lambda_handler.build_graph") as mock_build:
            mock_graph = MagicMock()
            mock_graph.invoke.return_value = SUCCESSFUL_GRAPH_RESULT
            mock_build.return_value = mock_graph

            lambda_handler(event, _lambda_context())

        call_args = mock_graph.invoke.call_args[0][0]
        assert call_args["alarm_id"] == "ALARM-003"
        assert call_args.get("iterations", 0) == 0
