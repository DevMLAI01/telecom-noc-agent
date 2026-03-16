"""
Tests for NOCAgentState schema (src/state.py).
Validates TypedDict structure, required fields, and type constraints.
"""

import pytest


# ── State schema tests ──────────────────────────────────────────────────────


class TestNOCAgentState:
    """Verify the workflow state TypedDict fields and defaults."""

    def test_state_has_required_fields(self):
        """NOCAgentState must contain the core fields used by all graph nodes."""
        from src.state import NOCAgentState

        hints = NOCAgentState.__annotations__
        required = {"alarm_id", "telemetry", "sops", "resolution_ticket", "is_safe", "iterations"}
        assert required.issubset(hints.keys()), f"Missing required fields: {required - hints.keys()}"

    def test_state_can_be_constructed(self):
        """A valid state dict should be constructable without errors."""
        from src.state import NOCAgentState

        state: NOCAgentState = {
            "alarm_id": "ALARM-001",
            "telemetry": {"device_id": "CMTS-NYC-01", "alarm_type": "DOCSIS_TIMEOUT"},
            "sops": [],
            "resolution_ticket": None,
            "is_safe": False,
            "iterations": 0,
            "safety_feedback": "",
        }
        assert state["alarm_id"] == "ALARM-001"
        assert state["iterations"] == 0

    def test_iterations_tracks_self_correction_loops(self):
        """iterations field must be an int to support loop guard logic."""
        from src.state import NOCAgentState

        hints = NOCAgentState.__annotations__
        assert hints.get("iterations") is int or str(hints.get("iterations")) in ("int", "<class 'int'>")

    def test_sops_field_is_list_type(self):
        """sops must be a list to hold multiple retrieved documents."""
        from src.state import NOCAgentState

        hints = NOCAgentState.__annotations__
        sops_type = str(hints.get("sops", ""))
        assert "list" in sops_type.lower() or "List" in sops_type


class TestSafetyAuditResult:
    """Tests for the Pydantic SafetyAuditResult model."""

    def test_valid_pass_result(self):
        from src.state import SafetyAuditResult

        result = SafetyAuditResult(is_safe=True, feedback="Approved.")
        assert result.is_safe is True
        assert result.feedback == "Approved."

    def test_valid_fail_result(self):
        from src.state import SafetyAuditResult

        result = SafetyAuditResult(is_safe=False, feedback="Missing rollback steps.")
        assert result.is_safe is False
        assert "rollback" in result.feedback

    def test_missing_is_safe_raises_validation_error(self):
        from pydantic import ValidationError
        from src.state import SafetyAuditResult

        with pytest.raises(ValidationError):
            SafetyAuditResult(feedback="No is_safe field provided")

    def test_missing_feedback_raises_validation_error(self):
        from pydantic import ValidationError
        from src.state import SafetyAuditResult

        with pytest.raises(ValidationError):
            SafetyAuditResult(is_safe=True)
