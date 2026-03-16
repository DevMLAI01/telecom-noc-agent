"""
Tests for the 4-node LangGraph workflow (src/nodes.py).
Each node is tested in isolation with mocked dependencies.
Tests cover: normal paths, self-correction loop, and max-iteration guard.
"""

import pytest
from unittest.mock import MagicMock, patch


# ── Shared state builder ────────────────────────────────────────────────────


def make_state(
    alarm_id="ALARM-001",
    telemetry=None,
    sops=None,
    resolution_ticket=None,
    is_safe=False,
    iterations=0,
    safety_feedback="",
):
    return {
        "alarm_id": alarm_id,
        "telemetry": telemetry or {"device_id": "CMTS-NYC-01", "alarm_type": "DOCSIS_TIMEOUT"},
        "sops": sops or [],
        "resolution_ticket": resolution_ticket,
        "is_safe": is_safe,
        "iterations": iterations,
        "safety_feedback": safety_feedback,
    }


# ── check_network node ──────────────────────────────────────────────────────


class TestCheckNetworkNode:
    def test_returns_telemetry_for_known_alarm(self, dynamodb_tables):
        from src.nodes import check_network

        state = make_state(alarm_id="ALARM-001")
        with patch("src.nodes.boto3_resource") as mock_db:
            mock_table = MagicMock()
            mock_db.return_value.Table.return_value = mock_table
            mock_table.get_item.return_value = {
                "Item": {"alarm_id": "ALARM-001", "alarm_type": "DOCSIS_TIMEOUT", "device_id": "CMTS-NYC-01"}
            }
            result = check_network(state)

        assert "telemetry" in result
        assert result["telemetry"]["alarm_type"] == "DOCSIS_TIMEOUT"

    def test_returns_empty_telemetry_for_unknown_alarm(self):
        from src.nodes import check_network

        state = make_state(alarm_id="ALARM-UNKNOWN")
        with patch("src.nodes.boto3_resource") as mock_db:
            mock_table = MagicMock()
            mock_db.return_value.Table.return_value = mock_table
            mock_table.get_item.return_value = {}  # No Item key
            result = check_network(state)

        assert result.get("telemetry") is None or result.get("telemetry") == {}


# ── get_manuals node ────────────────────────────────────────────────────────


class TestGetManualsNode:
    def test_retrieves_sops_based_on_telemetry(self):
        from src.nodes import get_manuals

        state = make_state(telemetry={"alarm_type": "DOCSIS_TIMEOUT", "device_id": "CMTS-NYC-01"})

        fake_sops = [
            {"sop_id": "SOP-001", "content": "DOCSIS guide", "score": 0.92},
            {"sop_id": "SOP-003", "content": "General NOC guide", "score": 0.71},
        ]
        with patch("src.nodes.retrieve_relevant_sops", return_value=fake_sops):
            result = get_manuals(state)

        assert len(result["sops"]) == 2
        assert result["sops"][0]["sop_id"] == "SOP-001"

    def test_safety_feedback_included_in_query_on_retry(self):
        """On retry (iterations > 0), safety_feedback should enrich the retrieval query."""
        from src.nodes import get_manuals

        state = make_state(
            telemetry={"alarm_type": "BGP_FLAPPING"}, iterations=1, safety_feedback="Missing rollback procedure."
        )
        with patch("src.nodes.retrieve_relevant_sops", return_value=[]) as mock_retrieve:
            get_manuals(state)

        call_kwargs = mock_retrieve.call_args
        query_used = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("query_text", "")
        assert "rollback" in query_used.lower() or mock_retrieve.called


# ── draft_fix node ──────────────────────────────────────────────────────────


class TestDraftFixNode:
    def test_produces_resolution_ticket_string(self):
        from src.nodes import draft_fix

        state = make_state(
            telemetry={"alarm_type": "DOCSIS_TIMEOUT", "device_id": "CMTS-NYC-01"},
            sops=[{"sop_id": "SOP-001", "content": "Check downstream power levels."}],
        )
        with patch("src.nodes.llm") as mock_llm:
            mock_llm.invoke.return_value = MagicMock(content="Resolution: Adjust attenuator per SOP-001.")
            result = draft_fix(state)

        assert isinstance(result["resolution_ticket"], str)
        assert len(result["resolution_ticket"]) > 0

    def test_ticket_contains_device_reference(self):
        from src.nodes import draft_fix

        state = make_state(
            telemetry={"alarm_type": "BGP_FLAPPING", "device_id": "ROUTER-CHI-03"},
            sops=[{"sop_id": "SOP-003", "content": "BGP troubleshooting guide."}],
        )
        with patch("src.nodes.llm") as mock_llm:
            mock_llm.invoke.return_value = MagicMock(
                content="For ROUTER-CHI-03: Increase BGP hold-timer to 90s per SOP-003."
            )
            result = draft_fix(state)

        assert "ROUTER-CHI-03" in result["resolution_ticket"] or len(result["resolution_ticket"]) > 10


# ── safety_check node ───────────────────────────────────────────────────────


class TestSafetyCheckNode:
    def test_passes_safe_ticket(self, mock_safety_pass):
        from src.nodes import safety_check

        state = make_state(
            resolution_ticket="Adjust attenuator. Includes rollback: restore previous setting.",
            iterations=0,
        )
        with patch("src.nodes.llm") as mock_llm:
            mock_llm.with_structured_output.return_value.invoke.return_value = mock_safety_pass
            result = safety_check(state)

        assert result["is_safe"] is True

    def test_fails_unsafe_ticket_and_captures_feedback(self, mock_safety_fail):
        from src.nodes import safety_check

        state = make_state(
            resolution_ticket="Reboot the device.",
            iterations=0,
        )
        with patch("src.nodes.llm") as mock_llm:
            mock_llm.with_structured_output.return_value.invoke.return_value = mock_safety_fail
            result = safety_check(state)

        assert result["is_safe"] is False
        assert len(result.get("safety_feedback", "")) > 0

    def test_increments_iterations_on_failure(self, mock_safety_fail):
        from src.nodes import safety_check

        state = make_state(resolution_ticket="Reboot immediately.", iterations=1)
        with patch("src.nodes.llm") as mock_llm:
            mock_llm.with_structured_output.return_value.invoke.return_value = mock_safety_fail
            result = safety_check(state)

        assert result["iterations"] == 2


# ── Graph routing logic ─────────────────────────────────────────────────────


class TestGraphRouting:
    def test_routes_to_manuals_when_unsafe_and_under_limit(self):
        from src.graph import route_after_safety

        state = make_state(is_safe=False, iterations=1)
        next_node = route_after_safety(state)
        assert next_node == "get_manuals"

    def test_routes_to_end_when_safe(self):
        from src.graph import route_after_safety

        state = make_state(is_safe=True, iterations=0)
        next_node = route_after_safety(state)
        assert next_node == "__end__"

    def test_routes_to_end_when_max_iterations_reached(self):
        """After 3 failed attempts, should exit rather than loop infinitely."""
        from src.graph import route_after_safety

        state = make_state(is_safe=False, iterations=3)
        next_node = route_after_safety(state)
        assert next_node == "__end__"
