"""Tests for hook app output models — WebhookPostOut, AgentStatusOut, HealthGetOut."""

import pytest
from pydantic import ValidationError

from app.apps.hook.model.output import AgentStatusOut, HealthGetOut, WebhookPostOut


# --- WebhookPostOut ---


class TestWebhookPostOut:
    def test_default_ok(self):
        model = WebhookPostOut()
        assert model.ok is True

    def test_explicit_true(self):
        model = WebhookPostOut.model_validate({"ok": True})
        assert model.ok is True

    def test_explicit_false(self):
        model = WebhookPostOut.model_validate({"ok": False})
        assert model.ok is False


# --- AgentStatusOut ---


class TestAgentStatusOut:
    def test_basic(self):
        data = {
            "running": True,
            "queue_depth": 3,
            "last_activity_at": 1700000000.0,
            "cards_processed": 12,
        }
        model = AgentStatusOut.model_validate(data)
        assert model.running is True
        assert model.queue_depth == 3
        assert model.last_activity_at == 1700000000.0
        assert model.cards_processed == 12

    def test_idle_agent(self):
        data = {
            "running": True,
            "queue_depth": 0,
            "last_activity_at": 0.0,
            "cards_processed": 0,
        }
        model = AgentStatusOut.model_validate(data)
        assert model.queue_depth == 0
        assert model.last_activity_at == 0.0
        assert model.cards_processed == 0

    def test_stopped_agent(self):
        data = {
            "running": False,
            "queue_depth": 0,
            "last_activity_at": 1700000000.0,
            "cards_processed": 5,
        }
        model = AgentStatusOut.model_validate(data)
        assert model.running is False

    def test_missing_running_raises(self):
        with pytest.raises(ValidationError):
            AgentStatusOut.model_validate({
                "queue_depth": 0,
                "last_activity_at": 0.0,
                "cards_processed": 0,
            })

    def test_missing_queue_depth_raises(self):
        with pytest.raises(ValidationError):
            AgentStatusOut.model_validate({
                "running": True,
                "last_activity_at": 0.0,
                "cards_processed": 0,
            })

    def test_missing_last_activity_at_raises(self):
        with pytest.raises(ValidationError):
            AgentStatusOut.model_validate({
                "running": True,
                "queue_depth": 0,
                "cards_processed": 0,
            })

    def test_missing_cards_processed_raises(self):
        with pytest.raises(ValidationError):
            AgentStatusOut.model_validate({
                "running": True,
                "queue_depth": 0,
                "last_activity_at": 0.0,
            })


# --- HealthGetOut ---


class TestHealthGetOut:
    def test_defaults(self):
        model = HealthGetOut()
        assert model.status == "ok"
        assert model.agents == {}
        assert model.costs_by_agent == {}
        assert model.costs_total == {}

    def test_with_agents(self):
        data = {
            "agents": {
                "api": {
                    "running": True,
                    "queue_depth": 1,
                    "last_activity_at": 1700000000.0,
                    "cards_processed": 5,
                },
            },
            "costs_by_agent": {
                "api": {"total_cost_usd": 0.15, "executions": 5},
            },
            "costs_total": {"total_cost_usd": 0.15, "total_executions": 5},
        }
        model = HealthGetOut.model_validate(data)
        assert "api" in model.agents
        assert model.agents["api"].running is True
        assert model.agents["api"].cards_processed == 5
        assert model.costs_by_agent["api"]["total_cost_usd"] == 0.15
        assert model.costs_total["total_executions"] == 5

    def test_multiple_agents(self):
        data = {
            "agents": {
                "api": {
                    "running": True,
                    "queue_depth": 0,
                    "last_activity_at": 1700000000.0,
                    "cards_processed": 3,
                },
                "reviewer": {
                    "running": True,
                    "queue_depth": 2,
                    "last_activity_at": 1700000100.0,
                    "cards_processed": 7,
                },
            },
        }
        model = HealthGetOut.model_validate(data)
        assert len(model.agents) == 2
        assert model.agents["reviewer"].queue_depth == 2

    def test_custom_status(self):
        model = HealthGetOut.model_validate({"status": "degraded"})
        assert model.status == "degraded"

    def test_invalid_agent_status_raises(self):
        with pytest.raises(ValidationError):
            HealthGetOut.model_validate({
                "agents": {"api": {"running": "yes"}},
            })
